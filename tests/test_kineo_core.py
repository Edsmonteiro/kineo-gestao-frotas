import pytest

from kineo_core import email_valido, normalizar_email, parse_valor_monetario_br


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("  EDSON@EXEMPLO.COM.BR  ", "edson@exemplo.com.br"),
        ("usuario@empresa.com", "usuario@empresa.com"),
        ("", ""),
        (None, ""),
        (123, "123"),
    ],
)
def test_normalizar_email(entrada, esperado):
    assert normalizar_email(entrada) == esperado


@pytest.mark.parametrize(
    "email",
    [
        "usuario@empresa.com",
        "nome.sobrenome+frota@sub.empresa.com.br",
        "A@B.COM",
        f"{'a' * 64}@empresa.com",
    ],
)
def test_email_valido_aceita_formatos_permitidos(email):
    assert email_valido(email) is True


@pytest.mark.parametrize(
    "email",
    [
        None,
        "",
        "   ",
        "usuario",
        "@empresa.com",
        "usuario@",
        "usuario @empresa.com",
        "usuario@empresa",
        "usuario@@empresa.com",
        f"{'a' * 245}@empresa.com",
    ],
)
def test_email_valido_rejeita_formatos_invalidos(email):
    assert email_valido(email) is False


def test_email_valido_normaliza_antes_de_validar():
    assert email_valido("  USUARIO@EMPRESA.COM  ") is True


def test_limite_de_254_caracteres():
    email_254 = f"{'a' * 242}@empresa.com"
    email_255 = f"{'a' * 243}@empresa.com"

    assert len(email_254) == 254
    assert len(email_255) == 255
    assert email_valido(email_254) is True
    assert email_valido(email_255) is False


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("1.012,08", 1012.08),
        ("R$ 1.012,08", 1012.08),
        ("1012.08", 1012.08),
        ("1.012", 1012.0),
        ("", 0.0),
        ("invalido", 0.0),
    ],
)
def test_parse_valor_monetario_br(entrada, esperado):
    assert parse_valor_monetario_br(entrada) == esperado
