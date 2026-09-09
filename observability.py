"""Observabilidade técnica centralizada do Kineo, sem dados sensíveis."""

from __future__ import annotations

import logging
import os
import re
import secrets
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "kineo"
_SENSITIVE_PATTERN = re.compile(
    r"senha|password|hash|token|secret|cookie|session|cpf|cnh|telefone|comprovante|"
    r"database_url|connection|string|aws|storage|arquivo|conteudo",
    re.IGNORECASE,
)
_ALLOWED_CONTEXT = {"empresa_id", "usuario_id", "modulo", "acao"}


def gerar_codigo_erro() -> str:
    """Gera um identificador curto, não sequencial e rastreável."""
    return f"KNE-{secrets.token_hex(3).upper()}"


def _contexto_seguro(contexto: dict | None) -> dict:
    if not contexto:
        return {}
    return {
        chave: valor
        for chave, valor in contexto.items()
        if chave in _ALLOWED_CONTEXT
        and not _SENSITIVE_PATTERN.search(str(chave))
        and isinstance(valor, (str, int, float, bool, type(None)))
    }


def _mensagem(mensagem: str, codigo: str | None = None, contexto: dict | None = None) -> str:
    partes = []
    if codigo:
        partes.append(f"codigo={codigo}")
    partes.extend(f"{chave}={valor}" for chave, valor in _contexto_seguro(contexto).items())
    partes.append(f'mensagem="{mensagem}"')
    return " ".join(partes)


def configurar_logging(app_env: str | None = None, is_managed_env: bool | None = None) -> logging.Logger:
    """Configura stdout sempre e arquivo rotativo apenas em desenvolvimento."""
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_kineo_configurado", False):
        return logger

    ambiente = str(app_env or os.getenv("KINEO_ENV", "development")).strip().lower()
    gerenciado = bool(is_managed_env) or ambiente in {
        "production", "prod", "staging", "homolog", "homologacao", "homologação"
    }
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if not gerenciado:
        diretorio = Path(os.getenv("KINEO_LOG_DIR", "logs"))
        try:
            diretorio.mkdir(parents=True, exist_ok=True)
            arquivo = RotatingFileHandler(
                diretorio / "kineo.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
            arquivo.setFormatter(formatter)
            logger.addHandler(arquivo)
        except OSError:
            logger.warning('mensagem="Arquivo local de log indisponível; usando console"')

    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._kineo_configurado = True
    return logger


def registrar_evento(mensagem: str, *, nivel: int = logging.INFO, logger=None, **contexto) -> None:
    (logger or logging.getLogger(LOGGER_NAME)).log(
        nivel, _mensagem(mensagem, contexto=contexto)
    )


def registrar_excecao(
    excecao: BaseException,
    mensagem: str,
    *,
    logger=None,
    empresa_id=None,
    usuario_id=None,
    modulo=None,
    acao=None,
    **contexto_ignorado,
) -> str:
    """Registra traceback e devolve o mesmo código seguro exibível ao usuário."""
    codigo = gerar_codigo_erro()
    contexto = {
        "empresa_id": empresa_id,
        "usuario_id": usuario_id,
        "modulo": modulo,
        "acao": acao,
    }
    destino = logger or logging.getLogger(LOGGER_NAME)

    # Evita que a representação textual de exceções (especialmente SQLAlchemy)
    # exponha parâmetros, credenciais ou outros dados sensíveis. Mantemos o
    # traceback de frames para diagnóstico e incluímos o detalhe da exceção
    # somente quando ele não contém marcadores sensíveis.
    detalhe = str(excecao or "").strip()
    if detalhe and _SENSITIVE_PATTERN.search(detalhe):
        detalhe = "[REDACTED]"
    tipo_excecao = type(excecao).__name__
    # Não usa traceback.format_list(): ele inclui a linha-fonte do frame e essa
    # linha pode conter literalmente um segredo (por exemplo, em um raise, SQL
    # montado em código ou chamada com argumento sensível). Mantemos arquivo,
    # linha e função, que são suficientes para diagnóstico, sem reproduzir o
    # conteúdo da linha de código.
    frames_extraidos = traceback.extract_tb(excecao.__traceback__)
    frames = "".join(
        f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
        for frame in frames_extraidos
    )
    bloco_traceback = f"Traceback (most recent call last):\n{frames}{tipo_excecao}"
    if detalhe:
        bloco_traceback += f": {detalhe}"

    destino.error(
        _mensagem(mensagem, codigo=codigo, contexto=contexto) + "\n" + bloco_traceback
    )
    return codigo
