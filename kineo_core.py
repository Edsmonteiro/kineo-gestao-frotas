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
