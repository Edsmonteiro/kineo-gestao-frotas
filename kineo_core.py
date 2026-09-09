"""Regras puras e testáveis do núcleo do Kineo.

Este módulo não importa Streamlit nem acessa banco de dados.
"""

import calendar
import re
from datetime import date
from decimal import Decimal, ROUND_DOWN


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalizar_email(valor) -> str:
    """Normaliza e-mail para busca e armazenamento."""
    return str(valor or "").strip().lower()


def email_valido(valor) -> bool:
    """Valida o formato e o limite adotados pelo cadastro do Kineo."""
    email = normalizar_email(valor)
    return bool(email and len(email) <= 254 and EMAIL_PATTERN.fullmatch(email))


def parse_valor_monetario_br(valor) -> float:
    """Converte valores monetários brasileiros ou internacionais para float.

    Aceita, por exemplo, 1.012,08, R$ 1.012,08 e 1012.08.
    Retorna 0.0 para valores vazios, inválidos ou variáveis.
    """
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip()
    if not texto or "vari" in texto.lower():
        return 0.0

    try:
        texto = texto.replace("R$", "").replace(" ", "")
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "." in texto:
            partes = texto.split(".")
            if (
                len(partes) > 2
                or (
                    len(partes) == 2
                    and len(partes[1]) == 3
                    and partes[0].replace("-", "").isdigit()
                    and partes[1].isdigit()
                )
            ):
                texto = "".join(partes)
        return float(texto)
    except (TypeError, ValueError):
        return 0.0


def tenant_get(session, model, obj_id, empresa_id):
    """Busca uma entidade somente dentro do tenant informado."""
    if obj_id is None or empresa_id is None:
        return None
    return session.query(model).filter(
        model.id == int(obj_id), model.empresa_id == int(empresa_id)
    ).first()


def add_months(data_base, meses):
    """Avança meses preservando o dia quando ele existe no mês de destino."""
    indice = data_base.month - 1 + int(meses)
    ano = data_base.year + indice // 12
    mes = indice % 12 + 1
    dia = min(data_base.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def dividir_valor_parcelas(valor, quantidade):
    """Divide em centavos e garante soma exatamente igual ao valor original."""
    total = Decimal(str(valor)).quantize(Decimal("0.01"))
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValueError("Quantidade de parcelas deve ser positiva.")
    base = (total / quantidade).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    parcelas = [base] * quantidade
    parcelas[-1] = total - base * (quantidade - 1)
    return parcelas


def normalizar_status_cobranca(status):
    valor = str(status or "").strip()
    return "Pendente de emissão" if not valor or valor == "Pendente" else valor


def dias_atraso_cobranca(vencimento, status, data_recebimento=None, hoje=None):
    if not vencimento or normalizar_status_cobranca(status) in {
        "Recebida", "Cancelada", "Não cobrar"
    }:
        return 0
    referencia = data_recebimento or hoje or date.today()
    return max((referencia - vencimento).days, 0)


def calcular_encargos_cobranca(valor, dias_atraso, multa_percentual=0, juros_percentual=0):
    principal = Decimal(str(valor or 0)).quantize(Decimal("0.01"))
    dias = max(int(dias_atraso or 0), 0)
    multa = (
        principal * Decimal(str(multa_percentual or 0)) / Decimal("100")
        if dias else Decimal("0")
    ).quantize(Decimal("0.01"))
    juros = (
        principal * Decimal(str(juros_percentual or 0)) / Decimal("100")
        * Decimal(dias) / Decimal("30")
        if dias else Decimal("0")
    ).quantize(Decimal("0.01"))
    return multa, juros, principal + multa + juros


def atualizar_km_sem_regressao(km_atual, km_informado):
    atual = float(km_atual or 0)
    if km_informado is None:
        return atual
    return max(atual, float(km_informado))


def classificar_alerta_data(data_referencia, limite_dias, hoje=None):
    """Classifica vencimentos sem conhecer UI ou persistência."""
    if data_referencia is None:
        return None
    dias = (data_referencia - (hoje or date.today())).days
    if dias < 0:
        return "CRÍTICO", dias
    if dias <= limite_dias:
        return "ATENÇÃO", dias
    return None
