import logging
import re

from observability import gerar_codigo_erro, registrar_evento, registrar_excecao


def test_codigo_erro_formato():
    assert re.fullmatch(r"KNE-[0-9A-F]{6}", gerar_codigo_erro())


def test_codigos_diferentes():
    assert gerar_codigo_erro() != gerar_codigo_erro()


def test_registrar_excecao_codigo_e_traceback(caplog):
    logger = logging.getLogger("teste.observability.excecao")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            raise RuntimeError("falha controlada")
        except RuntimeError as exc:
            codigo = registrar_excecao(exc, "Falha técnica", logger=logger,
                empresa_id=3, usuario_id=7, modulo="custos", acao="registrar")
    texto = caplog.text
    assert codigo in texto and "Traceback" in texto and "falha controlada" in texto
    assert "empresa_id=3" in texto and "usuario_id=7" in texto


def test_registrar_excecao_sem_contexto(caplog):
    logger = logging.getLogger("teste.observability.sem_contexto")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            1 / 0
        except ZeroDivisionError as exc:
            codigo = registrar_excecao(exc, "Falha", logger=logger)
    assert codigo in caplog.text


def test_contexto_sensivel_nao_e_registrado(caplog):
    logger = logging.getLogger("teste.observability.sensivel")
    with caplog.at_level(logging.INFO, logger=logger.name):
        registrar_evento("Evento", logger=logger, modulo="login", acao="teste",
                          senha="nao-vazar", cpf="12345678900", token="secreto")
    assert "nao-vazar" not in caplog.text
    assert "12345678900" not in caplog.text
    assert "secreto" not in caplog.text
    assert "modulo=login" in caplog.text


def test_excecao_sensivel_nao_vaza_no_traceback(caplog):
    logger = logging.getLogger("teste.observability.traceback_sensivel")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            raise RuntimeError("senha=nao-vazar cpf=12345678900 token=secreto")
        except RuntimeError as exc:
            codigo = registrar_excecao(
                exc, "Falha técnica", logger=logger, empresa_id=3, modulo="custos", acao="teste"
            )
    texto = caplog.text
    assert codigo in texto
    assert "Traceback" in texto
    assert "RuntimeError" in texto
    assert "nao-vazar" not in texto
    assert "12345678900" not in texto
    assert "secreto" not in texto
    assert "[REDACTED]" in texto
