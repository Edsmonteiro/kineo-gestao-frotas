from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from database import (
    CobrancaMensal,
    Contrato,
    Custo,
    Empresa,
    ItemPlanoManutencao,
    ManutencaoRealizada,
    Motorista,
    PlanoManutencao,
    SubstituicaoContrato,
    Veiculo,
)
from kineo_core import (
    add_months,
    atualizar_km_sem_regressao,
    calcular_encargos_cobranca,
    classificar_alerta_data,
    dias_atraso_cobranca,
    dividir_valor_parcelas,
    email_valido,
    normalizar_status_cobranca,
    normalizar_email,
    parse_valor_monetario_br,
    tenant_get,
)


def _cenario(db):
    a = Empresa(nome_fantasia="Empresa A")
    b = Empresa(nome_fantasia="Empresa B")
    db.add_all([a, b]); db.flush()
    va = Veiculo(empresa_id=a.id, placa="AAA1A11", modelo="A", km_atual=1000, status="Disponível")
    vb = Veiculo(empresa_id=b.id, placa="BBB2B22", modelo="B", km_atual=2000, status="Disponível")
    ma = Motorista(empresa_id=a.id, nome="Ana", matricula="A1", ativo=1)
    mb = Motorista(empresa_id=b.id, nome="Bia", matricula="B1", ativo=1)
    db.add_all([va, vb, ma, mb]); db.flush()
    ca = Contrato(empresa_id=a.id, veiculo_id=va.id, cliente="Cliente A", data_inicio=date(2026, 1, 1), ativo=1)
    cb = Contrato(empresa_id=b.id, veiculo_id=vb.id, cliente="Cliente B", data_inicio=date(2026, 1, 1), ativo=1)
    db.add_all([ca, cb]); db.flush()
    custo_a = Custo(empresa_id=a.id, veiculo_id=va.id, contrato_id=ca.id, motorista_id=ma.id,
                    data_custo=date(2026, 1, 10), categoria="Combustível",
                    valor_total=Decimal("100.00"), litros=None)
    custo_b = Custo(empresa_id=b.id, veiculo_id=vb.id, contrato_id=cb.id, motorista_id=mb.id,
                    data_custo=date(2026, 1, 10), categoria="Combustível",
                    valor_total=Decimal("200.00"), litros=20)
    db.add_all([custo_a, custo_b]); db.flush()
    return a, b, va, vb, ma, mb, ca, cb, custo_a, custo_b


@pytest.mark.parametrize("indice", range(4))
def test_tenant_isolation_entities(db_session, indice):
    a, b, va, vb, ma, mb, ca, cb, custo_a, custo_b = _cenario(db_session)
    pares = [(Veiculo, va, vb), (Contrato, ca, cb), (Motorista, ma, mb), (Custo, custo_a, custo_b)]
    model, proprio, alheio = pares[indice]
    assert tenant_get(db_session, model, proprio.id, a.id) is proprio
    assert tenant_get(db_session, model, alheio.id, a.id) is None


def test_custo_simples_e_litros_null(db_session):
    a, _, va, _, _, _, ca, _, custo, _ = _cenario(db_session)
    db_session.commit()
    salvo = tenant_get(db_session, Custo, custo.id, a.id)
    assert salvo.veiculo_id == va.id and salvo.contrato_id == ca.id
    assert salvo.valor_total == Decimal("100.00") and salvo.litros is None


@pytest.mark.parametrize("total,qtd,esperado", [
    ("100.00", 3, ["33.33", "33.33", "33.34"]),
    ("0.05", 2, ["0.02", "0.03"]),
    ("12.00", 12, ["1.00"] * 12),
])
def test_parcelamento_centavos(total, qtd, esperado):
    parcelas = dividir_valor_parcelas(Decimal(total), qtd)
    assert [str(v) for v in parcelas] == esperado
    assert sum(parcelas) == Decimal(total)


@pytest.mark.parametrize("base,meses,esperada", [
    (date(2026, 1, 31), 1, date(2026, 2, 28)),
    (date(2024, 1, 31), 1, date(2024, 2, 29)),
    (date(2026, 12, 15), 2, date(2027, 2, 15)),
])
def test_datas_mensais_parcelas(base, meses, esperada):
    assert add_months(base, meses) == esperada


def test_rollback_atomico_importacao(db_session):
    a, _, va, _, _, _, ca, _, _, _ = _cenario(db_session)
    db_session.commit()
    km_original = va.km_atual
    try:
        db_session.add(Custo(empresa_id=a.id, veiculo_id=va.id, contrato_id=ca.id,
                             data_custo=date(2026, 2, 1), categoria="Combustível",
                             valor_total=Decimal("50.00"), litros=None))
        va.km_atual = 1500
        db_session.flush()
        raise RuntimeError("falha técnica controlada")
    except RuntimeError:
        db_session.rollback()
    assert db_session.query(Custo).filter(Custo.data_custo == date(2026, 2, 1)).count() == 0
    assert tenant_get(db_session, Veiculo, va.id, a.id).km_atual == km_original
    assert db_session.query(ManutencaoRealizada).count() == 0


