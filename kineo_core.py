"""Regras puras e testáveis do núcleo do Kineo.

Este módulo não importa Streamlit nem acessa banco de dados.
"""

import re


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
