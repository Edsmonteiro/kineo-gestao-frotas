import os
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError


# O banco usado por esta suíte existe apenas em memória.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["KINEO_ENV"] = "development"
os.environ["KINEO_AUTO_MIGRATE"] = "1"
os.environ["KINEO_BOOTSTRAP_ADMIN_PASSWORD"] = "TesteLocal-123!NaoUsar"

from database import (  # noqa: E402
    Contrato,
    Empresa,
    SessionLocal,
    Usuario,
    Veiculo,
    gerar_senha_temporaria,
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_hash_de_senha_nao_armazena_texto_puro():
    senha = "Senha-Forte-123!"
    hash_gerado = hash_password(senha)

    assert hash_gerado != senha
    assert verify_password(senha, hash_gerado) is True


def test_verificacao_rejeita_senha_incorreta():
    hash_gerado = hash_password("Senha-Correta-123!")

    assert verify_password("Senha-Incorreta-123!", hash_gerado) is False


@pytest.mark.parametrize(
    ("senha", "hash_salvo"),
    [
        ("", ""),
        ("senha", ""),
        ("", "hash-invalido"),
        ("senha", "hash-invalido"),
    ],
)
def test_verificacao_rejeita_entradas_invalidas(senha, hash_salvo):
    assert verify_password(senha, hash_salvo) is False


def test_hash_atual_nao_precisa_rehash_imediato():
    hash_gerado = hash_password("Senha-Atual-123!")

    assert password_needs_rehash(hash_gerado) is False


def test_senha_temporaria_e_aleatoria():
    senha_a = gerar_senha_temporaria()
    senha_b = gerar_senha_temporaria()

    assert senha_a != senha_b
    assert len(senha_a) >= 16
    assert len(senha_b) >= 16


def test_consulta_de_usuario_respeita_empresa_id():
    session = SessionLocal()
    try:
        empresa_a = Empresa(id=9101, nome_fantasia="Empresa A")
        empresa_b = Empresa(id=9102, nome_fantasia="Empresa B")
        usuario_a = Usuario(
            id=9201,
            empresa_id=empresa_a.id,
            nome="Usuário A",
            login="usuario-a-isolamento",
            email="usuario-a@isolamento.test",
            senha=hash_password("Senha-A-123!"),
            perfil="admin",
            ativo=1,
        )
        usuario_b = Usuario(
            id=9202,
            empresa_id=empresa_b.id,
            nome="Usuário B",
            login="usuario-b-isolamento",
            email="usuario-b@isolamento.test",
            senha=hash_password("Senha-B-123!"),
            perfil="admin",
            ativo=1,
        )
        session.add_all([empresa_a, empresa_b, usuario_a, usuario_b])
        session.flush()

        encontrados = session.query(Usuario).filter(
            Usuario.empresa_id == empresa_a.id
        ).all()

        assert [usuario.id for usuario in encontrados] == [usuario_a.id]
        assert all(usuario.empresa_id == empresa_a.id for usuario in encontrados)
    finally:
        session.rollback()
        session.close()


def test_fk_composta_impede_contrato_com_veiculo_de_outra_empresa():
    session = SessionLocal()
    try:
        empresa_a = Empresa(id=9301, nome_fantasia="Empresa A FK")
        empresa_b = Empresa(id=9302, nome_fantasia="Empresa B FK")
        veiculo_a = Veiculo(
            id=9401,
            empresa_id=empresa_a.id,
            placa="TST9A01",
            modelo="Veículo de teste",
            status="Disponível",
            ativo=1,
        )
        session.add_all([empresa_a, empresa_b, veiculo_a])
        session.flush()

        contrato_cruzado = Contrato(
            empresa_id=empresa_b.id,
            veiculo_id=veiculo_a.id,
            cliente="Contrato inválido entre empresas",
            data_inicio=date(2026, 1, 1),
            ativo=1,
        )
        session.add(contrato_cruzado)

        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()