def test_fk_impede_contrato_cross_tenant(db_session):
    a, _, _, vb, _, _, _, cb, _, _ = _cenario(db_session)
    db_session.add(Custo(empresa_id=a.id, veiculo_id=vb.id, contrato_id=cb.id,
                         data_custo=date.today(), categoria="Outros", valor_total=10))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_substituicao_e_finalizacao(db_session):
    a, _, principal, _, _, _, contrato, _, _, _ = _cenario(db_session)
    reserva = Veiculo(empresa_id=a.id, placa="CCC3C33", modelo="Reserva", status="Disponível")
    db_session.add(reserva); db_session.flush()
    sub = SubstituicaoContrato(empresa_id=a.id, contrato_id=contrato.id,
        veiculo_principal_id=principal.id, veiculo_substituto_id=reserva.id,
        data_inicio=date.today(), ativo=1)
    principal.status = "Manutenção"; reserva.status = "Alugado"; db_session.add(sub); db_session.commit()
    assert principal.status == "Manutenção" and reserva.status == "Alugado"
    sub.ativo = 0; sub.data_fim = date.today(); principal.status = "Alugado"; reserva.status = "Disponível"
    db_session.commit()
    assert sub.ativo == 0 and reserva.status == "Disponível"


def test_manutencao_vinculos_e_km(db_session):
    a, _, va, _, _, _, ca, _, _, _ = _cenario(db_session)
    plano = PlanoManutencao(empresa_id=a.id, nome="Plano")
    db_session.add(plano); db_session.flush()
    item = ItemPlanoManutencao(empresa_id=a.id, plano_id=plano.id, tipo_manutencao="Revisão")
    db_session.add(item); db_session.flush()
    custo = Custo(empresa_id=a.id, veiculo_id=va.id, contrato_id=ca.id,
                  data_custo=date.today(), categoria="Manutenção Preventiva", valor_total=300)
    db_session.add(custo); db_session.flush()
    manut = ManutencaoRealizada(empresa_id=a.id, veiculo_id=va.id, plano_item_id=item.id,
                               custo_id=custo.id, data_execucao=date.today(), km_execucao=1200)
    db_session.add(manut); va.km_atual = atualizar_km_sem_regressao(va.km_atual, 1200)
    db_session.commit()
    assert manut.custo_id == custo.id and manut.veiculo_id == va.id and va.km_atual == 1200
    assert atualizar_km_sem_regressao(va.km_atual, 1100) == 1200


@pytest.mark.parametrize("entrada,esperado", [
    (None, "Pendente de emissão"), ("", "Pendente de emissão"),
    ("Pendente", "Pendente de emissão"), ("Recebida", "Recebida"),
    ("Cancelada", "Cancelada"), ("Não cobrar", "Não cobrar"),
])
def test_normalizacao_cobranca(entrada, esperado):
    assert normalizar_status_cobranca(entrada) == esperado


@pytest.mark.parametrize("status,esperado", [
    ("Pendente", 10), ("Recebida", 0), ("Cancelada", 0), ("Não cobrar", 0),
])
def test_dias_atraso(status, esperado):
    assert dias_atraso_cobranca(date(2026, 1, 1), status, hoje=date(2026, 1, 11)) == esperado


def test_encargos_cobranca():
    multa, juros, total = calcular_encargos_cobranca("1000", 30, 2, 1)
    assert (multa, juros, total) == (Decimal("20.00"), Decimal("10.00"), Decimal("1030.00"))


def test_cobranca_real_persistida(db_session):
    a, _, _, _, _, _, ca, _, _, _ = _cenario(db_session)
    cob = CobrancaMensal(empresa_id=a.id, contrato_id=ca.id, mes_ano="01/2026",
        cliente="Cliente A", forma_cobranca="Boleto", valor_previsto=Decimal("500.00"),
        vencimento=date(2026, 1, 10), status="Recebida", valor_liquidado=Decimal("510.00"),
        liquidacao_congelada=1)
    db_session.add(cob); db_session.commit()
    assert cob.valor_liquidado == Decimal("510.00") and cob.liquidacao_congelada == 1


@pytest.mark.parametrize("delta,limite,esperado", [
    (-1, 30, "CRÍTICO"), (0, 30, "ATENÇÃO"), (30, 30, "ATENÇÃO"),
    (31, 30, None), (-8, 7, "CRÍTICO"), (7, 7, "ATENÇÃO"), (8, 7, None),
])
def test_alertas_por_data(delta, limite, esperado):
    resultado = classificar_alerta_data(date(2026, 1, 1) + timedelta(days=delta), limite, date(2026, 1, 1))
    assert (resultado[0] if resultado else None) == esperado


def test_alertas_multitenant_fonte(db_session):
    a, b, *_ = _cenario(db_session)
    assert db_session.query(Contrato).filter(Contrato.empresa_id == a.id).count() == 1
    assert db_session.query(Contrato).filter(Contrato.empresa_id == b.id).count() == 1


@pytest.mark.parametrize("entrada,esperado", [
    (" Usuario@Exemplo.COM ", "usuario@exemplo.com"),
    (None, ""),
])
def test_normalizar_email_preservado(entrada, esperado):
    assert normalizar_email(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("a@b.com", True),
    ("invalido", False),
    (f"{'a' * 248}@b.com", True),
    (f"{'a' * 249}@b.com", False),
])
def test_email_valido_limite_preservado(entrada, esperado):
    assert email_valido(entrada) is esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("1.012", 1012.0),
    ("R$ 1.012,08", 1012.08),
    ("inválido", 0.0),
])
def test_parse_monetario_preservado(entrada, esperado):
    assert parse_valor_monetario_br(entrada) == esperado
