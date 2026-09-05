import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import (
    engine, SessionLocal, Veiculo, Contrato, SubstituicaoContrato, Custo, Usuario, Empresa, Motorista,
    CobrancaRecorrente, CobrancaMensal, PlanoManutencao, ItemPlanoManutencao, ManutencaoRealizada,
    Auditoria, hash_password, verify_password, password_needs_rehash, gerar_senha_temporaria,
    ARGON2_DISPONIVEL, APP_ENV, IS_MANAGED_ENV
)
from datetime import date, timedelta, datetime, timezone
import calendar
import os
import uuid
import time
import base64
import html
import re
import logging
import textwrap
import json
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from kineo_core import email_valido, normalizar_email, parse_valor_monetario_br

try:
    import boto3
    BOTO3_DISPONIVEL = True
except Exception:
    boto3 = None
    BOTO3_DISPONIVEL = False

try:
    from streamlit_js_eval import streamlit_js_eval
    STREAMLIT_JS_EVAL_DISPONIVEL = True
except Exception:
    streamlit_js_eval = None
    STREAMLIT_JS_EVAL_DISPONIVEL = False

logger = logging.getLogger("kineo")

IS_PRODUCTION_APP = str(APP_ENV or "").strip().lower() in {"production", "prod"}

# ─── FUSO HORÁRIO DE EXIBIÇÃO ───────────────────────────────────────────────
# Datas de auditoria/autenticação continuam armazenadas em UTC no banco.
# A interface converte para o fuso configurado antes de exibir ao usuário.
APP_TIMEZONE = os.getenv("KINEO_TIMEZONE", "America/Fortaleza").strip() or "America/Fortaleza"
try:
    ZoneInfo(APP_TIMEZONE)
except Exception:
    APP_TIMEZONE = "America/Fortaleza"


def agora_utc():
    """UTC ingênuo para persistência uniforme em SQLite/PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def agora_local():
    """Data/hora corrente no fuso operacional do Kineo."""
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def hoje_local():
    """Data corrente no fuso operacional, usada em regras de negócio."""
    return agora_local().date()


def formatar_serie_datetime_local(serie, formato="%d/%m/%Y %H:%M"):
    """Converte timestamps UTC do banco para o fuso local apenas na apresentação."""
    datas_utc = pd.to_datetime(serie, errors="coerce", utc=True)
    return datas_utc.dt.tz_convert(APP_TIMEZONE).dt.strftime(formato).fillna("—")


# ─── IDENTIDADE / LOGIN V10.3 ────────────────────────────────────────────────
LOGIN_REMEMBER_STORAGE_KEY = "kineo_login_identifier_v1"
def ler_identificador_lembrado():
    """Lê somente o identificador salvo no localStorage. Nunca armazena senha/token/sessão."""
    if not STREAMLIT_JS_EVAL_DISPONIVEL:
        return ""
    try:
        expr = (
            "setFrameHeight(0);"
            f"window.localStorage.getItem({json.dumps(LOGIN_REMEMBER_STORAGE_KEY)}) || ''"
        )
        valor = streamlit_js_eval(
            js_expressions=expr,
            want_output=True,
            key="kineo_login_remember_read",
        )
        if valor is None:
            return None
        return str(valor).strip()
    except Exception:
        logger.exception("Falha ao ler identificador lembrado do navegador")
        return ""


def persistir_identificador_lembrado(identificador, lembrar):
    """Persiste/remover apenas usuário/e-mail no navegador; não interfere no timeout da sessão."""
    if not STREAMLIT_JS_EVAL_DISPONIVEL:
        return False
    try:
        identificador = str(identificador or "").strip()
        if lembrar and identificador:
            expr = (
                "(() => {"
                f"window.localStorage.setItem({json.dumps(LOGIN_REMEMBER_STORAGE_KEY)}, "
                f"{json.dumps(identificador)}); return 'ok';"
                "})()"
            )
        else:
            expr = (
                "(() => {"
                f"window.localStorage.removeItem({json.dumps(LOGIN_REMEMBER_STORAGE_KEY)}); "
                "return 'ok';"
                "})()"
            )
        # Escrita é side-effect apenas: não devolvemos valor ao Python.
        # Isso evita o rerun assíncrono do custom component após o submit do login.
        expr = "setFrameHeight(0);" + expr
        streamlit_js_eval(
            js_expressions=expr,
            want_output=False,
            key="kineo_login_remember_write",
        )
        return True
    except Exception:
        logger.exception("Falha ao persistir identificador lembrado no navegador")
        return False


def processar_persistencia_login_pendente():
    """Executa a escrita no localStorage fora do ciclo do botão de login.

    Custom components podem provocar reruns/artefatos quando criados dentro do
    branch de um submit. Por isso o login apenas agenda a operação e o primeiro
    ciclo já autenticado executa o side-effect sem retorno ao Python.
    """
    if not st.session_state.get("autenticado"):
        return

    pendente = st.session_state.get("login_remember_pending")
    if not isinstance(pendente, dict):
        return

    # Limpa antes de montar o componente para garantir execução única.
    st.session_state["login_remember_pending"] = None
    persistir_identificador_lembrado(
        pendente.get("identificador", ""),
        bool(pendente.get("lembrar")),
    )


def login_frota_data_uri():
    """Carrega o asset visual do login. A tela continua funcional sem a imagem."""
    candidatos = [
        os.path.join("assets", "kineo_login_frota.png"),
        os.path.join(os.path.dirname(__file__), "assets", "kineo_login_frota.png"),
    ]
    for caminho in candidatos:
        try:
            if os.path.exists(caminho):
                with open(caminho, "rb") as f:
                    return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
        except Exception:
            logger.exception("Falha ao carregar asset visual do login")
    return ""


def aplicar_css_login():
    """CSS isolado da tela pública. Não altera a sidebar/layout do app autenticado."""
    st.markdown(
        """
<style>
body:has(.kineo-login-left) [data-testid="stSidebar"],
body:has(.kineo-login-left) [data-testid="collapsedControl"],
body:has(.kineo-login-left) header[data-testid="stHeader"],
body:has(.kineo-login-left) [data-testid="stDecoration"],
body:has(.kineo-login-left) [data-testid="stStatusWidget"] { display: none !important; }

[data-testid="stAppViewContainer"]:has(.kineo-login-left) [data-testid="stMain"] {
    min-height: 100dvh !important;
}

[data-testid="stAppViewContainer"]:has(.kineo-login-left) {
    background: linear-gradient(135deg, #E9F1FC 0%, #F7FAFF 55%, #E7F0FC 100%) !important;
    background-image: none !important;
    --kineo-sidebar-space: 0px !important;
}

[data-testid="stAppViewContainer"]:has(.kineo-login-left) > section.main,
[data-testid="stAppViewContainer"]:has(.kineo-login-left) > .main,
[data-testid="stAppViewContainer"]:has(.kineo-login-left) [data-testid="stMain"] {
    margin-left: 0 !important;
    width: 100% !important;
    max-width: none !important;
    padding-left: 0 !important;
}

/* O login ocupa uma viewport, sem scroll em desktop. */
.block-container:has(.kineo-login-left) {
    width: 100% !important;
    max-width: 1480px !important;
    min-height: 100dvh !important;
    margin: 0 auto !important;
    padding: 10px 18px !important;
    box-sizing: border-box !important;
    display: flex !important;
    align-items: center !important;
}

.block-container:has(.kineo-login-left) > div { width: 100% !important; }

/* O componente de localStorage é funcional, mas não deve reservar espaço visual. */
.block-container:has(.kineo-login-left) [data-testid="stCustomComponentV1"],
.block-container:has(.kineo-login-left) iframe[title*="streamlit_js_eval"] {
    display: block !important;
    width: 0 !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    overflow: hidden !important;
}

div[data-testid="stHorizontalBlock"]:has(.kineo-login-left) {
    gap: 0 !important;
    width: 100% !important;
    height: min(740px, calc(100dvh - 20px)) !important;
    min-height: 560px !important;
    max-height: 740px !important;
    background: #FFFFFF;
    border: 1px solid rgba(148, 163, 184, .22);
    border-radius: 24px;
    overflow: hidden;
    box-shadow: 0 22px 54px rgba(30, 64, 175, .12);
}

div[data-testid="stColumn"]:has(.kineo-login-left) {
    background: #EAF3FF;
    padding: 0 !important;
    overflow: hidden !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) {
    background: #FFFFFF;
    padding: 24px 48px 18px !important;
    display: flex;
    flex-direction: column;
    justify-content: center;
    overflow: hidden;
}

div[data-testid="stColumn"]:has(.kineo-login-right) .stTextInput > div > div > input {
    min-height: 46px;
    border-radius: 11px !important;
    border: 1px solid #CBD5E1 !important;
    background: #FFFFFF !important;
    font-size: .95rem !important;
    color: #0F2B57 !important;
    padding-left: 15px !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) .stTextInput > div > div > input:focus {
    border-color: #1768E5 !important;
    box-shadow: 0 0 0 3px rgba(23, 104, 229, .12) !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) label {
    color: #0F2B57 !important;
    font-weight: 650 !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) div[data-testid="stForm"] {
    border: 0 !important;
    padding: 0 !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) div[data-testid="stFormSubmitButton"] button[kind="primary"],
div[data-testid="stColumn"]:has(.kineo-login-right) div[data-testid="stFormSubmitButton"] button {
    min-height: 46px;
    border-radius: 10px !important;
}

/* A recuperação é uma ação secundária: aparência de link, não CTA concorrente. */
div[data-testid="stColumn"]:has(.kineo-login-right)
  div[data-testid="stHorizontalBlock"]
  div[data-testid="stColumn"]:last-child
  div[data-testid="stFormSubmitButton"] button {
    background: transparent !important;
    color: #0B63D9 !important;
    border: 0 !important;
    box-shadow: none !important;
    min-height: 34px !important;
    padding: 0 6px !important;
    font-weight: 600 !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) div[data-testid="stFormSubmitButton"]:last-child button {
    background: linear-gradient(90deg, #1262D8 0%, #0B6CF2 100%) !important;
    color: white !important;
    border: 0 !important;
    font-weight: 700 !important;
    font-size: .95rem !important;
    box-shadow: 0 10px 26px rgba(11, 108, 242, .18);
}

.kineo-login-left {
    position: relative;
    height: 100%;
    min-height: 0;
    padding: 30px 44px 34px;
    overflow: hidden;
    color: #0E2A55;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    isolation: isolate;
    background:
        radial-gradient(circle at 96% 6%, rgba(40, 126, 245, .28) 0 11%, transparent 11.5%),
        radial-gradient(circle at 71% 34%, rgba(255,255,255,.72) 0 18%, transparent 35%),
        linear-gradient(150deg, #EEF6FF 0%, #E4F0FF 42%, #CFE3FF 72%, #AFCFFF 100%);
}

/* Fundo decorativo ocupa toda a metade esquerda, sem usar imagem raster. */
.kineo-login-left::before {
    content: "";
    position: absolute;
    width: 430px;
    height: 430px;
    border: 1px solid rgba(37, 99, 235, .16);
    border-radius: 50%;
    right: -155px;
    top: -185px;
    z-index: -2;
    box-shadow:
        0 0 0 44px rgba(255,255,255,.18),
        0 0 0 88px rgba(255,255,255,.10);
}

.kineo-login-left::after {
    content: "";
    position: absolute;
    left: -9%;
    right: -9%;
    bottom: -15%;
    height: 48%;
    border-radius: 55% 45% 0 0 / 30% 34% 0 0;
    background:
        radial-gradient(circle at 22% 62%, rgba(255,255,255,.38), transparent 19%),
        radial-gradient(circle at 72% 22%, rgba(255,255,255,.22), transparent 24%),
        linear-gradient(155deg, rgba(72, 151, 255, .28) 0%, rgba(26, 108, 238, .60) 58%, rgba(11, 89, 220, .82) 100%);
    transform: rotate(-4deg);
    z-index: -1;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.38);
}

.kineo-login-brand {
    display: flex;
    align-items: center;
    gap: 13px;
    font-size: 1.62rem;
    font-weight: 850;
    letter-spacing: -.04em;
    position: relative;
    z-index: 3;
}

.kineo-login-mark {
    width: 42px;
    height: 42px;
    border-radius: 13px;
    background: linear-gradient(135deg, #0B6CF2, #4EA4FF);
    display: grid;
    place-items: center;
    color: #fff;
    font-weight: 900;
    box-shadow: 0 12px 28px rgba(11, 108, 242, .24);
}

.kineo-login-eyebrow {
    margin-top: 34px;
    font-size: .76rem;
    letter-spacing: .15em;
    font-weight: 800;
    color: #1768E5;
    text-transform: uppercase;
    position: relative;
    z-index: 3;
}

.kineo-login-title {
    margin: 8px 0 12px;
    font-size: clamp(2.0rem, 2.75vw, 3.1rem);
    line-height: 1.02;
    font-weight: 850;
    letter-spacing: -.055em;
    max-width: 650px;
    position: relative;
    z-index: 3;
}

.kineo-login-title span { color: #1262D8; }

.kineo-login-subtitle {
    max-width: 560px;
    font-size: .92rem;
    line-height: 1.48;
    color: #536784;
    position: relative;
    z-index: 3;
}

.kineo-login-features {
    margin-top: 24px;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
    width: 100%;
    max-width: 650px;
    position: relative;
    z-index: 4;
}

.kineo-login-feature {
    display: grid;
    grid-template-columns: 46px 1fr;
    gap: 12px;
    align-items: center;
    min-width: 0;
    min-height: 86px;
    padding: 12px 14px;
    border-radius: 16px;
    background: rgba(255,255,255,.84);
    border: 1px solid rgba(255,255,255,.72);
    box-shadow: 0 12px 28px rgba(38, 91, 164, .09);
    backdrop-filter: blur(4px);
}

.kineo-login-feature-icon {
    width: 44px;
    height: 44px;
    border-radius: 14px;
    background: linear-gradient(145deg, #F8FBFF, #E7F1FF);
    box-shadow: 0 6px 16px rgba(15,43,87,.08);
    display: grid;
    place-items: center;
    color: #1262D8;
    font-size: 1.05rem;
    font-weight: 900;
}

.kineo-login-feature strong {
    display: block;
    font-size: .88rem;
    line-height: 1.22;
    color: #0F2B57;
    margin-bottom: 4px;
}

.kineo-login-feature span {
    display: block;
    color: #536784;
    font-size: .72rem;
    line-height: 1.35;
}

.kineo-login-result {
    margin-top: 24px;
    width: min(510px, 82%);
    padding: 19px 22px 19px 78px;
    border-radius: 18px;
    background:
        radial-gradient(circle at 92% 10%, rgba(65, 157, 255, .24), transparent 28%),
        linear-gradient(135deg, #0C376F 0%, #0A2855 56%, #0A3E84 100%);
    color: white;
    box-shadow: 0 22px 46px rgba(7, 37, 78, .24);
    position: relative;
    z-index: 5;
    overflow: hidden;
}

.kineo-login-result::before {
    content: "↗";
    position: absolute;
    left: 18px;
    top: 50%;
    transform: translateY(-50%);
    width: 46px;
    height: 46px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 1.25rem;
    font-weight: 900;
    color: #FFFFFF;
    border: 1px solid rgba(255,255,255,.24);
    background: rgba(255,255,255,.06);
}

.kineo-login-result::after {
    content: "";
    position: absolute;
    width: 125px;
    height: 125px;
    border: 1px solid rgba(255,255,255,.16);
    border-radius: 50%;
    right: -40px;
    bottom: -62px;
}

.kineo-login-result strong { font-size: 1.02rem; }
.kineo-login-result div { margin-top: 6px; font-size: .79rem; opacity: .92; line-height: 1.42; }

.kineo-login-right { max-width: 610px; margin: 0 auto 10px; }
.kineo-login-right h1 {
    margin: 0; color: #0D2A56;
    font-size: clamp(1.65rem, 2.15vw, 2.2rem);
    letter-spacing: -.04em;
}
.kineo-login-right p {
    margin: 6px 0 16px;
    color: #687994;
    font-size: .94rem;
}
.kineo-login-exclusive {
    margin-top: 13px;
    padding: 12px 14px;
    border: 1px solid #D9E8FB;
    border-radius: 13px;
    background: linear-gradient(135deg, #F3F8FF, #F8FBFF);
    color: #24466F;
    font-size: .76rem;
    line-height: 1.4;
}
.kineo-login-exclusive strong { display: block; color: #123C73; margin-bottom: 3px; }
.kineo-login-footer {
    margin-top: 11px;
    text-align: center;
    color: #71819A;
    font-size: .72rem;
    line-height: 1.6;
}
.kineo-login-footer span { color: #365C8D; margin: 0 8px; }

.kineo-login-legal-label {
    margin-top: 9px;
    text-align: center;
    color: #71819A;
    font-size: .70rem;
}

div[data-testid="stColumn"]:has(.kineo-login-right) div[data-testid="stButton"] button {
    background: transparent !important;
    color: #365C8D !important;
    border: 0 !important;
    box-shadow: none !important;
    min-height: 28px !important;
    padding: 0 4px !important;
    font-size: .72rem !important;
    font-weight: 600 !important;
}

div[data-testid="stColumn"]:has(.kineo-login-right) div[data-testid="stButton"] button:hover {
    color: #0B63D9 !important;
    text-decoration: underline !important;
}

@media (min-width: 1025px) and (max-height: 700px) {
    div[data-testid="stHorizontalBlock"]:has(.kineo-login-left) { min-height: 540px !important; }
    .kineo-login-left { padding: 20px 30px 24px; }
    .kineo-login-eyebrow { margin-top: 18px; }
    .kineo-login-title { font-size: clamp(1.75rem, 2.35vw, 2.35rem); }
    .kineo-login-subtitle { font-size: .80rem; }
    .kineo-login-features { margin-top: 12px; gap: 8px; }
    .kineo-login-feature { min-height: 64px; padding: 8px 10px; grid-template-columns: 36px 1fr; gap: 8px; }
    .kineo-login-feature-icon { width: 34px; height: 34px; border-radius: 10px; }
    .kineo-login-feature strong { font-size: .76rem; margin-bottom: 2px; }
    .kineo-login-feature span { font-size: .62rem; }
    .kineo-login-result { margin-top: 12px; padding: 12px 16px 12px 64px; }
    .kineo-login-result::before { left: 14px; width: 38px; height: 38px; }
    div[data-testid="stColumn"]:has(.kineo-login-right) { padding: 18px 38px 14px !important; }
    .kineo-login-right p { margin-bottom: 10px; }
    .kineo-login-exclusive { margin-top: 9px; padding: 9px 12px; }
    .kineo-login-footer { margin-top: 7px; }
}

@media (max-width: 1024px) {
    .block-container:has(.kineo-login-left) {
        min-height: auto !important;
        display: block !important;
        padding: 12px !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.kineo-login-left) {
        display: block !important;
        height: auto !important;
        min-height: unset !important;
        max-height: none !important;
    }
    div[data-testid="stColumn"]:has(.kineo-login-left),
    div[data-testid="stColumn"]:has(.kineo-login-right) {
        width: 100% !important;
        flex: 1 1 100% !important;
    }
    .kineo-login-left { min-height: 640px; padding: 34px 34px 38px; }
    div[data-testid="stColumn"]:has(.kineo-login-right) { padding: 38px 32px 26px !important; }
}

@media (max-width: 680px) {
    .block-container:has(.kineo-login-left) { padding: 0 !important; }
    div[data-testid="stHorizontalBlock"]:has(.kineo-login-left) {
        border-radius: 0; border: 0; box-shadow: none;
    }
    .kineo-login-left { min-height: 440px; padding: 28px 22px; }
    .kineo-login-eyebrow { margin-top: 28px; }
    .kineo-login-title { font-size: 1.9rem; max-width: 94%; }
    .kineo-login-subtitle { max-width: 92%; }
    .kineo-login-features { display: none; }
    .kineo-login-result { width: min(360px, 94%); margin-top: auto; padding: 15px 16px 15px 64px; }
    div[data-testid="stColumn"]:has(.kineo-login-right) { padding: 34px 22px 24px !important; }
}
</style>
        """,
        unsafe_allow_html=True,
    )

def render_login_hero():
    # Painel esquerdo integralmente preenchido por arte CSS responsiva.
    # Mantém o lado direito funcional sem alterações de comportamento.
    hero_html = (
        '<div class="kineo-login-left">'
        '<div class="kineo-login-brand"><div class="kineo-login-mark">K</div><div>Kineo</div></div>'
        '<div class="kineo-login-eyebrow">Gestão de frotas</div>'
        '<div class="kineo-login-title">Gestão de frotas<br><span>inteligente e completa</span></div>'
        '<div class="kineo-login-subtitle">Tenha controle total da sua frota, reduza custos e aumente a eficiência da sua operação.</div>'
        '<div class="kineo-login-features">'
        '<div class="kineo-login-feature"><div class="kineo-login-feature-icon">F</div><div><strong>Controle total</strong><span>Veículos, motoristas e contratos em um só lugar.</span></div></div>'
        '<div class="kineo-login-feature"><div class="kineo-login-feature-icon">$</div><div><strong>Redução de custos</strong><span>Identifique gastos e aumente a eficiência operacional.</span></div></div>'
        '<div class="kineo-login-feature"><div class="kineo-login-feature-icon">↗</div><div><strong>Relatórios inteligentes</strong><span>Informação confiável para decisões melhores.</span></div></div>'
        '<div class="kineo-login-feature"><div class="kineo-login-feature-icon">✓</div><div><strong>Segurança e confiança</strong><span>Acesso controlado e dados separados por empresa.</span></div></div>'
        '</div>'
        '<div class="kineo-login-result"><strong>Informação que move resultados</strong><div>Mais controle, mais produtividade e melhores decisões para sua operação.</div></div>'
        '</div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)


# ─── DIRETÓRIOS ──────────────────────────────────────────────────────────────
for pasta in ["comprovantes", "logos"]:
    os.makedirs(pasta, exist_ok=True)

# ─── SESSION STATE INICIAL ───────────────────────────────────────────────────
for key, default in [
    ("autenticado", False),
    ("forcar_troca_senha", False),
    ("tela_config", False),
    # O menu autenticado inicia fixo/expandido. O usuário ainda pode recolhê-lo
    # pelo único botão de fixar/desafixar disponível na própria sidebar.
    ("sidebar_pinned", True),
    ("privacidade_pendente", False),
    ("privacidade_dialog_suspenso", False),
    ("privacidade_rever", False),
    ("ultima_atividade_ts", None),
    ("sessao_expirada_aviso", False),
    ("credencial_temporaria", None),
    ("login_identifier_prefill", ""),
    ("login_remember_loaded", False),
    ("pagina_frota", "Visão da Frota"),
    ("menu_frota_aberto", False),
    ("pagina_custos", "Visão de Custos"),
    ("menu_custos_aberto", False),
    ("pagina_contratos", "Visão de Contratos"),
    ("menu_contratos_aberto", False),
    ("pagina_cobrancas", "Visão Financeira"),
    ("menu_cobrancas_aberto", False),
    ("pagina_pessoas", "Motoristas"),
    ("menu_pessoas_aberto", False),
    ("login_remember_pending", None),
    ("uploader_key", 0), # Chave para resetar o uploader de planilhas
    ("custos_uploader_version", 0), # Chave para limpar o comprovante após registrar despesa
    ("veiculo_form_version", 0),
    ("contrato_form_version", 0),
    ("pontual_form_version", 0),
    ("recorrencias_editor_version", 0),
    ("cobrancas_editor_version", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─── CONFIGURAÇÃO DA PÁGINA ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Kineo | Gestão de Frotas",
    page_icon=":material/directions_car:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS DINÂMICO DA HOVER SIDEBAR ───────────────────────────────────────────
pinned = st.session_state.get("sidebar_pinned", False)
SIDEBAR_WIDTH = "260px" if pinned else "82px"
TEXT_OPACITY = "1" if pinned else "0"
TEXT_VISIBILITY = "visible" if pinned else "hidden"
BUTTON_WIDTH = "calc(100% - 34px)" if pinned else "48px"
POINTER_EVENTS = "auto" if pinned else "none"
SIDEBAR_COLLAPSE_DELAY = "0.10s" if not pinned else "0s"

css_template = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Reset & Base ── */
html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
    color: #111827;
}}

#MainMenu, footer {{ 
    visibility: hidden; 
}}

/*
   As tabelas continuam roláveis e, quando forem editores, as células seguem
   editáveis. O cabeçalho e a barra de ferramentas ficam bloqueados para que o
   usuário não oculte, formate ou reorganize colunas da visualização definida
   pelo Kineo.
*/
[data-testid="stElementToolbar"] {{
    display: none !important;
}}

[data-testid="stDataFrameGlideDataEditor"] {{
    position: relative !important;
}}

[data-testid="stDataFrameGlideDataEditor"]::after {{
    content: "";
    position: absolute;
    top: 0;
    right: 0;
    left: 0;
    height: 36px;
    z-index: 20;
    pointer-events: auto;
    cursor: default;
}}

[data-testid="stDataFrameColumnMenu"],
[data-testid="stDataFrameColumnVisibilityMenu"],
button[aria-label="Show/hide columns"] {{
    display: none !important;
}}

header[data-testid="stHeader"] {{ 
    display: none !important; 
}}

a.header-anchor {{
    display: none !important;
}}

[data-testid="stAppViewContainer"] {{ 
    background-color: #F8FAFC !important;
    background-image: radial-gradient(#CBD5E1 1px, transparent 1px) !important;
    background-size: 24px 24px !important;
}}

.block-container {{
    width: 100% !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 2rem 2.5rem 2rem !important;
    box-sizing: border-box !important;
}}

[data-testid="stSidebarCollapseButton"] {{ 
    display: none !important; 
}}

[data-testid="stSidebar"] {{
    background-color: #0B1120 !important;
    border-right: none !important;
    width: {SIDEBAR_WIDTH} !important;
    min-width: {SIDEBAR_WIDTH} !important;
    max-width: {SIDEBAR_WIDTH} !important;
    transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1) {SIDEBAR_COLLAPSE_DELAY}, min-width 0.3s cubic-bezier(0.4, 0, 0.2, 1) {SIDEBAR_COLLAPSE_DELAY}, max-width 0.3s cubic-bezier(0.4, 0, 0.2, 1) {SIDEBAR_COLLAPSE_DELAY} !important;
    overflow-x: hidden !important;
    position: fixed !important;
    height: 100vh !important;
    z-index: 999999 !important;
}}

/*
   ═══════════════════════════════════════════════════════════════════
   LAYOUT PRINCIPAL RESPONSIVO À SIDEBAR
   A sidebar é fixa. Portanto a área principal precisa ocupar apenas
   o espaço que começa DEPOIS da borda direita da sidebar.
   ═══════════════════════════════════════════════════════════════════
*/

[data-testid="stAppViewContainer"] {{
    --kineo-sidebar-space: {SIDEBAR_WIDTH};
}}

/*
   Compatibilidade com diferentes versões/estruturas do Streamlit.
   O mesmo comportamento é aplicado ao container principal encontrado.
*/
[data-testid="stAppViewContainer"] > section.main,
[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"] {{
    margin-left: var(--kineo-sidebar-space) !important;
    width: calc(100% - var(--kineo-sidebar-space)) !important;
    max-width: none !important;
    padding-left: 0 !important;
    box-sizing: border-box !important;
    transition:
        margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1) {SIDEBAR_COLLAPSE_DELAY},
        width 0.3s cubic-bezier(0.4, 0, 0.2, 1) {SIDEBAR_COLLAPSE_DELAY} !important;
}}

/*
   Quando a sidebar recolhida recebe hover, ela cresce para 260px.
   A variável abaixo faz a área principal acompanhar exatamente
   a mesma abertura, sem sobreposição.
*/
body:has([data-testid="stSidebar"]:hover) [data-testid="stAppViewContainer"] {{
    --kineo-sidebar-space: 260px;
}}

body:has([data-testid="stSidebar"]:hover) [data-testid="stAppViewContainer"] > section.main,
body:has([data-testid="stSidebar"]:hover) [data-testid="stAppViewContainer"] > .main,
body:has([data-testid="stSidebar"]:hover) [data-testid="stMain"] {{
    transition-delay: 0s !important;
}}

/* Força a barra lateral a colar no topo, removendo o gap nativo do Streamlit */
[data-testid="stSidebar"] .stScrollToBottomContainer > div:first-child {{
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    padding-top: 18px !important; 
}}

.sidebar-brand-wrapper {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-left: -16px; 
    padding-left: 17px; 
    width: {SIDEBAR_WIDTH}; 
    margin-bottom: 1rem;
    padding-top: 0;
    padding-right: 44px;
    padding-bottom: 1rem;
    overflow: hidden;
    white-space: nowrap;
    box-sizing: border-box;
    transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}}

.sidebar-logo-img {{
    min-width: 48px; 
    width: 48px; 
    height: 48px;
    border-radius: 50%; 
    object-fit: cover;
    border: 2px solid #3B82F6;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);
    background-color: #1E293B;
    display: flex; 
    align-items: center; 
    justify-content: center;
    color: #FFF; 
    font-weight: bold; 
    font-size: 1.2rem;
}}

.sidebar-brand-text {{
    display: flex; 
    flex-direction: column;
    opacity: {TEXT_OPACITY}; 
    visibility: {TEXT_VISIBILITY};
    transition: opacity 0.2s;
}}

.sidebar-brand-text h2 {{ 
    color: #F8FAFC !important; 
    font-size: 1.1rem !important; 
    margin: 0 !important; 
}}

.sidebar-brand-subtitle {{
    margin-top: 3px;
    color: #64748B;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.14em;
}}

.sidebar-nav-section {{
    max-height: {"24px" if pinned else "0"};
    margin: {"12px 0 4px 13px" if pinned else "0"};
    overflow: hidden;
    color: #64748B;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    line-height: 20px;
    opacity: {TEXT_OPACITY};
    visibility: {TEXT_VISIBILITY};
    white-space: nowrap;
    transition: opacity 0.2s, max-height 0.2s, margin 0.2s;
}}

[data-testid="stSidebar"] .st-key-nav_pin {{
    position: fixed !important;
    top: 16px;
    left: {"212px" if pinned else "34px"};
    z-index: 80;
}}

[data-testid="stSidebar"] .st-key-nav_pin button {{
    width: 36px !important;
    min-width: 36px !important;
    height: 36px !important;
    min-height: 36px !important;
    margin: 0 !important;
    padding: 0 !important;
    justify-content: center !important;
    border-radius: 8px !important;
    color: #94A3B8 !important;
}}

[data-testid="stSidebar"] .st-key-nav_pin button p {{
    display: none !important;
}}

[data-testid="stSidebar"] .st-key-nav_pin button span.material-symbols-rounded {{
    margin: 0 !important;
    font-size: 1.25rem !important;
}}

[data-testid="stSidebar"] .stButton > button {{
    width: {BUTTON_WIDTH} !important;
    min-width: 48px !important;
    height: 48px !important;
    border-radius: 8px !important;
    padding: 0 !important;
    display: flex; 
    align-items: center; 
    justify-content: flex-start;
    padding-left: 12px !important;
    margin-left: 0 !important; 
    margin-bottom: 8px !important;
    box-sizing: border-box !important;
    position: relative !important;
    overflow: hidden; 
    white-space: nowrap;
    background-color: transparent !important;
    color: #94A3B8 !important;
    border: none !important;
    box-shadow: none !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}}

[data-testid="stSidebar"] .stButton > button:hover {{ 
    background-color: #1E293B !important; 
    color: #F8FAFC !important; 
}}

[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background-color: #1E293B !important; 
    color: #FFFFFF !important;
    border: none !important; 
    border-radius: 8px !important; 
    margin-left: 0 !important; 
    padding-left: 12px !important; 
}}

/* Camada visual exclusiva da navegação desktop; o botão só recebe o clique. */
@media (min-width: 769px) {{
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"][data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stVerticalBlockBorderWrapper"] {{
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        padding: 0 !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] {{
        position: relative !important;
        width: 100% !important;
        min-width: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        gap: 0 !important;
        border: 0 !important;
        box-shadow: none !important;
        background: transparent !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stVerticalBlock"] {{
        gap: 0 !important;
    }}
    [data-testid="stSidebar"] .kineo-nav-line {{
        box-sizing: border-box;
        display: flex;
        align-items: center;
        justify-content: {"flex-start" if pinned else "center"};
        gap: {"12px" if pinned else "0"};
        height: 48px;
        padding: {"0 12px" if pinned else "0"};
        border-radius: 8px;
        background: transparent;
        color: #94A3B8;
        font-family: inherit;
        font-size: 14px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        pointer-events: none;
    }}
    [data-testid="stSidebar"] .kineo-nav-icon {{
        display: flex;
        align-items: center;
        justify-content: center;
        flex: 0 0 24px;
        width: 24px;
        font-family: "Material Symbols Rounded";
        font-size: 24px;
        font-weight: normal;
        line-height: 1;
        font-feature-settings: "liga";
    }}
    [data-testid="stSidebar"] .kineo-nav-label {{
        display: {"block" if pinned else "none"};
        min-width: 0;
        flex: 1 1 auto;
        text-align: left;
    }}
    [data-testid="stSidebar"] .kineo-nav-chevron {{
        display: {"flex" if pinned else "none"};
        flex: 0 0 20px;
        margin-left: auto;
        font-family: "Material Symbols Rounded";
        font-size: 20px;
        line-height: 1;
        font-feature-settings: "liga";
    }}
    [data-testid="stSidebar"] .kineo-nav-active {{
        background: #1E293B;
        color: #F8FAFC;
        box-shadow: inset 4px 0 #6366F1;
    }}
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] {{
        display: {"block" if pinned else "none"} !important;
        margin-left: 24px !important;
        width: calc(100% - 24px) !important;
    }}
    [data-testid="stSidebar"] .kineo-nav-sub {{
        height: 36px;
        font-size: 13px;
        background: rgba(30, 41, 59, 0.62);
    }}
    [data-testid="stSidebar"] .kineo-nav-sub .kineo-nav-icon {{
        flex-basis: 20px;
        width: 20px;
        font-size: 18px;
    }}
    [data-testid="stSidebar"] .kineo-nav-sub.kineo-nav-active {{
        background: rgba(99, 102, 241, 0.20);
        box-shadow: none;
    }}
    [data-testid="stSidebar"] .kineo-nav-privacy {{
        height: 36px;
        font-size: 12px;
        color: #64748B;
    }}
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"]:hover .kineo-nav-line {{
        background-color: #1E293B;
        color: #F8FAFC;
    }}
    [data-testid="stSidebar"]:hover .kineo-nav-line {{
        justify-content: flex-start;
        gap: 12px;
        padding: 0 12px;
    }}
    [data-testid="stSidebar"]:hover .kineo-nav-label {{
        display: block;
    }}
    [data-testid="stSidebar"]:hover .kineo-nav-chevron {{
        display: flex;
    }}
    [data-testid="stSidebar"]:hover [class*="st-key-kineo_nav_sub_"] {{
        display: block !important;
    }}
    /* Área clicável nativa, independente da geometria do ícone e do texto. */
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [class*="st-key-nav_"],
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stButton"],
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_"] .stButton {{
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        z-index: 5 !important;
    }}
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_"] button {{
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        min-width: 0 !important;
        height: 100% !important;
        min-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        opacity: 0 !important;
        pointer-events: auto !important;
        z-index: 1 !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"]:has(button:focus-visible) .kineo-nav-line {{
        outline: 2px solid #6366F1;
        outline-offset: -2px;
    }}
}}

.privacy-section {{
    padding: 1rem 0;
    border-bottom: 1px solid #E5E7EB;
}}

.privacy-section:last-child {{
    border-bottom: none;
}}

.kineo-404 {{
    max-width: 720px;
    margin: 6vh auto 1.5rem;
    text-align: center;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 16px;
    padding: 3rem 2rem;
    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}}

.kineo-404-code {{
    font-size: clamp(4rem, 10vw, 7rem);
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.06em;
    color: #6366F1;
}}

.kineo-404 h2 {{
    margin: 0.75rem 0 0.5rem;
    color: #111827;
}}

.kineo-404 p {{
    color: #64748B;
    max-width: 520px;
    margin: 0 auto;
}}

.profile-wrapper {{
    position: fixed;
    bottom: 0; 
    left: 0;
    width: {SIDEBAR_WIDTH}; 
    height: 80px;
    background-color: #0B1120;
    border-top: 1px solid #1E293B;
    display: flex; 
    align-items: center;
    padding-left: 17px; 
    gap: 12px;
    box-sizing: border-box;
    z-index: 50;
    overflow: hidden;
    white-space: nowrap;
    transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}}

.profile-avatar {{
    min-width: 48px; 
    width: 48px; 
    height: 48px;
    background: linear-gradient(135deg, #3B82F6, #2563EB); 
    color: #fff;
    border-radius: 50%; 
    display: flex; 
    align-items: center; 
    justify-content: center;
    font-weight: 700; 
    font-size: 1.2rem;
    border: 2px solid #1E293B;
    z-index: 55;
}}

.profile-text {{ 
    display: flex; 
    flex-direction: column;
    justify-content: center;
    opacity: {TEXT_OPACITY}; 
    visibility: {TEXT_VISIBILITY};
    transition: opacity 0.2s; 
    z-index: 55;
}}

.profile-text strong {{ 
    font-size: 0.9rem; 
    color: #F8FAFC; 
}}

.profile-text span {{ 
    font-size: 0.75rem; 
    color: #94A3B8; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button:not([class*="st-key-kineo_nav_"] *) {{
    position: fixed !important; 
    bottom: 10px !important; 
    left: 11px !important;   
    width: 60px !important;  
    height: 60px !important; 
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: transparent !important; 
    z-index: 60 !important;
    cursor: pointer !important;
    padding: 0 !important;
    border-radius: 12px !important; 
    transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s !important;
    margin: 0 !important;
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button:not([class*="st-key-kineo_nav_"] *) * {{
    display: none !important; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button:not([class*="st-key-kineo_nav_"] *):hover {{
    background-color: rgba(255, 255, 255, 0.08) !important; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:not([class*="st-key-kineo_nav_"] *) {{
    position: fixed !important; 
    bottom: 20px !important; 
    left: 204px !important;  
    width: 40px !important; 
    min-width: 40px !important; 
    height: 40px !important;
    padding: 0 !important; 
    display: flex !important;
    justify-content: center !important;
    align-items: center !important;
    background: transparent !important; 
    color: #EF4444 !important; 
    border: none !important;
    border-radius: 8px !important;
    z-index: 70 !important; 
    opacity: {TEXT_OPACITY} !important; 
    pointer-events: {POINTER_EVENTS} !important;
    margin: 0 !important;
    transition: opacity 0.2s !important;
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:not([class*="st-key-kineo_nav_"] *) p {{
    display: none !important; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:not([class*="st-key-kineo_nav_"] *) span {{
    margin: 0 !important;
    font-size: 1.5rem !important;
}}

[data-testid="stSidebar"]:hover {{
    width: 260px !important; 
    min-width: 260px !important; 
    max-width: 260px !important;
    transition-delay: 0s !important;
    box-shadow: 4px 0 20px rgba(0,0,0,0.4);
}}

[data-testid="stSidebar"]:hover .stButton > button {{
    width: calc(100% - 34px) !important;
}}

[data-testid="stSidebar"]:hover .sidebar-brand-wrapper, 
[data-testid="stSidebar"]:hover .profile-wrapper {{
    width: 260px !important;
}}

[data-testid="stSidebar"]:hover [data-testid="stVerticalBlock"] > div:nth-last-child(2) button:not([class*="st-key-kineo_nav_"] *),
.sidebar-pinned[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button:not([class*="st-key-kineo_nav_"] *) {{
    width: 180px !important; 
}}

[data-testid="stSidebar"]:hover .sidebar-brand-text, 
[data-testid="stSidebar"]:hover .profile-text, 
[data-testid="stSidebar"]:hover .stButton > button p {{
    opacity: 1 !important;
    visibility: visible !important;
}}

[data-testid="stSidebar"]:hover .sidebar-nav-section {{
    max-height: 24px;
    margin: 12px 0 4px 13px;
    opacity: 1 !important;
    visibility: visible !important;
}}

[data-testid="stSidebar"]:hover .st-key-nav_pin {{
    left: 212px;
}}

[data-testid="stSidebar"]:hover [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:not([class*="st-key-kineo_nav_"] *),
.sidebar-pinned[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:not([class*="st-key-kineo_nav_"] *) {{
    opacity: 1 !important; 
    pointer-events: auto !important;
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:not([class*="st-key-kineo_nav_"] *):hover {{
    background: rgba(239, 68, 68, 0.15) !important; 
}}

/* Hitbox integral da navegação desktop, após os ajustes legados de hover. */
@media (min-width: 769px) {{
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stElementContainer"]:has([data-testid="stButton"]),
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stElementContainer"]:has(.stButton),
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] .element-container:has(.stButton),
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stButton"],
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] .stButton {{
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        min-width: 100% !important;
        max-width: none !important;
        height: 100% !important;
        min-height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        z-index: 10 !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] [data-testid="stButton"] > button,
    [data-testid="stSidebar"] [class*="st-key-kineo_nav_"] .stButton > button,
    [data-testid="stSidebar"]:hover [class*="st-key-kineo_nav_"] [data-testid="stButton"] > button,
    [data-testid="stSidebar"]:hover [class*="st-key-kineo_nav_"] .stButton > button {{
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        min-width: 100% !important;
        max-width: none !important;
        height: 100% !important;
        min-height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        opacity: 0 !important;
        pointer-events: auto !important;
        z-index: 10 !important;
    }}
}}

[data-testid="stVerticalBlockBorderWrapper"] {{ 
    background: #FFFFFF !important; 
    border: 1px solid #E5E7EB !important; 
    border-radius: 10px !important; 
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03) !important; 
    padding: 1.25rem !important; 
}}

[data-testid="stMetric"] {{ 
    background: #FFFFFF; 
    border: 1px solid #E5E7EB; 
    border-radius: 10px; 
    padding: 1rem 1.25rem !important; 
}}

[data-testid="stMetricValue"] {{ 
    font-size: 1.6rem !important; 
    font-weight: 700 !important; 
    color: #111827 !important; 
}}

[data-testid="stMetricLabel"] {{ 
    font-size: 0.75rem !important; 
    font-weight: 500 !important; 
    color: #6B7280 !important; 
    text-transform: uppercase; 
    letter-spacing: 0.05em; 
}}

div[data-baseweb="select"] > div, 
div[data-baseweb="input"] > div, 
input[type="text"], 
input[type="number"], 
input[type="password"] {{ 
    border: 1px solid #94A3B8 !important; 
    border-radius: 8px !important; 
    background: #FFFFFF !important; 
    color: #111827 !important; 
    font-size: 0.875rem !important; 
    transition: border-color 0.15s ease; 
}}

div[data-baseweb="select"] > div:hover, 
input[type="text"]:hover, 
input[type="number"]:hover, 
div[data-baseweb="input"]:focus-within {{ 
    border-color: #6366F1 !important; 
}}

label {{ 
    font-size: 0.8rem !important; 
    font-weight: 600 !important; 
    color: #374151 !important; 
}}

.main .stButton > button {{ 
    background: #6366F1 !important; 
    color: #FFFFFF !important; 
    border: none !important; 
    border-radius: 8px !important; 
    font-size: 0.875rem !important; 
    font-weight: 600 !important; 
    padding: 0.5rem 1rem !important; 
    box-shadow: 0 1px 2px rgba(0,0,0,0.08); 
}}

.main .stButton > button:hover {{ 
    background: #4F46E5 !important; 
    transform: translateY(-1px); 
}}

[data-testid="stDownloadButton"] > button {{ 
    background: #FFFFFF !important; 
    color: #374151 !important; 
    border: 1px solid #D1D5DB !important; 
    font-size: 0.8rem !important; 
}}

[data-testid="stDownloadButton"] > button:hover {{ 
    background: #F3F4F6 !important; 
    transform: none !important; 
}}

[data-testid="stTabs"] [data-baseweb="tab-list"] {{ 
    border-bottom: 2px solid #E5E7EB; 
}}

[data-testid="stTabs"] [data-baseweb="tab"] {{ 
    background: transparent !important; 
    border: none !important; 
    color: #6B7280 !important; 
    font-weight: 500 !important; 
    padding: 0.5rem 1rem !important; 
}}

[data-testid="stTabs"] [aria-selected="true"] {{ 
    color: #6366F1 !important; 
    border-bottom: 2px solid #6366F1 !important; 
    font-weight: 600 !important; 
}}

[data-testid="stExpander"] {{ 
    background: #FFFFFF !important; 
    border: 1px solid #94A3B8 !important; 
    border-radius: 8px !important; 
}}

[data-testid="stForm"] {{ 
    background: #F8FAFC !important; 
    border: 1px solid #CBD5E1 !important; 
    border-radius: 10px !important; 
    padding: 1.25rem !important; 
}}

[data-testid="stDataFrame"] {{ 
    border: 1px solid #E5E7EB !important; 
    border-radius: 10px !important; 
    overflow: hidden; 
    background: #FFFFFF !important; 
}}

[data-testid="stNumberInputStepUp"], 
[data-testid="stNumberInputStepDown"] {{ 
    display: none !important; 
}}

.page-header {{ 
    margin-bottom: 1.5rem; 
    padding-bottom: 1rem; 
    border-bottom: 1px solid #E5E7EB; 
}}

.page-header h1 {{ 
    margin: 0 !important; 
}}

.page-header p {{ 
    color: #6B7280; 
    font-size: 0.875rem; 
    margin: 0.25rem 0 0; 
}}

/* Layout interno adaptado a telefones: conteúdo nunca fica comprimido
   pelo menu desktop e colunas passam a ser lidas em sequência. */
@media (max-width: 768px) {{
    /* No celular, o conteúdo ocupa toda a largura disponível. */
    [data-testid="stSidebar"] {{
        display: none !important;
    }}

    [data-testid="stAppViewContainer"] {{
        --kineo-sidebar-space: 0px !important;
    }}

    [data-testid="stAppViewContainer"] > section.main,
    [data-testid="stAppViewContainer"] > .main,
    [data-testid="stMain"] {{
        margin-left: 0 !important;
        width: 100% !important;
    }}

    .block-container {{
        padding: 0.9rem 0.85rem 2rem !important;
    }}

    [data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap !important;
        gap: 0.85rem !important;
    }}

    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        width: 100% !important;
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }}

    .profile-wrapper,
    .sidebar-brand-wrapper {{
        display: none !important;
    }}
}}

/* Override final: hitbox integral limitado ao retângulo recuado dos subitens. */
@media (min-width: 769px) {{
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] [data-testid="stElementContainer"]:has([data-testid="stButton"]),
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] [data-testid="stElementContainer"]:has(.stButton),
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] .element-container:has(.stButton),
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] [data-testid="stButton"],
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] .stButton {{
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        min-width: 100% !important;
        max-width: none !important;
        height: 100% !important;
        min-height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        z-index: 20 !important;
    }}
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] [data-testid="stButton"] > button,
    [data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-kineo_nav_sub_"] .stButton > button {{
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        min-width: 100% !important;
        max-width: none !important;
        height: 100% !important;
        min-height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        opacity: 0 !important;
        pointer-events: auto !important;
        z-index: 20 !important;
    }}
}}
</style>
"""
st.markdown(css_template, unsafe_allow_html=True)


# ─── HELPERS & CACHE DE CONSULTAS (OTIMIZAÇÃO DE PERFORMANCE) ───────────────
@st.cache_data(ttl=60)
def carregar_dados_tabela(query, empresa_id, params=None):
    """Consulta tabular parametrizada; empresa_id nunca é interpolado no SQL."""
    parametros = {"empresa_id": int(empresa_id)}
    if params:
        parametros.update(params)
    with engine.connect() as conn:
        return pd.read_sql(sql_text(query), conn, params=parametros)

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')

def get_valid_date(year, month, day):
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, max_day))

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# ─── SEGURANÇA / SESSÃO / TENANT ─────────────────────────────────────────────
PRIVACY_VERSION = "1.1"
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 20
LOGIN_MAX_ATTEMPTS = 5
LOGIN_BLOCK_MINUTES = 3


def _config_value(nome, default=None):
    try:
        if hasattr(st, "secrets") and nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    return os.getenv(nome, default)


# ─── STORAGE PRIVADO ──────────────────────────────────────────────────────────
# DEV usa filesystem local. Homologação/produção exigem S3 para que comprovantes,
# logos e avatares sobrevivam a reinícios/escala horizontal do servidor.
STORAGE_BACKEND = str(
    _config_value("KINEO_STORAGE_BACKEND", "s3" if IS_MANAGED_ENV else "local")
).strip().lower()
S3_BUCKET = str(_config_value("KINEO_S3_BUCKET", "") or "").strip()
S3_PREFIX = str(_config_value("KINEO_S3_PREFIX", "kineo") or "kineo").strip("/")

if STORAGE_BACKEND not in {"local", "s3"}:
    raise RuntimeError("KINEO_STORAGE_BACKEND deve ser 'local' ou 's3'.")
if IS_MANAGED_ENV and STORAGE_BACKEND != "s3":
    raise RuntimeError(
        "Homologação/produção exigem KINEO_STORAGE_BACKEND=s3 para armazenamento persistente de arquivos."
    )
if STORAGE_BACKEND == "s3" and (not BOTO3_DISPONIVEL or not S3_BUCKET):
    raise RuntimeError(
        "Storage S3 selecionado, mas boto3/KINEO_S3_BUCKET não estão configurados corretamente."
    )

_S3_CLIENT = None

def _obter_s3_client():
    global _S3_CLIENT
    if _S3_CLIENT is None:
        _S3_CLIENT = boto3.client("s3")
    return _S3_CLIENT

def referencia_storage(chave):
    chave = str(chave or "").replace("\\", "/").lstrip("/")
    if STORAGE_BACKEND == "s3":
        key = f"{S3_PREFIX}/{chave}" if S3_PREFIX else chave
        return f"s3://{S3_BUCKET}/{key}"
    return chave

def _parse_s3_ref(ref):
    texto = str(ref or "")
    if not texto.startswith("s3://"):
        return None, None
    resto = texto[5:]
    bucket, _, key = resto.partition("/")
    return bucket, key

def salvar_bytes_privado(chave, dados, content_type="application/octet-stream"):
    ref = referencia_storage(chave)
    if ref.startswith("s3://"):
        bucket, key = _parse_s3_ref(ref)
        _obter_s3_client().put_object(
            Bucket=bucket, Key=key, Body=dados, ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return ref
    pasta = os.path.dirname(ref)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(ref, "wb") as f:
        f.write(dados)
    return ref

def ler_bytes_privado(ref):
    if not ref:
        return None
    if str(ref).startswith("s3://"):
        bucket, key = _parse_s3_ref(ref)
        try:
            return _obter_s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception:
            logger.exception("Falha ao ler arquivo privado do S3")
            return None
    try:
        with open(ref, "rb") as f:
            return f.read()
    except OSError:
        return None

def storage_existe(ref):
    if not ref:
        return False
    if str(ref).startswith("s3://"):
        bucket, key = _parse_s3_ref(ref)
        try:
            _obter_s3_client().head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return os.path.exists(ref)

def excluir_storage(ref):
    if not ref:
        return
    if str(ref).startswith("s3://"):
        bucket, key = _parse_s3_ref(ref)
        try:
            _obter_s3_client().delete_object(Bucket=bucket, Key=key)
        except Exception:
            logger.exception("Falha ao excluir arquivo privado do S3")
    else:
        try:
            if os.path.exists(ref):
                os.remove(ref)
        except OSError:
            logger.exception("Falha ao excluir arquivo privado local")

def salvar_upload_privado(uploaded_file, chave, content_type=None):
    ext = str(getattr(uploaded_file, "name", "")).rsplit(".", 1)[-1].lower()
    mime = content_type or {
        "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"
    }.get(ext, "application/octet-stream")
    return salvar_bytes_privado(chave, uploaded_file.getvalue(), mime)


try:
    SESSION_TIMEOUT_MINUTES = max(5, int(_config_value("KINEO_SESSION_TIMEOUT_MINUTES", 30)))
except Exception:
    SESSION_TIMEOUT_MINUTES = 30


COMMON_PASSWORDS = {
    "123456", "12345678", "123456789", "1234567890", "password", "senha",
    "senha123", "admin", "administrator", "qwerty", "qwerty123", "abc123",
    "111111", "000000", "iloveyou", "welcome", "bemvindo", "kineo",
    "kineo123", "primeiroacesso", "primeiroacesso123", "changeme",
}


def validar_nova_senha(senha, login="", nome=""):
    """Retorna uma lista de problemas encontrados na nova senha."""
    erros = []
    if senha is None:
        return ["Informe uma senha."]

    if len(senha) < PASSWORD_MIN_LENGTH:
        erros.append(f"Use pelo menos {PASSWORD_MIN_LENGTH} caracteres.")
    if len(senha) > PASSWORD_MAX_LENGTH:
        erros.append(f"Use no máximo {PASSWORD_MAX_LENGTH} caracteres.")

    normalizada = senha.strip().lower()
    if normalizada in COMMON_PASSWORDS:
        erros.append("Essa senha é muito comum. Escolha uma frase-senha mais difícil de adivinhar.")

    login_norm = str(login or "").strip().lower()
    nome_norm = str(nome or "").strip().lower()
    if login_norm and len(login_norm) >= 4 and login_norm in normalizada:
        erros.append("A senha não deve conter o seu login.")
    if nome_norm:
        partes_nome = [p for p in re.split(r"\s+", nome_norm) if len(p) >= 4]
        if any(p in normalizada for p in partes_nome):
            erros.append("Evite usar partes do seu nome na senha.")

    # Bloqueia padrões triviais muito previsíveis mesmo quando alongados.
    if len(set(senha)) <= 3:
        erros.append("A senha possui pouca variedade de caracteres.")

    return erros


def tenant_get(session, model, obj_id, empresa_id):
    """Busca um objeto sempre limitado à empresa autenticada."""
    if obj_id is None:
        return None
    return session.query(model).filter(
        model.id == int(obj_id),
        model.empresa_id == int(empresa_id),
    ).first()


def registrar_auditoria(session, empresa_id, usuario_id, acao, entidade=None, entidade_id=None, detalhes=None):
    """Registra ação sem armazenar senhas, tokens ou segredos."""
    try:
        session.add(Auditoria(
            empresa_id=int(empresa_id) if empresa_id is not None else None,
            usuario_id=int(usuario_id) if usuario_id is not None else None,
            acao=str(acao)[:120],
            entidade=str(entidade)[:120] if entidade else None,
            entidade_id=int(entidade_id) if entidade_id is not None else None,
            detalhes=str(detalhes)[:1000] if detalhes else None,
            criado_em=agora_utc(),
        ))
    except Exception:
        # A auditoria nunca deve quebrar a operação principal; a transação ainda
        # poderá registrar o erro nos logs da infraestrutura.
        pass


def encerrar_sessao(expirada=False):
    """Limpa dados de autenticação do session_state."""
    preservar = {
        "sidebar_pinned": st.session_state.get("sidebar_pinned", False),
        "uploader_key": st.session_state.get("uploader_key", 0),
    }
    for chave in list(st.session_state.keys()):
        del st.session_state[chave]
    st.session_state.update({
        "autenticado": False,
        "forcar_troca_senha": False,
        "tela_config": False,
        "privacidade_pendente": False,
        "privacidade_dialog_suspenso": False,
        "privacidade_rever": False,
        "ultima_atividade_ts": None,
        "sessao_expirada_aviso": bool(expirada),
        "credencial_temporaria": None,
        **preservar,
    })


def validar_timeout_sessao():
    if not st.session_state.get("autenticado"):
        return False
    agora = time.time()
    ultima = st.session_state.get("ultima_atividade_ts")
    if ultima is not None and agora - float(ultima) > SESSION_TIMEOUT_MINUTES * 60:
        encerrar_sessao(expirada=True)
        return True
    st.session_state["ultima_atividade_ts"] = agora
    return False


def registrar_ciencia_privacidade():
    session = SessionLocal()
    try:
        user = tenant_get(
            session,
            Usuario,
            st.session_state.get("usuario_id"),
            st.session_state.get("empresa_id"),
        )
        if user is not None:
            user.privacidade_versao_aceita = PRIVACY_VERSION
            user.privacidade_vista_em = agora_utc()
            registrar_auditoria(
                session,
                user.empresa_id,
                user.id,
                "PRIVACIDADE_CIENTE",
                "Usuario",
                user.id,
                f"Versão {PRIVACY_VERSION}",
            )
            session.commit()
            st.session_state["privacidade_pendente"] = False
            st.session_state["privacidade_rever"] = False
            st.session_state["privacidade_dialog_suspenso"] = False
    except Exception:
        session.rollback()
        st.error("Não foi possível registrar a ciência da política de privacidade.", icon=None)
    finally:
        session.close()


def validar_upload_basico(uploaded_file, tipos_permitidos, max_mb=10):
    """Validação por tamanho, extensão e assinatura básica do arquivo."""
    if uploaded_file is None:
        return True, None
    dados = uploaded_file.getvalue()
    if len(dados) > max_mb * 1024 * 1024:
        return False, f"Arquivo acima do limite de {max_mb} MB."

    nome = str(getattr(uploaded_file, "name", ""))
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if ext not in {e.lower().lstrip(".") for e in tipos_permitidos}:
        return False, "Tipo de arquivo não permitido."

    if ext == "png" and not dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return False, "O conteúdo não corresponde a uma imagem PNG válida."
    if ext in {"jpg", "jpeg"} and not dados.startswith(b"\xff\xd8\xff"):
        return False, "O conteúdo não corresponde a uma imagem JPEG válida."
    if ext == "pdf" and not dados.startswith(b"%PDF-"):
        return False, "O conteúdo não corresponde a um PDF válido."
    return True, None



def salvar_imagem_segura(uploaded_file, chave_png, max_mb=5):
    ok, erro = validar_upload_basico(uploaded_file, {"png", "jpg", "jpeg"}, max_mb=max_mb)
    if not ok:
        return False, erro, None
    try:
        dados = uploaded_file.getvalue()
        with Image.open(BytesIO(dados)) as img:
            img.verify()
        with Image.open(BytesIO(dados)) as img:
            img = img.convert("RGBA" if img.mode in {"RGBA", "LA"} else "RGB")
            img.thumbnail((2000, 2000))
            buffer = BytesIO()
            img.save(buffer, format="PNG", optimize=True)
            ref = salvar_bytes_privado(chave_png, buffer.getvalue(), "image/png")
        return True, None, ref
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "A imagem enviada é inválida ou está corrompida.", None
    except Exception:
        logger.exception("Falha ao persistir imagem no storage privado")
        return False, "Não foi possível armazenar a imagem.", None



def parse_valor_cobranca(valor):
    """Compatibilidade para valores monetários exibidos na aplicação."""
    return parse_valor_monetario_br(valor)

def decimal_monetario(valor):
    """Normaliza um valor monetário para Decimal(2), sem aritmética financeira em float."""
    if isinstance(valor, Decimal):
        return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(str(parse_valor_cobranca(valor))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dividir_valor_parcelas(valor, quantidade):
    """Divide o total sem perder centavos; o resíduo fica na última parcela."""
    total = decimal_monetario(valor)
    qtd = int(quantidade or 0)
    if qtd <= 0:
        raise ValueError("Quantidade de parcelas inválida.")
    base = (total / Decimal(qtd)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    parcelas = [base for _ in range(qtd)]
    parcelas[-1] = (total - base * Decimal(qtd - 1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return parcelas


def competencia_para_data(mes_ano):
    """Retorna o primeiro dia da competência MM/AAAA."""
    mes, ano = map(int, str(mes_ano).split("/"))
    return date(ano, mes, 1)


def intervalo_competencia(mes_ano):
    """Retorna primeiro e último dia da competência MM/AAAA."""
    inicio = competencia_para_data(mes_ano)
    ultimo = calendar.monthrange(inicio.year, inicio.month)[1]
    return inicio, date(inicio.year, inicio.month, ultimo)


def opcoes_competencias(meses_antes=12, meses_depois=18):
    base = hoje_local().replace(day=1)
    return [
        add_months(base, i).strftime("%m/%Y")
        for i in range(-meses_antes, meses_depois + 1)
    ]


def salvar_valor_variavel_competencia(session, empresa_id, contrato, mes_ano, valor):
    """Cria ou atualiza a receita prevista de um contrato variável na competência.

    O contrato guarda apenas a regra "Variável". O valor financeiro pertence à
    cobrança mensal (competência), evitando transformar um valor de um único mês
    em mensalidade fixa do contrato.
    """
    if contrato is None or int(contrato.empresa_id) != int(empresa_id):
        raise ValueError("Contrato não encontrado para esta empresa.")
    if str(contrato.tipo_valor or "") != "Variável":
        raise ValueError("O valor por competência só pode ser usado em contratos variáveis.")

    valor_num = parse_valor_cobranca(valor)
    if valor_num <= 0:
        raise ValueError("Informe um valor de competência maior que zero.")
    valor_decimal = decimal_monetario(valor)

    recorrente = session.query(CobrancaRecorrente).filter(
        CobrancaRecorrente.empresa_id == int(empresa_id),
        CobrancaRecorrente.contrato_id == int(contrato.id),
        CobrancaRecorrente.ativo == 1,
    ).order_by(CobrancaRecorrente.id.desc()).first()

    mensal = session.query(CobrancaMensal).filter(
        CobrancaMensal.empresa_id == int(empresa_id),
        CobrancaMensal.contrato_id == int(contrato.id),
        CobrancaMensal.mes_ano == str(mes_ano),
        CobrancaMensal.tipo == "Recorrente",
    ).order_by(CobrancaMensal.id.desc()).first()

    mes, ano = map(int, str(mes_ano).split("/"))

    if mensal is not None:
        if int(getattr(mensal, "liquidacao_congelada", 0) or 0) == 1 and mensal.valor_liquidado is not None:
            raise ValueError(
                "A competência já foi recebida e está congelada no histórico financeiro. "
                "Não é possível alterar o valor previsto desta liquidação."
            )
        mensal.valor_previsto = valor_decimal
        mensal.cliente = contrato.cliente
        mensal.multa = float(contrato.multa or 0)
        mensal.juros = float(contrato.juros or 0)
        if recorrente is not None:
            mensal.recorrente_id = recorrente.id
            if not mensal.forma_cobranca or mensal.forma_cobranca == "A definir":
                mensal.forma_cobranca = recorrente.forma_cobranca
            if mensal.emissao_prevista is None:
                dia_emissao = recorrente.dia_emissao or (recorrente.data_base_emissao.day if recorrente.data_base_emissao else 1)
                mensal.emissao_prevista = get_valid_date(ano, mes, int(dia_emissao))
            if mensal.vencimento is None:
                dia_vencimento = recorrente.dia_vencimento or (recorrente.data_base_vencimento.day if recorrente.data_base_vencimento else 10)
                mensal.vencimento = get_valid_date(ano, mes, int(dia_vencimento))
        return mensal, False

    if recorrente is not None:
        forma = recorrente.forma_cobranca
        dia_emissao = recorrente.dia_emissao or (recorrente.data_base_emissao.day if recorrente.data_base_emissao else 1)
        dia_vencimento = recorrente.dia_vencimento or (recorrente.data_base_vencimento.day if recorrente.data_base_vencimento else 10)
        observacoes = recorrente.observacoes
        recorrente_id = recorrente.id
    else:
        # A regra de faturamento poderá ser completada depois no Motor de Cobranças.
        forma = "A definir"
        dia_emissao = 1
        dia_vencimento = 10
        observacoes = "Valor informado no contrato variável; complete a regra de faturamento em Cobranças Recorrentes."
        recorrente_id = None

    mensal = CobrancaMensal(
        empresa_id=int(empresa_id),
        contrato_id=int(contrato.id),
        recorrente_id=recorrente_id,
        mes_ano=str(mes_ano),
        tipo="Recorrente",
        cliente=contrato.cliente,
        forma_cobranca=forma,
        valor_previsto=valor_decimal,
        emissao_prevista=get_valid_date(ano, mes, int(dia_emissao)),
        vencimento=get_valid_date(ano, mes, int(dia_vencimento)),
        status="Pendente de emissão",
        multa=float(contrato.multa or 0),
        juros=float(contrato.juros or 0),
        observacoes=observacoes,
    )
    session.add(mensal)
    session.flush()
    return mensal, True


def encerrar_cobrancas_contrato(session, empresa_id, contrato_id, data_fim):
    """Encerra o fluxo futuro de cobrança sem destruir histórico financeiro.

    Regras:
    - desativa todas as regras recorrentes ativas vinculadas ao contrato;
    - preserva competências do mês de encerramento e anteriores;
    - preserva cobranças já recebidas, mesmo que tenham sido registradas adiante;
    - cancela competências posteriores ao mês de encerramento que ainda não foram recebidas;
    - mantém valor original, datas e observações para rastreabilidade.
    """
    data_fim = coerce_date(data_fim)
    if data_fim is None:
        raise ValueError("Informe a data de encerramento do contrato.")

    empresa_id = int(empresa_id)
    contrato_id = int(contrato_id)
    competencia_limite = date(data_fim.year, data_fim.month, 1)

    recorrencias = session.query(CobrancaRecorrente).filter(
        CobrancaRecorrente.empresa_id == empresa_id,
        CobrancaRecorrente.contrato_id == contrato_id,
        CobrancaRecorrente.ativo == 1,
    ).all()
    for rec in recorrencias:
        rec.ativo = 0

    canceladas = 0
    mensais = session.query(CobrancaMensal).filter(
        CobrancaMensal.empresa_id == empresa_id,
        CobrancaMensal.contrato_id == contrato_id,
    ).all()

    for cobranca in mensais:
        status = normalizar_status_cobranca(cobranca.status)
        if status in ["Recebida", "Cancelada", "Não cobrar"]:
            continue

        competencia = None
        try:
            competencia = competencia_para_data(cobranca.mes_ano)
        except Exception:
            pass

        # A unidade financeira do Kineo é a competência mensal. Portanto,
        # o mês em que o contrato foi encerrado é preservado; apenas meses
        # posteriores deixam de ser cobrados automaticamente.
        eh_futura = competencia is not None and competencia > competencia_limite
        if competencia is None:
            vencimento = coerce_date(cobranca.vencimento)
            eh_futura = vencimento is not None and vencimento > data_fim

        if eh_futura:
            cobranca.status = "Cancelada"
            motivo = (
                f"Cancelada automaticamente pelo encerramento do contrato "
                f"em {data_fim.strftime('%d/%m/%Y')}."
            )
            obs_atual = str(cobranca.observacoes or "").strip()
            if motivo not in obs_atual:
                cobranca.observacoes = f"{obs_atual}\n{motivo}".strip()
            canceladas += 1

    return {
        "recorrencias_desativadas": len(recorrencias),
        "cobrancas_canceladas": canceladas,
    }


def contrato_pode_ser_excluido(session, empresa_id, contrato_id):
    """Permite exclusão física apenas quando não existe histórico operacional/financeiro."""
    empresa_id = int(empresa_id)
    contrato_id = int(contrato_id)
    quantidades = {
        "custos": session.query(Custo).filter(
            Custo.empresa_id == empresa_id,
            Custo.contrato_id == contrato_id,
        ).count(),
        "cobrancas": session.query(CobrancaMensal).filter(
            CobrancaMensal.empresa_id == empresa_id,
            CobrancaMensal.contrato_id == contrato_id,
        ).count(),
        "substituicoes": session.query(SubstituicaoContrato).filter(
            SubstituicaoContrato.empresa_id == empresa_id,
            SubstituicaoContrato.contrato_id == contrato_id,
        ).count(),
    }
    return not any(quantidades.values()), quantidades


def veiculo_pode_ser_excluido(session, empresa_id, veiculo_id):
    """Exclusão física somente para cadastro sem qualquer histórico; caso contrário, arquiva."""
    empresa_id = int(empresa_id)
    veiculo_id = int(veiculo_id)
    quantidades = {
        "custos": session.query(Custo).filter(Custo.empresa_id == empresa_id, Custo.veiculo_id == veiculo_id).count(),
        "contratos": session.query(Contrato).filter(Contrato.empresa_id == empresa_id, Contrato.veiculo_id == veiculo_id).count(),
        "contratos_ativos": session.query(Contrato).filter(Contrato.empresa_id == empresa_id, Contrato.veiculo_id == veiculo_id, Contrato.ativo == 1).count(),
        "manutencoes": session.query(ManutencaoRealizada).filter(ManutencaoRealizada.empresa_id == empresa_id, ManutencaoRealizada.veiculo_id == veiculo_id).count(),
        "substituicoes": session.query(SubstituicaoContrato).filter(
            SubstituicaoContrato.empresa_id == empresa_id,
            (SubstituicaoContrato.veiculo_principal_id == veiculo_id) | (SubstituicaoContrato.veiculo_substituto_id == veiculo_id),
        ).count(),
    }
    tem_historico = any(v for k, v in quantidades.items() if k != "contratos_ativos")
    return not tem_historico, quantidades


def normalizar_status_cobranca(status):
    status = str(status or "").strip()
    if status == "Pendente":
        return "Pendente de emissão"
    return status or "Pendente de emissão"


def coerce_date(valor):
    """Normaliza valores vindos do Streamlit/Pandas para datetime.date.

    O data_editor pode devolver DateColumn como date, datetime, Timestamp ou
    string ISO (AAAA-MM-DD). O SQLAlchemy Date exige um objeto date real.
    """
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass

    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    convertido = pd.to_datetime(valor, errors="coerce")
    if pd.isna(convertido):
        return None
    if isinstance(convertido, pd.Timestamp):
        return convertido.date()
    try:
        return convertido.to_pydatetime().date()
    except Exception:
        return None


def preparar_datas_para_editor(df, colunas):
    """Converte colunas de data carregadas via SQL em datetime64 para o st.data_editor.

    Em SQLite, pandas.read_sql pode devolver colunas DATE como strings ISO.
    O Streamlit DateColumn exige uma coluna com tipo de data compatível antes
    mesmo da edição. Na volta do editor, coerce_date() converte para date.
    """
    df = df.copy()
    for coluna in colunas:
        if coluna in df.columns:
            df[coluna] = pd.to_datetime(df[coluna], errors="coerce")
    return df


def dias_atraso_cobranca(vencimento, status, data_recebimento=None):
    """Calcula os dias de atraso da cobrança.

    Regra financeira:
    - se houver data de recebimento, ela prevalece sobre o status e congela o atraso;
    - se ainda não houver recebimento, cobranças abertas usam a data de hoje;
    - Cancelada e Não cobrar nunca geram encargos.

    Isso evita o cenário inconsistente em que o financeiro informa o recebimento,
    mas esquece de mudar manualmente o status para Recebida.
    """
    venc = coerce_date(vencimento)
    if venc is None:
        return 0

    status_norm = normalizar_status_cobranca(status)
    if status_norm in ["Cancelada", "Não cobrar"]:
        return 0

    receb = coerce_date(data_recebimento)
    if receb is not None:
        return max((receb - venc).days, 0)

    if status_norm == "Recebida":
        # Status recebido sem data não permite determinar o atraso com segurança.
        return 0

    return max((hoje_local() - venc).days, 0)


def calcular_encargos_cobranca(
    valor_previsto,
    vencimento,
    status,
    data_recebimento=None,
    multa_percentual=0,
    juros_mensal_percentual=0,
):
    """Calcula multa, juros simples pró-rata e valor atualizado da cobrança.

    Regra adotada:
    - multa: aplicada uma única vez quando há pelo menos 1 dia de atraso;
    - juros: percentual mensal simples, proporcional aos dias de atraso / 30;
    - havendo data de recebimento: atraso é calculado até essa data, independentemente do status selecionado;
    - cobrança ainda aberta: atraso é calculado até hoje.
    """
    try:
        principal = decimal_monetario(valor_previsto)
    except Exception:
        principal = Decimal("0.00")

    dias = dias_atraso_cobranca(vencimento, status, data_recebimento)
    status_norm = normalizar_status_cobranca(status)
    if dias <= 0 or status_norm in ["Cancelada", "Não cobrar"]:
        return {
            "dias_atraso": 0,
            "valor_multa": Decimal("0.00"),
            "valor_juros": Decimal("0.00"),
            "valor_atualizado": principal,
        }

    try:
        pct_multa = Decimal(str(multa_percentual or 0))
    except Exception:
        pct_multa = Decimal("0")
    try:
        pct_juros = Decimal(str(juros_mensal_percentual or 0))
    except Exception:
        pct_juros = Decimal("0")

    valor_multa = (principal * pct_multa / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    valor_juros = (
        principal
        * pct_juros
        / Decimal("100")
        * Decimal(dias)
        / Decimal("30")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "dias_atraso": dias,
        "valor_multa": valor_multa,
        "valor_juros": valor_juros,
        "valor_atualizado": (principal + valor_multa + valor_juros).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
    }


def encargos_cobranca_exibicao(registro):
    """Usa a liquidação congelada quando existente; caso contrário calcula a posição atual."""
    try:
        congelada = int(registro.get("liquidacao_congelada") or 0) == 1
    except Exception:
        congelada = False
    valor_liquidado = registro.get("valor_liquidado")
    if congelada and pd.notna(valor_liquidado):
        return {
            "dias_atraso": int(registro.get("dias_atraso_liquidacao") or 0),
            "valor_multa": decimal_monetario(registro.get("multa_aplicada") or 0),
            "valor_juros": decimal_monetario(registro.get("juros_aplicados") or 0),
            "valor_atualizado": decimal_monetario(valor_liquidado),
        }
    return calcular_encargos_cobranca(
        registro.get("valor_previsto"), registro.get("vencimento"), registro.get("status"),
        registro.get("data_recebimento"), registro.get("multa"), registro.get("juros"),
    )


def congelar_liquidacao(cobranca, valor_principal, data_recebimento, multa_percentual, juros_percentual):
    """Persiste o retrato financeiro da liquidação; o passado deixa de ser recalculável."""
    if cobranca is None:
        raise ValueError("Cobrança não encontrada.")
    if int(getattr(cobranca, "liquidacao_congelada", 0) or 0) == 1 and cobranca.valor_liquidado is not None:
        return
    receb = coerce_date(data_recebimento)
    if receb is None:
        raise ValueError("Informe a data de recebimento para concluir a liquidação.")
    principal = decimal_monetario(valor_principal)
    encargos = calcular_encargos_cobranca(
        principal, cobranca.vencimento, "Recebida", receb, multa_percentual, juros_percentual
    )
    cobranca.valor_previsto = principal
    cobranca.data_recebimento = receb
    cobranca.status = "Recebida"
    cobranca.multa = float(multa_percentual or 0)
    cobranca.juros = float(juros_percentual or 0)
    cobranca.valor_principal_liquidado = principal
    cobranca.multa_aplicada = encargos["valor_multa"]
    cobranca.juros_aplicados = encargos["valor_juros"]
    cobranca.dias_atraso_liquidacao = int(encargos["dias_atraso"])
    cobranca.valor_liquidado = encargos["valor_atualizado"]
    cobranca.liquidacao_congelada = 1
    cobranca.liquidado_em = agora_utc()


def obter_contrato_por_veiculo_data(session, empresa_id, veiculo_id, data_ref):
    """
    Resolve o centro de resultado de um custo pela data e veículo.
    Prioriza contrato atendido como veículo reserva; depois o contrato do veículo principal.
    """
    if not data_ref or not veiculo_id:
        return None

    substituicoes = session.query(SubstituicaoContrato).filter(
        SubstituicaoContrato.empresa_id == empresa_id,
        SubstituicaoContrato.veiculo_substituto_id == veiculo_id,
        SubstituicaoContrato.data_inicio <= data_ref
    ).order_by(SubstituicaoContrato.data_inicio.desc()).all()

    for sub in substituicoes:
        if sub.data_fim is None or sub.data_fim >= data_ref:
            contrato = tenant_get(session, Contrato, sub.contrato_id, empresa_id)
            if contrato is not None:
                return contrato

    contratos = session.query(Contrato).filter(
        Contrato.empresa_id == empresa_id,
        Contrato.veiculo_id == veiculo_id,
        Contrato.data_inicio <= data_ref
    ).order_by(Contrato.data_inicio.desc()).all()

    for contrato in contratos:
        if contrato.data_fim is None or contrato.data_fim >= data_ref:
            return contrato

    return None

def page_header(title: str, subtitle: str = ""):
    title_safe = html.escape(str(title or ""))
    subtitle_safe = html.escape(str(subtitle or ""))
    st.markdown(f"""
    <div class="page-header">
        <h1>{title_safe}</h1>
        {"<p>" + subtitle_safe + "</p>" if subtitle_safe else ""}
    </div>
    """, unsafe_allow_html=True)

def fmt_brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def aplicar_css_dashboard_v11():
    """Aplica o tema executivo somente à tela do Painel Gerencial V11."""
    st.markdown(
        """
<style>
/* Streamlit varia o nome do container principal entre versões.
   Todos os seletores abaixo mantêm o dashboard junto ao topo da viewport. */
.block-container:has(.kineo-dashboard-v11),
[data-testid="stMainBlockContainer"]:has(.kineo-dashboard-v11),
[data-testid="stMain"] .block-container:has(.kineo-dashboard-v11),
section.main .block-container:has(.kineo-dashboard-v11) {
    width: 100% !important;
    max-width: none !important;
    margin-top: 0 !important;
    padding-top: .5rem !important;
    padding-bottom: 2rem !important;
}

.kineo-dashboard-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 22px;
    margin-bottom: 14px;
    padding: 18px 24px;
    border: 1px solid #D8E6F7;
    border-radius: 22px;
    background:
        radial-gradient(circle at 88% 14%, rgba(80, 155, 255, .20), transparent 29%),
        linear-gradient(135deg, #F8FBFF 0%, #EEF5FF 62%, #E5F0FF 100%);
    box-shadow: 0 15px 36px rgba(26, 73, 131, .08);
}

.kineo-dashboard-hero h1 {
    margin: 3px 0 5px;
    color: #0D2A56;
    font-size: clamp(1.5rem, 2vw, 2rem);
    line-height: 1.1;
    letter-spacing: -.045em;
}

.kineo-dashboard-hero p {
    max-width: 760px;
    margin: 0;
    color: #5F7290;
    font-size: .86rem;
    line-height: 1.4;
}

.kineo-dashboard-eyebrow {
    color: #1768E5;
    font-size: .72rem;
    font-weight: 800;
    letter-spacing: .14em;
    text-transform: uppercase;
}

.kineo-dashboard-period {
    min-width: 175px;
    padding: 11px 14px;
    border: 1px solid rgba(23, 104, 229, .15);
    border-radius: 15px;
    background: rgba(255, 255, 255, .72);
    box-shadow: 0 10px 24px rgba(26, 73, 131, .07);
}

.kineo-dashboard-period span,
.kineo-dashboard-period strong {
    display: block;
}

.kineo-dashboard-period span {
    margin-bottom: 4px;
    color: #73839B;
    font-size: .69rem;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
}

.kineo-dashboard-period strong {
    color: #153A66;
    font-size: .96rem;
}

.kineo-section-heading {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 16px;
    margin: 2px 0 8px;
}

.kineo-section-heading h2 {
    margin: 0;
    color: #17385F;
    font-size: 1.04rem;
    letter-spacing: -.015em;
}

.kineo-section-heading p {
    margin: 4px 0 0;
    color: #74849B;
    font-size: .78rem;
}

.kineo-kpi-card {
    min-height: 112px;
    padding: 14px 15px;
    border: 1px solid #E0E9F4;
    border-radius: 18px;
    background: #FFFFFF;
    box-shadow: 0 10px 28px rgba(31, 68, 112, .065);
}

.kineo-kpi-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.kineo-kpi-label {
    color: #65758D;
    font-size: .76rem;
    font-weight: 700;
}

.kineo-kpi-icon {
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 11px;
    font-size: .84rem;
    font-weight: 850;
}

.kineo-kpi-icon.green { color: #087A58; background: #E4F7F0; }
.kineo-kpi-icon.red { color: #C13B4D; background: #FDECEF; }
.kineo-kpi-icon.blue { color: #1768E5; background: #EAF2FF; }
.kineo-kpi-icon.indigo { color: #5A54C7; background: #EEEDFF; }
.kineo-kpi-icon.amber { color: #A96505; background: #FFF3DB; }

.kineo-kpi-value {
    margin-top: 8px;
    color: #102E55;
    font-size: clamp(1.25rem, 1.75vw, 1.72rem);
    font-weight: 820;
    line-height: 1.1;
    letter-spacing: -.035em;
}

.kineo-kpi-detail {
    margin-top: 5px;
    color: #7A899D;
    font-size: .7rem;
    line-height: 1.35;
}

.kineo-mini-stat {
    min-height: 62px;
    padding: 10px 13px;
    border: 1px solid #E5ECF5;
    border-radius: 15px;
    background: #F9FBFE;
}

.kineo-mini-stat span,
.kineo-mini-stat strong { display: block; }
.kineo-mini-stat span { color: #738198; font-size: .7rem; font-weight: 650; }
.kineo-mini-stat strong { margin-top: 3px; color: #17385F; font-size: 1.08rem; }

.kineo-alert-card,
.kineo-ok-card {
    min-height: 125px;
    padding: 17px;
    border-radius: 16px;
}

.kineo-alert-card {
    border: 1px solid #F3D8A6;
    background: #FFF9ED;
}

.kineo-alert-card .tag {
    display: inline-block;
    margin-bottom: 10px;
    padding: 3px 8px;
    border-radius: 999px;
    color: #985B06;
    background: #FFEBC5;
    font-size: .61rem;
    font-weight: 800;
    letter-spacing: .05em;
    text-transform: uppercase;
}

.kineo-alert-card strong { display: block; color: #5E431D; font-size: .88rem; }
.kineo-alert-card p { margin: 6px 0 0; color: #806A4A; font-size: .72rem; line-height: 1.45; }

.kineo-ok-card {
    min-height: auto;
    border: 1px solid #CDEBDD;
    color: #147253;
    background: #F0FAF6;
    font-size: .84rem;
    font-weight: 650;
}

.kineo-contract-row,
.kineo-health-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 12px 0;
    border-bottom: 1px solid #EDF1F6;
}

.kineo-contract-row:last-child,
.kineo-health-row:last-child { border-bottom: 0; }
.kineo-contract-row span,
.kineo-health-row span { color: #67768C; font-size: .78rem; }
.kineo-contract-row strong,
.kineo-health-row strong { color: #17385F; font-size: .82rem; text-align: right; }

.block-container:has(.kineo-dashboard-v11) [data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #E1EAF4 !important;
    border-radius: 18px !important;
    background: #FFFFFF;
    box-shadow: 0 10px 28px rgba(31, 68, 112, .055);
}

.block-container:has(.kineo-dashboard-v11) [data-testid="stButton"] button {
    min-height: 42px;
    border-radius: 11px;
}

@media (max-width: 900px) {
    .kineo-dashboard-hero { align-items: flex-start; flex-direction: column; padding: 22px; }
    .kineo-dashboard-period { min-width: 0; width: 100%; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def dashboard_kpi_card(titulo, valor, detalhe, icone, tom="blue"):
    """Renderiza um KPI executivo com valores escapados para HTML."""
    tons_validos = {"green", "red", "blue", "indigo", "amber"}
    tom_seguro = tom if tom in tons_validos else "blue"
    st.markdown(
        f"""
        <div class="kineo-kpi-card">
            <div class="kineo-kpi-top">
                <span class="kineo-kpi-label">{html.escape(str(titulo))}</span>
                <span class="kineo-kpi-icon {tom_seguro}">{html.escape(str(icone))}</span>
            </div>
            <div class="kineo-kpi-value">{html.escape(str(valor))}</div>
            <div class="kineo-kpi-detail">{html.escape(str(detalhe))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def dashboard_mini_stat(titulo, valor):
    """Renderiza um indicador operacional compacto."""
    st.markdown(
        f"""
        <div class="kineo-mini-stat">
            <span>{html.escape(str(titulo))}</span>
            <strong>{html.escape(str(valor))}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


def aplicar_css_gestao_frota_v11():
    """Moderniza a Gestão de Frota sem interferir nas demais telas."""
    st.markdown(
        """
<style>
.block-container:has(.kineo-frota-v11) {
    max-width: 1600px;
    padding-top: 1.35rem;
    padding-bottom: 2.5rem;
}

.kineo-frota-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    margin-bottom: 20px;
    padding: 25px 28px;
    border: 1px solid #D8E6F7;
    border-radius: 21px;
    background:
        radial-gradient(circle at 90% 15%, rgba(45, 134, 255, .18), transparent 27%),
        linear-gradient(135deg, #F8FBFF 0%, #EEF5FF 64%, #E5F0FF 100%);
    box-shadow: 0 14px 34px rgba(26, 73, 131, .075);
}

.kineo-frota-eyebrow {
    color: #1768E5;
    font-size: .7rem;
    font-weight: 800;
    letter-spacing: .14em;
    text-transform: uppercase;
}

.kineo-frota-hero h1 {
    margin: 5px 0 7px;
    color: #0D2A56;
    font-size: clamp(1.65rem, 2.25vw, 2.25rem);
    line-height: 1.1;
    letter-spacing: -.04em;
}

.kineo-frota-hero p {
    max-width: 780px;
    margin: 0;
    color: #5F7290;
    font-size: .9rem;
    line-height: 1.5;
}

.kineo-frota-total {
    min-width: 145px;
    padding: 14px 17px;
    border: 1px solid rgba(23, 104, 229, .15);
    border-radius: 15px;
    background: rgba(255, 255, 255, .78);
    text-align: right;
}

.kineo-frota-total span,
.kineo-frota-total strong { display: block; }
.kineo-frota-total span { color: #718199; font-size: .68rem; font-weight: 700; text-transform: uppercase; }
.kineo-frota-total strong { margin-top: 2px; color: #153A66; font-size: 1.55rem; }

.kineo-frota-stat {
    min-height: 106px;
    padding: 17px 18px;
    border: 1px solid #E1EAF4;
    border-radius: 17px;
    background: #FFFFFF;
    box-shadow: 0 9px 25px rgba(31, 68, 112, .055);
}

.kineo-frota-stat-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.kineo-frota-stat span { color: #68788F; font-size: .73rem; font-weight: 700; }
.kineo-frota-stat strong { display: block; margin-top: 10px; color: #17385F; font-size: 1.42rem; line-height: 1; }
.kineo-frota-stat small { display: block; margin-top: 7px; color: #8794A7; font-size: .65rem; }
.kineo-frota-dot { width: 9px; height: 9px; border-radius: 50%; }
.kineo-frota-dot.blue { background: #1768E5; box-shadow: 0 0 0 5px #EAF2FF; }
.kineo-frota-dot.green { background: #17A673; box-shadow: 0 0 0 5px #E7F7F1; }
.kineo-frota-dot.indigo { background: #6765D8; box-shadow: 0 0 0 5px #EFEEFF; }
.kineo-frota-dot.amber { background: #E59A23; box-shadow: 0 0 0 5px #FFF3DF; }

.block-container:has(.kineo-frota-v11) [data-testid="stTabs"] {
    margin-top: 18px;
}

.block-container:has(.kineo-frota-v11) [data-baseweb="tab-list"] {
    gap: 7px;
    padding: 6px;
    border: 1px solid #E0E8F2;
    border-radius: 14px;
    background: #F5F8FC;
}

.block-container:has(.kineo-frota-v11) [data-baseweb="tab"] {
    min-height: 40px;
    padding: 8px 14px;
    border-radius: 10px;
    color: #607189;
    font-size: .76rem;
    font-weight: 650;
}

.block-container:has(.kineo-frota-v11) [data-baseweb="tab"][aria-selected="true"] {
    color: #145FCF;
    background: #FFFFFF;
    box-shadow: 0 4px 13px rgba(28, 72, 124, .09);
}

.block-container:has(.kineo-frota-v11) [data-baseweb="tab-highlight"] { display: none; }

.block-container:has(.kineo-frota-v11) [data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #E1EAF4 !important;
    border-radius: 18px !important;
    background: #FFFFFF;
    box-shadow: 0 9px 26px rgba(31, 68, 112, .05);
}

.block-container:has(.kineo-frota-v11) [data-testid="stForm"],
.block-container:has(.kineo-frota-v11) [data-testid="stExpander"] {
    border-color: #E1EAF4 !important;
    border-radius: 15px !important;
}

.block-container:has(.kineo-frota-v11) [data-testid="stButton"] button,
.block-container:has(.kineo-frota-v11) [data-testid="stDownloadButton"] button {
    min-height: 41px;
    border-radius: 10px;
}

.block-container:has(.kineo-frota-v11) [data-testid="stDataFrame"] {
    overflow: hidden;
    border: 1px solid #E3EAF3;
    border-radius: 13px;
}

.kineo-frota-overview-head {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 18px;
    margin: 8px 0 16px;
}

.kineo-frota-overview-head h2 {
    margin: 0;
    color: #17385F;
    font-size: 1.08rem;
}

.kineo-frota-overview-head p {
    margin: 4px 0 0;
    color: #77869B;
    font-size: .77rem;
}

.kineo-frota-insight {
    min-height: 105px;
    padding: 16px;
    border: 1px solid #E2EAF4;
    border-radius: 15px;
    background: #F9FBFE;
}

.kineo-frota-insight span,
.kineo-frota-insight strong,
.kineo-frota-insight small { display: block; }
.kineo-frota-insight span { color: #738198; font-size: .67rem; font-weight: 750; text-transform: uppercase; }
.kineo-frota-insight strong { margin-top: 8px; color: #17385F; font-size: 1.18rem; }
.kineo-frota-insight small { margin-top: 6px; color: #8290A3; font-size: .68rem; line-height: 1.4; }

@media (max-width: 900px) {
    .kineo-frota-hero { align-items: flex-start; flex-direction: column; padding: 21px; }
    .kineo-frota-total { min-width: 0; width: 100%; text-align: left; }
    .block-container:has(.kineo-frota-v11) [data-baseweb="tab-list"] { overflow-x: auto; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def frota_stat_card(titulo, valor, detalhe, tom="blue"):
    tons_validos = {"blue", "green", "indigo", "amber"}
    tom_seguro = tom if tom in tons_validos else "blue"
    st.markdown(
        f"""
        <div class="kineo-frota-stat">
            <div class="kineo-frota-stat-top">
                <span>{html.escape(str(titulo))}</span>
                <i class="kineo-frota-dot {tom_seguro}"></i>
            </div>
            <strong>{html.escape(str(valor))}</strong>
            <small>{html.escape(str(detalhe))}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


def aplicar_css_modulos_v11():
    """Linguagem visual compartilhada pelos módulos operacionais internos."""
    st.markdown(
        """
<style>
.block-container:has(.kineo-module-v11) {
    max-width: 1600px;
    padding-top: 1.35rem;
    padding-bottom: 2.5rem;
}
.kineo-module-hero {
    display:flex; align-items:center; justify-content:space-between; gap:24px;
    margin-bottom:20px; padding:25px 28px; border:1px solid #D8E6F7;
    border-radius:21px;
    background:radial-gradient(circle at 90% 15%,rgba(45,134,255,.17),transparent 27%),linear-gradient(135deg,#F8FBFF 0%,#EEF5FF 64%,#E5F0FF 100%);
    box-shadow:0 14px 34px rgba(26,73,131,.075);
}
.kineo-module-eyebrow { color:#1768E5; font-size:.7rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
.kineo-module-hero h1 { margin:5px 0 7px; color:#0D2A56; font-size:clamp(1.65rem,2.25vw,2.25rem); line-height:1.1; letter-spacing:-.04em; }
.kineo-module-hero p { max-width:790px; margin:0; color:#5F7290; font-size:.9rem; line-height:1.5; }
.kineo-module-badge { min-width:150px; padding:14px 17px; border:1px solid rgba(23,104,229,.15); border-radius:15px; background:rgba(255,255,255,.78); text-align:right; }
.kineo-module-badge span,.kineo-module-badge strong { display:block; }
.kineo-module-badge span { color:#718199; font-size:.66rem; font-weight:700; text-transform:uppercase; }
.kineo-module-badge strong { margin-top:3px; color:#153A66; font-size:1.38rem; }
.kineo-module-stat { min-height:105px; padding:17px 18px; border:1px solid #E1EAF4; border-radius:17px; background:#FFF; box-shadow:0 9px 25px rgba(31,68,112,.055); }
.kineo-module-stat span,.kineo-module-stat strong,.kineo-module-stat small { display:block; }
.kineo-module-stat span { color:#68788F; font-size:.71rem; font-weight:700; }
.kineo-module-stat strong { margin-top:10px; color:#17385F; font-size:1.32rem; line-height:1; }
.kineo-module-stat small { margin-top:7px; color:#8794A7; font-size:.65rem; line-height:1.35; }
.kineo-account-card { display:flex; align-items:center; gap:20px; padding:22px; border:1px solid #E1EAF4; border-radius:18px; background:#FFF; box-shadow:0 9px 26px rgba(31,68,112,.05); }
.kineo-account-avatar { display:grid; width:78px; height:78px; flex:0 0 78px; place-items:center; overflow:hidden; border-radius:22px; color:#FFF; background:linear-gradient(145deg,#1768E5,#5BA4FF); font-size:1.55rem; font-weight:850; box-shadow:0 12px 25px rgba(23,104,229,.2); }
.kineo-account-avatar img { width:100%; height:100%; object-fit:cover; }
.kineo-account-card h2 { margin:0; color:#17385F; font-size:1.2rem; }
.kineo-account-card p { margin:5px 0 0; color:#708097; font-size:.78rem; }
.kineo-account-role { display:inline-block; margin-top:9px; padding:4px 9px; border-radius:999px; color:#1768E5; background:#EAF2FF; font-size:.63rem; font-weight:750; text-transform:uppercase; }
.kineo-info-row { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:13px 0; border-bottom:1px solid #EDF1F6; }
.kineo-info-row:last-child { border-bottom:0; }
.kineo-info-row span { color:#708097; font-size:.75rem; }
.kineo-info-row strong { color:#17385F; font-size:.78rem; text-align:right; }
.block-container:has(.kineo-module-v11) [data-testid="stTabs"] { margin-top:18px; }
.block-container:has(.kineo-module-v11) [data-baseweb="tab-list"] { gap:7px; padding:6px; border:1px solid #E0E8F2; border-radius:14px; background:#F5F8FC; }
.block-container:has(.kineo-module-v11) [data-baseweb="tab"] { min-height:40px; padding:8px 14px; border-radius:10px; color:#607189; font-size:.76rem; font-weight:650; }
.block-container:has(.kineo-module-v11) [data-baseweb="tab"][aria-selected="true"] { color:#145FCF; background:#FFF; box-shadow:0 4px 13px rgba(28,72,124,.09); }
.block-container:has(.kineo-module-v11) [data-baseweb="tab-highlight"] { display:none; }
.block-container:has(.kineo-module-v11) [data-testid="stVerticalBlockBorderWrapper"] { border-color:#E1EAF4 !important; border-radius:18px !important; background:#FFF; box-shadow:0 9px 26px rgba(31,68,112,.05); }
.block-container:has(.kineo-module-v11) [data-testid="stForm"],.block-container:has(.kineo-module-v11) [data-testid="stExpander"] { border-color:#E1EAF4 !important; border-radius:15px !important; }
.block-container:has(.kineo-module-v11) [data-testid="stButton"] button,.block-container:has(.kineo-module-v11) [data-testid="stDownloadButton"] button { min-height:41px; border-radius:10px; }
.block-container:has(.kineo-module-v11) [data-testid="stDataFrame"] { overflow:hidden; border:1px solid #E3EAF3; border-radius:13px; }
@media(max-width:900px){.kineo-module-hero{align-items:flex-start;flex-direction:column;padding:21px}.kineo-module-badge{min-width:0;width:100%;text-align:left}.block-container:has(.kineo-module-v11) [data-baseweb="tab-list"]{overflow-x:auto}}
</style>
        """,
        unsafe_allow_html=True,
    )


def module_hero(eyebrow, titulo, subtitulo, badge_label, badge_value):
    st.markdown(
        f"""
        <div class="kineo-module-v11"></div>
        <div class="kineo-module-hero">
            <div>
                <div class="kineo-module-eyebrow">{html.escape(str(eyebrow))}</div>
                <h1>{html.escape(str(titulo))}</h1>
                <p>{html.escape(str(subtitulo))}</p>
            </div>
            <div class="kineo-module-badge">
                <span>{html.escape(str(badge_label))}</span>
                <strong>{html.escape(str(badge_value))}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def module_stat_card(titulo, valor, detalhe):
    st.markdown(
        f"""
        <div class="kineo-module-stat">
            <span>{html.escape(str(titulo))}</span>
            <strong>{html.escape(str(valor))}</strong>
            <small>{html.escape(str(detalhe))}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _texto_planilha(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor).strip()


def _numero_planilha(valor, inteiro=False):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or str(valor).strip() == "":
        return None
    try:
        if isinstance(valor, str):
            texto = valor.strip().replace(" ", "")
            if "," in texto and "." in texto:
                texto = texto.replace(".", "").replace(",", ".")
            elif "," in texto:
                texto = texto.replace(",", ".")
            elif texto.count(".") == 1:
                esquerda, direita = texto.split(".")
                if direita.isdigit() and len(direita) == 3 and esquerda.replace("-", "").isdigit():
                    texto = esquerda + direita
            numero = float(texto)
        else:
            numero = float(valor)
        return int(numero) if inteiro else numero
    except Exception:
        return None


def _nome_plano_padrao(row):
    partes = [
        _texto_planilha(row.get("fabricante")),
        _texto_planilha(row.get("modelo")),
        _texto_planilha(row.get("ano_modelo")),
        _texto_planilha(row.get("motorizacao")),
    ]
    partes = [p for p in partes if p and p.upper() != "NAN"]
    return "Plano " + " ".join(partes) if partes else "Plano de manutenção"


def _intervalo_efetivo(valor_empresa, valor_fabricante):
    empresa = _numero_planilha(valor_empresa)
    fabricante = _numero_planilha(valor_fabricante)
    if empresa is not None and empresa > 0:
        return empresa
    if fabricante is not None and fabricante > 0:
        return fabricante
    return None


def gerar_planilha_planos(df_base):
    """Gera o modelo XLSX usado tanto na importação individual quanto massiva."""
    colunas = [
        "placa", "fabricante", "modelo", "ano_modelo", "versao", "motorizacao",
        "combustivel", "transmissao", "nome_plano", "codigo_servico",
        "tipo_manutencao", "descricao_servico", "intervalo_fabricante_km",
        "intervalo_fabricante_meses", "intervalo_empresa_km", "intervalo_empresa_meses",
        "ultima_manutencao_km", "ultima_manutencao_data", "observacoes"
    ]
    df_saida = df_base.copy()
    for col in colunas:
        if col not in df_saida.columns:
            df_saida[col] = ""
    df_saida = df_saida[colunas]

    instrucoes = pd.DataFrame({
        "Campo": [
            "placa", "nome_plano", "tipo_manutencao", "intervalo_fabricante_km",
            "intervalo_fabricante_meses", "intervalo_empresa_km", "intervalo_empresa_meses",
            "ultima_manutencao_km", "ultima_manutencao_data"
        ],
        "Orientação": [
            "Placa existente no Kineo. É a chave do histórico individual do veículo.",
            "Nome do plano-base. Veículos equivalentes podem usar exatamente o mesmo nome.",
            "Serviço estruturado, por exemplo: Troca de óleo do motor.",
            "Intervalo em KM recomendado pelo fabricante.",
            "Intervalo em meses recomendado pelo fabricante.",
            "Opcional. Se preenchido, substitui o intervalo de KM do fabricante na operação.",
            "Opcional. Se preenchido, substitui o intervalo em meses do fabricante.",
            "KM da última execução conhecida deste serviço para esta placa.",
            "Data da última execução conhecida. Use DD/MM/AAAA ou uma data válida do Excel."
        ]
    })

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_saida.to_excel(writer, index=False, sheet_name="Planos")
        instrucoes.to_excel(writer, index=False, sheet_name="Instruções")
    buffer.seek(0)
    return buffer.getvalue()


def diagnostico_manutencao(empresa_id):
    """Calcula a situação de cada item de manutenção a partir do plano e do histórico real."""
    df_v = carregar_dados_tabela(f"""
        SELECT id, placa, fabricante, modelo, ano_modelo, versao, motorizacao,
               km_atual, status, plano_manutencao_id
        FROM veiculos
        WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1 AND plano_manutencao_id IS NOT NULL
        ORDER BY modelo, placa
    """, empresa_id)

    if df_v.empty:
        return pd.DataFrame()

    df_itens = carregar_dados_tabela(f"""
        SELECT i.id, i.plano_id, i.codigo_servico, i.tipo_manutencao, i.descricao,
               i.intervalo_fabricante_km, i.intervalo_fabricante_meses,
               i.intervalo_empresa_km, i.intervalo_empresa_meses
        FROM itens_plano_manutencao i
        WHERE i.empresa_id = :empresa_id AND COALESCE(i.ativo, 1)=1
    """, empresa_id)

    if df_itens.empty:
        return pd.DataFrame()

    df_hist = carregar_dados_tabela(f"""
        SELECT id, veiculo_id, plano_item_id, custo_id, data_execucao, km_execucao, origem
        FROM manutencoes_realizadas
        WHERE empresa_id = :empresa_id
    """, empresa_id)

    registros = []
    hoje = hoje_local()

    for _, veiculo in df_v.iterrows():
        itens = df_itens[df_itens["plano_id"] == veiculo["plano_manutencao_id"]]
        for _, item in itens.iterrows():
            hist = df_hist[
                (df_hist["veiculo_id"] == veiculo["id"]) &
                (df_hist["plano_item_id"] == item["id"])
            ] if not df_hist.empty else pd.DataFrame()

            ultima_km = None
            ultima_data = None
            if not hist.empty:
                hist = hist.copy()
                hist["data_execucao"] = pd.to_datetime(hist["data_execucao"], errors="coerce")
                hist["km_execucao"] = pd.to_numeric(hist["km_execucao"], errors="coerce")
                kms_validos = hist["km_execucao"].dropna()
                datas_validas = hist["data_execucao"].dropna()
                if not kms_validos.empty:
                    ultima_km = float(kms_validos.max())
                if not datas_validas.empty:
                    ultima_data = datas_validas.max().date()

            intervalo_km = _intervalo_efetivo(item["intervalo_empresa_km"], item["intervalo_fabricante_km"])
            intervalo_meses = _intervalo_efetivo(item["intervalo_empresa_meses"], item["intervalo_fabricante_meses"])
            if intervalo_meses is not None:
                intervalo_meses = int(intervalo_meses)

            km_atual = float(veiculo["km_atual"] or 0)
            proximo_km = (ultima_km + intervalo_km) if ultima_km is not None and intervalo_km else None
            proxima_data = add_months(ultima_data, intervalo_meses) if ultima_data and intervalo_meses else None
            faltam_km = (proximo_km - km_atual) if proximo_km is not None else None
            faltam_dias = (proxima_data - hoje).days if proxima_data is not None else None

            if ultima_km is None and ultima_data is None:
                status_item = "SEM HISTÓRICO"
            else:
                vencido = ((faltam_km is not None and faltam_km <= 0) or
                           (faltam_dias is not None and faltam_dias <= 0))
                limite_proximo_km = max((intervalo_km or 0) * 0.05, 1000) if intervalo_km else None
                limite_atencao_km = max((intervalo_km or 0) * 0.20, 2000) if intervalo_km else None
                proximo = ((faltam_km is not None and limite_proximo_km is not None and faltam_km <= limite_proximo_km) or
                           (faltam_dias is not None and faltam_dias <= 30))
                atencao = ((faltam_km is not None and limite_atencao_km is not None and faltam_km <= limite_atencao_km) or
                           (faltam_dias is not None and faltam_dias <= 60))
                status_item = "VENCIDO" if vencido else ("PRÓXIMO" if proximo else ("ATENÇÃO" if atencao else "OK"))

            registros.append({
                "veiculo_id": int(veiculo["id"]),
                "Placa": veiculo["placa"],
                "Modelo": veiculo["modelo"],
                "KM Atual": int(km_atual),
                "Serviço": item["tipo_manutencao"],
                "Última KM": int(ultima_km) if ultima_km is not None else None,
                "Última Data": ultima_data,
                "Próxima KM": int(proximo_km) if proximo_km is not None else None,
                "Próxima Data": proxima_data,
                "Faltam KM": int(faltam_km) if faltam_km is not None else None,
                "Faltam Dias": int(faltam_dias) if faltam_dias is not None else None,
                "Status": status_item,
                "plano_item_id": int(item["id"]),
            })

    return pd.DataFrame(registros)


def processar_planilha_planos(df_import, empresa_id, usuario, veiculo_id_forcado=None):
    """Cria/atualiza planos-base, itens e históricos iniciais sem duplicar execuções iguais."""
    df = df_import.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    obrigatorias = ["placa", "nome_plano", "tipo_manutencao"]
    faltantes = [c for c in obrigatorias if c not in df.columns]
    if faltantes:
        raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(faltantes))

    session = SessionLocal()
    planos_tocados = set()
    itens_criados = 0
    historicos_criados = 0
    veiculos_vinculados = set()
    ignorados = []

    try:
        for idx, row in df.iterrows():
            placa = _texto_planilha(row.get("placa")).upper()
            tipo = _texto_planilha(row.get("tipo_manutencao"))
            if not placa or placa == "NAN" or not tipo or tipo.upper() == "NAN":
                ignorados.append(f"Linha {idx + 2}: placa ou tipo de manutenção vazio")
                continue

            if veiculo_id_forcado:
                veiculo = session.query(Veiculo).filter(
                    Veiculo.id == veiculo_id_forcado,
                    Veiculo.empresa_id == empresa_id,
                    Veiculo.ativo == 1
                ).first()
                if veiculo and veiculo.placa.upper() != placa:
                    ignorados.append(f"Linha {idx + 2}: placa diferente do veículo selecionado")
                    continue
            else:
                veiculo = session.query(Veiculo).filter(
                    Veiculo.empresa_id == empresa_id,
                    Veiculo.placa == placa,
                    Veiculo.ativo == 1
                ).first()

            if not veiculo:
                ignorados.append(f"Linha {idx + 2}: veículo {placa} não encontrado")
                continue

            nome_plano = _texto_planilha(row.get("nome_plano")) or _nome_plano_padrao(row)
            plano = session.query(PlanoManutencao).filter(
                PlanoManutencao.empresa_id == empresa_id,
                PlanoManutencao.nome == nome_plano
            ).first()

            if plano is None:
                plano = PlanoManutencao(
                    empresa_id=empresa_id,
                    nome=nome_plano,
                    fabricante=_texto_planilha(row.get("fabricante")) or veiculo.fabricante,
                    modelo=_texto_planilha(row.get("modelo")) or veiculo.modelo,
                    ano_modelo=_numero_planilha(row.get("ano_modelo"), inteiro=True) or veiculo.ano_modelo,
                    versao=_texto_planilha(row.get("versao")) or veiculo.versao,
                    motorizacao=_texto_planilha(row.get("motorizacao")) or veiculo.motorizacao,
                    combustivel=_texto_planilha(row.get("combustivel")) or veiculo.combustivel,
                    transmissao=_texto_planilha(row.get("transmissao")) or veiculo.transmissao,
                    ativo=1
                )
                session.add(plano)
                session.flush()
            else:
                for attr, col in [
                    ("fabricante", "fabricante"), ("modelo", "modelo"), ("versao", "versao"),
                    ("motorizacao", "motorizacao"), ("combustivel", "combustivel"), ("transmissao", "transmissao")
                ]:
                    novo = _texto_planilha(row.get(col))
                    if novo and novo.upper() != "NAN":
                        setattr(plano, attr, novo)
                ano = _numero_planilha(row.get("ano_modelo"), inteiro=True)
                if ano:
                    plano.ano_modelo = ano

            # Enriquece também o cadastro do veículo com os dados da planilha.
            for attr, col in [
                ("fabricante", "fabricante"), ("versao", "versao"), ("motorizacao", "motorizacao"),
                ("combustivel", "combustivel"), ("transmissao", "transmissao")
            ]:
                novo = _texto_planilha(row.get(col))
                if novo and novo.upper() != "NAN":
                    setattr(veiculo, attr, novo)
            ano = _numero_planilha(row.get("ano_modelo"), inteiro=True)
            if ano:
                veiculo.ano_modelo = ano

            veiculo.plano_manutencao_id = plano.id
            planos_tocados.add(plano.id)
            veiculos_vinculados.add(veiculo.id)

            # Uma linha sem serviço ainda é útil: ela vincula a placa a um plano-base
            # já cadastrado por outro veículo equivalente.
            if not tipo or tipo.upper() == "NAN":
                continue

            codigo = _texto_planilha(row.get("codigo_servico"))
            item_query = session.query(ItemPlanoManutencao).filter(
                ItemPlanoManutencao.empresa_id == empresa_id,
                ItemPlanoManutencao.plano_id == plano.id
            )
            if codigo and codigo.upper() != "NAN":
                item = item_query.filter(ItemPlanoManutencao.codigo_servico == codigo).first()
            else:
                item = item_query.filter(ItemPlanoManutencao.tipo_manutencao == tipo).first()

            if item is None:
                item = ItemPlanoManutencao(
                    empresa_id=empresa_id,
                    plano_id=plano.id,
                    codigo_servico=codigo or None,
                    tipo_manutencao=tipo,
                    ativo=1
                )
                session.add(item)
                session.flush()
                itens_criados += 1

            item.descricao = _texto_planilha(row.get("descricao_servico")) or item.descricao
            item.intervalo_fabricante_km = _numero_planilha(row.get("intervalo_fabricante_km"))
            item.intervalo_fabricante_meses = _numero_planilha(row.get("intervalo_fabricante_meses"), inteiro=True)
            item.intervalo_empresa_km = _numero_planilha(row.get("intervalo_empresa_km"))
            item.intervalo_empresa_meses = _numero_planilha(row.get("intervalo_empresa_meses"), inteiro=True)
            item.ativo = 1

            km_ultima = _numero_planilha(row.get("ultima_manutencao_km"))
            data_ultima = row.get("ultima_manutencao_data")
            if data_ultima is not None and not (isinstance(data_ultima, float) and pd.isna(data_ultima)) and str(data_ultima).strip():
                data_ultima = pd.to_datetime(data_ultima, dayfirst=True, errors="coerce")
                data_ultima = data_ultima.date() if pd.notna(data_ultima) else None
            else:
                data_ultima = None

            if km_ultima is not None or data_ultima is not None:
                existente = session.query(ManutencaoRealizada).filter(
                    ManutencaoRealizada.empresa_id == empresa_id,
                    ManutencaoRealizada.veiculo_id == veiculo.id,
                    ManutencaoRealizada.plano_item_id == item.id,
                    ManutencaoRealizada.km_execucao == km_ultima,
                    ManutencaoRealizada.data_execucao == data_ultima,
                    ManutencaoRealizada.origem == "Importação"
                ).first()
                if existente is None:
                    session.add(ManutencaoRealizada(
                        empresa_id=empresa_id,
                        veiculo_id=veiculo.id,
                        plano_item_id=item.id,
                        custo_id=None,
                        data_execucao=data_ultima,
                        km_execucao=km_ultima,
                        observacoes=_texto_planilha(row.get("observacoes")) or None,
                        origem="Importação"
                    ))
                    historicos_criados += 1

        session.commit()
        return {
            "planos": len(planos_tocados),
            "itens_novos": itens_criados,
            "historicos_novos": historicos_criados,
            "veiculos": len(veiculos_vinculados),
            "ignorados": ignorados,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def obter_contrato_ativo_do_principal(session, empresa_id, veiculo_id):
    return session.query(Contrato).filter(
        Contrato.empresa_id == empresa_id,
        Contrato.veiculo_id == veiculo_id,
        Contrato.ativo == 1
    ).order_by(Contrato.data_inicio.desc()).first()

def obter_substituicao_ativa_por_principal(session, empresa_id, veiculo_id):
    return session.query(SubstituicaoContrato).filter(
        SubstituicaoContrato.empresa_id == empresa_id,
        SubstituicaoContrato.veiculo_principal_id == veiculo_id,
        SubstituicaoContrato.ativo == 1
    ).order_by(SubstituicaoContrato.data_inicio.desc()).first()

def obter_substituicao_ativa_por_reserva(session, empresa_id, veiculo_id):
    return session.query(SubstituicaoContrato).filter(
        SubstituicaoContrato.empresa_id == empresa_id,
        SubstituicaoContrato.veiculo_substituto_id == veiculo_id,
        SubstituicaoContrato.ativo == 1
    ).order_by(SubstituicaoContrato.data_inicio.desc()).first()

def iniciar_substituicao_contrato(session, empresa_id, contrato, veiculo_principal, veiculo_substituto, usuario):
    if contrato is None or contrato.ativo != 1:
        raise ValueError("O veículo principal não possui contrato vigente.")
    if veiculo_principal.id == veiculo_substituto.id:
        raise ValueError("O veículo substituto deve ser diferente do principal.")
    if veiculo_substituto.status != "Disponível":
        raise ValueError("O veículo substituto precisa estar com status Disponível.")
    if obter_substituicao_ativa_por_principal(session, empresa_id, veiculo_principal.id):
        raise ValueError("Já existe uma substituição ativa para este veículo principal.")
    if obter_substituicao_ativa_por_reserva(session, empresa_id, veiculo_substituto.id):
        raise ValueError("O veículo selecionado já está sendo utilizado como reserva.")

    substituicao = SubstituicaoContrato(
        empresa_id=empresa_id,
        contrato_id=contrato.id,
        veiculo_principal_id=veiculo_principal.id,
        veiculo_substituto_id=veiculo_substituto.id,
        data_inicio=hoje_local(),
        data_fim=None,
        ativo=1,
        usuario_lancamento=usuario
    )
    session.add(substituicao)
    veiculo_principal.status = "Manutenção"
    veiculo_substituto.status = "Alugado"
    return substituicao

def finalizar_substituicao_contrato(session, substituicao, status_principal="Alugado"):
    principal = tenant_get(session, Veiculo, substituicao.veiculo_principal_id, substituicao.empresa_id)
    substituto = tenant_get(session, Veiculo, substituicao.veiculo_substituto_id, substituicao.empresa_id)

    substituicao.ativo = 0
    substituicao.data_fim = hoje_local()

    if principal is not None:
        principal.status = status_principal
    if substituto is not None:
        substituto.status = "Disponível"

    return principal, substituto

PLOTLY_LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(t=20, b=20, l=10, r=10),
    font=dict(family="Inter", color="#374151", size=12),
)

PALETTE = dict(
    indigo="#6366F1", 
    green="#10B981", 
    red="#EF4444", 
    amber="#F59E0B", 
    blue="#3B82F6", 
    slate="#64748B"
)

# ─── FUNÇÕES DE NAVEGAÇÃO ───────────────────────────────────────────────────
def set_menu(menu_name):
    st.session_state["ultimo_menu"] = menu_name
    st.session_state["tela_config"] = False
    if menu_name == "Gestão de Frota":
        st.session_state["pagina_frota"] = "Visão da Frota"
        st.session_state["menu_frota_aberto"] = True
    else:
        st.session_state["menu_frota_aberto"] = False
    for modulo, slug, padrao in [
        ("Gestão de Custos", "custos", "Visão de Custos"),
        ("Contratos e Locação", "contratos", "Visão de Contratos"),
        ("Gestão de Cobranças", "cobrancas", "Visão Financeira"),
        ("Pessoas e Acessos", "pessoas", "Motoristas"),
    ]:
        st.session_state[f"menu_{slug}_aberto"] = menu_name == modulo
        if menu_name == modulo:
            st.session_state[f"pagina_{slug}"] = padrao
    if st.session_state.get("privacidade_pendente"):
        st.session_state["privacidade_dialog_suspenso"] = False

def set_config():
    st.session_state["tela_config"] = True
    st.session_state["ultimo_menu"] = "Configurações"

def set_pagina_frota(pagina):
    set_menu("Gestão de Frota")
    st.session_state["pagina_frota"] = pagina
    st.session_state["menu_frota_aberto"] = True

def toggle_menu_frota():
    if st.session_state.get("ultimo_menu") == "Gestão de Frota":
        st.session_state["menu_frota_aberto"] = not st.session_state["menu_frota_aberto"]
    else:
        set_menu("Gestão de Frota")

def set_pagina_custos(pagina):
    set_menu("Gestão de Custos")
    st.session_state["pagina_custos"] = pagina
    st.session_state["menu_custos_aberto"] = True

def toggle_menu_custos():
    if st.session_state.get("ultimo_menu") == "Gestão de Custos":
        st.session_state["menu_custos_aberto"] = not st.session_state["menu_custos_aberto"]
    else:
        set_menu("Gestão de Custos")

def set_pagina_contratos(pagina):
    set_menu("Contratos e Locação")
    st.session_state["pagina_contratos"] = pagina
    st.session_state["menu_contratos_aberto"] = True

def toggle_menu_contratos():
    if st.session_state.get("ultimo_menu") == "Contratos e Locação":
        st.session_state["menu_contratos_aberto"] = not st.session_state["menu_contratos_aberto"]
    else:
        set_menu("Contratos e Locação")

def set_pagina_cobrancas(pagina):
    set_menu("Gestão de Cobranças")
    st.session_state["pagina_cobrancas"] = pagina
    st.session_state["menu_cobrancas_aberto"] = True

def toggle_menu_cobrancas():
    if st.session_state.get("ultimo_menu") == "Gestão de Cobranças":
        st.session_state["menu_cobrancas_aberto"] = not st.session_state["menu_cobrancas_aberto"]
    else:
        set_menu("Gestão de Cobranças")

def set_pagina_pessoas(pagina):
    set_menu("Pessoas e Acessos")
    st.session_state["pagina_pessoas"] = (
        "Motoristas" if pagina == "Usuários do Sistema" and st.session_state["perfil"] != "admin"
        else pagina
    )
    st.session_state["menu_pessoas_aberto"] = True

def toggle_menu_pessoas():
    if st.session_state.get("ultimo_menu") == "Pessoas e Acessos":
        st.session_state["menu_pessoas_aberto"] = not st.session_state["menu_pessoas_aberto"]
    else:
        set_menu("Pessoas e Acessos")

def set_perfil():
    st.session_state["tela_config"] = False
    st.session_state["ultimo_menu"] = "Meu Perfil"

def set_privacidade():
    st.session_state["tela_config"] = False
    st.session_state["ultimo_menu"] = "Política de Privacidade"

def toggle_pin():
    st.session_state["sidebar_pinned"] = not st.session_state["sidebar_pinned"]


def efetuar_logout():
    encerrar_sessao(expirada=False)


def _conteudo_aviso_cookies():
    st.markdown(
        "O Kineo utiliza apenas recursos técnicos necessários para autenticação, "
        "segurança, sessão e preferências de interface. "
        "Nesta versão, o aplicativo não utiliza cookies próprios de publicidade comportamental."
    )
    st.caption(
        f"Política de Privacidade versão {PRIVACY_VERSION}. "
        "Este aviso volta a ser apresentado somente quando houver uma nova versão relevante da política."
    )

    c_cookie_1, c_cookie_2 = st.columns(2)

    if c_cookie_1.button(
        "Ciente e continuar",
        type="primary",
        use_container_width=True,
        key="cookie_ciente"
    ):
        registrar_ciencia_privacidade()
        st.rerun()

    if c_cookie_2.button(
        "Política de Privacidade",
        use_container_width=True,
        key="cookie_privacidade"
    ):
        st.session_state["privacidade_dialog_suspenso"] = True
        set_privacidade()
        st.rerun()


if hasattr(st, "dialog"):
    aviso_cookies = st.dialog(
        "Privacidade e recursos essenciais",
        width="small"
    )(_conteudo_aviso_cookies)
else:
    aviso_cookies = _conteudo_aviso_cookies


# Timeout é avaliado em cada nova interação/rerun da aplicação.
if validar_timeout_sessao():
    st.rerun()


def render_gestao_motoristas(emp_id):
    """Cadastro operacional de motoristas separado das credenciais de acesso."""
    is_admin = st.session_state.get("perfil") == "admin"
    df_motoristas = carregar_dados_tabela(
        """
        SELECT m.id, m.nome, m.cpf, m.matricula, m.telefone, m.cnh,
               m.categoria_cnh, m.validade_cnh, m.ativo, m.observacoes,
               m.usuario_id, u.login AS usuario_login
        FROM motoristas m
        LEFT JOIN usuarios u
            ON u.id = m.usuario_id AND u.empresa_id = m.empresa_id
        WHERE m.empresa_id = :empresa_id
        ORDER BY COALESCE(m.ativo, 1) DESC, m.nome
        """,
        emp_id,
    )

    if is_admin:
        st.caption(
            "Motoristas são cadastros operacionais e não precisam ter acesso ao Kineo. "
            "Administradores podem vincular opcionalmente um motorista a um usuário do sistema."
        )
    else:
        st.caption(
            "Cadastre e mantenha os motoristas utilizados nas rotinas operacionais e nos lançamentos de custos."
        )

    if not df_motoristas.empty:
        view = df_motoristas.copy()
        view["Status"] = view["ativo"].apply(
            lambda x: "Ativo" if int(x or 0) == 1 else "Inativo"
        )
        view["Validade CNH"] = pd.to_datetime(
            view["validade_cnh"], errors="coerce"
        ).dt.strftime("%d/%m/%Y").fillna("—")
        view["Acesso Kineo"] = view["usuario_login"].fillna("—")
        view["Matrícula"] = view["matricula"].fillna("—")
        view["CNH"] = view["cnh"].fillna("—")
        view["Categoria"] = view["categoria_cnh"].fillna("—")
        colunas_motoristas = ["nome", "Matrícula", "CNH", "Categoria", "Validade CNH", "Status"]
        if is_admin:
            colunas_motoristas.append("Acesso Kineo")
        st.dataframe(
            view[colunas_motoristas].rename(columns={"nome": "Motorista"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nenhum motorista cadastrado.", icon=None)

    opcoes_usuario = {"Nenhum acesso vinculado": None}
    if is_admin:
        df_users_motorista = carregar_dados_tabela(
            """
            SELECT id, nome, login
            FROM usuarios
            WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1) = 1
            ORDER BY nome, login
            """,
            emp_id,
        )
        if not df_users_motorista.empty:
            for _, row in df_users_motorista.iterrows():
                opcoes_usuario[f"{row['nome']} ({row['login']})"] = int(row["id"])

    tab_gestao, tab_novo = st.tabs(["Visão geral", "Adicionar motorista"])

    with tab_novo:
        with st.form("form_novo_motorista", clear_on_submit=True):
            a1, a2, a3 = st.columns(3)
            nome = a1.text_input("Nome completo *", max_chars=150)
            matricula = a2.text_input("Matrícula", max_chars=60)
            telefone = a3.text_input("Telefone", max_chars=40)

            b1, b2, b3, b4 = st.columns([1.1, 1.1, 0.8, 1])
            cpf = b1.text_input("CPF (opcional)", max_chars=18, help="Cadastre somente se houver necessidade operacional.")
            cnh = b2.text_input("CNH", max_chars=20)
            categoria = b3.selectbox(
                "Categoria CNH",
                ["Não informada", "A", "B", "AB", "C", "D", "E", "AC", "AD", "AE"],
            )
            validade_cnh = b4.date_input("Validade da CNH", value=None, format="DD/MM/YYYY")

            if is_admin:
                usuario_label = st.selectbox(
                    "Usuário do sistema vinculado (opcional)",
                    list(opcoes_usuario.keys()),
                    key="motorista_novo_usuario",
                )
            else:
                usuario_label = "Nenhum acesso vinculado"
            observacoes = st.text_area("Observações", max_chars=500)

            if st.form_submit_button("Cadastrar motorista", use_container_width=True):
                nome_limpo = str(nome or "").strip()
                cpf_limpo = re.sub(r"\D", "", str(cpf or "")) or None
                cnh_limpa = re.sub(r"\D", "", str(cnh or "")) or None
                matricula_limpa = str(matricula or "").strip() or None
                telefone_limpo = str(telefone or "").strip() or None
                categoria_val = None if categoria == "Não informada" else categoria
                usuario_id = opcoes_usuario.get(usuario_label)

                if len(nome_limpo) < 2:
                    st.error("Informe o nome do motorista.", icon=None)
                elif cpf_limpo and len(cpf_limpo) != 11:
                    st.error("CPF deve possuir 11 dígitos quando informado.", icon=None)
                elif cnh_limpa and len(cnh_limpa) != 11:
                    st.error("CNH deve possuir 11 dígitos quando informada.", icon=None)
                else:
                    session = SessionLocal()
                    try:
                        filtros = [Motorista.empresa_id == emp_id]
                        conflitos = []
                        if cpf_limpo:
                            conflitos.append(session.query(Motorista).filter(*filtros, Motorista.cpf == cpf_limpo).first())
                        if cnh_limpa:
                            conflitos.append(session.query(Motorista).filter(*filtros, Motorista.cnh == cnh_limpa).first())
                        if matricula_limpa:
                            conflitos.append(session.query(Motorista).filter(*filtros, Motorista.matricula == matricula_limpa).first())
                        usuario_conflito = (
                            session.query(Motorista).filter(
                                Motorista.empresa_id == emp_id,
                                Motorista.usuario_id == usuario_id,
                            ).first()
                            if usuario_id is not None else None
                        )
                        if any(x is not None for x in conflitos):
                            st.error("Já existe motorista com CPF, CNH ou matrícula informada.", icon=None)
                        elif usuario_conflito is not None:
                            st.error("Este usuário do sistema já está vinculado a outro motorista.", icon=None)
                        else:
                            novo = Motorista(
                                empresa_id=emp_id,
                                nome=nome_limpo,
                                cpf=cpf_limpo,
                                matricula=matricula_limpa,
                                telefone=telefone_limpo,
                                cnh=cnh_limpa,
                                categoria_cnh=categoria_val,
                                validade_cnh=validade_cnh,
                                ativo=1,
                                observacoes=str(observacoes or "").strip() or None,
                                usuario_id=usuario_id,
                            )
                            session.add(novo)
                            session.flush()
                            registrar_auditoria(
                                session, emp_id, st.session_state["usuario_id"],
                                "MOTORISTA_CRIADO", "Motorista", novo.id,
                                f"Motorista: {nome_limpo}",
                            )
                            session.commit()
                            st.cache_data.clear()
                            st.success("Motorista cadastrado com sucesso.")
                            st.rerun()
                    except Exception:
                        session.rollback()
                        logger.exception("Falha ao cadastrar motorista")
                        st.error("Não foi possível cadastrar o motorista.", icon=None)
                    finally:
                        session.close()

    with tab_gestao:
        if df_motoristas.empty:
            st.info("Cadastre um motorista para habilitar a gestão.", icon=None)
        else:
            opcoes_motoristas = {
                f"{r['nome']} · {r['matricula'] or ('#' + str(int(r['id'])))}": int(r["id"])
                for _, r in df_motoristas.iterrows()
            }
            motorista_label = st.selectbox(
                "Motorista",
                list(opcoes_motoristas.keys()),
                key="gestao_motorista_sel",
            )
            motorista_id = opcoes_motoristas[motorista_label]
            row = df_motoristas[df_motoristas["id"].astype(int) == int(motorista_id)].iloc[0]

            with st.form("form_editar_motorista"):
                e1, e2, e3 = st.columns(3)
                e_nome = e1.text_input("Nome completo *", value=str(row["nome"] or ""), max_chars=150)
                e_matricula = e2.text_input("Matrícula", value=str(row["matricula"] or ""), max_chars=60)
                e_telefone = e3.text_input("Telefone", value=str(row["telefone"] or ""), max_chars=40)

                f1, f2, f3, f4 = st.columns([1.1, 1.1, 0.8, 1])
                e_cpf = f1.text_input("CPF (opcional)", value=str(row["cpf"] or ""), max_chars=18)
                e_cnh = f2.text_input("CNH", value=str(row["cnh"] or ""), max_chars=20)
                categorias = ["Não informada", "A", "B", "AB", "C", "D", "E", "AC", "AD", "AE"]
                cat_atual = str(row["categoria_cnh"] or "Não informada")
                if cat_atual not in categorias:
                    categorias.append(cat_atual)
                e_categoria = f3.selectbox("Categoria CNH", categorias, index=categorias.index(cat_atual))
                validade_atual = pd.to_datetime(row["validade_cnh"], errors="coerce")
                e_validade = f4.date_input(
                    "Validade da CNH",
                    value=(validade_atual.date() if pd.notna(validade_atual) else None),
                    format="DD/MM/YYYY",
                )

                usuario_atual = None if pd.isna(row["usuario_id"]) else int(row["usuario_id"])
                if is_admin:
                    labels_usuario = list(opcoes_usuario.keys())
                    label_usuario_atual = next(
                        (lbl for lbl, uid in opcoes_usuario.items() if uid == usuario_atual),
                        "Nenhum acesso vinculado",
                    )
                    e_usuario_label = st.selectbox(
                        "Usuário do sistema vinculado (opcional)",
                        labels_usuario,
                        index=labels_usuario.index(label_usuario_atual),
                        key="motorista_editar_usuario",
                    )
                else:
                    e_usuario_label = None
                e_status = st.selectbox(
                    "Status",
                    ["Ativo", "Inativo"],
                    index=0 if int(row["ativo"] or 0) == 1 else 1,
                    help="Motoristas inativos permanecem no histórico, mas não aparecem em novos lançamentos de custos.",
                )
                e_obs = st.text_area("Observações", value=str(row["observacoes"] or ""), max_chars=500)

                if st.form_submit_button("Salvar alterações", use_container_width=True):
                    nome_limpo = str(e_nome or "").strip()
                    cpf_limpo = re.sub(r"\D", "", str(e_cpf or "")) or None
                    cnh_limpa = re.sub(r"\D", "", str(e_cnh or "")) or None
                    matricula_limpa = str(e_matricula or "").strip() or None
                    if len(nome_limpo) < 2:
                        st.error("Informe o nome do motorista.", icon=None)
                    elif cpf_limpo and len(cpf_limpo) != 11:
                        st.error("CPF deve possuir 11 dígitos quando informado.", icon=None)
                    elif cnh_limpa and len(cnh_limpa) != 11:
                        st.error("CNH deve possuir 11 dígitos quando informada.", icon=None)
                    else:
                        session = SessionLocal()
                        try:
                            conflito = None
                            if cpf_limpo:
                                conflito = session.query(Motorista).filter(
                                    Motorista.empresa_id == emp_id,
                                    Motorista.id != motorista_id,
                                    Motorista.cpf == cpf_limpo,
                                ).first()
                            if conflito is None and cnh_limpa:
                                conflito = session.query(Motorista).filter(
                                    Motorista.empresa_id == emp_id,
                                    Motorista.id != motorista_id,
                                    Motorista.cnh == cnh_limpa,
                                ).first()
                            if conflito is None and matricula_limpa:
                                conflito = session.query(Motorista).filter(
                                    Motorista.empresa_id == emp_id,
                                    Motorista.id != motorista_id,
                                    Motorista.matricula == matricula_limpa,
                                ).first()
                            # Somente administradores podem criar/alterar vínculos entre motoristas
                            # e credenciais do Kineo. Operadores preservam eventual vínculo existente.
                            usuario_id_edicao = (
                                opcoes_usuario.get(e_usuario_label) if is_admin else usuario_atual
                            )
                            usuario_conflito = (
                                session.query(Motorista).filter(
                                    Motorista.empresa_id == emp_id,
                                    Motorista.id != motorista_id,
                                    Motorista.usuario_id == usuario_id_edicao,
                                ).first()
                                if is_admin and usuario_id_edicao is not None else None
                            )
                            if conflito is not None:
                                st.error("CPF, CNH ou matrícula já pertence a outro motorista.", icon=None)
                            elif usuario_conflito is not None:
                                st.error("Este usuário do sistema já está vinculado a outro motorista.", icon=None)
                            else:
                                m = tenant_get(session, Motorista, motorista_id, emp_id)
                                if m is None:
                                    st.error("Motorista não encontrado.", icon=None)
                                else:
                                    m.nome = nome_limpo
                                    m.cpf = cpf_limpo
                                    m.matricula = matricula_limpa
                                    m.telefone = str(e_telefone or "").strip() or None
                                    m.cnh = cnh_limpa
                                    m.categoria_cnh = None if e_categoria == "Não informada" else e_categoria
                                    m.validade_cnh = e_validade
                                    m.ativo = 1 if e_status == "Ativo" else 0
                                    m.observacoes = str(e_obs or "").strip() or None
                                    m.usuario_id = usuario_id_edicao
                                    registrar_auditoria(
                                        session, emp_id, st.session_state["usuario_id"],
                                        "MOTORISTA_ATUALIZADO", "Motorista", m.id,
                                        f"Status: {e_status}",
                                    )
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Motorista atualizado.")
                                    st.rerun()
                        except Exception:
                            session.rollback()
                            logger.exception("Falha ao atualizar motorista")
                            st.error("Não foi possível atualizar o motorista.", icon=None)
                        finally:
                            session.close()

            # Exclusão permanente é uma ação administrativa e só é permitida
            # quando o motorista nunca foi utilizado em lançamentos históricos.
            st.markdown("---")
            if is_admin:
                with st.container(border=True):
                    st.markdown("**Excluir motorista**")
                    st.caption(
                        "A exclusão permanente é indicada apenas para cadastros criados por engano. "
                        "Se o motorista já possui custos vinculados, preserve o histórico e altere o status para Inativo."
                    )

                    session_ref = SessionLocal()
                    try:
                        qtd_custos_motorista = (
                            session_ref.query(Custo)
                            .filter(
                                Custo.empresa_id == emp_id,
                                Custo.motorista_id == motorista_id,
                            )
                            .count()
                        )
                    finally:
                        session_ref.close()

                    if qtd_custos_motorista > 0:
                        st.warning(
                            f"Este motorista possui {qtd_custos_motorista} lançamento(s) de custo vinculado(s). "
                            "Para preservar o histórico, a exclusão permanente foi bloqueada. Use o status Inativo.",
                            icon=None,
                        )
                    else:
                        confirmacao_motorista = st.text_input(
                            f"Digite o nome do motorista para confirmar: {row['nome']}",
                            key=f"confirmar_exclusao_motorista_{motorista_id}",
                        )
                        if st.button(
                            "Excluir motorista permanentemente",
                            type="primary",
                            use_container_width=True,
                            key=f"excluir_motorista_{motorista_id}",
                        ):
                            if str(confirmacao_motorista or "").strip() != str(row["nome"] or "").strip():
                                st.error("Digite exatamente o nome do motorista para confirmar a exclusão.", icon=None)
                            else:
                                session = SessionLocal()
                                try:
                                    m = tenant_get(session, Motorista, motorista_id, emp_id)
                                    if m is None:
                                        st.error("Motorista não encontrado.", icon=None)
                                    else:
                                        nome_excluido = m.nome
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "MOTORISTA_EXCLUIDO", "Motorista", m.id,
                                            f"Motorista excluído: {nome_excluido}",
                                        )
                                        session.delete(m)
                                        session.commit()
                                        st.cache_data.clear()
                                        st.success("Motorista excluído permanentemente.")
                                        st.rerun()
                                except Exception:
                                    session.rollback()
                                    logger.exception("Falha ao excluir motorista")
                                    st.error("Não foi possível excluir o motorista.", icon=None)
                                finally:
                                    session.close()
            else:
                st.caption(
                    "A exclusão permanente de motorista está disponível somente para administradores. "
                    "Operadores podem alterar o status para Inativo."
                )


def render_gestao_usuarios(emp_id):
    # Defesa em profundidade: mesmo que a função seja chamada por engano,
    # somente administradores podem consultar ou alterar credenciais.
    if st.session_state.get("perfil") != "admin":
        st.error("Acesso Negado: usuários do sistema são gerenciados somente por administradores.", icon=None)
        return

    if not ARGON2_DISPONIVEL:
        st.warning(
            "O pacote argon2-cffi ainda não está disponível neste ambiente. "
            "Instale-o antes da produção; enquanto isso, o fallback bcrypt continua funcional.",
            icon=None,
        )

    credencial = st.session_state.pop("credencial_temporaria", None)
    if credencial:
        st.success("Credencial temporária gerada. Copie agora: ela não será exibida novamente.")
        email_cred = str(credencial.get("email") or "").strip()
        linha_email = f"\nE-mail: {email_cred}" if email_cred else ""
        st.code(
            f"Usuário: {credencial['login']}{linha_email}\nSenha temporária: {credencial['senha']}",
            language=None,
        )
        st.caption("O usuário será obrigado a definir uma senha pessoal no primeiro acesso.")

    df_users = carregar_dados_tabela(
        f"""
        SELECT id, nome, login, email, perfil, ativo, must_change_password,
               tentativas_login, bloqueado_ate, ultimo_login
        FROM usuarios
        WHERE empresa_id = :empresa_id
        ORDER BY nome, login
        """,
        emp_id,
    )

    if not df_users.empty:
        users_view = df_users.copy()
        users_view["Status"] = users_view["ativo"].apply(
            lambda x: "Ativo" if int(x or 0) == 1 else "Revogado"
        )
        users_view["Troca de senha"] = users_view["must_change_password"].apply(
            lambda x: "Pendente" if int(x or 0) == 1 else "OK"
        )
        users_view["Último acesso"] = formatar_serie_datetime_local(
            users_view["ultimo_login"], "%d/%m/%Y %H:%M"
        )
        st.dataframe(
            users_view[["nome", "login", "email", "perfil", "Status", "Troca de senha", "Último acesso"]].rename(
                columns={"nome": "Nome", "login": "Usuário", "email": "E-mail", "perfil": "Perfil"}
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nenhum usuário cadastrado.", icon=None)

    sub2, sub1, sub3, sub4 = st.tabs([
        "Gestão de acessos",
        "Nova credencial",
        "Redefinir Acesso",
        "Excluir Usuário",
    ])

    with sub1:
        with st.form("form_novo_user", clear_on_submit=True):
            ua, ub = st.columns(2)
            u_nome = ua.text_input("Colaborador", max_chars=120)
            u_login = ub.text_input("Usuário", max_chars=120, help="Identificador legado/alternativo de acesso.")
            u_email = st.text_input("E-mail", max_chars=254, placeholder="nome@empresa.com.br")
            u_perfil = st.selectbox("Camada de Acesso", ["operador", "admin"])

            if st.form_submit_button("Criar credencial", use_container_width=True):
                nome_limpo = str(u_nome or "").strip()
                login_limpo = str(u_login or "").strip()
                email_limpo = normalizar_email(u_email)
                if len(nome_limpo) < 2 or len(login_limpo) < 3:
                    st.error("Informe nome e usuário válidos.", icon=None)
                elif not re.fullmatch(r"[A-Za-z0-9._@-]+", login_limpo):
                    st.error("O usuário pode conter apenas letras, números, ponto, hífen, _ e @.", icon=None)
                elif not email_valido(email_limpo):
                    st.error("Informe um e-mail válido para o colaborador.", icon=None)
                else:
                    session = SessionLocal()
                    try:
                        conflito_login = session.query(Usuario).filter(
                            (Usuario.login == login_limpo) |
                            (Usuario.email == normalizar_email(login_limpo))
                        ).first()
                        conflito_email = session.query(Usuario).filter(
                            (Usuario.email == email_limpo) |
                            (Usuario.login == email_limpo)
                        ).first()
                        if conflito_login:
                            st.error("Identificador de usuário em uso por outra credencial.", icon=None)
                        elif conflito_email:
                            st.error("E-mail já vinculado a outra credencial.", icon=None)
                        else:
                            temporaria = gerar_senha_temporaria()
                            novo_user = Usuario(
                                empresa_id=emp_id,
                                nome=nome_limpo,
                                login=login_limpo,
                                email=email_limpo,
                                senha=hash_password(temporaria),
                                perfil=u_perfil,
                                ativo=1,
                                must_change_password=1,
                                tentativas_login=0,
                            )
                            session.add(novo_user)
                            session.flush()
                            registrar_auditoria(
                                session,
                                emp_id,
                                st.session_state["usuario_id"],
                                "USUARIO_CRIADO",
                                "Usuario",
                                novo_user.id,
                                f"Login {login_limpo}; e-mail {email_limpo}; perfil {u_perfil}",
                            )
                            session.commit()
                            st.session_state["credencial_temporaria"] = {
                                "login": login_limpo,
                                "email": email_limpo,
                                "senha": temporaria,
                            }
                            st.cache_data.clear()
                            st.rerun()
                    except Exception:
                        session.rollback()
                        st.error("Não foi possível criar o usuário.", icon=None)
                    finally:
                        session.close()

    with sub2:
        if df_users.empty:
            st.info("Nenhum usuário disponível para edição.", icon=None)
        else:
            opt_u = {
                f"{r['nome']} ({r['login']})": int(r["id"])
                for _, r in df_users.iterrows()
            }
            u_sel = st.selectbox("Usuário", list(opt_u.keys()), key="admin_editar_usuario")

            if u_sel:
                uid = opt_u[u_sel]
                row_u = df_users[df_users["id"] == uid].iloc[0]
                e_nom = st.text_input("Nome", value=str(row_u["nome"]), max_chars=120)
                e_log = st.text_input("Usuário", value=str(row_u["login"]), max_chars=120)
                email_atual = "" if pd.isna(row_u.get("email")) else str(row_u.get("email") or "")
                e_email = st.text_input("E-mail", value=email_atual, max_chars=254)
                e_prf = st.selectbox(
                    "Perfil",
                    ["operador", "admin"],
                    index=0 if row_u["perfil"] == "operador" else 1,
                )
                e_ativo = st.selectbox(
                    "Acesso",
                    ["Ativo", "Revogado"],
                    index=0 if int(row_u["ativo"] or 0) == 1 else 1,
                )

                if st.button("Salvar Modificação", use_container_width=True, key="admin_salvar_usuario"):
                    nome_limpo = str(e_nom or "").strip()
                    login_limpo = str(e_log or "").strip()
                    email_limpo = normalizar_email(e_email)
                    if uid == st.session_state["usuario_id"] and e_ativo == "Revogado":
                        st.error("Você não pode revogar o próprio acesso.", icon=None)
                    elif not re.fullmatch(r"[A-Za-z0-9._@-]+", login_limpo):
                        st.error("Usuário inválido.", icon=None)
                    elif email_limpo and not email_valido(email_limpo):
                        st.error("E-mail inválido.", icon=None)
                    else:
                        session = SessionLocal()
                        try:
                            conflito_login = session.query(Usuario).filter(
                                Usuario.id != uid,
                                (
                                    (Usuario.login == login_limpo) |
                                    (Usuario.email == normalizar_email(login_limpo))
                                ),
                            ).first()
                            conflito_email = (
                                session.query(Usuario).filter(
                                    Usuario.id != uid,
                                    (
                                        (Usuario.email == email_limpo) |
                                        (Usuario.login == email_limpo)
                                    ),
                                ).first()
                                if email_limpo else None
                            )
                            if conflito_login:
                                st.error("Conflito de usuários na base.", icon=None)
                            elif conflito_email:
                                st.error("E-mail já vinculado a outro usuário.", icon=None)
                            else:
                                u = tenant_get(session, Usuario, uid, emp_id)
                                if u is None:
                                    st.error("Usuário não encontrado.", icon=None)
                                else:
                                    u.nome = nome_limpo
                                    u.login = login_limpo
                                    u.email = email_limpo or None
                                    u.perfil = e_prf
                                    u.ativo = 1 if e_ativo == "Ativo" else 0
                                    if u.ativo == 0:
                                        u.bloqueado_ate = None
                                        u.tentativas_login = 0
                                    registrar_auditoria(
                                        session,
                                        emp_id,
                                        st.session_state["usuario_id"],
                                        "USUARIO_ATUALIZADO",
                                        "Usuario",
                                        u.id,
                                        f"Perfil {e_prf}; acesso {e_ativo}; e-mail {email_limpo or 'não informado'}",
                                    )
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Usuário atualizado.")
                                    st.rerun()
                        except Exception:
                            session.rollback()
                            st.error("Não foi possível atualizar o usuário.", icon=None)
                        finally:
                            session.close()

    with sub3:
        if df_users.empty:
            st.info("Nenhum usuário disponível.", icon=None)
        else:
            opt_r = {
                f"{r['nome']} ({r['login']})": int(r["id"])
                for _, r in df_users.iterrows()
            }
            u_rst = st.selectbox("Usuário", list(opt_r.keys()), key="admin_reset_usuario")
            st.caption(
                "Uma nova senha temporária aleatória será criada. A credencial anterior deixa de funcionar "
                "e o usuário deverá definir uma senha pessoal no próximo acesso."
            )

            if st.button("Gerar nova credencial temporária", use_container_width=True, key="admin_reset_senha"):
                session = SessionLocal()
                try:
                    u = tenant_get(session, Usuario, opt_r[u_rst], emp_id)
                    if u is None:
                        st.error("Usuário não encontrado.", icon=None)
                    elif u.id == st.session_state["usuario_id"]:
                        st.error("Para sua própria conta, use a troca de senha em Meu Perfil.", icon=None)
                    else:
                        temporaria = gerar_senha_temporaria()
                        u.senha = hash_password(temporaria)
                        u.must_change_password = 1
                        u.tentativas_login = 0
                        u.bloqueado_ate = None
                        u.ativo = 1
                        registrar_auditoria(
                            session,
                            emp_id,
                            st.session_state["usuario_id"],
                            "SENHA_REDEFINIDA_ADMIN",
                            "Usuario",
                            u.id,
                        )
                        session.commit()
                        st.session_state["credencial_temporaria"] = {
                            "login": u.login,
                            "email": u.email,
                            "senha": temporaria,
                        }
                        st.cache_data.clear()
                        st.rerun()
                except Exception:
                    session.rollback()
                    st.error("Não foi possível redefinir o acesso.", icon=None)
                finally:
                    session.close()

    with sub4:
        usuarios_excluiveis = df_users[
            df_users["id"].astype(int) != int(st.session_state["usuario_id"])
        ].copy() if not df_users.empty else df_users.copy()

        if usuarios_excluiveis.empty:
            st.info(
                "Não há outro usuário disponível para exclusão. "
                "A conta atualmente logada nunca pode excluir a si própria.",
                icon=None,
            )
        else:
            st.warning(
                "A exclusão é permanente. Para apenas impedir o acesso sem remover a conta, "
                "use Gestão de Credencial → Acesso: Revogado.",
                icon=None,
            )

            opt_del = {
                f"{r['nome']} ({r['login']}) — {r['perfil']}": int(r["id"])
                for _, r in usuarios_excluiveis.iterrows()
            }
            u_del_label = st.selectbox(
                "Usuário a excluir",
                list(opt_del.keys()),
                key="admin_excluir_usuario",
            )
            uid_del = opt_del[u_del_label]
            row_del = usuarios_excluiveis[
                usuarios_excluiveis["id"].astype(int) == int(uid_del)
            ].iloc[0]
            login_confirmacao = str(row_del["login"])

            st.caption(
                "Os eventos de auditoria já registrados serão preservados. "
                "O vínculo técnico com a conta removida será anonimizado."
            )
            confirmar_login = st.text_input(
                f'Digite o login "{login_confirmacao}" para confirmar',
                key="admin_confirmar_exclusao_usuario",
            )

            pode_excluir = str(confirmar_login or "").strip() == login_confirmacao
            if st.button(
                "Excluir usuário permanentemente",
                type="primary",
                use_container_width=True,
                disabled=not pode_excluir,
                key="admin_excluir_usuario_btn",
            ):
                session = SessionLocal()
                try:
                    u = tenant_get(session, Usuario, uid_del, emp_id)
                    if u is None:
                        st.error("Usuário não encontrado.", icon=None)
                    elif u.id == st.session_state["usuario_id"]:
                        st.error("Você não pode excluir a própria conta.", icon=None)
                    else:
                        if u.perfil == "admin" and int(u.ativo or 0) == 1:
                            admins_ativos = session.query(Usuario).filter(
                                Usuario.empresa_id == emp_id,
                                Usuario.perfil == "admin",
                                Usuario.ativo == 1,
                            ).count()
                            if admins_ativos <= 1:
                                st.error(
                                    "Não é possível excluir o último administrador ativo da empresa.",
                                    icon=None,
                                )
                                raise ValueError("ultimo_admin_ativo")

                        usuario_snapshot = f"{u.nome} ({u.login}); perfil {u.perfil}"

                        # Preserva os eventos antigos sem manter uma FK para a conta removida.
                        session.query(Auditoria).filter(
                            Auditoria.empresa_id == emp_id,
                            Auditoria.usuario_id == u.id,
                        ).update(
                            {Auditoria.usuario_id: None},
                            synchronize_session=False,
                        )

                        registrar_auditoria(
                            session,
                            emp_id,
                            st.session_state["usuario_id"],
                            "USUARIO_EXCLUIDO",
                            "Usuario",
                            u.id,
                            usuario_snapshot,
                        )
                        avatar_excluido = referencia_storage(f"logos/avatars/avatar_{u.id}.png")
                        session.delete(u)
                        session.commit()

                        excluir_storage(avatar_excluido)

                        st.cache_data.clear()
                        st.success("Usuário excluído permanentemente.")
                        time.sleep(0.5)
                        st.rerun()
                except ValueError as e:
                    session.rollback()
                    if str(e) != "ultimo_admin_ativo":
                        st.error("Não foi possível excluir o usuário.", icon=None)
                except Exception:
                    session.rollback()
                    st.error(
                        "Não foi possível excluir o usuário. Revogue o acesso e tente novamente.",
                        icon=None,
                    )
                finally:
                    session.close()



def _conteudo_politica_login():
    st.caption(f"Última atualização: 1 de setembro de 2026 · Versão {PRIVACY_VERSION}")
    st.markdown("**1. Escopo**")
    st.markdown(
        "Esta política descreve como o **Kineo | Gestão de Frotas** trata informações necessárias "
        "à administração corporativa de veículos, contratos, custos, cobranças, motoristas e usuários autorizados."
    )
    st.markdown("**2. Dados e finalidades**")
    st.markdown(
        "Podem ser tratados dados de identificação e acesso, dados operacionais de motoristas, empresas, "
        "veículos, manutenção, contratos, custos, cobranças e arquivos enviados ao sistema. O tratamento serve "
        "à autenticação, gestão da frota, segurança, auditoria e execução das rotinas da organização."
    )
    st.markdown("**3. Privacidade, sessão e segurança**")
    st.markdown(
        "O acesso é autenticado e separado por empresa. O Kineo utiliza recursos técnicos necessários para "
        "sessão, segurança e preferências de interface e não implementa cookies próprios de publicidade comportamental."
    )
    st.markdown("**4. LGPD e direitos**")
    st.markdown(
        "O tratamento deve observar a Lei Geral de Proteção de Dados (LGPD) e demais normas aplicáveis. "
        "Solicitações relativas a dados pessoais devem ser encaminhadas à organização responsável pelo ambiente."
    )
    st.info(
        "A política completa permanece disponível dentro do Kineo após a autenticação.",
        icon=None,
    )


def _conteudo_termos_login():
    st.caption("Termos de Uso · versão operacional")
    st.markdown("**Acesso autorizado**")
    st.markdown(
        "O Kineo é destinado exclusivamente a usuários autorizados pela organização responsável pelo ambiente. "
        "As credenciais são pessoais e não devem ser compartilhadas."
    )
    st.markdown("**Uso adequado**")
    st.markdown(
        "O sistema deve ser utilizado para finalidades profissionais relacionadas à gestão de frotas e às rotinas "
        "operacionais autorizadas pela empresa. Tentativas de acesso indevido, alteração não autorizada ou uso abusivo "
        "podem resultar em bloqueio ou revogação do acesso."
    )
    st.markdown("**Dados e responsabilidade**")
    st.markdown(
        "Cada organização é responsável pela legitimidade dos dados inseridos, pela gestão dos usuários autorizados "
        "e pela observância das obrigações legais aplicáveis à sua operação."
    )
    st.markdown("**Auditoria e segurança**")
    st.markdown(
        "Ações relevantes de autenticação e administração podem ser registradas para segurança, auditoria e rastreabilidade."
    )
    st.caption(
        "Estes termos apresentam as regras operacionais atuais do produto e podem ser atualizados conforme a evolução do Kineo."
    )


if hasattr(st, "dialog"):
    politica_login_dialog = st.dialog("Política de Privacidade", width="large")(_conteudo_politica_login)
    termos_login_dialog = st.dialog("Termos de Uso", width="large")(_conteudo_termos_login)
else:
    politica_login_dialog = _conteudo_politica_login
    termos_login_dialog = _conteudo_termos_login


# Mantém o CSS do login presente durante o rerun que troca a tela pública
# pelo app autenticado, evitando a breve renderização sem estilo.
aplicar_css_login()

# A escrita de "lembrar usuário/e-mail" é processada somente depois que o
# submit já terminou e a sessão está autenticada, evitando duplicação visual.
processar_persistencia_login_pendente()

# ══════════════════════════════════════════════════════════════════════════════
# 1 · TELA DE LOGIN — UX V10.3
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state["autenticado"]:

    # O componente de localStorage retorna de forma assíncrona e pode provocar um rerun.
    # Apenas o identificador é lembrado; senha, tenant e tokens nunca são persistidos aqui.
    # Mantém o componente na mesma posição da árvore visual em todos os reruns.
    # Removê-lo depois da primeira leitura deslocava os elementos do formulário e
    # fazia o Streamlit exibir temporariamente duas cópias da tela no submit.
    lembrado = ler_identificador_lembrado()
    if (
        not st.session_state.get("login_remember_loaded", False)
        and STREAMLIT_JS_EVAL_DISPONIVEL
        and lembrado is not None
    ):
        st.session_state["login_identifier_prefill"] = lembrado
        st.session_state["login_remember_loaded"] = True

    col_visual, col_login = st.columns([1.08, 0.92])

    with col_visual:
        render_login_hero()

    with col_login:
        st.markdown(
            '<div class="kineo-login-right"><h1>Bem-vindo de volta!</h1><p>Acesse sua conta para continuar.</p></div>',
            unsafe_allow_html=True,
        )

        if st.session_state.get("sessao_expirada_aviso"):
            st.warning(
                f"Sua sessão foi encerrada após {SESSION_TIMEOUT_MINUTES} minutos de inatividade. Entre novamente.",
                icon=None,
            )
            st.session_state["sessao_expirada_aviso"] = False

        identificador_inicial = str(st.session_state.get("login_identifier_prefill") or "").strip()

        with st.form("login_form"):
            usuario_input = st.text_input(
                "E-mail ou usuário",
                value=identificador_inicial,
                placeholder="seu@email.com ou usuário",
                max_chars=254,
            )
            senha_input = st.text_input(
                "Senha",
                type="password",
                placeholder="Digite sua senha",
                max_chars=PASSWORD_MAX_LENGTH,
            )

            c_lembrar, c_esqueci = st.columns([1.15, 0.85])
            with c_lembrar:
                lembrar_identificador = st.checkbox(
                    "Lembrar meu usuário/e-mail",
                    value=bool(identificador_inicial),
                )
            with c_esqueci:
                esqueceu_senha = st.form_submit_button(
                    "Esqueci minha senha",
                    use_container_width=True,
                )

            submitted = st.form_submit_button(
                "Entrar",
                type="primary",
                use_container_width=True,
            )

        if esqueceu_senha:
            st.info(
                "Por segurança, a redefinição é feita pelo administrador da sua empresa. "
                "Solicite a ele uma nova credencial temporária.",
                icon=None,
            )

        if submitted:
            with st.spinner("Validando seu acesso..."):
                login_digitado = str(usuario_input or "").strip()
                login_email = normalizar_email(login_digitado)
                agora = agora_utc()
                session = SessionLocal()
                try:
                    # Identidade global nesta fase: usuário OU e-mail único.
                    # O empresa_id é obtido exclusivamente do registro autenticado.
                    user = session.query(Usuario).filter(
                        (Usuario.login == login_digitado) |
                        (Usuario.email == login_email)
                    ).first()
    
                    if user and user.bloqueado_ate and user.bloqueado_ate > agora:
                        segundos = int((user.bloqueado_ate - agora).total_seconds())
                        st.error(
                            f"Acesso temporariamente bloqueado. Tente novamente em aproximadamente {max(segundos, 1)}s."
                        )
                    else:
                        if user and user.bloqueado_ate and user.bloqueado_ate <= agora:
                            user.bloqueado_ate = None
                            user.tentativas_login = 0
    
                        autenticado_ok = (
                            user is not None
                            and int(user.ativo or 0) == 1
                            and verify_password(senha_input, user.senha)
                        )
    
                        if autenticado_ok:
                            user.tentativas_login = 0
                            user.bloqueado_ate = None
                            user.ultimo_login = agora
    
                            # Compatibilidade com contas antigas criadas antes da V8.
                            if verify_password("PRIMEIROACESSO", user.senha):
                                user.must_change_password = 1
    
                            # Migração transparente: bcrypt legado -> Argon2id.
                            if password_needs_rehash(user.senha):
                                user.senha = hash_password(senha_input)
    
                            registrar_auditoria(
                                session,
                                user.empresa_id,
                                user.id,
                                "LOGIN_SUCESSO",
                                "Usuario",
                                user.id,
                                f"Ambiente: {APP_ENV}; método: {'email' if login_email and user.email == login_email else 'usuario'}",
                            )
                            session.commit()
    
                            # Apenas usuário/e-mail é lembrado. A escrita no navegador
                            # é adiada para o primeiro ciclo já autenticado, fora do submit.
                            st.session_state["login_remember_pending"] = {
                                "identificador": (
                                    user.email
                                    if (login_email and user.email == login_email)
                                    else user.login
                                ),
                                "lembrar": bool(lembrar_identificador),
                            }
    
                            st.session_state.update({
                                "autenticado": True,
                                "usuario_id": user.id,
                                "empresa_id": int(user.empresa_id),
                                "nome": user.nome,
                                "login": user.login,
                                "email": user.email,
                                "perfil": user.perfil,
                                "forcar_troca_senha": bool(user.must_change_password),
                                "privacidade_pendente": user.privacidade_versao_aceita != PRIVACY_VERSION,
                                "privacidade_dialog_suspenso": False,
                                "privacidade_rever": False,
                                "ultima_atividade_ts": time.time(),
                                "ultimo_menu": "Painel Gerencial",
                                "tela_config": False,
                            })
                            st.rerun()
                        else:
                            # O bloqueio é persistido por usuário, não por session_state/navegador.
                            if user:
                                user.tentativas_login = int(user.tentativas_login or 0) + 1
                                if user.tentativas_login >= LOGIN_MAX_ATTEMPTS:
                                    user.bloqueado_ate = agora + timedelta(minutes=LOGIN_BLOCK_MINUTES)
                                    user.tentativas_login = LOGIN_MAX_ATTEMPTS
                                registrar_auditoria(
                                    session,
                                    user.empresa_id,
                                    user.id,
                                    "LOGIN_FALHA",
                                    "Usuario",
                                    user.id,
                                    "Credencial inválida ou usuário inativo",
                                )
                                session.commit()
                            else:
                                # Pequeno atraso reduz a utilidade de enumeração/tentativas em massa.
                                time.sleep(0.5)
                            st.error("Credenciais inválidas ou acesso indisponível.")
                except Exception:
                    session.rollback()
                    logger.exception("Falha inesperada na autenticação")
                    st.error("Não foi possível concluir a autenticação. Tente novamente.", icon=None)
                finally:
                    session.close()

        st.markdown(
            """
            <div class="kineo-login-exclusive">
                <strong>🔐 Acesso exclusivo</strong>
                Este sistema é exclusivo para clientes e parceiros autorizados.
                Para obter acesso, entre em contato com o administrador da sua empresa.
            </div>
            <div class="kineo-login-footer">
                © 2026 Kineo Gestão de Frotas. Todos os direitos reservados.
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="kineo-login-legal-label">Informações legais</div>', unsafe_allow_html=True)
        legal_priv, legal_termos = st.columns(2)
        with legal_priv:
            if st.button(
                "Política de Privacidade",
                type="tertiary",
                use_container_width=True,
                key="login_politica_privacidade",
            ):
                politica_login_dialog()
        with legal_termos:
            if st.button(
                "Termos de Uso",
                type="tertiary",
                use_container_width=True,
                key="login_termos_uso",
            ):
                termos_login_dialog()

# ══════════════════════════════════════════════════════════════════════════════
# 2 · TROCA DE SENHA OBRIGATÓRIA
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state["forcar_troca_senha"]:
    st.markdown("<br><br>", unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 1.2, 1])

    with col_c:
        with st.container(border=True):
            st.markdown("### Defina sua senha")
            st.info(
                "Primeiro acesso ou redefinição administrativa detectada. "
                f"Crie uma frase-senha com pelo menos {PASSWORD_MIN_LENGTH} caracteres."
            )
            st.caption(
                "Você pode usar espaços. Evite nome, login, sequências previsíveis e senhas reutilizadas em outros serviços."
            )

            with st.form("form_troca"):
                nova = st.text_input(
                    "Nova senha",
                    type="password",
                    placeholder=f"Mínimo {PASSWORD_MIN_LENGTH} caracteres",
                    max_chars=PASSWORD_MAX_LENGTH,
                )
                conf = st.text_input(
                    "Confirmação",
                    type="password",
                    placeholder="Repita a nova senha",
                    max_chars=PASSWORD_MAX_LENGTH,
                )

                if st.form_submit_button("Salvar e entrar", use_container_width=True):
                    erros_senha = validar_nova_senha(
                        nova,
                        st.session_state.get("login", ""),
                        st.session_state.get("nome", ""),
                    )
                    if nova != conf:
                        erros_senha.append("As senhas informadas não coincidem.")

                    if erros_senha:
                        st.error("Não foi possível aceitar a senha: " + " ".join(erros_senha), icon=None)
                    else:
                        session = SessionLocal()
                        try:
                            user = tenant_get(
                                session,
                                Usuario,
                                st.session_state["usuario_id"],
                                st.session_state["empresa_id"],
                            )
                            if user is None or int(user.ativo or 0) != 1:
                                st.error("Usuário não encontrado ou acesso revogado.", icon=None)
                            elif verify_password(nova, user.senha):
                                st.error("A nova senha precisa ser diferente da credencial atual.", icon=None)
                            else:
                                user.senha = hash_password(nova)
                                user.must_change_password = 0
                                user.senha_alterada_em = agora_utc()
                                user.tentativas_login = 0
                                user.bloqueado_ate = None
                                registrar_auditoria(
                                    session,
                                    user.empresa_id,
                                    user.id,
                                    "SENHA_DEFINIDA",
                                    "Usuario",
                                    user.id,
                                    "Senha obrigatória atualizada",
                                )
                                session.commit()
                                st.session_state["forcar_troca_senha"] = False
                                st.session_state["ultima_atividade_ts"] = time.time()
                                st.success("Senha atualizada com segurança.")
                                time.sleep(0.5)
                                st.rerun()
                        except Exception:
                            session.rollback()
                            st.error("Não foi possível atualizar a senha.", icon=None)
                        finally:
                            session.close()

# ══════════════════════════════════════════════════════════════════════════════
# 3 · APP PRINCIPAL (HOVER SIDEBAR)
# ══════════════════════════════════════════════════════════════════════════════
else:
    emp_id = int(st.session_state["empresa_id"])
    tela_ativa = st.session_state.get("ultimo_menu", "Painel Gerencial")

    # Caminho do Avatar Pessoal do Usuário Logado
    avatar_path = referencia_storage(f"logos/avatars/avatar_{st.session_state['usuario_id']}.png")

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        session_logo = SessionLocal()
        empresa_atual = session_logo.get(Empresa, emp_id)
        session_logo.close()

        # Renderização Logo Dinâmica
        logo_bytes = ler_bytes_privado(empresa_atual.logo_path) if empresa_atual and empresa_atual.logo_path else None
        if empresa_atual and empresa_atual.logo_path and logo_bytes:
            encoded_string = base64.b64encode(logo_bytes).decode()
            logo_ext = os.path.splitext(str(empresa_atual.logo_path))[1].lower()
            logo_mime = "image/png" if logo_ext == ".png" else "image/jpeg"
            
            st.markdown(f"""
            <div class="sidebar-brand-wrapper">
                <img src="data:{logo_mime};base64,{encoded_string}" class="sidebar-logo-img">
                <div class="sidebar-brand-text">
                    <h2>{html.escape(str(empresa_atual.nome_fantasia or "Kineo"))}</h2>
                    <span class="sidebar-brand-subtitle">KINEO</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            nome_emp = str(empresa_atual.nome_fantasia if empresa_atual else "Kineo")
            nome_emp_safe = html.escape(nome_emp)
            letra = html.escape(nome_emp[0].upper())
            
            st.markdown(f"""
            <div class="sidebar-brand-wrapper">
                <div class="sidebar-logo-img">{letra}</div>
                <div class="sidebar-brand-text">
                    <h2>{nome_emp_safe}</h2>
                    <span class="sidebar-brand-subtitle">KINEO</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        pin_lbl = "Recolher menu" if st.session_state["sidebar_pinned"] else "Fixar menu"
        pin_icn = ":material/keyboard_double_arrow_left:" if st.session_state["sidebar_pinned"] else ":material/keyboard_double_arrow_right:"
        st.button(
            pin_lbl,
            icon=pin_icn,
            on_click=toggle_pin,
            key="nav_pin"
        )

        # Itens Principais do Menu
        def render_desktop_nav(label, icon, type, use_container_width, on_click, key, args=()):
            """Visual próprio; o botão transparente mantém o callback e o teclado nativos."""
            subitem = key.startswith(("nav_frota_", "nav_custos_", "nav_contratos_", "nav_cobrancas_", "nav_pessoas_"))
            level = "sub" if subitem else "main"
            classes = "kineo-nav-line"
            if subitem:
                classes += " kineo-nav-sub"
            if type == "primary":
                classes += " kineo-nav-active"
            if key == "nav_main_privacidade":
                classes += " kineo-nav-privacy"
            symbol = html.escape(icon.removeprefix(":material/").removesuffix(":"))
            chevron = ""
            chevron_state = {
                "nav_main_frota": "menu_frota_aberto",
                "nav_main_custos": "menu_custos_aberto",
                "nav_main_contratos": "menu_contratos_aberto",
                "nav_main_cobrancas": "menu_cobrancas_aberto",
                "nav_main_pessoas": "menu_pessoas_aberto",
            }.get(key)
            if chevron_state:
                direction = "expand_less" if st.session_state[chevron_state] else "expand_more"
                chevron = f'<span class="kineo-nav-chevron">{direction}</span>'
            with st.container(key=f"kineo_nav_{level}_{key}", border=False):
                st.markdown(
                    f'<div class="{classes}" aria-hidden="true">'
                    f'<span class="kineo-nav-icon">{symbol}</span>'
                    f'<span class="kineo-nav-label">{html.escape(label)}</span>'
                    f'{chevron}</div>',
                    unsafe_allow_html=True,
                )
                st.button(
                    label, icon=icon, type=type, use_container_width=use_container_width,
                    on_click=on_click, args=args, key=key,
                )

        MENU_ITEMS = [
            ("Painel Gerencial", ":material/bar_chart:", "painel"),
            ("Gestão de Frota", ":material/directions_car:", "frota"),
            ("Gestão de Custos", ":material/account_balance_wallet:", "custos"),
            ("Contratos e Locação", ":material/description:", "contratos"),
            ("Gestão de Cobranças", ":material/request_quote:", "cobrancas")
        ]
        # Todos os perfis autenticados acessam Motoristas.
        # A gestão de Usuários do Sistema é liberada apenas para administradores.
        MENU_ITEMS.append(("Pessoas e Acessos", ":material/group:", "pessoas"))

        MENU_TOGGLES = {
            "frota": toggle_menu_frota,
            "custos": toggle_menu_custos,
            "contratos": toggle_menu_contratos,
            "cobrancas": toggle_menu_cobrancas,
            "pessoas": toggle_menu_pessoas,
        }
        NOVOS_SUBMENUS = {
            "custos": (set_pagina_custos, [
                ("Visão de Custos", ":material/monitoring:"),
                ("Registrar Despesa", ":material/add_card:"),
                ("Lançamentos", ":material/receipt_long:"),
            ]),
            "contratos": (set_pagina_contratos, [
                ("Visão de Contratos", ":material/dashboard:"),
                ("Novo Contrato", ":material/note_add:"),
                ("Gestão de Contratos", ":material/edit_document:"),
                ("Substituições", ":material/swap_horiz:"),
            ]),
            "cobrancas": (set_pagina_cobrancas, [
                ("Visão Financeira", ":material/account_balance:"),
                ("Recorrências", ":material/repeat:"),
                ("Operação Mensal", ":material/calendar_month:"),
            ]),
            "pessoas": (set_pagina_pessoas, [
                ("Motoristas", ":material/badge:"),
            ] + ([("Usuários do Sistema", ":material/manage_accounts:")]
                 if st.session_state["perfil"] == "admin" else [])),
        }

        st.markdown('<div class="sidebar-nav-section">PAINEL</div>', unsafe_allow_html=True)
        for label, icon, slug in MENU_ITEMS:
            if label == "Gestão de Frota":
                st.markdown('<div class="sidebar-nav-section">OPERAÇÃO</div>', unsafe_allow_html=True)
            is_active = (tela_ativa == label)
            render_desktop_nav(
                label, 
                icon=icon, 
                type="primary" if is_active else "secondary", 
                use_container_width=True, 
                on_click=MENU_TOGGLES.get(slug, set_menu),
                args=() if slug in MENU_TOGGLES else (label,),
                key=f"nav_main_{slug}"
            )
            if label == "Gestão de Frota" and tela_ativa == "Gestão de Frota" and st.session_state["menu_frota_aberto"]:
                for pagina, icone in [
                    ("Visão da Frota", ":material/dashboard:"),
                    ("Veículos", ":material/directions_car:"),
                    ("Status da Frota", ":material/sync_alt:"),
                    ("Análise por Veículo", ":material/monitoring:"),
                    ("Saúde da Frota", ":material/health_and_safety:"),
                    ("Planos de Manutenção", ":material/build:"),
                ]:
                    render_desktop_nav(
                        pagina,
                        icon=icone,
                        type="primary" if st.session_state["pagina_frota"] == pagina else "secondary",
                        use_container_width=True,
                        on_click=set_pagina_frota,
                        args=(pagina,),
                        key=f"nav_frota_{pagina}",
                    )
            if slug in NOVOS_SUBMENUS and tela_ativa == label and st.session_state[f"menu_{slug}_aberto"]:
                callback_pagina, paginas_menu = NOVOS_SUBMENUS[slug]
                for pagina, icone in paginas_menu:
                    render_desktop_nav(
                        pagina,
                        icon=icone,
                        type="primary" if st.session_state[f"pagina_{slug}"] == pagina else "secondary",
                        use_container_width=True,
                        on_click=callback_pagina,
                        args=(pagina,),
                        key=f"nav_{slug}_{pagina}",
                    )

        if st.session_state["perfil"] == "admin":
            st.markdown('<div class="sidebar-nav-section">ADMINISTRAÇÃO</div>', unsafe_allow_html=True)
            is_cfg = (tela_ativa == "Configurações")
            render_desktop_nav(
                "Configurações", 
                icon=":material/settings:", 
                type="primary" if is_cfg else "secondary", 
                use_container_width=True, 
                on_click=set_config, 
                key="nav_main_configuracoes"
            )

        # Divisor Flexbox invisível que empurra o resto para baixo
        st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)

        # Privacidade/Cookies: acesso discreto, disponível para todos os perfis
        render_desktop_nav(
            "Privacidade · Cookies",
            icon=":material/policy:",
            type="primary" if tela_ativa == "Política de Privacidade" else "secondary",
            use_container_width=True,
            on_click=set_privacidade,
            key="nav_main_privacidade"
        )

        # Espaço protetor estrito para acomodar exatamente a altura do perfil sem gerar scroll
        st.markdown('<div style="height: 85px;"></div>', unsafe_allow_html=True)

        # Renderização do Avatar do Usuário (Rodapé HTML - Sem Placeholder)
        avatar_bytes = ler_bytes_privado(avatar_path)
        if avatar_bytes:
            encoded_avatar = base64.b64encode(avatar_bytes).decode()
            avatar_html = f'<img src="data:image/png;base64,{encoded_avatar}" class="profile-avatar" style="object-fit: cover;">'
        else:
            letra_inicial = st.session_state["nome"][0].upper() if st.session_state.get("nome") else "U"
            avatar_html = f'<div class="profile-avatar">{letra_inicial}</div>'

        nome_perfil_safe = html.escape(str(st.session_state.get('nome', 'Usuário')))
        perfil_safe = html.escape(str(st.session_state.get('perfil', '')).title())
        st.markdown(f"""
        <div class="profile-wrapper">
            {avatar_html}
            <div class="profile-text">
                <strong>{nome_perfil_safe}</strong>
                <span>{perfil_safe}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── OS DOIS BOTÕES MÁGICOS DO RODAPÉ ── 
        
        # Penúltimo Botão (Invisível) - Aciona a tela Meu Perfil
        st.button(
            "Botao_Invisivel_Perfil", 
            key="btn_perfil", 
            on_click=set_perfil
        )

        # Último Botão - Logout Flutuante
        st.button(
            "Sair", 
            icon=":material/logout:", 
            key="nav_logout",
            on_click=efetuar_logout
        )

    # Transparência versionada: mostra no primeiro acesso à versão atual da política.
    if (
        (st.session_state.get("privacidade_pendente") or st.session_state.get("privacidade_rever"))
        and not st.session_state.get("privacidade_dialog_suspenso", False)
    ):
        aviso_cookies()


    # Evita que o spinner global reserve espaço acima da primeira tela.
    # Operações específicas exibem seus próprios indicadores quando necessário.
    if True:

        # ══════════════════════════════════════════════════════════════════════════
        # PAINEL GERENCIAL
        # ══════════════════════════════════════════════════════════════════════════
        if tela_ativa == "Painel Gerencial":
            aplicar_css_dashboard_v11()
            st.markdown('<div class="kineo-dashboard-v11"></div>', unsafe_allow_html=True)

            hoje = hoje_local()
            mes_atual_str = hoje.strftime("%m/%Y")
            primeiro_dia_mes = hoje.replace(day=1)
            mes_anterior_str = (primeiro_dia_mes - timedelta(days=1)).strftime("%m/%Y")
            limite_30_dias = hoje + timedelta(days=30)

            # ── Consultas principais (regras existentes preservadas) ──────────────
            df_status = carregar_dados_tabela("""
                SELECT status, COUNT(id) AS qtd
                FROM veiculos
                WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1
                GROUP BY status
            """, emp_id)

            df_veiculos_dash = carregar_dados_tabela("""
                SELECT id, placa, modelo, km_atual, status
                FROM veiculos
                WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1
            """, emp_id)

            df_custos = carregar_dados_tabela("""
                SELECT c.id, c.veiculo_id, c.data_custo, c.categoria, c.valor_total,
                       v.placa, v.modelo
                FROM custos c
                LEFT JOIN veiculos v ON v.id=c.veiculo_id AND v.empresa_id=c.empresa_id
                WHERE c.empresa_id = :empresa_id
            """, emp_id)

            df_cobrancas = carregar_dados_tabela("""
                SELECT mes_ano, valor_previsto, status, vencimento,
                       data_recebimento, multa, juros, valor_principal_liquidado,
                       multa_aplicada, juros_aplicados, dias_atraso_liquidacao,
                       valor_liquidado, liquidacao_congelada, liquidado_em
                FROM cobrancas_mensais
                WHERE empresa_id = :empresa_id
            """, emp_id)

            df_contratos_dash = carregar_dados_tabela("""
                SELECT c.id, c.veiculo_id, c.cliente, c.data_inicio, c.data_fim,
                       c.ativo, c.tipo_valor, c.valor_mensal, v.placa, v.modelo
                FROM contratos c
                INNER JOIN veiculos v ON v.id=c.veiculo_id AND v.empresa_id=c.empresa_id
                WHERE c.empresa_id = :empresa_id
            """, emp_id)

            try:
                df_substituicoes_dash = carregar_dados_tabela("""
                    SELECT s.id, s.contrato_id, s.veiculo_principal_id,
                           s.veiculo_substituto_id, s.data_inicio, s.data_fim, s.ativo,
                           vp.placa AS placa_principal,
                           vs.placa AS placa_substituto,
                           c.cliente
                    FROM substituicoes_contrato s
                    INNER JOIN contratos c ON c.id=s.contrato_id AND c.empresa_id=s.empresa_id
                    INNER JOIN veiculos vp ON vp.id=s.veiculo_principal_id AND vp.empresa_id=s.empresa_id
                    INNER JOIN veiculos vs ON vs.id=s.veiculo_substituto_id AND vs.empresa_id=s.empresa_id
                    WHERE s.empresa_id = :empresa_id AND s.ativo=1
                """, emp_id)
            except Exception:
                df_substituicoes_dash = pd.DataFrame()

            # ── Tratamento dos dados ──────────────────────────────────────────────
            if not df_custos.empty:
                df_custos["data_custo"] = pd.to_datetime(df_custos["data_custo"], errors="coerce")
                df_custos["mes_ano"] = df_custos["data_custo"].dt.strftime("%m/%Y")
                df_custos["valor_total"] = pd.to_numeric(
                    df_custos["valor_total"], errors="coerce"
                ).fillna(0.0)

            if not df_cobrancas.empty:
                df_cobrancas["valor_previsto"] = pd.to_numeric(
                    df_cobrancas["valor_previsto"], errors="coerce"
                ).fillna(0.0)
                df_cobrancas["vencimento"] = pd.to_datetime(
                    df_cobrancas["vencimento"], errors="coerce"
                )
                df_cobrancas["status"] = (
                    df_cobrancas["status"].fillna("").apply(normalizar_status_cobranca)
                )
                df_cobrancas["_encargos"] = df_cobrancas.apply(
                    encargos_cobranca_exibicao, axis=1
                )
                df_cobrancas["_valor_atualizado"] = df_cobrancas["_encargos"].apply(
                    lambda x: float(x["valor_atualizado"])
                )
                df_cobrancas["_valor_dashboard"] = df_cobrancas.apply(
                    lambda r: (
                        float(r["_valor_atualizado"])
                        if r.get("status") == "Recebida"
                        else float(r.get("valor_previsto") or 0.0)
                    ),
                    axis=1,
                )
                df_cobrancas["_encargos_recebidos"] = df_cobrancas.apply(
                    lambda r: max(
                        float(r["_valor_atualizado"]) - float(r.get("valor_previsto") or 0.0),
                        0.0,
                    ) if r.get("status") == "Recebida" else 0.0,
                    axis=1,
                )

            if not df_contratos_dash.empty:
                df_contratos_dash["data_inicio"] = pd.to_datetime(
                    df_contratos_dash["data_inicio"], errors="coerce"
                )
                df_contratos_dash["data_fim"] = pd.to_datetime(
                    df_contratos_dash["data_fim"], errors="coerce"
                )
                df_contratos_dash["valor_mensal"] = pd.to_numeric(
                    df_contratos_dash["valor_mensal"], errors="coerce"
                ).fillna(0.0)

            def qtd_status(nome):
                if df_status.empty:
                    return 0
                valores = df_status.loc[df_status["status"] == nome, "qtd"]
                return int(valores.sum()) if not valores.empty else 0

            def variacao_mes(atual, anterior):
                atual = float(atual or 0)
                anterior = float(anterior or 0)
                if anterior == 0:
                    return "Sem histórico anterior" if atual == 0 else "Novo no mês"
                return f"{((atual-anterior)/abs(anterior))*100:+.1f}% vs mês anterior"

            # ── Indicadores operacionais ──────────────────────────────────────────
            veiculos_totais = int(df_status["qtd"].sum()) if not df_status.empty else 0
            veiculos_disponiveis = qtd_status("Disponível")
            veiculos_alugados = qtd_status("Alugado")
            veiculos_manutencao = qtd_status("Manutenção")
            taxa_ocupacao = (veiculos_alugados / veiculos_totais * 100) if veiculos_totais else 0

            contratos_ativos = 0
            contratos_vencendo_30 = 0
            receita_contratada = 0.0

            if not df_contratos_dash.empty:
                contratos_ativos_df = df_contratos_dash[
                    df_contratos_dash["ativo"] == 1
                ].copy()
                contratos_ativos = len(contratos_ativos_df)
                if not contratos_ativos_df.empty:
                    contratos_vencendo_30 = len(contratos_ativos_df[
                        contratos_ativos_df["data_fim"].notna()
                        & (contratos_ativos_df["data_fim"] >= pd.Timestamp(hoje))
                        & (contratos_ativos_df["data_fim"] <= pd.Timestamp(limite_30_dias))
                    ])
                    receita_contratada = contratos_ativos_df.loc[
                        contratos_ativos_df["tipo_valor"] == "Fixo", "valor_mensal"
                    ].sum()

            reservas_em_uso = (
                len(df_substituicoes_dash) if not df_substituicoes_dash.empty else 0
            )

            # ── Indicadores financeiros ───────────────────────────────────────────
            custos_mes_atual = 0.0
            custos_mes_anterior = 0.0
            if not df_custos.empty:
                custos_mes_atual = df_custos.loc[
                    df_custos["mes_ano"] == mes_atual_str, "valor_total"
                ].sum()
                custos_mes_anterior = df_custos.loc[
                    df_custos["mes_ano"] == mes_anterior_str, "valor_total"
                ].sum()

            faturamento_mes_atual = 0.0
            faturamento_mes_anterior = 0.0
            encargos_recebidos_mes = 0.0
            inadimplencia_qtd = 0
            if not df_cobrancas.empty:
                cobrancas_validas = df_cobrancas[
                    ~df_cobrancas["status"].isin(["Cancelada", "Não cobrar"])
                ].copy()
                faturamento_mes_atual = cobrancas_validas.loc[
                    cobrancas_validas["mes_ano"] == mes_atual_str, "_valor_dashboard"
                ].sum()
                faturamento_mes_anterior = cobrancas_validas.loc[
                    cobrancas_validas["mes_ano"] == mes_anterior_str, "_valor_dashboard"
                ].sum()
                encargos_recebidos_mes = cobrancas_validas.loc[
                    cobrancas_validas["mes_ano"] == mes_atual_str, "_encargos_recebidos"
                ].sum()
                inadimplencia_qtd = len(cobrancas_validas[
                    cobrancas_validas["status"].isin(
                        ["Pendente", "Pendente de emissão", "Emitida", "Enviada"]
                    )
                    & cobrancas_validas["vencimento"].notna()
                    & (cobrancas_validas["vencimento"] < pd.Timestamp(hoje))
                ])

            saldo_mes = faturamento_mes_atual - custos_mes_atual

            # ── Alertas e manutenção preventiva ───────────────────────────────────
            alertas = []
            if contratos_vencendo_30:
                alertas.append((
                    "Contratos próximos do vencimento",
                    f"{contratos_vencendo_30} contrato(s) vencem nos próximos 30 dias."
                ))
            if veiculos_manutencao:
                alertas.append((
                    "Veículos em manutenção",
                    f"{veiculos_manutencao} veículo(s) estão indisponíveis para operação."
                ))
            if reservas_em_uso:
                alertas.append((
                    "Reservas em operação",
                    f"{reservas_em_uso} veículo(s) reserva atendem contratos temporariamente."
                ))
            if inadimplencia_qtd:
                alertas.append((
                    "Cobranças vencidas",
                    f"{inadimplencia_qtd} cobrança(s) estão pendentes e vencidas."
                ))

            diag_dashboard = diagnostico_manutencao(emp_id)
            revisoes_proximas = []
            if not diag_dashboard.empty:
                diag_alerta = diag_dashboard[
                    diag_dashboard["Status"].isin(["VENCIDO", "PRÓXIMO", "ATENÇÃO"])
                ].copy()
                prioridade_dash = {"VENCIDO": 0, "PRÓXIMO": 1, "ATENÇÃO": 2}
                diag_alerta["_ordem"] = diag_alerta["Status"].map(prioridade_dash)
                diag_alerta = diag_alerta.sort_values(
                    ["_ordem", "Faltam KM", "Faltam Dias"], na_position="last"
                )
                for _, manut in diag_alerta.iterrows():
                    if pd.notna(manut["Faltam KM"]):
                        detalhe = f"{int(manut['Faltam KM']):,} km".replace(",", ".")
                    elif pd.notna(manut["Faltam Dias"]):
                        detalhe = f"{int(manut['Faltam Dias'])} dia(s)"
                    else:
                        detalhe = manut["Status"]
                    revisoes_proximas.append({
                        "placa": manut["Placa"],
                        "servico": manut["Serviço"],
                        "status": manut["Status"],
                        "detalhe": detalhe,
                    })
            else:
                df_v_km = carregar_dados_tabela("""
                    SELECT id, placa, km_atual
                    FROM veiculos
                    WHERE empresa_id = :empresa_id
                      AND COALESCE(ativo, 1)=1
                      AND km_atual>0
                """, emp_id)
                df_manu = carregar_dados_tabela("""
                    SELECT veiculo_id, MAX(km_momento) AS ultimo_km
                    FROM custos
                    WHERE empresa_id = :empresa_id
                      AND categoria='Manutenção Preventiva'
                    GROUP BY veiculo_id
                """, emp_id)
                for _, v in df_v_km.iterrows():
                    ultimo_km = 0.0
                    if not df_manu.empty and v["id"] in df_manu["veiculo_id"].values:
                        serie = df_manu.loc[
                            df_manu["veiculo_id"] == v["id"], "ultimo_km"
                        ]
                        if not serie.empty and pd.notna(serie.iloc[0]):
                            ultimo_km = float(serie.iloc[0])
                    km_rodado = float(v["km_atual"] or 0) - ultimo_km
                    if km_rodado >= 9500:
                        revisoes_proximas.append({
                            "placa": v["placa"],
                            "servico": "Revisão preventiva",
                            "status": "PRÓXIMO",
                            "detalhe": (
                                f"{km_rodado:,.0f} km desde a última preventiva"
                            ),
                        })

            if revisoes_proximas:
                veiculos_alerta = len({r["placa"] for r in revisoes_proximas})
                primeiro = revisoes_proximas[0]
                alertas.append((
                    "Manutenção preventiva",
                    (
                        f"{veiculos_alerta} veículo(s) exigem atenção. "
                        f"{primeiro['placa']} · {primeiro['servico']} "
                        f"({primeiro['status']})."
                    ),
                ))

            qtd_revisao = len({r["placa"] for r in revisoes_proximas})
            veiculos_saudaveis = max(
                veiculos_totais - veiculos_manutencao - qtd_revisao, 0
            )

            # ── Cabeçalho executivo ────────────────────────────────────────────────
            nome_usuario = str(st.session_state.get("nome") or "Gestor").strip()
            primeiro_nome = html.escape(nome_usuario.split()[0] if nome_usuario else "Gestor")
            meses_pt = [
                "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
            ]
            periodo_label = f"{meses_pt[hoje.month - 1]} de {hoje.year}"

            st.markdown(
                f"""
                <div class="kineo-dashboard-hero">
                    <div>
                        <div class="kineo-dashboard-eyebrow">Visão executiva</div>
                        <h1>Olá, {primeiro_nome}. Veja sua operação hoje.</h1>
                        <p>Frota, contratos e financeiro reunidos em uma visão objetiva para apoiar decisões rápidas.</p>
                    </div>
                    <div class="kineo-dashboard-period">
                        <span>Competência atual</span>
                        <strong>{html.escape(periodo_label)}</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ── KPIs executivos ───────────────────────────────────────────────────
            st.markdown(
                """
                <div class="kineo-section-heading">
                    <div><h2>Indicadores principais</h2><p>Resumo financeiro e operacional da competência atual.</p></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                dashboard_kpi_card(
                    "Faturamento",
                    fmt_brl(faturamento_mes_atual),
                    variacao_mes(faturamento_mes_atual, faturamento_mes_anterior),
                    "R$",
                    "green",
                )
            with k2:
                dashboard_kpi_card(
                    "Despesas",
                    fmt_brl(custos_mes_atual),
                    variacao_mes(custos_mes_atual, custos_mes_anterior),
                    "↘",
                    "red",
                )
            with k3:
                dashboard_kpi_card(
                    "Saldo líquido",
                    fmt_brl(saldo_mes),
                    (
                        f"{inadimplencia_qtd} cobrança(s) vencida(s)"
                        if inadimplencia_qtd
                        else "Sem cobranças vencidas"
                    ),
                    "↗" if saldo_mes >= 0 else "−",
                    "blue" if saldo_mes >= 0 else "red",
                )
            with k4:
                dashboard_kpi_card(
                    "Taxa de ocupação",
                    f"{taxa_ocupacao:.1f}%",
                    f"{veiculos_alugados} alugado(s) de {veiculos_totais} veículo(s)",
                    "%",
                    "indigo",
                )

            if encargos_recebidos_mes > 0:
                st.caption(
                    f"O faturamento do mês inclui {fmt_brl(encargos_recebidos_mes)} "
                    "em multa e juros de cobranças recebidas em atraso."
                )

            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                dashboard_mini_stat("Frota total", veiculos_totais)
            with m2:
                dashboard_mini_stat("Disponíveis", veiculos_disponiveis)
            with m3:
                dashboard_mini_stat("Contratos ativos", contratos_ativos)
            with m4:
                dashboard_mini_stat("Vencendo em 30 dias", contratos_vencendo_30)
            with m5:
                dashboard_mini_stat("Reservas em uso", reservas_em_uso)

            # ── Alertas executivos ────────────────────────────────────────────────
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            st.markdown(
                """
                <div class="kineo-section-heading">
                    <div><h2>Atenção operacional</h2><p>Pontos que merecem acompanhamento antes de virarem impacto.</p></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if alertas:
                cols_alerta = st.columns(min(len(alertas), 4))
                for idx, (titulo, descricao) in enumerate(alertas[:4]):
                    with cols_alerta[idx]:
                        st.markdown(
                            f"""
                            <div class="kineo-alert-card">
                                <span class="tag">Acompanhar</span>
                                <strong>{html.escape(str(titulo))}</strong>
                                <p>{html.escape(str(descricao))}</p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
            else:
                st.markdown(
                    '<div class="kineo-ok-card">✓ Nenhum alerta operacional relevante neste momento.</div>',
                    unsafe_allow_html=True,
                )

            # ── Visão analítica principal ─────────────────────────────────────────
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            with st.container(border=True):
                st.markdown("### Evolução Financeira")
                st.caption("Faturamento e despesas nos últimos meses.")

                if not df_custos.empty or not df_cobrancas.empty:
                    frames_fluxo = []

                    if not df_custos.empty:
                        dc = (
                            df_custos.groupby("mes_ano")["valor_total"]
                            .sum()
                            .reset_index()
                        )
                        dc.columns = ["mes_ano", "valor"]
                        dc["tipo"] = "Despesas"
                        frames_fluxo.append(dc)

                    if not df_cobrancas.empty:
                        df_cobrancas_graf = df_cobrancas[
                            ~df_cobrancas["status"].isin(["Cancelada", "Não cobrar"])
                        ].copy()
                        dr = (
                            df_cobrancas_graf.groupby("mes_ano")["_valor_dashboard"]
                            .sum()
                            .reset_index()
                        )
                        dr.columns = ["mes_ano", "valor"]
                        dr["tipo"] = "Faturamento"
                        frames_fluxo.append(dr)

                    df_fluxo = pd.concat(frames_fluxo, ignore_index=True)
                    df_fluxo["data_ordem"] = pd.to_datetime(
                        df_fluxo["mes_ano"], format="%m/%Y", errors="coerce"
                    )
                    df_fluxo = (
                        df_fluxo.dropna(subset=["data_ordem"])
                        .sort_values("data_ordem")
                    )

                    if not df_fluxo.empty:
                        meses = df_fluxo["mes_ano"].drop_duplicates().tolist()[-12:]
                        df_fluxo = df_fluxo[df_fluxo["mes_ano"].isin(meses)]

                        fig_fluxo = px.bar(
                            df_fluxo,
                            x="mes_ano",
                            y="valor",
                            color="tipo",
                            barmode="group",
                            text="valor",
                            color_discrete_map={
                                "Faturamento": "#1768E5",
                                "Despesas": "#8CA3C2",
                            },
                        )
                        fig_fluxo.update_traces(
                            hovertemplate="<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>",
                            marker_line_width=0,
                            texttemplate="R$ %{text:,.0f}",
                            textposition="outside",
                            cliponaxis=False,
                        )
                        fig_fluxo.update_layout(
                            **{
                                **PLOTLY_LAYOUT,
                                "margin": dict(l=10, r=10, t=35, b=10),
                            },
                            height=310,
                            separators=",.",
                            bargap=0.28,
                            xaxis=dict(title="", type="category", showgrid=False),
                            yaxis=dict(
                                title="",
                                tickprefix="R$ ",
                                gridcolor="#EDF2F7",
                                zeroline=False,
                            ),
                            legend=dict(
                                title="",
                                orientation="h",
                                y=1.10,
                                x=0,
                            ),
                        )
                        st.plotly_chart(
                            fig_fluxo,
                            use_container_width=True,
                            config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True},
                        )
                    else:
                        st.info("Ainda não há histórico mensal suficiente.", icon=None)
                else:
                    vf1, vf2 = st.columns(2)
                    vf1.metric("Receita no mês", fmt_brl(faturamento_mes_atual))
                    vf2.metric("Despesa no mês", fmt_brl(custos_mes_atual))
                    st.info(
                        "Cadastre despesas ou cobranças para habilitar a evolução financeira.",
                        icon=None,
                    )

            # ── Contratos e saúde da frota ────────────────────────────────────────
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            col_contratos, col_saude = st.columns([1, 1])

            with col_contratos:
                with st.container(border=True):
                    st.markdown("### Carteira de Contratos")
                    st.caption("Leitura rápida da operação comercial.")

                    st.markdown(
                        f"""
                        <div class="kineo-contract-row"><span>Receita mensal contratada</span><strong>{html.escape(fmt_brl(receita_contratada))}</strong></div>
                        <div class="kineo-contract-row"><span>Contratos ativos</span><strong>{contratos_ativos}</strong></div>
                        <div class="kineo-contract-row"><span>Vencendo em 30 dias</span><strong>{contratos_vencendo_30}</strong></div>
                        <div class="kineo-contract-row"><span>Reservas em uso</span><strong>{reservas_em_uso}</strong></div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if reservas_em_uso > 0:
                        st.markdown("**Substituições temporárias**")
                        for _, r in df_substituicoes_dash.head(3).iterrows():
                            cliente = html.escape(str(r["cliente"]))
                            principal = html.escape(str(r["placa_principal"]))
                            reserva = html.escape(str(r["placa_substituto"]))
                            st.caption(f"{cliente} · {principal} → {reserva}")

            with col_saude:
                with st.container(border=True):
                    st.markdown("### Saúde da Frota")
                    st.caption("Disponibilidade e manutenção preventiva.")

                    st.markdown(
                        f"""
                        <div class="kineo-health-row"><span>Operação normal</span><strong>{veiculos_saudaveis}</strong></div>
                        <div class="kineo-health-row"><span>Em manutenção</span><strong>{veiculos_manutencao}</strong></div>
                        <div class="kineo-health-row"><span>Revisão próxima</span><strong>{qtd_revisao}</strong></div>
                        <div class="kineo-health-row"><span>Reservas em uso</span><strong>{reservas_em_uso}</strong></div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if revisoes_proximas:
                        st.markdown("**Próximas atenções**")
                        for revisao in revisoes_proximas[:3]:
                            st.caption(
                                f"{revisao['placa']} · {revisao['servico']} · "
                                f"{revisao['status']} · {revisao['detalhe']}"
                            )
                    elif veiculos_manutencao == 0:
                        st.success("Nenhum alerta crítico de manutenção.", icon=None)

            # ── Custos e atalhos ──────────────────────────────────────────────────
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            col_custos, col_acoes = st.columns([1.55, 1])

            with col_custos:
                with st.container(border=True):
                    st.markdown("### Maiores Custos por Veículo")
                    st.caption("Veículos com maior impacto financeiro acumulado.")

                    if not df_custos.empty:
                        df_gastos = (
                            df_custos.groupby(
                                ["veiculo_id", "placa", "modelo"],
                                dropna=False,
                            )["valor_total"]
                            .sum()
                            .reset_index()
                            .sort_values("valor_total", ascending=False)
                            .head(5)
                        )
                        if not df_gastos.empty:
                            df_gastos["veiculo"] = (
                                df_gastos["placa"].fillna("Sem placa").astype(str)
                                + " · "
                                + df_gastos["modelo"].fillna("").astype(str)
                            )
                            fig_gastos = px.bar(
                                df_gastos.sort_values("valor_total"),
                                x="valor_total",
                                y="veiculo",
                                orientation="h",
                                text="valor_total",
                                color_discrete_sequence=["#3D78D8"],
                            )
                            fig_gastos.update_traces(
                                hovertemplate="<b>%{y}</b><br>R$ %{x:,.2f}<extra></extra>",
                                marker_line_width=0,
                                texttemplate="R$ %{text:,.0f}",
                                textposition="outside",
                                cliponaxis=False,
                            )
                            fig_gastos.update_layout(
                                **{
                                    **PLOTLY_LAYOUT,
                                    "margin": dict(l=5, r=70, t=10, b=5),
                                },
                                height=250,
                                separators=",.",
                                xaxis=dict(
                                    title="",
                                    showgrid=True,
                                    gridcolor="#EDF2F7",
                                    tickprefix="R$ ",
                                ),
                                yaxis=dict(title=""),
                            )
                            st.plotly_chart(
                                fig_gastos,
                                use_container_width=True,
                                config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True},
                            )
                    else:
                        st.info(
                            "O ranking aparecerá após os primeiros lançamentos de despesas.",
                            icon=None,
                        )

            with col_acoes:
                with st.container(border=True):
                    st.markdown("### Ações Rápidas")
                    st.caption("Acesse as rotinas mais frequentes.")

                    st.button(
                        "Registrar despesa",
                        icon=":material/add_card:",
                        use_container_width=True,
                        on_click=set_menu,
                        args=("Gestão de Custos",),
                        key="dash_v11_acao_custos",
                    )
                    st.button(
                        "Abrir contratos",
                        icon=":material/description:",
                        use_container_width=True,
                        on_click=set_menu,
                        args=("Contratos e Locação",),
                        key="dash_v11_acao_contratos",
                    )
                    st.button(
                        "Gerenciar frota",
                        icon=":material/directions_car:",
                        use_container_width=True,
                        on_click=set_menu,
                        args=("Gestão de Frota",),
                        key="dash_v11_acao_frota",
                    )
                    st.button(
                        "Abrir cobranças",
                        icon=":material/request_quote:",
                        use_container_width=True,
                        on_click=set_menu,
                        args=("Gestão de Cobranças",),
                        key="dash_v11_acao_cobrancas",
                    )

        elif tela_ativa == "Gestão de Frota":
            aplicar_css_gestao_frota_v11()
            st.markdown('<div class="kineo-frota-v11"></div>', unsafe_allow_html=True)

            df_veiculos = carregar_dados_tabela(
                "SELECT * FROM veiculos WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1", emp_id
            )
            total = len(df_veiculos)

            qtd_disponiveis = (
                len(df_veiculos[df_veiculos["status"] == "Disponível"])
                if total else 0
            )
            qtd_alugados = (
                len(df_veiculos[df_veiculos["status"] == "Alugado"])
                if total else 0
            )
            qtd_manutencao = (
                len(df_veiculos[df_veiculos["status"] == "Manutenção"])
                if total else 0
            )
            ocupacao_frota = (qtd_alugados / total * 100) if total else 0.0

            st.markdown(
                f"""
                <div class="kineo-frota-hero">
                    <div>
                        <div class="kineo-frota-eyebrow">Operação da frota</div>
                        <h1>Gestão de Frota</h1>
                        <p>Cadastre veículos, acompanhe disponibilidade, custos e manutenção preventiva em um único ambiente.</p>
                    </div>
                    <div class="kineo-frota-total">
                        <span>Veículos ativos</span>
                        <strong>{total}</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                frota_stat_card("Frota total", total, "veículos ativos", "blue")
            with c2:
                frota_stat_card("Disponíveis", qtd_disponiveis, "prontos para operação", "green")
            with c3:
                frota_stat_card(
                    "Em contrato",
                    qtd_alugados,
                    f"{ocupacao_frota:.1f}% de ocupação",
                    "indigo",
                )
            with c4:
                frota_stat_card("Em manutenção", qtd_manutencao, "atenção operacional", "amber")
            
            pagina_frota = st.session_state["pagina_frota"]

            # ── Aba: Visão geral operacional ─────────────────────────────────────
            if pagina_frota == "Visão da Frota":
                st.markdown(
                    """
                    <div class="kineo-frota-overview-head">
                        <div>
                            <h2>Catálogo operacional</h2>
                            <p>Consulte rapidamente a situação e os principais dados de cada veículo.</p>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if total == 0:
                    st.info(
                        "A frota ainda está vazia. Use a aba **Adicionar veículo** para iniciar a operação.",
                        icon=None,
                    )
                else:
                    filtro_busca_col, filtro_status_col = st.columns([1.45, 1])
                    busca_frota = filtro_busca_col.text_input(
                        "Localizar veículo",
                        placeholder="Busque por placa, modelo ou fabricante",
                        key="frota_visao_busca",
                    )
                    status_existentes = sorted(
                        df_veiculos["status"].dropna().astype(str).unique().tolist()
                    )
                    status_frota = filtro_status_col.multiselect(
                        "Situação operacional",
                        status_existentes,
                        default=status_existentes,
                        key="frota_visao_status",
                    )

                    df_catalogo = df_veiculos.copy()
                    if status_frota:
                        df_catalogo = df_catalogo[
                            df_catalogo["status"].astype(str).isin(status_frota)
                        ]
                    else:
                        df_catalogo = df_catalogo.iloc[0:0]

                    termo_frota = str(busca_frota or "").strip().lower()
                    if termo_frota:
                        campos_busca = [
                            coluna for coluna in ["placa", "modelo", "fabricante"]
                            if coluna in df_catalogo.columns
                        ]
                        mascara_busca = pd.Series(False, index=df_catalogo.index)
                        for coluna in campos_busca:
                            mascara_busca = mascara_busca | (
                                df_catalogo[coluna]
                                .fillna("")
                                .astype(str)
                                .str.lower()
                                .str.contains(termo_frota, regex=False)
                            )
                        df_catalogo = df_catalogo[mascara_busca]

                    colunas_catalogo = [
                        coluna for coluna in [
                            "placa", "fabricante", "modelo", "ano_modelo",
                            "combustivel", "transmissao", "km_atual", "status"
                        ] if coluna in df_catalogo.columns
                    ]
                    catalogo_exibir = df_catalogo[colunas_catalogo].copy()
                    catalogo_exibir = catalogo_exibir.rename(columns={
                        "placa": "Placa",
                        "fabricante": "Fabricante",
                        "modelo": "Modelo",
                        "ano_modelo": "Ano/modelo",
                        "combustivel": "Combustível",
                        "transmissao": "Transmissão",
                        "km_atual": "KM atual",
                        "status": "Situação",
                    })

                    tabela_col, insights_col = st.columns([2.7, 1])
                    with tabela_col:
                        with st.container(border=True):
                            st.markdown(f"**{len(catalogo_exibir)} veículo(s) encontrado(s)**")
                            st.caption("A lista respeita os filtros aplicados acima.")
                            st.dataframe(
                                catalogo_exibir,
                                use_container_width=True,
                                hide_index=True,
                            )

                    with insights_col:
                        sem_plano = (
                            int(df_veiculos["plano_manutencao_id"].isna().sum())
                            if "plano_manutencao_id" in df_veiculos.columns else total
                        )
                        st.markdown(
                            f"""
                            <div class="kineo-frota-insight">
                                <span>Disponibilidade</span>
                                <strong>{qtd_disponiveis} veículo(s)</strong>
                                <small>Prontos para uma nova operação ou contrato.</small>
                            </div>
                            <div style="height:10px"></div>
                            <div class="kineo-frota-insight">
                                <span>Manutenção</span>
                                <strong>{qtd_manutencao} veículo(s)</strong>
                                <small>Atualmente sinalizados em manutenção.</small>
                            </div>
                            <div style="height:10px"></div>
                            <div class="kineo-frota-insight">
                                <span>Plano preventivo</span>
                                <strong>{sem_plano} sem plano</strong>
                                <small>Cadastros que ainda precisam de um plano associado.</small>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            # ── Aba: Cadastro ─────────────────────────────────────────────────────
            elif pagina_frota == "Veículos":
                st.markdown(
                    """
                    <div class="kineo-frota-overview-head">
                        <div>
                            <h2>Entrada de veículos</h2>
                            <p>Escolha entre o cadastro guiado de uma unidade ou a importação de uma frota.</p>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                col_cad_tipo1, col_cad_tipo2 = st.tabs(["Cadastro guiado", "Importação em massa"])

                with col_cad_tipo1:
                    veiculo_form_version = st.session_state["veiculo_form_version"]
                    with st.container(border=True):
                        st.markdown("**Adicionar Novo Veículo**")
                        status_novo = st.selectbox(
                            "Status inicial",
                            ["Disponível", "Alugado", "Manutenção"],
                            key=f"frota_status_novo_{veiculo_form_version}",
                        )
                        
                        with st.container():
                            ca, cb, cc = st.columns([0.9, 1.15, 0.7])
                            placa = ca.text_input("Placa", placeholder="ABC-1234", key=f"frota_placa_novo_{veiculo_form_version}")
                            fabricante = cb.text_input("Fabricante", placeholder="Ex.: Fiat", key=f"frota_fabricante_novo_{veiculo_form_version}")
                            ano_modelo = cc.number_input("Ano/modelo", min_value=1900, max_value=2100, step=1, value=hoje_local().year, key=f"frota_ano_novo_{veiculo_form_version}")

                            cm1, cm2, cm3 = st.columns(3)
                            modelo = cm1.text_input("Modelo", placeholder="Ex.: Argo", key=f"frota_modelo_novo_{veiculo_form_version}")
                            versao = cm2.text_input("Versão (opcional)", placeholder="Ex.: Drive", key=f"frota_versao_novo_{veiculo_form_version}")
                            motorizacao = cm3.text_input("Motorização (opcional)", placeholder="Ex.: 1.0 Firefly", key=f"frota_motor_novo_{veiculo_form_version}")

                            cm4, cm5, cm6 = st.columns(3)
                            combustivel_veiculo = cm4.selectbox("Combustível", ["Não informado", "Flex", "Gasolina", "Etanol", "Diesel", "Elétrico", "Híbrido"], key=f"frota_combustivel_novo_{veiculo_form_version}")
                            transmissao = cm5.selectbox("Transmissão", ["Não informado", "Manual", "Automática", "Automatizada", "CVT"], key=f"frota_transmissao_novo_{veiculo_form_version}")
                            km = cm6.number_input("KM atual", min_value=0.0, step=100.0, value=0.0, key=f"frota_km_novo_{veiculo_form_version}")

                            d_inicio = km_ini = d_fim = km_fim = cliente = cnpj_v = tipo_v = None
                            valor_m = multa_c = juros_c = 0.0
                            is_ativo = False
                            
                            if status_novo == "Alugado":
                                st.markdown("---")
                                st.markdown("**Dados do contrato**")
                                c1, c2 = st.columns(2)
                                cliente  = c1.text_input("Razão Social do Cliente", key=f"frota_cliente_novo_{veiculo_form_version}")
                                cnpj_v   = c2.text_input("CNPJ", key=f"frota_cnpj_novo_{veiculo_form_version}")
                                
                                c3, c4   = st.columns(2)
                                d_inicio = c3.date_input("Início do contrato", format="DD/MM/YYYY", key=f"frota_inicio_novo_{veiculo_form_version}")
                                km_ini   = c4.number_input("KM na entrega", min_value=0.0, step=50.0, value=0.0, key=f"frota_km_entrega_novo_{veiculo_form_version}")
                                
                                st.markdown("**Dados Financeiros do Contrato**")
                                cf1, cf2 = st.columns(2)
                                tipo_v = cf1.selectbox("Tipo de Cobrança", ["Fixo", "Variável"], key=f"frota_tipo_{veiculo_form_version}")
                                valor_m = 0.0
                                comp_var_frota = None
                                valor_comp_var_frota = 0.0
                                valor_comp_var_frota_txt = ""

                                if tipo_v == "Fixo":
                                    valor_m_txt = cf2.text_input(
                                        "Valor Mensal (R$)",
                                        value="",
                                        placeholder="Ex.: 52.800,00",
                                        key=f"frota_val_{veiculo_form_version}"
                                    )
                                    valor_m = parse_valor_cobranca(valor_m_txt)
                                else:
                                    cf2.info("Receita variável: o valor é informado por competência.")
                                    vf1, vf2 = st.columns(2)
                                    competencias_var = opcoes_competencias(12, 18)
                                    comp_padrao = hoje_local().strftime("%m/%Y")
                                    idx_comp = competencias_var.index(comp_padrao) if comp_padrao in competencias_var else 12
                                    comp_var_frota = vf1.selectbox(
                                        "Mês de referência",
                                        competencias_var,
                                        index=idx_comp,
                                        key=f"frota_comp_var_{veiculo_form_version}"
                                    )
                                    valor_comp_var_frota_txt = vf2.text_input(
                                        "Valor previsto da competência (R$)",
                                        value="",
                                        placeholder="Ex.: 52.800,00",
                                        key=f"frota_val_comp_var_{veiculo_form_version}"
                                    )
                                    valor_comp_var_frota = parse_valor_cobranca(valor_comp_var_frota_txt)
                                    st.caption(
                                        "O valor acima pertence somente à competência selecionada. "
                                        "Os próximos meses podem ter valores diferentes."
                                    )
                                
                                cf3, cf4 = st.columns(2)
                                multa_c = cf3.number_input("Multa por Atraso (%)", min_value=0.0, step=1.0, value=2.0, key=f"frota_mul_{veiculo_form_version}")
                                juros_c = cf4.number_input("Juros ao Mês (%)", min_value=0.0, step=0.1, value=1.0, key=f"frota_jur_{veiculo_form_version}")

                                st.markdown("<br>", unsafe_allow_html=True)
                                is_ativo = st.checkbox("Contrato em andamento", value=True, key=f"frota_contrato_ativo_{veiculo_form_version}")
                                
                                if not is_ativo:
                                    c5, c6 = st.columns(2)
                                    d_fim  = c5.date_input("Data de devolução", format="DD/MM/YYYY", key=f"frota_fim_novo_{veiculo_form_version}")
                                    km_fim = c6.number_input("KM na devolução", min_value=0.0, step=50.0, value=0.0, key=f"frota_km_devolucao_novo_{veiculo_form_version}")

                            if st.button("Salvar Veículo", use_container_width=True, key=f"btn_salvar_veiculo_{veiculo_form_version}"):
                                if not placa or not modelo:
                                    st.error("Placa e Modelo são obrigatórios.", icon=None)
                                else:
                                    km_val = km or 0.0
                                    session = SessionLocal()
                                    erro = False
                                    
                                    if status_novo == "Alugado" and not is_ativo:
                                        km_ini_v = km_ini or 0.0
                                        km_fim_v = km_fim or 0.0
                                        if d_fim < d_inicio or km_fim_v < km_ini_v:
                                            st.error("Datas ou KMs inválidos.", icon=None)
                                            erro = True
                                            
                                    if not erro:
                                        nv = Veiculo(
                                            empresa_id=emp_id,
                                            placa=placa.upper(),
                                            fabricante=fabricante or None,
                                            modelo=modelo,
                                            ano_modelo=int(ano_modelo) if ano_modelo else None,
                                            versao=versao or None,
                                            motorizacao=motorizacao or None,
                                            combustivel=None if combustivel_veiculo == "Não informado" else combustivel_veiculo,
                                            transmissao=None if transmissao == "Não informado" else transmissao,
                                            km_atual=km_val,
                                            status=status_novo
                                        )
                                        session.add(nv)
                                        session.flush()
                                        
                                        if status_novo == "Alugado":
                                            novo_contrato = Contrato(
                                                empresa_id=emp_id, 
                                                veiculo_id=nv.id,
                                                cliente=cliente, 
                                                cnpj=cnpj_v,
                                                data_inicio=d_inicio, 
                                                data_fim=d_fim,
                                                km_inicial=km_ini or 0.0, 
                                                km_final=km_fim or 0.0,
                                                ativo=1 if is_ativo else 0,
                                                usuario_lancamento=st.session_state["nome"],
                                                tipo_valor=tipo_v, 
                                                valor_mensal=decimal_monetario(valor_m) if tipo_v == "Fixo" else Decimal("0.00"),
                                                multa=multa_c, 
                                                juros=juros_c
                                            )
                                            session.add(novo_contrato)
                                            session.flush()
                                            if tipo_v == "Variável" and valor_comp_var_frota_txt.strip():
                                                salvar_valor_variavel_competencia(
                                                    session, emp_id, novo_contrato,
                                                    comp_var_frota, valor_comp_var_frota
                                                )
                                                registrar_auditoria(
                                                    session, emp_id, st.session_state["usuario_id"],
                                                    "VALOR_VARIAVEL_COMPETENCIA", "Contrato", novo_contrato.id,
                                                    f"Competência {comp_var_frota}; valor {valor_comp_var_frota:.2f}"
                                                )
                                            
                                        session.commit()
                                        st.cache_data.clear()
                                        session.close()
                                        st.session_state["veiculo_form_version"] += 1
                                        st.success(f"Veículo cadastrado com sucesso.")
                                        time.sleep(0.8)
                                        st.rerun()

                # ── Aba de Importação em Massa (.xls / .xlsx) ────────────────────────
                with col_cad_tipo2:
                    with st.container(border=True):
                        st.markdown("**Importação em Massa de Veículos Disponíveis**")
                        st.caption("Envie uma planilha contendo as colunas: **placa**, **modelo** e **km** (opcional). Os veículos serão cadastrados automaticamente com o status **Disponível**.")

                        arquivo_xls = st.file_uploader("Selecione o arquivo Excel (.xls ou .xlsx)", type=["xls", "xlsx"], key=f"up_xls_{st.session_state['uploader_key']}")

                        if arquivo_xls:
                            try:
                                ok_upload, erro_upload = validar_upload_basico(
                                    arquivo_xls, {"xls", "xlsx"}, max_mb=10
                                )
                                if not ok_upload:
                                    raise ValueError(erro_upload)
                                df_import = pd.read_excel(arquivo_xls)
                                if len(df_import) > 5000:
                                    raise ValueError("A planilha excede o limite de 5.000 veículos por importação.")
                                df_import.columns = [str(c).strip().lower() for c in df_import.columns]

                                colunas_necessarias = ["placa", "modelo"]
                                if not all(col in df_import.columns for col in colunas_necessarias):
                                    st.error("O arquivo Excel precisa conter obrigatoriamente as colunas 'placa' e 'modelo'.", icon=None)
                                else:
                                    st.markdown("---")
                                    st.markdown("**Pré-visualização dos dados carregados:**")
                                    st.dataframe(df_import.head(), use_container_width=True)

                                    if st.button("Confirmar Importação de Veículos", use_container_width=True):
                                        session = SessionLocal()
                                        sucessos = 0
                                        erros = 0

                                        for _, row in df_import.iterrows():
                                            p_val = str(row["placa"]).strip().upper()
                                            m_val = str(row["modelo"]).strip()

                                            if not p_val or p_val == "NAN" or not m_val or m_val == "NAN":
                                                erros += 1
                                                continue

                                            km_val = 0.0
                                            if "km" in df_import.columns:
                                                try:
                                                    val_k = row["km"]
                                                    if pd.notna(val_k):
                                                        km_val = float(val_k)
                                                except:
                                                    km_val = 0.0

                                            existe_placa = session.query(Veiculo).filter_by(empresa_id=emp_id, placa=p_val).first()
                                            if not existe_placa:
                                                novo_v = Veiculo(
                                                    empresa_id=emp_id,
                                                    placa=p_val,
                                                    modelo=m_val,
                                                    km_atual=km_val,
                                                    status="Disponível"
                                                )
                                                session.add(novo_v)
                                                sucessos += 1

                                        session.commit()
                                        st.cache_data.clear()
                                        session.close()

                                        st.success(f"Importação concluída! {sucessos} veículo(s) cadastrado(s) com sucesso. ({erros} ignorados).")
                                        # Atualiza a key do uploader para limpá-lo, o st.rerun() voltará para a aba de Cadastro Individual
                                        st.session_state["uploader_key"] += 1
                                        time.sleep(1.5)
                                        st.rerun()

                            except ValueError as e:
                                st.error(str(e), icon=None)
                            except Exception:
                                logger.exception("Falha ao processar planilha de veículos")
                                st.error("Não foi possível processar a planilha de veículos.", icon=None)

                if st.session_state["perfil"] == "admin":
                    with st.expander("Arquivar / excluir veículo — Zona restrita"):
                        st.caption(
                            "Veículos com histórico nunca têm custos, contratos ou manutenções apagados. "
                            "Nesses casos o Kineo apenas arquiva o cadastro. Exclusão física fica restrita "
                            "a veículos criados por engano e sem qualquer movimentação."
                        )

                        if total > 0:
                            opcoes_v = {
                                f"{r['modelo']} ({r['placa']})": int(r["id"])
                                for _, r in df_veiculos.iterrows()
                            }
                            v_excluir = st.selectbox(
                                "Veículo", list(opcoes_v.keys()), key="veiculo_arquivar_excluir"
                            )
                            vid = opcoes_v[v_excluir]

                            session_ref = SessionLocal()
                            try:
                                pode_excluir, hist = veiculo_pode_ser_excluido(
                                    session_ref, emp_id, vid
                                )
                            finally:
                                session_ref.close()

                            if hist.get("contratos_ativos", 0) > 0:
                                st.warning(
                                    "Este veículo possui contrato vigente. Finalize o contrato antes de arquivar o veículo.",
                                    icon=None,
                                )
                            elif pode_excluir:
                                confirmar = st.checkbox(
                                    f"Confirmo a exclusão permanente de {v_excluir}.",
                                    key="confirmar_exclusao_veiculo_sem_historico",
                                )
                                if st.button(
                                    "Excluir cadastro sem histórico",
                                    use_container_width=True,
                                    disabled=not confirmar,
                                    key="btn_excluir_veiculo_sem_historico",
                                ):
                                    session = SessionLocal()
                                    try:
                                        veiculo = tenant_get(session, Veiculo, vid, emp_id)
                                        if veiculo is None:
                                            raise ValueError("Veículo não encontrado.")
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "VEICULO_EXCLUIDO", "Veiculo", int(vid),
                                            "Exclusão física autorizada por ausência de histórico.",
                                        )
                                        session.delete(veiculo)
                                        session.commit()
                                        st.cache_data.clear()
                                        st.success("Cadastro de veículo sem histórico excluído.")
                                        st.rerun()
                                    except Exception:
                                        session.rollback()
                                        logger.exception("Falha ao excluir veículo sem histórico")
                                        st.error("Não foi possível excluir o veículo.", icon=None)
                                    finally:
                                        session.close()
                            else:
                                st.info(
                                    f"Histórico encontrado: {hist['contratos']} contrato(s), "
                                    f"{hist['custos']} custo(s), {hist['manutencoes']} manutenção(ões) e "
                                    f"{hist['substituicoes']} substituição(ões). O histórico será preservado.",
                                    icon=None,
                                )
                                confirmar_arq = st.checkbox(
                                    f"Confirmo o arquivamento de {v_excluir}.",
                                    key="confirmar_arquivamento_veiculo",
                                )
                                if st.button(
                                    "Arquivar veículo",
                                    use_container_width=True,
                                    disabled=not confirmar_arq,
                                    key="btn_arquivar_veiculo",
                                ):
                                    session = SessionLocal()
                                    try:
                                        veiculo = tenant_get(session, Veiculo, vid, emp_id)
                                        if veiculo is None:
                                            raise ValueError("Veículo não encontrado.")
                                        veiculo.ativo = 0
                                        veiculo.status = "Arquivado"
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "VEICULO_ARQUIVADO", "Veiculo", int(vid),
                                            "Cadastro arquivado com histórico operacional e financeiro preservado.",
                                        )
                                        session.commit()
                                        st.cache_data.clear()
                                        st.success("Veículo arquivado sem perda de histórico.")
                                        st.rerun()
                                    except Exception:
                                        session.rollback()
                                        logger.exception("Falha ao arquivar veículo")
                                        st.error("Não foi possível arquivar o veículo.", icon=None)
                                    finally:
                                        session.close()
                        else:
                            st.caption("Nenhum veículo ativo disponível para arquivar ou excluir.")

                        df_arquivados = carregar_dados_tabela(
                            "SELECT id, placa, modelo FROM veiculos "
                            "WHERE empresa_id=:empresa_id AND COALESCE(ativo,1)=0 ORDER BY modelo, placa",
                            emp_id,
                        )
                        if not df_arquivados.empty:
                            st.markdown("**Veículos arquivados**")
                            op_arq = {
                                f"{r['modelo']} ({r['placa']})": int(r["id"])
                                for _, r in df_arquivados.iterrows()
                            }
                            arq_sel = st.selectbox(
                                "Reativar veículo", list(op_arq.keys()), key="reativar_veiculo_sel"
                            )
                            if st.button(
                                "Reativar cadastro", use_container_width=True, key="btn_reativar_veiculo"
                            ):
                                session = SessionLocal()
                                try:
                                    veiculo = tenant_get(session, Veiculo, op_arq[arq_sel], emp_id)
                                    if veiculo is None:
                                        raise ValueError("Veículo não encontrado.")
                                    veiculo.ativo = 1
                                    veiculo.status = "Disponível"
                                    registrar_auditoria(
                                        session, emp_id, st.session_state["usuario_id"],
                                        "VEICULO_REATIVADO", "Veiculo", veiculo.id,
                                    )
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Veículo reativado.")
                                    st.rerun()
                                except Exception:
                                    session.rollback()
                                    logger.exception("Falha ao reativar veículo")
                                    st.error("Não foi possível reativar o veículo.", icon=None)
                                finally:
                                    session.close()

            # ── Aba: Alterar Status ────────────────────────────────────────────────
            elif pagina_frota == "Status da Frota":
                if total == 0:
                    st.info("Nenhum veículo cadastrado.", icon=None)
                else:
                    with st.container(border=True):
                        st.markdown("**Alteração operacional do veículo**")
                        st.caption("Quando um veículo com contrato vigente entra em manutenção, selecione um veículo disponível para atuar como reserva. Ao retornar o principal para Alugado, o reserva é liberado automaticamente.")

                        opcoes_status = {
                            f"{r['modelo']} ({r['placa']}) · {r['status']}": int(r['id'])
                            for _, r in df_veiculos.sort_values(["modelo", "placa"]).iterrows()
                        }
                        veiculo_status_sel = st.selectbox(
                            "Veículo",
                            list(opcoes_status.keys()),
                            key="status_veiculo_sel"
                        )
                        veiculo_status_id = opcoes_status[veiculo_status_sel]
                        row_status = df_veiculos[df_veiculos["id"] == veiculo_status_id].iloc[0]
                        status_atual = row_status["status"]

                        st.info(f"Status atual: **{status_atual}**", icon=None)

                        novo_status = st.selectbox(
                            "Novo status",
                            ["Disponível", "Alugado", "Manutenção"],
                            index=["Disponível", "Alugado", "Manutenção"].index(status_atual) if status_atual in ["Disponível", "Alugado", "Manutenção"] else 0,
                            key="status_novo_sel"
                        )

                        session_preview = SessionLocal()
                        contrato_ativo_preview = obter_contrato_ativo_do_principal(session_preview, emp_id, veiculo_status_id)
                        sub_principal_preview = obter_substituicao_ativa_por_principal(session_preview, emp_id, veiculo_status_id)
                        sub_reserva_preview = obter_substituicao_ativa_por_reserva(session_preview, emp_id, veiculo_status_id)
                        session_preview.close()

                        reserva_id = None
                        if novo_status == "Manutenção" and contrato_ativo_preview is not None and sub_principal_preview is None:
                            disponiveis = df_veiculos[
                                (df_veiculos["status"] == "Disponível") &
                                (df_veiculos["id"] != veiculo_status_id)
                            ].copy()

                            if disponiveis.empty:
                                st.warning("Este veículo possui contrato vigente, mas não há veículo disponível para substituição. Cadastre/libere um veículo antes de enviá-lo para manutenção.", icon=None)
                            else:
                                opcoes_reserva = {
                                    f"{r['modelo']} ({r['placa']})": int(r['id'])
                                    for _, r in disponiveis.iterrows()
                                }
                                reserva_label = st.selectbox(
                                    "Veículo reserva durante a manutenção",
                                    list(opcoes_reserva.keys()),
                                    key="status_reserva_sel"
                                )
                                reserva_id = opcoes_reserva[reserva_label]
                                st.caption(f"Contrato vigente: {contrato_ativo_preview.cliente}")

                        if sub_principal_preview is not None:
                            st.info("Este veículo é o principal de uma substituição ativa. Ao retornar para **Alugado**, o veículo reserva será liberado automaticamente.", icon=None)

                        if sub_reserva_preview is not None:
                            st.warning("Este veículo está atuando como reserva de um contrato. O status dele deve ser alterado pelo retorno do veículo principal ou pela aba de Contratos.", icon=None)

                        if st.button("Aplicar alteração de status", use_container_width=True, key="btn_alterar_status_veiculo"):
                            session = SessionLocal()
                            try:
                                veiculo = tenant_get(session, Veiculo, veiculo_status_id, emp_id)
                                if veiculo is None:
                                    raise ValueError("Veículo não encontrado.")

                                sub_reserva = obter_substituicao_ativa_por_reserva(session, emp_id, veiculo.id)
                                if sub_reserva is not None:
                                    raise ValueError("Este veículo está ativo como reserva e não pode ter o status alterado manualmente.")

                                contrato_ativo = obter_contrato_ativo_do_principal(session, emp_id, veiculo.id)
                                sub_principal = obter_substituicao_ativa_por_principal(session, emp_id, veiculo.id)

                                if novo_status == veiculo.status:
                                    st.info("O veículo já está com esse status.", icon=None)
                                elif novo_status == "Manutenção" and contrato_ativo is not None:
                                    if sub_principal is not None:
                                        veiculo.status = "Manutenção"
                                    else:
                                        if reserva_id is None:
                                            raise ValueError("Selecione um veículo reserva para o contrato vigente.")
                                        reserva = tenant_get(session, Veiculo, reserva_id, emp_id)
                                        iniciar_substituicao_contrato(
                                            session, emp_id, contrato_ativo, veiculo, reserva, st.session_state["nome"]
                                        )
                                elif novo_status == "Alugado" and sub_principal is not None:
                                    finalizar_substituicao_contrato(session, sub_principal, status_principal="Alugado")
                                elif novo_status == "Disponível" and contrato_ativo is not None:
                                    raise ValueError("Um veículo principal com contrato vigente não pode ser marcado como Disponível. Finalize o contrato ou mantenha-o Alugado/Manutenção.")
                                else:
                                    veiculo.status = novo_status

                                session.commit()
                                st.cache_data.clear()
                                st.success("Status atualizado com sucesso.")
                                time.sleep(0.6)
                                st.rerun()
                            except ValueError as e:
                                session.rollback()
                                st.error(str(e), icon=None)
                            except Exception:
                                session.rollback()
                                logger.exception("Falha em operação de frota/contrato")
                                st.error("Não foi possível concluir a operação.", icon=None)
                            finally:
                                session.close()

            # ── Aba: Gastos ───────────────────────────────────────────────────────
            elif pagina_frota == "Análise por Veículo":
                if total == 0:
                    st.info("Nenhum veículo cadastrado.", icon=None) 
                else:
                    df_custos_all = carregar_dados_tabela(f"SELECT * FROM custos WHERE empresa_id = :empresa_id", emp_id)
                    
                    if df_custos_all.empty:
                        st.info("Nenhum custo registrado.", icon=None)
                    else:
                        df_custos_all["Mes_Ano"] = pd.to_datetime(df_custos_all["data_custo"]).dt.strftime("%m/%Y")
                        df_custos_all["Sort_Date"] = pd.to_datetime(df_custos_all["data_custo"]).dt.strftime("%Y-%m")
                        df_custos_all = df_custos_all.sort_values("Sort_Date")

                        gasto_veiculo = df_custos_all.groupby("veiculo_id")["valor_total"].sum().reset_index()
                        df_merged = pd.merge(df_veiculos, gasto_veiculo, left_on="id", right_on="veiculo_id", how="left")
                        df_merged["valor_total"] = df_merged["valor_total"].fillna(0)

                        fca, fcb = st.columns(2)
                        ordem = fca.selectbox("Ordenar por", ["Maior gasto", "Menor gasto", "Alfabético"])
                        
                        if ordem == "Maior gasto":   
                            df_merged = df_merged.sort_values("valor_total", ascending=False)
                        elif ordem == "Menor gasto":  
                            df_merged = df_merged.sort_values("valor_total")
                        else:                        
                            df_merged = df_merged.sort_values("modelo")

                        lista_v = [f"{r['modelo']} ({r['placa']})" for _, r in df_merged.iterrows()]
                        sel = fcb.multiselect("Filtrar visualização", lista_v, default=lista_v)

                        for _, v in df_merged.iterrows():
                            label = f"{v['modelo']} ({v['placa']})"
                            if label not in sel: 
                                continue
                                
                            df_v  = df_custos_all[df_custos_all["veiculo_id"] == v["id"]]
                            with st.container(border=True):
                                st.markdown(f"**{label}** · Total Gasto: **{fmt_brl(v['valor_total'])}**")
                                
                                if not df_v.empty:
                                    ga, gb = st.columns(2)
                                    df_comb = df_v[df_v["categoria"] == "Combustível"].groupby("Mes_Ano")["valor_total"].sum().reset_index()
                                    df_outr = df_v[df_v["categoria"] != "Combustível"].groupby(["Mes_Ano", "categoria"])["valor_total"].sum().reset_index()
                                    
                                    with ga:
                                        if not df_comb.empty:
                                            fig_comb = px.bar(
                                                df_comb, 
                                                x="Mes_Ano", 
                                                y="valor_total", 
                                                text="valor_total", 
                                                color_discrete_sequence=[PALETTE["green"]]
                                            )
                                            fig_comb.update_traces(texttemplate="R$ %{text:,.0f}", textposition="outside")
                                            fig_comb.update_layout(
                                                **PLOTLY_LAYOUT, 
                                                title_text="Combustível", 
                                                height=220, 
                                                xaxis=dict(title="", type="category"), 
                                                yaxis=dict(visible=False)
                                            )
                                            st.plotly_chart(fig_comb, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True}, key=f"custos_combustivel_{v['id']}")
                                        else:
                                            st.caption("Sem abastecimentos.")
                                            
                                    with gb:
                                        if not df_outr.empty:
                                            fig_outros = px.bar(
                                                df_outr, 
                                                x="Mes_Ano", 
                                                y="valor_total", 
                                                color="categoria", 
                                                text="valor_total",
                                                color_discrete_sequence=[PALETTE["indigo"], PALETTE["amber"], PALETTE["slate"]]
                                            )
                                            fig_outros.update_traces(
                                                texttemplate="R$ %{text:,.0f}",
                                                textposition="outside",
                                                cliponaxis=False,
                                            )
                                            fig_outros.update_layout(
                                                **PLOTLY_LAYOUT, 
                                                title_text="Manutenção e Outros", 
                                                height=220, 
                                                separators=",.",
                                                xaxis=dict(title="", type="category"), 
                                                yaxis=dict(visible=False)
                                            )
                                            st.plotly_chart(fig_outros, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": True}, key=f"custos_outros_{v['id']}")
                                        else:
                                            st.caption("Sem outras despesas.")
                                else:
                                    st.caption("Veículo sem histórico financeiro.")

            # ── Aba: Planos de manutenção ─────────────────────────────────────────
            elif pagina_frota == "Planos de Manutenção":
                st.markdown("### Planos de manutenção")
                st.caption(
                    "Cadastre o plano uma vez por configuração de veículo e reutilize-o em todas as placas compatíveis. "
                    "O histórico permanece individual por veículo."
                )

                df_planos = carregar_dados_tabela(f"""
                    SELECT id, nome, fabricante, modelo, ano_modelo, versao, motorizacao,
                           combustivel, transmissao, ativo
                    FROM planos_manutencao
                    WHERE empresa_id = :empresa_id
                    ORDER BY nome
                """, emp_id)

                com_plano = int(df_veiculos["plano_manutencao_id"].notna().sum()) if "plano_manutencao_id" in df_veiculos.columns else 0
                pm1, pm2, pm3 = st.columns(3)
                pm1.metric("Planos-base", len(df_planos))
                pm2.metric("Veículos com plano", com_plano)
                pm3.metric("Sem plano", max(total - com_plano, 0))

                st.markdown("<br>", unsafe_allow_html=True)
                plano_individual, plano_massivo, planos_existentes = st.tabs([
                    "Por veículo", "Importação massiva", "Planos cadastrados"
                ])

                with plano_individual:
                    opcoes_plano_veiculo = {
                        f"{r['modelo']} · {r['placa']}": int(r["id"])
                        for _, r in df_veiculos.sort_values(["modelo", "placa"]).iterrows()
                    }
                    if not opcoes_plano_veiculo:
                        st.info("Cadastre ao menos um veículo para configurar um plano de manutenção.", icon=None)
                    else:
                        veiculo_plano_label = st.selectbox(
                            "Veículo",
                            list(opcoes_plano_veiculo.keys()),
                            key="plano_veiculo_individual"
                        )
                        veiculo_plano_id = opcoes_plano_veiculo[veiculo_plano_label]
                        vrow = df_veiculos.loc[df_veiculos["id"] == veiculo_plano_id].iloc[0]

                        atual_plano_id = vrow.get("plano_manutencao_id")
                        plano_atual_nome = "Nenhum plano associado"
                        if pd.notna(atual_plano_id) and not df_planos.empty and int(atual_plano_id) in df_planos["id"].astype(int).values:
                            plano_atual_nome = df_planos.loc[df_planos["id"].astype(int) == int(atual_plano_id), "nome"].iloc[0]

                        st.info(
                            f"**{vrow['modelo']} · {vrow['placa']}**  |  KM: **{float(vrow['km_atual'] or 0):,.0f}**  |  "
                            f"Plano atual: **{plano_atual_nome}**",
                            icon=None
                        )

                        # Monta o modelo individual com os itens já cadastrados, quando existirem.
                        base_rows = []
                        if pd.notna(atual_plano_id):
                            df_itens_modelo = carregar_dados_tabela(f"""
                                SELECT i.id, i.codigo_servico, i.tipo_manutencao, i.descricao,
                                       i.intervalo_fabricante_km, i.intervalo_fabricante_meses,
                                       i.intervalo_empresa_km, i.intervalo_empresa_meses
                                FROM itens_plano_manutencao i
                                WHERE i.empresa_id = :empresa_id AND i.plano_id=:plano_id AND COALESCE(i.ativo,1)=1
                                ORDER BY i.tipo_manutencao
                            """, emp_id, {"plano_id": int(atual_plano_id)})
                        else:
                            df_itens_modelo = pd.DataFrame()

                        if not df_itens_modelo.empty:
                            df_hist_modelo = carregar_dados_tabela(f"""
                                SELECT plano_item_id, data_execucao, km_execucao, id
                                FROM manutencoes_realizadas
                                WHERE empresa_id = :empresa_id AND veiculo_id=:veiculo_id
                                ORDER BY id DESC
                            """, emp_id, {"veiculo_id": int(veiculo_plano_id)})
                            for _, item in df_itens_modelo.iterrows():
                                hist_item = df_hist_modelo[df_hist_modelo["plano_item_id"] == item["id"]] if not df_hist_modelo.empty else pd.DataFrame()
                                ult_km = ""
                                ult_data = ""
                                if not hist_item.empty:
                                    hist_item = hist_item.copy()
                                    hist_item["data_execucao"] = pd.to_datetime(hist_item["data_execucao"], errors="coerce")
                                    hist_item["km_execucao"] = pd.to_numeric(hist_item["km_execucao"], errors="coerce")
                                    kms_validos = hist_item["km_execucao"].dropna()
                                    datas_validas = hist_item["data_execucao"].dropna()
                                    ult_km = kms_validos.max() if not kms_validos.empty else ""
                                    ult_data = datas_validas.max().date() if not datas_validas.empty else ""
                                base_rows.append({
                                    "placa": vrow["placa"],
                                    "fabricante": vrow.get("fabricante", ""),
                                    "modelo": vrow["modelo"],
                                    "ano_modelo": vrow.get("ano_modelo", ""),
                                    "versao": vrow.get("versao", ""),
                                    "motorizacao": vrow.get("motorizacao", ""),
                                    "combustivel": vrow.get("combustivel", ""),
                                    "transmissao": vrow.get("transmissao", ""),
                                    "nome_plano": plano_atual_nome,
                                    "codigo_servico": item["codigo_servico"] or "",
                                    "tipo_manutencao": item["tipo_manutencao"],
                                    "descricao_servico": item["descricao"] or "",
                                    "intervalo_fabricante_km": item["intervalo_fabricante_km"] or "",
                                    "intervalo_fabricante_meses": item["intervalo_fabricante_meses"] or "",
                                    "intervalo_empresa_km": item["intervalo_empresa_km"] or "",
                                    "intervalo_empresa_meses": item["intervalo_empresa_meses"] or "",
                                    "ultima_manutencao_km": ult_km,
                                    "ultima_manutencao_data": ult_data,
                                    "observacoes": "",
                                })
                        else:
                            base_rows.append({
                                "placa": vrow["placa"],
                                "fabricante": vrow.get("fabricante", ""),
                                "modelo": vrow["modelo"],
                                "ano_modelo": vrow.get("ano_modelo", ""),
                                "versao": vrow.get("versao", ""),
                                "motorizacao": vrow.get("motorizacao", ""),
                                "combustivel": vrow.get("combustivel", ""),
                                "transmissao": vrow.get("transmissao", ""),
                                "nome_plano": _nome_plano_padrao(vrow),
                            })

                        modelo_individual = gerar_planilha_planos(pd.DataFrame(base_rows))
                        di1, di2 = st.columns(2)
                        di1.download_button(
                            "Baixar modelo deste veículo",
                            modelo_individual,
                            file_name=f"plano_{str(vrow['placa']).replace('-', '')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="baixar_plano_individual"
                        )

                        arquivo_plano_ind = di2.file_uploader(
                            "Importar plano preenchido",
                            type=["xlsx", "xls"],
                            key="upload_plano_individual",
                            label_visibility="collapsed"
                        )

                        if arquivo_plano_ind:
                            try:
                                ok_upload, erro_upload = validar_upload_basico(
                                    arquivo_plano_ind, {"xls", "xlsx"}, max_mb=10
                                )
                                if not ok_upload:
                                    raise ValueError(erro_upload)
                                df_pi = pd.read_excel(arquivo_plano_ind, sheet_name="Planos")
                                if len(df_pi) > 5000:
                                    raise ValueError("O plano excede o limite de 5.000 linhas por importação.")
                                st.dataframe(df_pi.head(20), use_container_width=True, hide_index=True)
                                if st.button("Validar e importar plano deste veículo", use_container_width=True, key="importar_plano_individual"):
                                    resultado = processar_planilha_planos(
                                        df_pi, emp_id, st.session_state["nome"], veiculo_id_forcado=veiculo_plano_id
                                    )
                                    st.cache_data.clear()
                                    st.success(
                                        f"Plano importado: {resultado['veiculos']} veículo vinculado, "
                                        f"{resultado['itens_novos']} item(ns) novo(s) e "
                                        f"{resultado['historicos_novos']} histórico(s) inicial(is)."
                                    )
                                    if resultado["ignorados"]:
                                        st.warning("Algumas linhas foram ignoradas: " + " | ".join(resultado["ignorados"][:5]), icon=None)
                                    time.sleep(0.6)
                                    st.rerun()
                            except ValueError as e:
                                st.error(str(e), icon=None)
                            except Exception:
                                logger.exception("Falha ao importar plano individual")
                                st.error("Não foi possível ler/importar o plano.", icon=None)

                with plano_massivo:
                    st.markdown("**Modelo massivo da frota**")
                    st.caption(
                        "O arquivo já traz todas as placas cadastradas. Cadastre os serviços apenas uma vez para cada nome_plano; "
                        "as demais placas equivalentes podem manter o tipo_manutencao em branco e serão vinculadas ao mesmo plano-base. "
                        "Duplique somente a linha usada para cadastrar os vários serviços daquele plano."
                    )
                    rows_massivo = []
                    for _, vr in df_veiculos.sort_values(["modelo", "placa"]).iterrows():
                        rows_massivo.append({
                            "placa": vr["placa"],
                            "fabricante": vr.get("fabricante", ""),
                            "modelo": vr["modelo"],
                            "ano_modelo": vr.get("ano_modelo", ""),
                            "versao": vr.get("versao", ""),
                            "motorizacao": vr.get("motorizacao", ""),
                            "combustivel": vr.get("combustivel", ""),
                            "transmissao": vr.get("transmissao", ""),
                            "nome_plano": _nome_plano_padrao(vr),
                        })
                    modelo_massivo = gerar_planilha_planos(pd.DataFrame(rows_massivo))
                    mm1, mm2 = st.columns(2)
                    mm1.download_button(
                        "Baixar modelo massivo",
                        modelo_massivo,
                        file_name="planos_manutencao_frota.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="baixar_planos_massivo"
                    )
                    arquivo_massivo = mm2.file_uploader(
                        "Importar planos em massa",
                        type=["xlsx", "xls"],
                        key="upload_planos_massivo",
                        label_visibility="collapsed"
                    )
                    if arquivo_massivo:
                        try:
                            ok_upload, erro_upload = validar_upload_basico(
                                arquivo_massivo, {"xls", "xlsx"}, max_mb=15
                            )
                            if not ok_upload:
                                raise ValueError(erro_upload)
                            df_pm = pd.read_excel(arquivo_massivo, sheet_name="Planos")
                            if len(df_pm) > 15000:
                                raise ValueError("A planilha excede o limite de 15.000 linhas por importação.")
                            st.dataframe(df_pm.head(30), use_container_width=True, hide_index=True)
                            if st.button("Validar e importar planos em massa", use_container_width=True, key="importar_planos_massivo"):
                                resultado = processar_planilha_planos(df_pm, emp_id, st.session_state["nome"])
                                st.cache_data.clear()
                                st.success(
                                    f"Importação concluída: {resultado['planos']} plano(s), "
                                    f"{resultado['veiculos']} veículo(s), {resultado['itens_novos']} item(ns) novo(s) e "
                                    f"{resultado['historicos_novos']} histórico(s) inicial(is)."
                                )
                                if resultado["ignorados"]:
                                    st.warning("Linhas ignoradas: " + " | ".join(resultado["ignorados"][:8]), icon=None)
                                time.sleep(0.6)
                                st.rerun()
                        except ValueError as e:
                            st.error(str(e), icon=None)
                        except Exception:
                            logger.exception("Falha ao importar planos em massa")
                            st.error("Não foi possível ler/importar a planilha.", icon=None)

                with planos_existentes:
                    if df_planos.empty:
                        st.info("Nenhum plano-base cadastrado ainda.", icon=None)
                    else:
                        df_contagem_itens = carregar_dados_tabela(f"""
                            SELECT plano_id, COUNT(*) AS itens
                            FROM itens_plano_manutencao
                            WHERE empresa_id = :empresa_id AND COALESCE(ativo,1)=1
                            GROUP BY plano_id
                        """, emp_id)
                        df_contagem_veiculos = carregar_dados_tabela(f"""
                            SELECT plano_manutencao_id AS plano_id, COUNT(*) AS veiculos
                            FROM veiculos
                            WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1 AND plano_manutencao_id IS NOT NULL
                            GROUP BY plano_manutencao_id
                        """, emp_id)
                        df_show = df_planos.copy()
                        df_show = df_show.merge(df_contagem_itens, left_on="id", right_on="plano_id", how="left") if not df_contagem_itens.empty else df_show.assign(itens=0)
                        if "plano_id" in df_show.columns:
                            df_show = df_show.drop(columns=["plano_id"])
                        df_show = df_show.merge(df_contagem_veiculos, left_on="id", right_on="plano_id", how="left") if not df_contagem_veiculos.empty else df_show.assign(veiculos=0)
                        if "plano_id" in df_show.columns:
                            df_show = df_show.drop(columns=["plano_id"])
                        df_show["itens"] = df_show["itens"].fillna(0).astype(int)
                        df_show["veiculos"] = df_show["veiculos"].fillna(0).astype(int)
                        st.dataframe(
                            df_show[["nome", "fabricante", "modelo", "ano_modelo", "motorizacao", "itens", "veiculos"]].rename(columns={
                                "nome": "Plano", "fabricante": "Fabricante", "modelo": "Modelo",
                                "ano_modelo": "Ano", "motorizacao": "Motorização",
                                "itens": "Itens", "veiculos": "Veículos"
                            }),
                            use_container_width=True,
                            hide_index=True
                        )

            # ── Aba: Saúde ────────────────────────────────────────────────────────
            elif pagina_frota == "Saúde da Frota":
                if total == 0:
                    st.info("Nenhum veículo cadastrado.", icon=None)
                else:
                    ch1, ch2 = st.columns([4, 1])
                    ch1.markdown("**Saúde preventiva da frota**")
                    ch1.caption("A situação é recalculada automaticamente sempre que o KM ou uma manutenção vinculada é registrada.")
                    with ch2:
                        csv_f = convert_df_to_csv(df_veiculos[["placa", "modelo", "km_atual", "status"]])
                        st.download_button("Exportar frota", csv_f, "frota.csv", "text/csv", use_container_width=True)

                    diag = diagnostico_manutencao(emp_id)
                    veiculos_sem_plano = df_veiculos[df_veiculos["plano_manutencao_id"].isna()] if "plano_manutencao_id" in df_veiculos.columns else df_veiculos

                    if diag.empty:
                        st.info(
                            "Nenhum plano de manutenção com itens ativos está associado à frota. "
                            "Use a aba **Planos de manutenção** para importar o primeiro plano.",
                            icon=None
                        )
                        if not veiculos_sem_plano.empty:
                            st.dataframe(
                                veiculos_sem_plano[["placa", "modelo", "km_atual", "status"]].rename(columns={
                                    "placa": "Placa", "modelo": "Modelo", "km_atual": "KM Atual", "status": "Status"
                                }),
                                use_container_width=True,
                                hide_index=True
                            )
                    else:
                        ordem_status = {"VENCIDO": 0, "PRÓXIMO": 1, "ATENÇÃO": 2, "SEM HISTÓRICO": 3, "OK": 4}
                        diag["_ordem"] = diag["Status"].map(ordem_status).fillna(9)
                        diag = diag.sort_values(["_ordem", "Placa", "Serviço"])

                        criticos = diag[diag["Status"] == "VENCIDO"]
                        proximos = diag[diag["Status"] == "PRÓXIMO"]
                        atencao = diag[diag["Status"] == "ATENÇÃO"]
                        normais = diag[diag["Status"] == "OK"]

                        hs1, hs2, hs3, hs4 = st.columns(4)
                        hs1.metric("Manutenções vencidas", len(criticos))
                        hs2.metric("Próximas", len(proximos))
                        hs3.metric("Em atenção", len(atencao))
                        hs4.metric("Dentro do plano", len(normais))

                        st.markdown("<br>", unsafe_allow_html=True)
                        filtro_status = st.multiselect(
                            "Filtrar situação",
                            ["VENCIDO", "PRÓXIMO", "ATENÇÃO", "SEM HISTÓRICO", "OK"],
                            default=["VENCIDO", "PRÓXIMO", "ATENÇÃO", "SEM HISTÓRICO", "OK"],
                            key="saude_filtro_status"
                        )
                        diag_exibir = diag[diag["Status"].isin(filtro_status)].copy()
                        diag_exibir["Última Data"] = pd.to_datetime(diag_exibir["Última Data"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("—")
                        diag_exibir["Próxima Data"] = pd.to_datetime(diag_exibir["Próxima Data"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("—")
                        for col in ["Última KM", "Próxima KM", "Faltam KM", "Faltam Dias"]:
                            diag_exibir[col] = diag_exibir[col].apply(lambda x: "—" if pd.isna(x) else f"{int(x):,}".replace(",", "."))

                        tabela_diag = diag_exibir[[
                            "Placa", "Modelo", "KM Atual", "Serviço", "Última KM", "Próxima KM",
                            "Faltam KM", "Próxima Data", "Faltam Dias", "Status"
                        ]]

                        def cor_status_manut(v):
                            if v == "OK":
                                return "color:#065F46;background:#D1FAE5;font-weight:600;"
                            if v == "ATENÇÃO":
                                return "color:#92400E;background:#FEF3C7;font-weight:600;"
                            if v == "PRÓXIMO":
                                return "color:#9A3412;background:#FFEDD5;font-weight:600;"
                            if v == "VENCIDO":
                                return "color:#991B1B;background:#FEE2E2;font-weight:600;"
                            return "color:#475569;background:#F1F5F9;font-weight:600;"

                        if hasattr(tabela_diag.style, "map"):
                            styled_diag = tabela_diag.style.map(cor_status_manut, subset=["Status"])
                        else:
                            styled_diag = tabela_diag.style.applymap(cor_status_manut, subset=["Status"])
                        st.dataframe(styled_diag, use_container_width=True, hide_index=True)

                        if not veiculos_sem_plano.empty:
                            with st.expander(f"Veículos sem plano de manutenção ({len(veiculos_sem_plano)})"):
                                st.dataframe(
                                    veiculos_sem_plano[["placa", "modelo", "km_atual", "status"]].rename(columns={
                                        "placa": "Placa", "modelo": "Modelo", "km_atual": "KM Atual", "status": "Status"
                                    }),
                                    use_container_width=True,
                                    hide_index=True
                                )

        # ══════════════════════════════════════════════════════════════════════════
        # GESTÃO DE CUSTOS
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Gestão de Custos":
            aplicar_css_modulos_v11()

            df_veiculos = carregar_dados_tabela(f"""
                SELECT id, placa, modelo, km_atual, status, plano_manutencao_id
                FROM veiculos
                WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1
                ORDER BY modelo, placa
            """, emp_id)

            df_custos_resumo = carregar_dados_tabela("""
                SELECT c.id, c.data_custo, c.categoria, c.valor_total,
                       v.placa, v.modelo
                FROM custos c
                LEFT JOIN veiculos v
                  ON v.id=c.veiculo_id AND v.empresa_id=c.empresa_id
                WHERE c.empresa_id=:empresa_id
                ORDER BY c.data_custo DESC, c.id DESC
            """, emp_id)
            if not df_custos_resumo.empty:
                df_custos_resumo["data_custo"] = pd.to_datetime(
                    df_custos_resumo["data_custo"], errors="coerce"
                )
                df_custos_resumo["valor_total"] = pd.to_numeric(
                    df_custos_resumo["valor_total"], errors="coerce"
                ).fillna(0.0)
                custos_total_resumo = float(df_custos_resumo["valor_total"].sum())
                custos_mes_resumo = float(df_custos_resumo.loc[
                    df_custos_resumo["data_custo"].dt.strftime("%m/%Y")
                    == hoje_local().strftime("%m/%Y"),
                    "valor_total",
                ].sum())
                ticket_custo_resumo = float(df_custos_resumo["valor_total"].mean())
                categorias_custo_resumo = int(df_custos_resumo["categoria"].nunique())
            else:
                custos_total_resumo = custos_mes_resumo = ticket_custo_resumo = 0.0
                categorias_custo_resumo = 0

            module_hero(
                "Controle financeiro",
                "Gestão de Custos",
                "Acompanhe o impacto financeiro da frota e registre novas despesas somente quando necessário.",
                "Despesas no mês",
                fmt_brl(custos_mes_resumo),
            )
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1:
                module_stat_card("Acumulado", fmt_brl(custos_total_resumo), "histórico de despesas")
            with rc2:
                module_stat_card("Lançamentos", len(df_custos_resumo), "registros financeiros")
            with rc3:
                module_stat_card("Ticket médio", fmt_brl(ticket_custo_resumo), "valor por lançamento")
            with rc4:
                module_stat_card("Categorias usadas", categorias_custo_resumo, "classificações com movimento")

            if df_veiculos.empty:
                st.warning(
                    "Cadastre ao menos um veículo antes de registrar custos.",
                    icon=None
                )
            else:
                CATEGORIAS = [
                    "Combustível",
                    "Manutenção Preventiva",
                    "Manutenção Corretiva",
                    "Custos com Motorista",
                    "Lavagem/Higienização",
                    "Consórcio/Financiamento",
                    "Seguro",
                    "Rastreamento",
                    "Licenças/Autorizações",
                    "Impostos/Documentação",
                    "Multas",
                    "Outros"
                ]

                FORMAS_PAGAMENTO = [
                    "Pix",
                    "Dinheiro",
                    "PR",
                    "Cartão de Crédito"
                ]

                opcoes_v = {
                    f"{r['modelo']} · {r['placa']}": int(r["id"])
                    for _, r in df_veiculos.iterrows()
                }

                pagina_custos = st.session_state["pagina_custos"]

                if pagina_custos == "Visão de Custos":
                    visao_custo_col, ranking_custo_col = st.columns([1.7, 1])
                    with visao_custo_col:
                        with st.container(border=True):
                            st.markdown("### Movimentações recentes")
                            st.caption("Últimos registros financeiros da frota.")
                            if df_custos_resumo.empty:
                                st.info("Nenhuma despesa registrada até o momento.", icon=None)
                            else:
                                recentes_custos = df_custos_resumo.head(12).copy()
                                recentes_custos["Data"] = recentes_custos["data_custo"].dt.strftime("%d/%m/%Y")
                                recentes_custos["Veículo"] = (
                                    recentes_custos["placa"].fillna("Sem veículo").astype(str)
                                    + " · "
                                    + recentes_custos["modelo"].fillna("").astype(str)
                                )
                                recentes_custos["Valor"] = recentes_custos["valor_total"].apply(fmt_brl)
                                st.dataframe(
                                    recentes_custos[["Data", "Veículo", "categoria", "Valor"]].rename(
                                        columns={"categoria": "Categoria"}
                                    ),
                                    use_container_width=True,
                                    hide_index=True,
                                )
                    with ranking_custo_col:
                        with st.container(border=True):
                            st.markdown("### Impacto por categoria")
                            st.caption("Onde a frota concentra mais despesas.")
                            if df_custos_resumo.empty:
                                st.info("O ranking aparecerá após o primeiro lançamento.", icon=None)
                            else:
                                ranking_custos = (
                                    df_custos_resumo.groupby("categoria", as_index=False)["valor_total"]
                                    .sum()
                                    .sort_values("valor_total", ascending=False)
                                    .head(8)
                                )
                                fig_ranking_custos = px.bar(
                                    ranking_custos,
                                    x="categoria",
                                    y="valor_total",
                                    text="valor_total",
                                    labels={
                                        "categoria": "Categoria",
                                        "valor_total": "Valor (R$)",
                                    },
                                )
                                fig_ranking_custos.update_traces(
                                    texttemplate="R$ %{text:,.0f}",
                                    textposition="outside",
                                    cliponaxis=False,
                                )
                                fig_ranking_custos.update_layout(**PLOTLY_LAYOUT, separators=",.")
                                st.plotly_chart(
                                    fig_ranking_custos,
                                    use_container_width=True,
                                    config={
                                        "displayModeBar": False,
                                        "scrollZoom": False,
                                        "staticPlot": True,
                                    },
                                )

                # ──────────────────────────────────────────────────────────────
                # REGISTRAR DESPESA
                # ──────────────────────────────────────────────────────────────
                elif pagina_custos == "Registrar Despesa":
                    # Uma nova versão de chave recria os widgets limpos após salvar.
                    custos_form_version = st.session_state.setdefault("custos_form_version", 0)
                    with st.container(border=True):
                        st.markdown("### Nova despesa")
                        st.caption(
                            "Preencha os dados do lançamento. Campos específicos "
                            "aparecem conforme a categoria selecionada."
                        )

                        c1, c2, c3 = st.columns([1.05, 1.35, 0.85])

                        cat = c1.selectbox(
                            "Categoria",
                            CATEGORIAS,
                            key=f"custos_categoria_{custos_form_version}"
                        )

                        veiculo_sel = c2.selectbox(
                            "Veículo",
                            list(opcoes_v.keys()),
                            key=f"custos_veiculo_{custos_form_version}"
                        )

                        data_custo = c3.date_input(
                            "Data",
                            format="DD/MM/YYYY",
                            key=f"custos_data_{custos_form_version}"
                        )

                        veiculo_id_sel = opcoes_v[veiculo_sel]
                        veiculo_ctx = df_veiculos.loc[
                            df_veiculos["id"] == veiculo_id_sel
                        ].iloc[0]

                        km_cadastrado = float(veiculo_ctx["km_atual"] or 0)
                        status_veiculo = str(
                            veiculo_ctx["status"] or "Não informado"
                        )

                        st.info(
                            f"**{veiculo_ctx['modelo']} · {veiculo_ctx['placa']}**  |  "
                            f"Status: **{status_veiculo}**  |  "
                            f"KM cadastrado: **{km_cadastrado:,.0f} km**",
                            icon=None
                        )

                        session_vinculo = SessionLocal()
                        try:
                            contrato_ctx = obter_contrato_por_veiculo_data(
                                session_vinculo,
                                emp_id,
                                veiculo_id_sel,
                                data_custo
                            )
                            if contrato_ctx is not None:
                                st.caption(
                                    f"Centro de resultado automático: **{contrato_ctx.cliente}** "
                                    f"(Contrato #{contrato_ctx.id})."
                                )
                            else:
                                st.caption(
                                    "Este veículo não possui contrato associado à data informada. "
                                    "O custo ficará classificado como sem contrato."
                                )
                        finally:
                            session_vinculo.close()

                        d1, d2, d3 = st.columns([1, 1, 1])

                        valor_texto = d1.text_input(
                            "Valor total (R$)",
                            placeholder="Ex.: 1.012,08",
                            key=f"custos_valor_{custos_form_version}"
                        )
                        valor_total_decimal = decimal_monetario(valor_texto)
                        valor = float(valor_total_decimal)
                        if str(valor_texto or "").strip() and valor_total_decimal > 0:
                            d1.caption(f"Valor reconhecido: **{fmt_brl(valor_total_decimal)}**")

                        km_atual = d2.number_input(
                            "KM no momento",
                            min_value=0.0,
                            step=50.0,
                            value=km_cadastrado,
                            key=f"custos_km_{custos_form_version}_{veiculo_id_sel}"
                        )

                        if float(km_atual or 0) > 0 and float(km_atual or 0) < km_cadastrado:
                            st.warning(
                                f"O KM informado ({float(km_atual):,.0f}) é inferior ao hodômetro atual ({km_cadastrado:,.0f}). "
                                "O lançamento será aceito como histórico e não reduzirá o KM atual do veículo.",
                                icon=None
                            )

                        litros = None
                        if cat == "Combustível":
                            litros = d3.number_input(
                                "Litros abastecidos",
                                min_value=0.1,
                                step=1.0,
                                value=0.1,
                                key=f"custos_litros_{custos_form_version}"
                            )

                            if litros > 0:
                                preco_litro = valor / litros
                                d3.caption(
                                    f"Preço calculado: **{fmt_brl(preco_litro)}/L**"
                                )

                        elif cat in [
                            "Manutenção Preventiva",
                            "Manutenção Corretiva"
                        ]:
                            d3.metric(
                                "KM desde cadastro",
                                f"{max(float(km_atual) - km_cadastrado, 0):,.0f} km"
                            )
                        else:
                            d3.caption(
                                "Esta categoria não exige informação complementar."
                            )

                        tipo_manutencao = None
                        plano_item_id = None
                        if cat in ["Manutenção Preventiva", "Manutenção Corretiva"]:
                            plano_id_veiculo = veiculo_ctx.get("plano_manutencao_id")
                            if pd.notna(plano_id_veiculo):
                                df_itens_custo = carregar_dados_tabela(f"""
                                    SELECT id, tipo_manutencao, descricao,
                                           intervalo_fabricante_km, intervalo_empresa_km
                                    FROM itens_plano_manutencao
                                    WHERE empresa_id = :empresa_id AND plano_id=:plano_id AND COALESCE(ativo,1)=1
                                    ORDER BY tipo_manutencao
                                """, emp_id, {"plano_id": int(plano_id_veiculo)})
                            else:
                                df_itens_custo = pd.DataFrame()

                            if not df_itens_custo.empty:
                                opcoes_manut = {
                                    str(r["tipo_manutencao"]): int(r["id"])
                                    for _, r in df_itens_custo.iterrows()
                                }
                                opcoes_labels = list(opcoes_manut.keys()) + ["Outro / não vinculado ao plano"]
                                manut_label = st.selectbox(
                                    "Tipo de manutenção",
                                    opcoes_labels,
                                    key=f"custos_tipo_manutencao_{custos_form_version}"
                                )
                                if manut_label != "Outro / não vinculado ao plano":
                                    tipo_manutencao = manut_label
                                    plano_item_id = opcoes_manut[manut_label]
                                    item_ctx = df_itens_custo.loc[df_itens_custo["id"] == plano_item_id].iloc[0]
                                    intervalo_ctx = _intervalo_efetivo(item_ctx["intervalo_empresa_km"], item_ctx["intervalo_fabricante_km"])
                                    if intervalo_ctx:
                                        st.caption(f"Este lançamento reiniciará o ciclo de **{manut_label}**. Intervalo efetivo: **{intervalo_ctx:,.0f} km**.")
                            else:
                                tipo_manutencao = st.text_input(
                                    "Tipo de manutenção",
                                    placeholder="Ex.: Troca de óleo do motor",
                                    key=f"custos_tipo_manutencao_livre_{custos_form_version}"
                                )
                                st.warning(
                                    "Este veículo ainda não possui plano vinculado. O custo será registrado, mas não reiniciará automaticamente um ciclo preventivo.",
                                    icon=None
                                )

                        descricao = st.text_input(
                            "Descrição / observação",
                            placeholder=(
                                "Ex.: abastecimento, troca de óleo, documentação, "
                                "serviço realizado..."
                            ),
                            key=f"custos_descricao_{custos_form_version}"
                        )

                        st.markdown("---")

                        p1, p2 = st.columns(2)

                        forma_pag = p1.selectbox(
                            "Forma de pagamento",
                            FORMAS_PAGAMENTO,
                            key=f"custos_forma_pagamento_{custos_form_version}"
                        )

                        df_motoristas_custo = carregar_dados_tabela(
                            """
                            SELECT id, nome, matricula
                            FROM motoristas
                            WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1) = 1
                            ORDER BY nome
                            """,
                            emp_id,
                        )
                        opcoes_motorista_custo = {"Não atribuído": None}
                        nomes_motorista_custo = {}
                        if not df_motoristas_custo.empty:
                            for _, mr in df_motoristas_custo.iterrows():
                                mid = int(mr["id"])
                                complemento = (
                                    f"Matrícula {mr['matricula']}"
                                    if pd.notna(mr["matricula"]) and str(mr["matricula"]).strip()
                                    else f"#{mid}"
                                )
                                label = f"{mr['nome']} · {complemento}"
                                opcoes_motorista_custo[label] = mid
                                nomes_motorista_custo[mid] = str(mr["nome"])

                        motorista_label = p2.selectbox(
                            "Motorista relacionado",
                            list(opcoes_motorista_custo.keys()),
                            key=f"custos_motorista_{custos_form_version}"
                        )
                        motorista_id = opcoes_motorista_custo[motorista_label]
                        motorista = nomes_motorista_custo.get(motorista_id) if motorista_id else None
                        if len(opcoes_motorista_custo) == 1:
                            p2.caption("Nenhum motorista ativo cadastrado. Use Pessoas e Acessos para cadastrar quando necessário.")

                        condicao_pag = None
                        parcelas_q = None

                        if forma_pag == "Cartão de Crédito":
                            pc1, pc2 = st.columns(2)

                            condicao_pag = pc1.radio(
                                "Condição",
                                ["À vista", "Parcelado"],
                                horizontal=True,
                                key=f"custos_condicao_pagamento_{custos_form_version}"
                            )

                            if condicao_pag == "Parcelado":
                                parcelas_q = pc2.number_input(
                                    "Nº de parcelas",
                                    min_value=2,
                                    max_value=48,
                                    step=1,
                                    value=2,
                                    key=f"custos_parcelas_{custos_form_version}"
                                )

                        st.markdown("**Comprovante**")
                        arquivo = st.file_uploader(
                            "Anexar imagem ou PDF",
                            type=["png", "jpg", "jpeg", "pdf"],
                            label_visibility="collapsed",
                            key=f"custos_comprovante_{st.session_state['custos_uploader_version']}"
                        )

                        acao_col1, acao_col2 = st.columns([4, 1.2])

                        with acao_col2:
                            salvar_custo = st.button(
                                "Registrar despesa",
                                icon=":material/add_card:",
                                use_container_width=True,
                                key=f"btn_registrar_custo_{custos_form_version}"
                            )

                        if salvar_custo and (
                            not str(valor_texto or "").strip()
                            or valor_total_decimal <= 0
                        ):
                            st.error(
                                "Informe um valor total válido, como 1.012,08.",
                                icon=None,
                            )
                            salvar_custo = False

                        if salvar_custo:
                            km_val = float(km_atual or 0.0)
                            session = SessionLocal()

                            try:
                                veiculo_db = tenant_get(
                                    session, Veiculo, veiculo_id_sel, emp_id
                                )

                                if veiculo_db is None:
                                    st.error(
                                        "O veículo selecionado não foi encontrado.",
                                        icon=None
                                    )

                                else:
                                    comp_path = None

                                    if arquivo:
                                        ok_upload, erro_upload = validar_upload_basico(
                                            arquivo,
                                            {"png", "jpg", "jpeg", "pdf"},
                                            max_mb=10,
                                        )
                                        if not ok_upload:
                                            raise ValueError(erro_upload)
                                        ext = arquivo.name.rsplit(".", 1)[-1].lower()
                                        comp_path = salvar_upload_privado(
                                            arquivo,
                                            f"comprovantes/{emp_id}/comp_{uuid.uuid4().hex}.{ext}",
                                        )

                                    custo_manutencao_base_id = None

                                    if (
                                        forma_pag == "Cartão de Crédito"
                                        and condicao_pag == "Parcelado"
                                        and parcelas_q
                                    ):
                                        valores_parcelas = dividir_valor_parcelas(
                                            valor_total_decimal, int(parcelas_q)
                                        )

                                        for i, valor_parcela in enumerate(valores_parcelas):
                                            dt_parcela = add_months(
                                                data_custo,
                                                i
                                            )

                                            descricao_parcela = (
                                                f"{descricao} "
                                                f"(Parcela {i + 1}/{parcelas_q})"
                                                if descricao
                                                else
                                                f"Parcela {i + 1}/{parcelas_q}"
                                            )

                                            contrato_parcela = obter_contrato_por_veiculo_data(
                                                session,
                                                emp_id,
                                                veiculo_db.id,
                                                dt_parcela
                                            )

                                            custo_parcela = Custo(
                                                empresa_id=emp_id,
                                                veiculo_id=veiculo_db.id,
                                                contrato_id=(
                                                    contrato_parcela.id
                                                    if contrato_parcela is not None
                                                    else None
                                                ),
                                                data_custo=dt_parcela,
                                                categoria=cat,
                                                descricao=descricao_parcela,
                                                valor_total=valor_parcela,
                                                km_momento=(
                                                    km_val if i == 0 else 0
                                                ),
                                                litros=(
                                                    litros if i == 0 else None
                                                ),
                                                usuario_lancamento=(
                                                    st.session_state["nome"]
                                                ),
                                                forma_pagamento=forma_pag,
                                                condicao_pagamento=condicao_pag,
                                                parcelas=int(parcelas_q),
                                                motorista_id=motorista_id,
                                                motorista=motorista,
                                                comprovante=(
                                                    comp_path
                                                    if i == 0
                                                    else None
                                                ),
                                                tipo_manutencao=tipo_manutencao,
                                                plano_item_id=plano_item_id
                                            )
                                            session.add(custo_parcela)
                                            if i == 0:
                                                session.flush()
                                                custo_manutencao_base_id = custo_parcela.id

                                    else:
                                        contrato_custo = obter_contrato_por_veiculo_data(
                                            session,
                                            emp_id,
                                            veiculo_db.id,
                                            data_custo
                                        )

                                        custo_unico = Custo(
                                            empresa_id=emp_id,
                                            veiculo_id=veiculo_db.id,
                                            contrato_id=(
                                                contrato_custo.id
                                                if contrato_custo is not None
                                                else None
                                            ),
                                            data_custo=data_custo,
                                            categoria=cat,
                                            descricao=descricao,
                                            valor_total=valor_total_decimal,
                                            km_momento=km_val,
                                            litros=litros,
                                            usuario_lancamento=(
                                                st.session_state["nome"]
                                            ),
                                            forma_pagamento=forma_pag,
                                            condicao_pagamento=condicao_pag,
                                            parcelas=parcelas_q,
                                            motorista_id=motorista_id,
                                            motorista=motorista,
                                            comprovante=comp_path,
                                            tipo_manutencao=tipo_manutencao,
                                            plano_item_id=plano_item_id
                                        )
                                        session.add(custo_unico)
                                        session.flush()
                                        custo_manutencao_base_id = custo_unico.id

                                    if (
                                        plano_item_id
                                        and cat in ["Manutenção Preventiva", "Manutenção Corretiva"]
                                        and custo_manutencao_base_id
                                    ):
                                        session.add(ManutencaoRealizada(
                                            empresa_id=emp_id,
                                            veiculo_id=veiculo_db.id,
                                            plano_item_id=plano_item_id,
                                            custo_id=custo_manutencao_base_id,
                                            data_execucao=data_custo,
                                            km_execucao=km_val if km_val > 0 else None,
                                            observacoes=descricao or tipo_manutencao,
                                            origem="Gestão de Custos"
                                        ))

                                    if km_val > float(
                                        veiculo_db.km_atual or 0
                                    ):
                                        veiculo_db.km_atual = km_val

                                    registrar_auditoria(
                                        session,
                                        emp_id,
                                        st.session_state["usuario_id"],
                                        "CUSTO_REGISTRADO",
                                        "Custo",
                                        custo_manutencao_base_id,
                                        f"Categoria: {cat}; veículo: {veiculo_db.id}",
                                    )
                                    session.commit()

                                    # Limpa o file_uploader do comprovante após o registro.
                                    # Uma nova chave força o Streamlit a recriar o widget vazio.
                                    st.session_state["custos_uploader_version"] += 1
                                    st.session_state["custos_form_version"] += 1

                                    st.cache_data.clear()
                                    st.success(
                                        "Despesa registrada com sucesso."
                                    )
                                    time.sleep(0.5)
                                    st.rerun()

                            except ValueError as e:
                                session.rollback()
                                st.error(str(e), icon=None)
                            except Exception:
                                session.rollback()
                                logger.exception("Falha ao registrar despesa")
                                st.error(
                                    "Não foi possível registrar a despesa.",
                                    icon=None
                                )

                            finally:
                                session.close()

                # ──────────────────────────────────────────────────────────────
                # LANÇAMENTOS FINANCEIROS
                # ──────────────────────────────────────────────────────────────
                elif pagina_custos == "Lançamentos":
                    df_custos = carregar_dados_tabela(f"""
                        SELECT
                            c.id,
                            c.data_custo,
                            c.veiculo_id,
                            v.placa,
                            v.modelo,
                            c.categoria,
                            c.tipo_manutencao,
                            c.descricao,
                            c.valor_total,
                            c.km_momento,
                            c.litros,
                            c.forma_pagamento,
                            c.condicao_pagamento,
                            c.parcelas,
                            c.motorista_id,
                            COALESCE(m.nome, NULLIF(c.motorista, ''), 'Não atribuído') AS motorista_exibicao,
                            c.comprovante,
                            c.usuario_lancamento
                        FROM custos c
                        JOIN veiculos v
                            ON c.veiculo_id = v.id AND c.empresa_id = v.empresa_id
                        LEFT JOIN motoristas m
                            ON m.id = c.motorista_id AND m.empresa_id = c.empresa_id
                        WHERE c.empresa_id = :empresa_id
                        ORDER BY c.data_custo DESC, c.id DESC
                    """, emp_id)

                    with st.container(border=True):
                        st.markdown("### Lançamentos financeiros")
                        st.caption(
                            "Consulte, filtre, exporte, visualize comprovantes "
                            "e gerencie os registros financeiros."
                        )

                        if df_custos.empty:
                            st.info(
                                "Nenhum lançamento financeiro registrado.",
                                icon=None
                            )

                        else:
                            df_custos["data_custo"] = pd.to_datetime(
                                df_custos["data_custo"],
                                errors="coerce"
                            )

                            df_custos["valor_total"] = pd.to_numeric(
                                df_custos["valor_total"],
                                errors="coerce"
                            ).fillna(0.0)

                            df_custos["km_momento"] = pd.to_numeric(
                                df_custos["km_momento"],
                                errors="coerce"
                            ).fillna(0.0)

                            df_custos["litros"] = pd.to_numeric(
                                df_custos["litros"],
                                errors="coerce"
                            )

                            filtros1, filtros2, filtros3, filtros4, filtros5 = st.columns(
                                [1, 1.2, 1.1, 1, 1.15]
                            )

                            periodo_sel = filtros1.selectbox(
                                "Período",
                                [
                                    "Este mês",
                                    "Últimos 30 dias",
                                    "Este ano",
                                    "Todos"
                                ],
                                key="custos_filtro_periodo"
                            )

                            veiculos_filtro = (
                                ["Todos"]
                                + sorted(
                                    df_custos["placa"]
                                    .dropna()
                                    .astype(str)
                                    .unique()
                                    .tolist()
                                )
                            )

                            veiculo_filtro = filtros2.selectbox(
                                "Veículo",
                                veiculos_filtro,
                                key="custos_filtro_veiculo"
                            )

                            categorias_filtro = (
                                ["Todas"]
                                + sorted(
                                    df_custos["categoria"]
                                    .dropna()
                                    .astype(str)
                                    .unique()
                                    .tolist()
                                )
                            )

                            categoria_filtro = filtros3.selectbox(
                                "Categoria",
                                categorias_filtro,
                                key="custos_filtro_categoria"
                            )

                            pagamentos_filtro = (
                                ["Todos"]
                                + sorted(
                                    df_custos["forma_pagamento"]
                                    .dropna()
                                    .astype(str)
                                    .unique()
                                    .tolist()
                                )
                            )

                            pagamento_filtro = filtros4.selectbox(
                                "Pagamento",
                                pagamentos_filtro,
                                key="custos_filtro_pagamento"
                            )

                            motoristas_filtro = (
                                ["Todos"]
                                + sorted(
                                    df_custos["motorista_exibicao"]
                                    .fillna("Não atribuído")
                                    .astype(str)
                                    .unique()
                                    .tolist()
                                )
                            )
                            motorista_filtro = filtros5.selectbox(
                                "Motorista",
                                motoristas_filtro,
                                key="custos_filtro_motorista"
                            )

                            df_filtrado = df_custos.copy()
                            hoje_custos = hoje_local()

                            if periodo_sel == "Este mês":
                                df_filtrado = df_filtrado[
                                    (
                                        df_filtrado["data_custo"].dt.month
                                        == hoje_custos.month
                                    )
                                    & (
                                        df_filtrado["data_custo"].dt.year
                                        == hoje_custos.year
                                    )
                                ]

                            elif periodo_sel == "Últimos 30 dias":
                                limite_data = pd.Timestamp(
                                    hoje_custos - timedelta(days=30)
                                )

                                df_filtrado = df_filtrado[
                                    df_filtrado["data_custo"]
                                    >= limite_data
                                ]

                            elif periodo_sel == "Este ano":
                                df_filtrado = df_filtrado[
                                    df_filtrado["data_custo"].dt.year
                                    == hoje_custos.year
                                ]

                            if veiculo_filtro != "Todos":
                                df_filtrado = df_filtrado[
                                    df_filtrado["placa"]
                                    == veiculo_filtro
                                ]

                            if categoria_filtro != "Todas":
                                df_filtrado = df_filtrado[
                                    df_filtrado["categoria"]
                                    == categoria_filtro
                                ]

                            if pagamento_filtro != "Todos":
                                df_filtrado = df_filtrado[
                                    df_filtrado["forma_pagamento"]
                                    == pagamento_filtro
                                ]

                            if motorista_filtro != "Todos":
                                df_filtrado = df_filtrado[
                                    df_filtrado["motorista_exibicao"].fillna("Não atribuído")
                                    == motorista_filtro
                                ]

                            total_filtrado = float(
                                df_filtrado["valor_total"].sum()
                            )

                            qtd_filtrada = len(df_filtrado)

                            ticket_medio = (
                                total_filtrado / qtd_filtrada
                                if qtd_filtrada
                                else 0.0
                            )

                            m1, m2, m3 = st.columns(3)

                            m1.metric(
                                "Lançamentos",
                                qtd_filtrada
                            )

                            m2.metric(
                                "Total filtrado",
                                fmt_brl(total_filtrado)
                            )

                            m3.metric(
                                "Ticket médio",
                                fmt_brl(ticket_medio)
                            )

                            if not df_filtrado.empty:
                                resumo_motorista = (
                                    df_filtrado.assign(
                                        Motorista=df_filtrado["motorista_exibicao"].fillna("Não atribuído")
                                    )
                                    .groupby("Motorista")["valor_total"]
                                    .agg(["count", "sum"])
                                    .reset_index()
                                    .rename(columns={"count": "Lançamentos", "sum": "Total relacionado"})
                                )
                                resumo_motorista["Total relacionado"] = resumo_motorista["Total relacionado"].apply(fmt_brl)
                                with st.expander("Custos relacionados por motorista", expanded=False):
                                    st.caption(
                                        "Visão gerencial de custos relacionados aos lançamentos. "
                                        "Não representa cobrança ou responsabilização financeira do motorista."
                                    )
                                    st.dataframe(resumo_motorista, use_container_width=True, hide_index=True)

                            st.markdown("<br>", unsafe_allow_html=True)

                            if df_filtrado.empty:
                                st.info(
                                    "Nenhum lançamento encontrado com "
                                    "os filtros selecionados.",
                                    icon=None
                                )

                            else:
                                df_exibicao = df_filtrado.copy()

                                df_exibicao["Data"] = (
                                    df_exibicao["data_custo"]
                                    .dt.strftime("%d/%m/%Y")
                                )

                                df_exibicao["Veículo"] = (
                                    df_exibicao["modelo"]
                                    .fillna("")
                                    .astype(str)
                                    + " · "
                                    + df_exibicao["placa"]
                                    .fillna("")
                                    .astype(str)
                                )

                                df_exibicao["Pagamento"] = df_exibicao.apply(
                                    lambda r: (
                                        f"{r['forma_pagamento']} · "
                                        f"{int(r['parcelas'])}x"
                                        if (
                                            r["forma_pagamento"]
                                            == "Cartão de Crédito"
                                            and r["condicao_pagamento"]
                                            == "Parcelado"
                                            and pd.notna(r["parcelas"])
                                        )
                                        else (
                                            r["forma_pagamento"]
                                            or "—"
                                        )
                                    ),
                                    axis=1
                                )

                                df_exibicao["Valor"] = (
                                    df_exibicao["valor_total"]
                                    .apply(fmt_brl)
                                )

                                df_exibicao["KM"] = (
                                    df_exibicao["km_momento"]
                                    .apply(
                                        lambda x: (
                                            f"{x:,.0f}"
                                            if float(x or 0) > 0
                                            else "—"
                                        )
                                    )
                                )

                                df_exibicao["Preço/L"] = df_exibicao.apply(
                                    lambda r: (
                                        fmt_brl(
                                            float(r["valor_total"])
                                            / float(r["litros"])
                                        )
                                        if (
                                            pd.notna(r["litros"])
                                            and float(r["litros"]) > 0
                                        )
                                        else "—"
                                    ),
                                    axis=1
                                )

                                df_exibicao["Comprovante"] = (
                                    df_exibicao["comprovante"]
                                    .apply(
                                        lambda x: "Anexado" if x else "—"
                                    )
                                )

                                df_exibicao["Tipo manutenção"] = df_exibicao["tipo_manutencao"].fillna("—")

                                tabela_custos = df_exibicao[[
                                    "Data",
                                    "Veículo",
                                    "categoria",
                                    "Tipo manutenção",
                                    "descricao",
                                    "Valor",
                                    "Pagamento",
                                    "KM",
                                    "Preço/L",
                                    "motorista_exibicao",
                                    "Comprovante"
                                ]].rename(columns={
                                    "categoria": "Categoria",
                                    "descricao": "Descrição",
                                    "motorista_exibicao": "Motorista"
                                })

                                export_col1, export_col2 = st.columns(
                                    [4, 1]
                                )

                                with export_col2:
                                    csv_custos = convert_df_to_csv(
                                        tabela_custos
                                    )

                                    st.download_button(
                                        "Exportar base",
                                        csv_custos,
                                        "custos_filtrados.csv",
                                        "text/csv",
                                        use_container_width=True,
                                        key="custos_exportar"
                                    )

                                st.dataframe(
                                    tabela_custos,
                                    use_container_width=True,
                                    hide_index=True
                                )

                                st.markdown("---")

                                # ── Comprovantes ─────────────────────────────
                                df_anexos = df_filtrado[
                                    df_filtrado["comprovante"].notna()
                                    & (
                                        df_filtrado["comprovante"]
                                        .astype(str)
                                        .str.strip()
                                        != ""
                                    )
                                ]

                                if not df_anexos.empty:
                                    with st.expander(
                                        "Consultar comprovantes"
                                    ):
                                        opcoes_anx = {
                                            (
                                                f"{pd.to_datetime(r['data_custo']).strftime('%d/%m/%Y')}"
                                                f" · {r['placa']}"
                                                f" · {r['categoria']}"
                                                f" · {fmt_brl(float(r['valor_total'] or 0))}"
                                            ): r["comprovante"]
                                            for _, r in df_anexos.iterrows()
                                        }

                                        anx_sel = st.selectbox(
                                            "Lançamento",
                                            list(opcoes_anx.keys()),
                                            key="custos_anexo_selecao"
                                        )

                                        caminho = opcoes_anx[anx_sel]

                                        dados_anexo = ler_bytes_privado(caminho) if caminho else None
                                        if dados_anexo:
                                            if str(caminho).lower().endswith(".pdf"):
                                                st.download_button(
                                                    "Baixar PDF",
                                                    dados_anexo,
                                                    os.path.basename(str(caminho)),
                                                    "application/pdf",
                                                    key="custos_baixar_pdf"
                                                )
                                            else:
                                                st.image(dados_anexo, use_container_width=True)
                                        else:
                                            st.warning(
                                                "O arquivo do comprovante "
                                                "não foi encontrado.",
                                                icon=None
                                            )

                                # ── Exclusão integrada ─────────────────────
                                if (
                                    st.session_state["perfil"]
                                    == "admin"
                                ):
                                    with st.expander(
                                        "Gerenciar lançamento"
                                    ):
                                        st.caption(
                                            "A exclusão é permanente e deve "
                                            "ser usada somente para corrigir "
                                            "lançamentos incorretos."
                                        )

                                        opcoes_exclusao = {
                                            (
                                                f"{pd.to_datetime(r['data_custo']).strftime('%d/%m/%Y')}"
                                                f" · {r['placa']}"
                                                f" · {r['categoria']}"
                                                f" · {fmt_brl(float(r['valor_total'] or 0))}"
                                            ): int(r["id"])
                                            for _, r in df_filtrado.iterrows()
                                        }

                                        custo_excluir_label = st.selectbox(
                                            "Selecione o lançamento",
                                            list(
                                                opcoes_exclusao.keys()
                                            ),
                                            key="custos_excluir_selecao"
                                        )

                                        confirmar_exclusao = st.checkbox(
                                            "Confirmo a exclusão permanente "
                                            "deste lançamento.",
                                            key="custos_confirmar_exclusao"
                                        )

                                        ex1, ex2 = st.columns([4, 1])

                                        with ex2:
                                            excluir_custo = st.button(
                                                "Excluir lançamento",
                                                icon=":material/delete:",
                                                use_container_width=True,
                                                disabled=(
                                                    not confirmar_exclusao
                                                ),
                                                key=(
                                                    "btn_excluir_custo"
                                                )
                                            )

                                        if excluir_custo:
                                            session = SessionLocal()

                                            try:
                                                custo_id = (
                                                    opcoes_exclusao[
                                                        custo_excluir_label
                                                    ]
                                                )

                                                custo_db = tenant_get(
                                                    session, Custo, custo_id, emp_id
                                                )

                                                if custo_db is None:
                                                    st.warning(
                                                        "O lançamento "
                                                        "selecionado não foi "
                                                        "encontrado.",
                                                        icon=None
                                                    )

                                                else:
                                                    comprovante_excluir = custo_db.comprovante
                                                    custo_snapshot = (
                                                        f"Categoria: {custo_db.categoria}; valor: {custo_db.valor_total}; "
                                                        f"veículo: {custo_db.veiculo_id}; contrato: {custo_db.contrato_id}"
                                                    )
                                                    historicos_vinculados = session.query(ManutencaoRealizada).filter(
                                                        ManutencaoRealizada.empresa_id == emp_id,
                                                        ManutencaoRealizada.custo_id == custo_db.id
                                                    ).all()
                                                    for historico in historicos_vinculados:
                                                        session.delete(historico)
                                                    registrar_auditoria(
                                                        session, emp_id, st.session_state["usuario_id"],
                                                        "CUSTO_EXCLUIDO", "Custo", custo_db.id, custo_snapshot,
                                                    )
                                                    session.delete(custo_db)
                                                    session.commit()
                                                    excluir_storage(comprovante_excluir)
                                                    st.cache_data.clear()

                                                    st.success(
                                                        "Registro financeiro "
                                                        "excluído com sucesso."
                                                    )

                                                    time.sleep(0.5)
                                                    st.rerun()

                                            except Exception:
                                                session.rollback()
                                                st.error(
                                                    "Não foi possível excluir "
                                                    "o registro financeiro.",
                                                    icon=None
                                                )

                                            finally:
                                                session.close()


        # ══════════════════════════════════════════════════════════════════════════
        # GESTÃO DE COBRANÇAS
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Gestão de Cobranças":
            aplicar_css_modulos_v11()

            STATUS_COBRANCA = [
                "Pendente de emissão",
                "Emitida",
                "Enviada",
                "Recebida",
                "Não cobrar",
                "Cancelada",
            ]

            FORMAS_COBRANCA = [
                "Boleto",
                "Nota fiscal + boleto",
                "Pix",
                "Cartão",
                "Outro",
            ]

            # Base contratual usada pelas três visões.
            df_contratos_fin = carregar_dados_tabela(f"""
                SELECT
                    c.id,
                    c.veiculo_id,
                    c.cliente,
                    c.data_inicio,
                    c.data_fim,
                    c.ativo,
                    c.tipo_valor,
                    c.valor_mensal,
                    c.multa,
                    c.juros,
                    v.placa,
                    v.modelo
                FROM contratos c
                INNER JOIN veiculos v ON v.id = c.veiculo_id AND v.empresa_id = c.empresa_id
                WHERE c.empresa_id = :empresa_id
                ORDER BY c.ativo DESC, c.cliente, v.placa
            """, emp_id)

            df_cobrancas_resumo = carregar_dados_tabela("""
                SELECT status, valor_previsto, vencimento, mes_ano
                FROM cobrancas_mensais
                WHERE empresa_id=:empresa_id
            """, emp_id)
            if not df_cobrancas_resumo.empty:
                df_cobrancas_resumo["status"] = (
                    df_cobrancas_resumo["status"].fillna("").apply(normalizar_status_cobranca)
                )
                df_cobrancas_resumo["valor_previsto"] = pd.to_numeric(
                    df_cobrancas_resumo["valor_previsto"], errors="coerce"
                ).fillna(0.0)
                df_cobrancas_resumo["vencimento"] = pd.to_datetime(
                    df_cobrancas_resumo["vencimento"], errors="coerce"
                )
                cobrancas_validas_resumo = df_cobrancas_resumo[
                    ~df_cobrancas_resumo["status"].isin(["Cancelada", "Não cobrar"])
                ].copy()
                previsto_mes_resumo = float(cobrancas_validas_resumo.loc[
                    cobrancas_validas_resumo["mes_ano"] == hoje_local().strftime("%m/%Y"),
                    "valor_previsto",
                ].sum())
                recebidas_resumo = int((cobrancas_validas_resumo["status"] == "Recebida").sum())
                vencidas_resumo = int((
                    cobrancas_validas_resumo["vencimento"].notna()
                    & (cobrancas_validas_resumo["vencimento"] < pd.Timestamp(hoje_local()))
                    & ~cobrancas_validas_resumo["status"].isin(["Recebida"])
                ).sum())
                pendentes_resumo = int(cobrancas_validas_resumo["status"].isin([
                    "Pendente de emissão", "Emitida", "Enviada"
                ]).sum())
            else:
                previsto_mes_resumo = 0.0
                recebidas_resumo = vencidas_resumo = pendentes_resumo = 0

            contratos_ativos_cob = (
                int((df_contratos_fin["ativo"] == 1).sum())
                if not df_contratos_fin.empty else 0
            )
            module_hero(
                "Receita e recebimentos",
                "Gestão de Cobranças",
                "Acompanhe previsão, emissão e recebimento antes de acessar as rotinas de cobrança.",
                "Previsto no mês",
                fmt_brl(previsto_mes_resumo),
            )
            cb1, cb2, cb3, cb4 = st.columns(4)
            with cb1:
                module_stat_card("Contratos ativos", contratos_ativos_cob, "carteira geradora de receita")
            with cb2:
                module_stat_card("Pendentes", pendentes_resumo, "em emissão ou envio")
            with cb3:
                module_stat_card("Recebidas", recebidas_resumo, "cobranças liquidadas")
            with cb4:
                module_stat_card("Vencidas", vencidas_resumo, "exigem acompanhamento")

            pagina_cobrancas = st.session_state["pagina_cobrancas"]

            # ──────────────────────────────────────────────────────────────────────
            # VISÃO FINANCEIRA — RECEITA - CUSTOS = RESULTADO
            # ──────────────────────────────────────────────────────────────────────
            if pagina_cobrancas == "Visão Financeira":
                st.markdown("### Resultado financeiro")
                st.caption(
                    "Compare a receita prevista/recebida com os custos registrados na Gestão de Custos. "
                    "Use os filtros para analisar a empresa inteira, um cliente, um contrato ou um veículo específico."
                )

                competencias = opcoes_competencias(18, 18)
                comp_atual = hoje_local().strftime("%m/%Y")
                idx_atual = competencias.index(comp_atual) if comp_atual in competencias else len(competencias) // 2

                f1, f2 = st.columns(2)
                comp_ini = f1.selectbox(
                    "Competência inicial",
                    competencias,
                    index=max(0, idx_atual - 5),
                    key="cob_fin_comp_ini"
                )
                comp_fim = f2.selectbox(
                    "Competência final",
                    competencias,
                    index=idx_atual,
                    key="cob_fin_comp_fim"
                )

                inicio_periodo, _ = intervalo_competencia(comp_ini)
                _, fim_periodo = intervalo_competencia(comp_fim)

                if inicio_periodo > fim_periodo:
                    st.warning(
                        "A competência inicial deve ser anterior ou igual à competência final.",
                        icon=None
                    )
                else:
                    df_cobrancas_fin = carregar_dados_tabela(f"""
                        SELECT
                            id, contrato_id, recorrente_id, mes_ano, tipo, cliente,
                            forma_cobranca, valor_previsto, emissao_prevista, vencimento,
                            status, data_emissao, data_envio, num_boleto,
                            data_recebimento, multa, juros, valor_principal_liquidado, multa_aplicada, juros_aplicados, dias_atraso_liquidacao, valor_liquidado, liquidacao_congelada, liquidado_em, observacoes
                        FROM cobrancas_mensais
                        WHERE empresa_id = :empresa_id
                    """, emp_id)

                    df_custos_fin = carregar_dados_tabela(f"""
                        SELECT
                            c.id, c.contrato_id, c.veiculo_id, c.data_custo,
                            c.categoria, c.descricao, c.valor_total,
                            v.placa, v.modelo
                        FROM custos c
                        INNER JOIN veiculos v ON v.id = c.veiculo_id AND v.empresa_id = c.empresa_id
                        WHERE c.empresa_id = :empresa_id
                          AND c.data_custo >= :inicio_periodo
                          AND c.data_custo <= :fim_periodo
                    """, emp_id, {
                        "inicio_periodo": inicio_periodo,
                        "fim_periodo": fim_periodo,
                    })

                    df_sub_fin = carregar_dados_tabela(f"""
                        SELECT
                            id, contrato_id, veiculo_principal_id, veiculo_substituto_id,
                            data_inicio, data_fim
                        FROM substituicoes_contrato
                        WHERE empresa_id = :empresa_id
                    """, emp_id)

                    # Filtra receitas pelo vencimento; se ausente, pela emissão prevista;
                    # em último caso, pela competência.
                    if not df_cobrancas_fin.empty:
                        df_cobrancas_fin = df_cobrancas_fin.copy()
                        df_cobrancas_fin["status"] = (
                            df_cobrancas_fin["status"]
                            .fillna("")
                            .apply(normalizar_status_cobranca)
                        )
                        df_cobrancas_fin["_encargos"] = df_cobrancas_fin.apply(
                            encargos_cobranca_exibicao, axis=1
                        )
                        df_cobrancas_fin["_valor_atualizado"] = df_cobrancas_fin[
                            "_encargos"
                        ].apply(lambda x: float(x["valor_atualizado"]))
                        df_cobrancas_fin["_data_ref"] = pd.to_datetime(
                            df_cobrancas_fin["vencimento"], errors="coerce"
                        )
                        sem_venc = df_cobrancas_fin["_data_ref"].isna()
                        df_cobrancas_fin.loc[sem_venc, "_data_ref"] = pd.to_datetime(
                            df_cobrancas_fin.loc[sem_venc, "emissao_prevista"],
                            errors="coerce"
                        )
                        sem_data = df_cobrancas_fin["_data_ref"].isna()
                        if sem_data.any():
                            df_cobrancas_fin.loc[sem_data, "_data_ref"] = pd.to_datetime(
                                df_cobrancas_fin.loc[sem_data, "mes_ano"].apply(
                                    lambda x: competencia_para_data(x)
                                    if isinstance(x, str) and "/" in x
                                    else None
                                ),
                                errors="coerce"
                            )

                        df_cobrancas_fin = df_cobrancas_fin[
                            (df_cobrancas_fin["_data_ref"] >= pd.Timestamp(inicio_periodo))
                            & (df_cobrancas_fin["_data_ref"] <= pd.Timestamp(fim_periodo))
                        ]

                    if not df_custos_fin.empty:
                        df_custos_fin = df_custos_fin.copy()
                        df_custos_fin["data_custo"] = pd.to_datetime(
                            df_custos_fin["data_custo"], errors="coerce"
                        )

                    contratos_calc = df_contratos_fin.copy()
                    if not contratos_calc.empty:
                        contratos_calc["data_inicio"] = pd.to_datetime(
                            contratos_calc["data_inicio"], errors="coerce"
                        )
                        contratos_calc["data_fim"] = pd.to_datetime(
                            contratos_calc["data_fim"], errors="coerce"
                        )

                    subs_calc = df_sub_fin.copy()
                    if not subs_calc.empty:
                        subs_calc["data_inicio"] = pd.to_datetime(
                            subs_calc["data_inicio"], errors="coerce"
                        )
                        subs_calc["data_fim"] = pd.to_datetime(
                            subs_calc["data_fim"], errors="coerce"
                        )

                    def resolver_contrato_custo_linha(row):
                        if pd.notna(row.get("contrato_id")):
                            try:
                                return int(row["contrato_id"])
                            except Exception:
                                pass

                        if contratos_calc.empty or pd.isna(row.get("data_custo")):
                            return None

                        veiculo_id = int(row["veiculo_id"])
                        data_ref = row["data_custo"]

                        if not subs_calc.empty:
                            candidatos_sub = subs_calc[
                                (subs_calc["veiculo_substituto_id"] == veiculo_id)
                                & (subs_calc["data_inicio"] <= data_ref)
                                & (
                                    subs_calc["data_fim"].isna()
                                    | (subs_calc["data_fim"] >= data_ref)
                                )
                            ].sort_values("data_inicio", ascending=False)
                            if not candidatos_sub.empty:
                                return int(candidatos_sub.iloc[0]["contrato_id"])

                        candidatos = contratos_calc[
                            (contratos_calc["veiculo_id"] == veiculo_id)
                            & (contratos_calc["data_inicio"] <= data_ref)
                            & (
                                contratos_calc["data_fim"].isna()
                                | (contratos_calc["data_fim"] >= data_ref)
                            )
                        ].sort_values("data_inicio", ascending=False)

                        return (
                            int(candidatos.iloc[0]["id"])
                            if not candidatos.empty
                            else None
                        )

                    def resolver_contrato_cobranca_linha(row):
                        if pd.notna(row.get("contrato_id")):
                            try:
                                return int(row["contrato_id"])
                            except Exception:
                                pass

                        if contratos_calc.empty or pd.isna(row.get("_data_ref")):
                            return None

                        candidatos = contratos_calc[
                            (contratos_calc["cliente"] == row.get("cliente"))
                            & (contratos_calc["data_inicio"] <= row["_data_ref"])
                            & (
                                contratos_calc["data_fim"].isna()
                                | (contratos_calc["data_fim"] >= row["_data_ref"])
                            )
                        ].sort_values("data_inicio", ascending=False)

                        if len(candidatos) == 1:
                            return int(candidatos.iloc[0]["id"])
                        return None

                    if not df_custos_fin.empty:
                        df_custos_fin["_contrato_calc"] = df_custos_fin.apply(
                            resolver_contrato_custo_linha, axis=1
                        )

                    if not df_cobrancas_fin.empty:
                        df_cobrancas_fin["_contrato_calc"] = df_cobrancas_fin.apply(
                            resolver_contrato_cobranca_linha, axis=1
                        )

                    # ── Filtros gerenciais ─────────────────────────────────────────
                    contratos_index = (
                        contratos_calc.set_index("id")
                        if not contratos_calc.empty else pd.DataFrame()
                    )

                    clientes_opcoes = ["Todos"]
                    if not contratos_calc.empty:
                        clientes_opcoes += sorted(
                            contratos_calc["cliente"].dropna().astype(str).unique().tolist()
                        )
                    elif not df_cobrancas_fin.empty:
                        clientes_opcoes += sorted(
                            df_cobrancas_fin["cliente"].dropna().astype(str).unique().tolist()
                        )

                    ff1, ff2, ff3 = st.columns([1.05, 1.6, 1.35])
                    cliente_filtro = ff1.selectbox(
                        "Cliente",
                        clientes_opcoes,
                        key="cob_fin_cliente"
                    )

                    contratos_para_filtro = contratos_calc.copy()
                    if cliente_filtro != "Todos" and not contratos_para_filtro.empty:
                        contratos_para_filtro = contratos_para_filtro[
                            contratos_para_filtro["cliente"].astype(str) == cliente_filtro
                        ]

                    opcoes_contrato_filtro = {"Todos": None}
                    if not contratos_para_filtro.empty:
                        for _, r in contratos_para_filtro.iterrows():
                            label = (
                                f"#{int(r['id'])} · {r['cliente']} · "
                                f"{r['modelo']} {r['placa']}"
                            )
                            opcoes_contrato_filtro[label] = int(r["id"])

                    contrato_filtro_label = ff2.selectbox(
                        "Contrato",
                        list(opcoes_contrato_filtro.keys()),
                        key="cob_fin_contrato"
                    )
                    contrato_filtro_id = opcoes_contrato_filtro[contrato_filtro_label]

                    # Veículos disponíveis no cadastro contratual e/ou com custos no período.
                    veiculos_filtro_df = pd.DataFrame(columns=["veiculo_id", "modelo", "placa"])
                    partes_veiculos = []
                    if not contratos_para_filtro.empty:
                        partes_veiculos.append(
                            contratos_para_filtro[["veiculo_id", "modelo", "placa"]].drop_duplicates()
                        )
                    if not df_custos_fin.empty:
                        partes_veiculos.append(
                            df_custos_fin[["veiculo_id", "modelo", "placa"]].drop_duplicates()
                        )
                    if partes_veiculos:
                        veiculos_filtro_df = pd.concat(partes_veiculos, ignore_index=True).drop_duplicates("veiculo_id")

                    opcoes_veiculo_filtro = {"Todos": None}
                    if not veiculos_filtro_df.empty:
                        for _, r in veiculos_filtro_df.sort_values(["modelo", "placa"]).iterrows():
                            opcoes_veiculo_filtro[
                                f"{r['modelo']} · {r['placa']}"
                            ] = int(r["veiculo_id"])

                    veiculo_filtro_label = ff3.selectbox(
                        "Veículo",
                        list(opcoes_veiculo_filtro.keys()),
                        key="cob_fin_veiculo"
                    )
                    veiculo_filtro_id = opcoes_veiculo_filtro[veiculo_filtro_label]

                    cobrancas_filtradas = df_cobrancas_fin.copy()
                    custos_filtrados = df_custos_fin.copy()

                    if cliente_filtro != "Todos":
                        ids_cliente = set(
                            contratos_calc.loc[
                                contratos_calc["cliente"].astype(str) == cliente_filtro,
                                "id"
                            ].astype(int).tolist()
                        ) if not contratos_calc.empty else set()

                        if not cobrancas_filtradas.empty:
                            cobrancas_filtradas = cobrancas_filtradas[
                                cobrancas_filtradas["_contrato_calc"].isin(ids_cliente)
                                | (
                                    cobrancas_filtradas["_contrato_calc"].isna()
                                    & (cobrancas_filtradas["cliente"].astype(str) == cliente_filtro)
                                )
                            ]
                        if not custos_filtrados.empty:
                            custos_filtrados = custos_filtrados[
                                custos_filtrados["_contrato_calc"].isin(ids_cliente)
                            ]

                    if contrato_filtro_id is not None:
                        if not cobrancas_filtradas.empty:
                            cobrancas_filtradas = cobrancas_filtradas[
                                cobrancas_filtradas["_contrato_calc"] == contrato_filtro_id
                            ]
                        if not custos_filtrados.empty:
                            custos_filtrados = custos_filtrados[
                                custos_filtrados["_contrato_calc"] == contrato_filtro_id
                            ]

                    if veiculo_filtro_id is not None:
                        # Na receita, o veículo é atribuído ao contrato em que ele é o principal.
                        # Nos custos, usamos o veículo que efetivamente recebeu o lançamento.
                        ids_veiculo_principal = set(
                            contratos_calc.loc[
                                contratos_calc["veiculo_id"] == veiculo_filtro_id,
                                "id"
                            ].astype(int).tolist()
                        ) if not contratos_calc.empty else set()

                        if not cobrancas_filtradas.empty:
                            cobrancas_filtradas = cobrancas_filtradas[
                                cobrancas_filtradas["_contrato_calc"].isin(ids_veiculo_principal)
                            ]
                        if not custos_filtrados.empty:
                            custos_filtrados = custos_filtrados[
                                custos_filtrados["veiculo_id"] == veiculo_filtro_id
                            ]

                    filtros_ativos = []
                    if cliente_filtro != "Todos":
                        filtros_ativos.append(f"Cliente: {cliente_filtro}")
                    if contrato_filtro_id is not None:
                        filtros_ativos.append(f"Contrato: {contrato_filtro_label}")
                    if veiculo_filtro_id is not None:
                        filtros_ativos.append(f"Veículo: {veiculo_filtro_label}")
                    if filtros_ativos:
                        st.caption("Filtro ativo · " + " · ".join(filtros_ativos))

                    cobrancas_validas = (
                        cobrancas_filtradas[
                            ~cobrancas_filtradas["status"].isin(["Cancelada", "Não cobrar"])
                        ].copy()
                        if not cobrancas_filtradas.empty
                        else pd.DataFrame()
                    )

                    receita_prevista = (
                        float(cobrancas_validas["valor_previsto"].fillna(0).sum())
                        if not cobrancas_validas.empty else 0.0
                    )
                    receita_recebida = (
                        float(
                            cobrancas_validas.loc[
                                cobrancas_validas["status"] == "Recebida",
                                "_valor_atualizado"
                            ].fillna(0).sum()
                        )
                        if not cobrancas_validas.empty else 0.0
                    )
                    custos_periodo = (
                        float(custos_filtrados["valor_total"].fillna(0).sum())
                        if not custos_filtrados.empty else 0.0
                    )
                    resultado_previsto = receita_prevista - custos_periodo
                    margem_prevista = (
                        (resultado_previsto / receita_prevista) * 100
                        if receita_prevista > 0 else 0.0
                    )
                    resultado_realizado = receita_recebida - custos_periodo

                    atrasadas = 0
                    if not cobrancas_validas.empty:
                        atrasadas = int(
                            cobrancas_validas.apply(
                                lambda r: (
                                    dias_atraso_cobranca(
                                        r.get("vencimento"),
                                        r.get("status"),
                                        r.get("data_recebimento")
                                    ) > 0
                                    and normalizar_status_cobranca(r.get("status"))
                                    != "Recebida"
                                ),
                                axis=1
                            ).sum()
                        )

                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Receita prevista", fmt_brl(receita_prevista))
                    m2.metric("Receita recebida", fmt_brl(receita_recebida))
                    m3.metric("Custos do período", fmt_brl(custos_periodo))
                    m4.metric(
                        "Resultado previsto",
                        fmt_brl(resultado_previsto),
                        delta=f"{margem_prevista:.1f}% de margem"
                    )
                    m5.metric(
                        "Resultado realizado",
                        fmt_brl(resultado_realizado),
                        delta=f"{atrasadas} cobrança(s) em atraso",
                        delta_color="inverse" if atrasadas else "off"
                    )

                    if veiculo_filtro_id is not None:
                        st.info(
                            "Na análise por veículo, a receita é atribuída aos contratos em que o veículo "
                            "é o principal; os custos são os lançamentos efetivamente vinculados a esse veículo. "
                            "Custos de veículos reserva continuam vinculados ao contrato correspondente na análise por contrato.",
                            icon=None
                        )

                    # ── Rentabilidade por contrato ────────────────────────────────
                    st.markdown("### Rentabilidade por contrato")

                    receita_por = {}
                    recebido_por = {}
                    if not cobrancas_validas.empty:
                        for contrato_id, grupo in cobrancas_validas.groupby(
                            "_contrato_calc", dropna=False
                        ):
                            chave = int(contrato_id) if pd.notna(contrato_id) else None
                            receita_por[chave] = float(grupo["valor_previsto"].fillna(0).sum())
                            recebido_por[chave] = float(
                                grupo.loc[
                                    grupo["status"] == "Recebida",
                                    "_valor_atualizado"
                                ].fillna(0).sum()
                            )

                    custos_por = {}
                    if not custos_filtrados.empty:
                        for contrato_id, grupo in custos_filtrados.groupby(
                            "_contrato_calc", dropna=False
                        ):
                            chave = int(contrato_id) if pd.notna(contrato_id) else None
                            custos_por[chave] = float(grupo["valor_total"].fillna(0).sum())

                    ids_resultado = set(receita_por) | set(custos_por)
                    linhas_resultado = []

                    for contrato_id in ids_resultado:
                        receita = receita_por.get(contrato_id, 0.0)
                        recebido = recebido_por.get(contrato_id, 0.0)
                        custo = custos_por.get(contrato_id, 0.0)
                        resultado = receita - custo
                        margem = (resultado / receita * 100) if receita > 0 else None

                        if contrato_id is not None and not contratos_index.empty and contrato_id in contratos_index.index:
                            cinfo = contratos_index.loc[contrato_id]
                            if isinstance(cinfo, pd.DataFrame):
                                cinfo = cinfo.iloc[0]
                            cliente_label = str(cinfo["cliente"])
                            veiculo_label = f"{cinfo['modelo']} · {cinfo['placa']}"
                            contrato_label = f"#{int(contrato_id)}"
                        else:
                            cliente_label = "Sem vínculo"
                            veiculo_label = "—"
                            contrato_label = "—"

                        linhas_resultado.append({
                            "Contrato": contrato_label,
                            "Cliente": cliente_label,
                            "Veículo principal": veiculo_label,
                            "Receita prevista": receita,
                            "Receita recebida": recebido,
                            "Custos": custo,
                            "Resultado": resultado,
                            "Margem (%)": margem,
                        })

                    if linhas_resultado:
                        df_resultado = pd.DataFrame(linhas_resultado).sort_values(
                            "Resultado", ascending=False
                        )
                        df_resultado_exib = df_resultado.copy()
                        for col_monetaria in [
                            "Receita prevista", "Receita recebida", "Custos", "Resultado"
                        ]:
                            df_resultado_exib[col_monetaria] = (
                                df_resultado_exib[col_monetaria]
                                .apply(lambda v: fmt_brl(float(v or 0)))
                            )
                        df_resultado_exib["Margem (%)"] = (
                            df_resultado_exib["Margem (%)"]
                            .apply(
                                lambda v: (
                                    f"{float(v):,.1f}%"
                                    .replace(",", "X").replace(".", ",").replace("X", ".")
                                    if pd.notna(v) else "—"
                                )
                            )
                        )
                        st.dataframe(
                            df_resultado_exib,
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info(
                            "Ainda não há receitas ou custos para os filtros selecionados.",
                            icon=None
                        )

                    # ── Rentabilidade por veículo ─────────────────────────────────
                    st.markdown("### Rentabilidade por veículo")
                    st.caption(
                        "A receita é atribuída ao veículo principal do contrato. Os custos permanecem no veículo "
                        "em que foram efetivamente lançados, permitindo identificar veículos que pressionam a margem."
                    )

                    receita_veiculo = {}
                    recebido_veiculo = {}
                    if not cobrancas_validas.empty and not contratos_calc.empty:
                        for _, r in cobrancas_validas.iterrows():
                            contrato_id = r.get("_contrato_calc")
                            if pd.isna(contrato_id):
                                continue
                            contrato_id = int(contrato_id)
                            if contrato_id not in contratos_index.index:
                                continue
                            cinfo = contratos_index.loc[contrato_id]
                            if isinstance(cinfo, pd.DataFrame):
                                cinfo = cinfo.iloc[0]
                            veiculo_id = int(cinfo["veiculo_id"])
                            receita_veiculo[veiculo_id] = receita_veiculo.get(veiculo_id, 0.0) + float(r.get("valor_previsto") or 0)
                            if r.get("status") == "Recebida":
                                recebido_veiculo[veiculo_id] = (
                                    recebido_veiculo.get(veiculo_id, 0.0)
                                    + float(r.get("_valor_atualizado") or r.get("valor_previsto") or 0)
                                )

                    custos_veiculo = {}
                    info_veiculo = {}
                    if not custos_filtrados.empty:
                        for veiculo_id, grupo in custos_filtrados.groupby("veiculo_id"):
                            vid = int(veiculo_id)
                            custos_veiculo[vid] = float(grupo["valor_total"].fillna(0).sum())
                            primeiro = grupo.iloc[0]
                            info_veiculo[vid] = (str(primeiro["modelo"]), str(primeiro["placa"]))

                    if not contratos_calc.empty:
                        for _, r in contratos_calc.iterrows():
                            vid = int(r["veiculo_id"])
                            info_veiculo.setdefault(vid, (str(r["modelo"]), str(r["placa"])))

                    ids_veiculos_resultado = set(receita_veiculo) | set(custos_veiculo)
                    if veiculo_filtro_id is not None:
                        ids_veiculos_resultado &= {veiculo_filtro_id}

                    linhas_veiculo = []
                    for veiculo_id in ids_veiculos_resultado:
                        receita = receita_veiculo.get(veiculo_id, 0.0)
                        recebido = recebido_veiculo.get(veiculo_id, 0.0)
                        custo = custos_veiculo.get(veiculo_id, 0.0)
                        resultado = receita - custo
                        margem = (resultado / receita * 100) if receita > 0 else None
                        modelo, placa = info_veiculo.get(veiculo_id, ("Veículo", str(veiculo_id)))

                        linhas_veiculo.append({
                            "Veículo": f"{modelo} · {placa}",
                            "Receita prevista": receita,
                            "Receita recebida": recebido,
                            "Custos": custo,
                            "Resultado": resultado,
                            "Margem (%)": margem,
                        })

                    if linhas_veiculo:
                        df_resultado_veiculo = pd.DataFrame(linhas_veiculo).sort_values(
                            "Resultado", ascending=False
                        )
                        df_resultado_veiculo_exib = df_resultado_veiculo.copy()
                        for col_monetaria in [
                            "Receita prevista", "Receita recebida", "Custos", "Resultado"
                        ]:
                            df_resultado_veiculo_exib[col_monetaria] = (
                                df_resultado_veiculo_exib[col_monetaria]
                                .apply(lambda v: fmt_brl(float(v or 0)))
                            )
                        df_resultado_veiculo_exib["Margem (%)"] = (
                            df_resultado_veiculo_exib["Margem (%)"]
                            .apply(
                                lambda v: (
                                    f"{float(v):,.1f}%"
                                    .replace(",", "X").replace(".", ",").replace("X", ".")
                                    if pd.notna(v) else "—"
                                )
                            )
                        )
                        st.dataframe(
                            df_resultado_veiculo_exib,
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info(
                            "Não há movimentação suficiente para calcular a rentabilidade por veículo.",
                            icon=None
                        )

                    # ── Composição dos custos conforme filtros ─────────────────────
                    if not custos_filtrados.empty:
                        st.markdown("### Composição dos custos")
                        resumo_categoria = (
                            custos_filtrados.groupby("categoria", as_index=False)["valor_total"]
                            .sum()
                            .rename(columns={
                                "categoria": "Categoria",
                                "valor_total": "Valor"
                            })
                            .sort_values("Valor", ascending=False)
                        )
                        resumo_categoria_exib = resumo_categoria.copy()
                        resumo_categoria_exib["Valor"] = (
                            resumo_categoria_exib["Valor"]
                            .apply(lambda v: fmt_brl(float(v or 0)))
                        )
                        st.dataframe(
                            resumo_categoria_exib,
                            use_container_width=True,
                            hide_index=True
                        )

            # ──────────────────────────────────────────────────────────────────────
            # COBRANÇAS RECORRENTES
            # ──────────────────────────────────────────────────────────────────────
            elif pagina_cobrancas == "Recorrências":
                st.markdown("### Motor de cobranças recorrentes")
                st.caption(
                    "Cadastre uma única vez a regra de faturamento. O Kineo replica "
                    "a cobrança para cada competência sem alterar o contrato original."
                )

                ativos_fin = (
                    df_contratos_fin[df_contratos_fin["ativo"] == 1].copy()
                    if not df_contratos_fin.empty else pd.DataFrame()
                )
                # Um contrato com recorrência ativa já possui regra de faturamento.
                # Ele não pode ser escolhido novamente nesta criação.
                df_contratos_recorrentes = carregar_dados_tabela(
                    """
                    SELECT DISTINCT contrato_id
                    FROM cobrancas_recorrentes
                    WHERE empresa_id = :empresa_id
                      AND contrato_id IS NOT NULL
                      AND COALESCE(ativo, 1) = 1
                    """,
                    emp_id,
                )
                contratos_com_recorrencia = set(
                    df_contratos_recorrentes["contrato_id"].dropna().astype(int).tolist()
                ) if not df_contratos_recorrentes.empty else set()
                contratos_disponiveis_rec = (
                    ativos_fin[~ativos_fin["id"].astype(int).isin(contratos_com_recorrencia)].copy()
                    if not ativos_fin.empty else ativos_fin
                )

                recorrencia_form_version = st.session_state.setdefault(
                    "recorrencia_form_version", 0
                )
                opcoes_contratos = {"Cadastro manual / sem vínculo": None}
                if not contratos_disponiveis_rec.empty:
                    for _, row in contratos_disponiveis_rec.iterrows():
                        label = (
                            f"#{int(row['id'])} · {row['cliente']} · "
                            f"{row['modelo']} {row['placa']}"
                        )
                        opcoes_contratos[label] = int(row["id"])

                contrato_label = st.selectbox(
                    "Contrato vinculado",
                    list(opcoes_contratos.keys()),
                    key=f"cob_rec_contrato_{recorrencia_form_version}"
                )
                contrato_id_rec = opcoes_contratos[contrato_label]
                recorrencia_form_key = f"{contrato_id_rec or 'manual'}_{recorrencia_form_version}"

                contrato_base = None
                if contrato_id_rec is not None and not ativos_fin.empty:
                    encontrados = ativos_fin[ativos_fin["id"] == contrato_id_rec]
                    if not encontrados.empty:
                        contrato_base = encontrados.iloc[0]

                with st.container(border=True):
                    r1, r2 = st.columns([1.35, 1])
                    if contrato_base is not None:
                        c_cli = r1.text_input(
                            "Cliente",
                            value=str(contrato_base["cliente"]),
                            disabled=True,
                            key=f"cob_rec_cliente_{recorrencia_form_key}"
                        )
                    else:
                        c_cli = r1.text_input(
                            "Cliente",
                            key=f"cob_rec_cliente_manual_{recorrencia_form_version}"
                        )

                    c_form = r2.selectbox(
                        "Forma de cobrança",
                        FORMAS_COBRANCA,
                        key=f"cob_rec_forma_{recorrencia_form_key}"
                    )

                    default_tipo = (
                        str(contrato_base["tipo_valor"])
                        if contrato_base is not None
                        else "Fixo"
                    )
                    if default_tipo not in ["Fixo", "Variável"]:
                        default_tipo = "Fixo"

                    r3, r4, r5, r6 = st.columns(4)
                    c_tipo = r3.selectbox(
                        "Tipo do valor",
                        ["Fixo", "Variável"],
                        index=0 if default_tipo == "Fixo" else 1,
                        key=f"cob_rec_tipo_{recorrencia_form_key}"
                    )

                    valor_padrao = (
                        float(contrato_base["valor_mensal"] or 0)
                        if contrato_base is not None else 0.0
                    )
                    c_val_txt = r4.text_input(
                        "Valor mensal (R$)",
                        value=(fmt_brl(valor_padrao).replace("R$ ", "") if valor_padrao else ""),
                        placeholder="Ex.: 52.800,00",
                        disabled=(c_tipo == "Variável"),
                        key=f"cob_rec_valor_{recorrencia_form_key}"
                    )
                    c_val_num = parse_valor_cobranca(c_val_txt) if c_tipo == "Fixo" else 0.0
                    c_de = r5.number_input(
                        "Dia previsto de emissão",
                        min_value=1,
                        max_value=31,
                        value=1,
                        step=1,
                        key=f"cob_rec_emissao_{recorrencia_form_key}"
                    )
                    c_dv = r6.number_input(
                        "Dia de vencimento",
                        min_value=1,
                        max_value=31,
                        value=10,
                        step=1,
                        key=f"cob_rec_venc_{recorrencia_form_key}"
                    )

                    r7, r8 = st.columns(2)
                    multa_padrao = (
                        float(contrato_base["multa"] or 0)
                        if contrato_base is not None else 2.0
                    )
                    juros_padrao = (
                        float(contrato_base["juros"] or 0)
                        if contrato_base is not None else 1.0
                    )
                    c_multa = r7.number_input(
                        "Multa (%)",
                        min_value=0.0,
                        step=0.1,
                        value=multa_padrao,
                        key=f"cob_rec_multa_{recorrencia_form_key}"
                    )
                    c_juros = r8.number_input(
                        "Juros (%)",
                        min_value=0.0,
                        step=0.1,
                        value=juros_padrao,
                        key=f"cob_rec_juros_{recorrencia_form_key}"
                    )

                    c_obs = st.text_area(
                        "Orientações de faturamento",
                        placeholder=(
                            "Ex.: enviar e-mail após aprovação, contatos responsáveis, "
                            "regras específicas do cliente..."
                        ),
                        key=f"cob_rec_obs_{recorrencia_form_key}"
                    )

                    if st.button(
                        "Salvar cobrança recorrente",
                        icon=":material/save:",
                        use_container_width=True,
                        key=f"btn_salvar_cobranca_recorrente_{recorrencia_form_version}"
                    ):
                        cliente_limpo = str(c_cli or "").strip()
                        if not cliente_limpo:
                            st.error("Informe o cliente.", icon=None)
                        else:
                            session = SessionLocal()
                            try:
                                if contrato_id_rec is not None:
                                    existente = session.query(CobrancaRecorrente).filter(
                                        CobrancaRecorrente.empresa_id == emp_id,
                                        CobrancaRecorrente.contrato_id == contrato_id_rec,
                                        CobrancaRecorrente.ativo == 1
                                    ).first()
                                else:
                                    existente = None

                                if existente is not None:
                                    st.warning(
                                        "Este contrato já possui uma cobrança recorrente ativa. "
                                        "Edite o cadastro existente abaixo.",
                                        icon=None
                                    )
                                else:
                                    valor_txt = (
                                        "Variável"
                                        if c_tipo == "Variável"
                                        else f"{float(c_val_num):.2f}"
                                    )
                                    nova_recorrencia = CobrancaRecorrente(
                                        empresa_id=emp_id,
                                        contrato_id=contrato_id_rec,
                                        cliente=cliente_limpo,
                                        forma_cobranca=c_form,
                                        tipo_valor=c_tipo,
                                        valor_mensal=valor_txt,
                                        data_base_emissao=get_valid_date(2000, 1, int(c_de)),
                                        data_base_vencimento=get_valid_date(2000, 1, int(c_dv)),
                                        dia_emissao=int(c_de),
                                        dia_vencimento=int(c_dv),
                                        multa=float(c_multa),
                                        juros=float(c_juros),
                                        ativo=1,
                                        observacoes=c_obs.strip() or None
                                    )
                                    session.add(nova_recorrencia)
                                    session.flush()
                                    registrar_auditoria(
                                        session, emp_id, st.session_state["usuario_id"],
                                        "COBRANCA_RECORRENTE_CRIADA", "CobrancaRecorrente", nova_recorrencia.id,
                                        f"Cliente: {cliente_limpo}; contrato: {contrato_id_rec}; tipo: {c_tipo}",
                                    )

                                    # Se um contrato variável recebeu valor por competência antes
                                    # de sua regra recorrente ser cadastrada, completa agora os
                                    # dados de faturamento desses lançamentos ainda pendentes.
                                    if contrato_id_rec is not None:
                                        mensais_sem_regra = session.query(CobrancaMensal).filter(
                                            CobrancaMensal.empresa_id == emp_id,
                                            CobrancaMensal.contrato_id == contrato_id_rec,
                                            CobrancaMensal.tipo == "Recorrente",
                                            CobrancaMensal.recorrente_id.is_(None),
                                        ).all()
                                        for mensal in mensais_sem_regra:
                                            mensal.recorrente_id = nova_recorrencia.id
                                            mensal.forma_cobranca = c_form
                                            try:
                                                mes_m, ano_m = map(int, str(mensal.mes_ano).split("/"))
                                                mensal.emissao_prevista = get_valid_date(ano_m, mes_m, int(c_de))
                                                mensal.vencimento = get_valid_date(ano_m, mes_m, int(c_dv))
                                            except Exception:
                                                pass
                                            mensal.multa = float(c_multa)
                                            mensal.juros = float(c_juros)
                                            if c_obs.strip():
                                                mensal.observacoes = c_obs.strip()

                                    session.commit()
                                    st.cache_data.clear()
                                    st.session_state["recorrencia_form_version"] += 1
                                    st.session_state["recorrencias_editor_version"] += 1
                                    st.session_state["cobrancas_editor_version"] += 1
                                    st.success("Cobrança recorrente cadastrada.")
                                    st.rerun()
                            finally:
                                session.close()

                df_rec_all = carregar_dados_tabela(f"""
                    SELECT
                        cr.id,
                        cr.contrato_id,
                        cr.cliente,
                        cr.forma_cobranca,
                        cr.tipo_valor,
                        cr.valor_mensal,
                        cr.dia_emissao,
                        cr.dia_vencimento,
                        cr.multa,
                        cr.juros,
                        cr.ativo,
                        cr.observacoes,
                        v.placa
                    FROM cobrancas_recorrentes cr
                    LEFT JOIN contratos c
                        ON c.id = cr.contrato_id AND c.empresa_id = cr.empresa_id
                    LEFT JOIN veiculos v ON v.id = c.veiculo_id AND v.empresa_id = c.empresa_id
                    WHERE cr.empresa_id = :empresa_id
                    ORDER BY COALESCE(cr.ativo, 1) DESC, cr.cliente
                """, emp_id)

                if not df_rec_all.empty:
                    recorrencias_sem_vinculo = df_rec_all[
                        df_rec_all["contrato_id"].isna()
                    ].copy()
                    if not recorrencias_sem_vinculo.empty and not ativos_fin.empty:
                        with st.expander(
                            "Vincular cadastros recorrentes antigos aos contratos"
                        ):
                            st.caption(
                                "Use esta opção para os registros criados antes do vínculo "
                                "financeiro por contrato. Isso melhora a rentabilidade por rota/veículo."
                            )
                            op_rec_legado = {
                                f"#{int(r['id'])} · {r['cliente']}": int(r["id"])
                                for _, r in recorrencias_sem_vinculo.iterrows()
                            }
                            rec_leg_label = st.selectbox(
                                "Cobrança recorrente",
                                list(op_rec_legado.keys()),
                                key="cob_rec_legado_sel"
                            )
                            contrato_leg_label = st.selectbox(
                                "Contrato correspondente",
                                [
                                    k for k, v in opcoes_contratos.items()
                                    if v is not None
                                ],
                                key="cob_rec_legado_contrato"
                            )
                            if st.button(
                                "Vincular recorrência ao contrato",
                                use_container_width=True,
                                key="btn_vincular_rec_legado"
                            ):
                                session = SessionLocal()
                                try:
                                    rec_db = tenant_get(
                                        session, CobrancaRecorrente, op_rec_legado[rec_leg_label], emp_id
                                    )
                                    contrato_destino_id = opcoes_contratos[
                                        contrato_leg_label
                                    ]
                                    contrato_db = tenant_get(
                                        session, Contrato, contrato_destino_id, emp_id
                                    )
                                    if (
                                        rec_db is not None
                                        and contrato_db is not None
                                        and rec_db.empresa_id == emp_id
                                        and contrato_db.empresa_id == emp_id
                                    ):
                                        rec_db.contrato_id = contrato_db.id
                                        session.commit()
                                        st.cache_data.clear()
                                        st.session_state["recorrencias_editor_version"] += 1
                                        st.session_state["cobrancas_editor_version"] += 1
                                        st.success(
                                            "Recorrência vinculada ao contrato."
                                        )
                                        st.rerun()
                                    else:
                                        st.error(
                                            "Não foi possível validar o vínculo.",
                                            icon=None
                                        )
                                finally:
                                    session.close()

                    st.markdown("### Recorrências cadastradas")
                    df_rec_edit = df_rec_all.copy()
                    df_rec_edit["tipo_valor"] = df_rec_edit.apply(
                        lambda r: (
                            r["tipo_valor"]
                            if r["tipo_valor"] in ["Fixo", "Variável"]
                            else (
                                "Variável"
                                if "vari" in str(r["valor_mensal"]).lower()
                                else "Fixo"
                            )
                        ),
                        axis=1
                    )
                    df_rec_edit["dia_emissao"] = pd.to_numeric(
                        df_rec_edit["dia_emissao"], errors="coerce"
                    ).fillna(1).astype(int)
                    df_rec_edit["dia_vencimento"] = pd.to_numeric(
                        df_rec_edit["dia_vencimento"], errors="coerce"
                    ).fillna(10).astype(int)
                    df_rec_edit["multa"] = pd.to_numeric(
                        df_rec_edit["multa"], errors="coerce"
                    ).fillna(0.0)
                    df_rec_edit["juros"] = pd.to_numeric(
                        df_rec_edit["juros"], errors="coerce"
                    ).fillna(0.0)
                    df_rec_edit["ativo"] = (
                        pd.to_numeric(df_rec_edit["ativo"], errors="coerce")
                        .fillna(1).astype(int).astype(bool)
                    )
                    # Exibe valores fixos no padrão brasileiro, mantendo a coluna editável.
                    df_rec_edit["valor_mensal"] = df_rec_edit.apply(
                        lambda r: (
                            "Variável"
                            if r["tipo_valor"] == "Variável"
                            else fmt_brl(parse_valor_cobranca(r["valor_mensal"])).replace("R$ ", "")
                        ),
                        axis=1
                    )
                    df_rec_edit["Contrato"] = df_rec_edit.apply(
                        lambda r: (
                            f"#{int(r['contrato_id'])} · {r['placa']}"
                            if pd.notna(r["contrato_id"])
                            else "Sem vínculo"
                        ),
                        axis=1
                    )

                    rec_cols = [
                        "id", "Contrato", "cliente", "forma_cobranca",
                        "tipo_valor", "valor_mensal", "dia_emissao",
                        "dia_vencimento", "multa", "juros", "ativo",
                        "observacoes"
                    ]

                    ed_recorrentes = st.data_editor(
                        df_rec_edit[rec_cols],
                        use_container_width=True,
                        hide_index=True,
                        key=f"editor_cobrancas_recorrentes_{st.session_state['recorrencias_editor_version']}",
                        column_config={
                            "id": None,
                            "Contrato": st.column_config.TextColumn(
                                "Contrato", disabled=True
                            ),
                            "cliente": st.column_config.TextColumn(
                                "Cliente", disabled=True
                            ),
                            "forma_cobranca": st.column_config.SelectboxColumn(
                                "Forma", options=FORMAS_COBRANCA
                            ),
                            "tipo_valor": st.column_config.SelectboxColumn(
                                "Valor", options=["Fixo", "Variável"]
                            ),
                            "valor_mensal": st.column_config.TextColumn(
                                "Valor mensal"
                            ),
                            "dia_emissao": st.column_config.NumberColumn(
                                "Emissão", min_value=1, max_value=31, step=1
                            ),
                            "dia_vencimento": st.column_config.NumberColumn(
                                "Vencimento", min_value=1, max_value=31, step=1
                            ),
                            "multa": st.column_config.NumberColumn(
                                "Multa (%)", min_value=0.0, format="%.2f"
                            ),
                            "juros": st.column_config.NumberColumn(
                                "Juros (%)", min_value=0.0, format="%.2f"
                            ),
                            "ativo": st.column_config.CheckboxColumn("Ativo"),
                            "observacoes": st.column_config.TextColumn(
                                "Orientações"
                            ),
                        }
                    )

                    if st.button(
                        "Salvar alterações das recorrências",
                        use_container_width=True,
                        key="btn_salvar_recorrencias_edit"
                    ):
                        session = SessionLocal()
                        try:
                            for _, row in ed_recorrentes.iterrows():
                                rec_db = tenant_get(
                                    session, CobrancaRecorrente, int(row["id"]), emp_id
                                )
                                if rec_db is None or rec_db.empresa_id != emp_id:
                                    continue

                                rec_db.forma_cobranca = row["forma_cobranca"]
                                rec_db.tipo_valor = row["tipo_valor"]
                                rec_db.valor_mensal = (
                                    "Variável"
                                    if row["tipo_valor"] == "Variável"
                                    else f"{parse_valor_cobranca(row['valor_mensal']):.2f}"
                                )
                                rec_db.dia_emissao = int(row["dia_emissao"])
                                rec_db.dia_vencimento = int(row["dia_vencimento"])
                                rec_db.data_base_emissao = get_valid_date(
                                    2000, 1, int(row["dia_emissao"])
                                )
                                rec_db.data_base_vencimento = get_valid_date(
                                    2000, 1, int(row["dia_vencimento"])
                                )
                                rec_db.multa = float(row["multa"] or 0)
                                rec_db.juros = float(row["juros"] or 0)
                                rec_db.ativo = 1 if bool(row["ativo"]) else 0
                                rec_db.observacoes = (
                                    str(row["observacoes"]).strip()
                                    if pd.notna(row["observacoes"])
                                    else None
                                )
                                registrar_auditoria(
                                    session, emp_id, st.session_state["usuario_id"],
                                    "COBRANCA_RECORRENTE_ATUALIZADA", "CobrancaRecorrente", rec_db.id,
                                    f"Ativo: {rec_db.ativo}; emissão: dia {rec_db.dia_emissao}; vencimento: dia {rec_db.dia_vencimento}",
                                )

                            session.commit()
                            st.cache_data.clear()
                            st.session_state["recorrencias_editor_version"] += 1
                            st.success("Recorrências atualizadas.")
                            st.rerun()
                        finally:
                            session.close()

                    if st.session_state.get("perfil") == "admin":
                        with st.expander("Excluir cobrança recorrente — Zona restrita"):
                            st.caption(
                                "Exclusão permanente é permitida quando a recorrência não possui histórico. "
                                "Se houver competências geradas, produção preserva o histórico e exige apenas a desativação. "
                                "Em DEV/HOMOLOGAÇÃO é possível remover uma recorrência de teste e as competências vinculadas, "
                                "mediante confirmação explícita."
                            )
                            op_rec_excluir = {
                                (
                                    f"#{int(r['id'])} · {r['cliente']} · "
                                    f"{'Ativa' if int(r['ativo'] or 0) == 1 else 'Inativa'}"
                                ): int(r["id"])
                                for _, r in df_rec_all.iterrows()
                            }
                            rec_exc_label = st.selectbox(
                                "Recorrência para excluir",
                                list(op_rec_excluir.keys()),
                                key="recorrencia_excluir_sel",
                            )
                            rec_exc_id = op_rec_excluir[rec_exc_label]

                            session_info = SessionLocal()
                            try:
                                qtd_competencias_rec = session_info.query(CobrancaMensal).filter(
                                    CobrancaMensal.empresa_id == emp_id,
                                    CobrancaMensal.recorrente_id == rec_exc_id,
                                ).count()
                            finally:
                                session_info.close()

                            if qtd_competencias_rec:
                                st.warning(
                                    f"Esta recorrência possui {qtd_competencias_rec} competência(s) gerada(s). "
                                    + (
                                        "Em produção ela não pode ser apagada; desative o cadastro para preservar o histórico."
                                        if IS_PRODUCTION_APP
                                        else "Como este ambiente não é produção, a exclusão de teste também removerá essas competências."
                                    ),
                                    icon=None,
                                )
                            else:
                                st.info("Nenhuma competência mensal está vinculada a esta recorrência.", icon=None)

                            confirm_rec = st.text_input(
                                f"Digite EXCLUIR {rec_exc_id} para confirmar",
                                key=f"confirmar_excluir_rec_{rec_exc_id}",
                            )
                            if st.button(
                                "Excluir recorrência permanentemente",
                                type="primary",
                                use_container_width=True,
                                key=f"btn_excluir_rec_{rec_exc_id}",
                            ):
                                if confirm_rec.strip() != f"EXCLUIR {rec_exc_id}":
                                    st.error("Confirmação inválida.", icon=None)
                                elif IS_PRODUCTION_APP and qtd_competencias_rec > 0:
                                    st.error(
                                        "Esta recorrência possui histórico e não pode ser excluída em produção. "
                                        "Desative-a no campo Ativo.",
                                        icon=None,
                                    )
                                else:
                                    session = SessionLocal()
                                    try:
                                        rec_db = tenant_get(
                                            session, CobrancaRecorrente, rec_exc_id, emp_id
                                        )
                                        if rec_db is None:
                                            st.error("Recorrência não encontrada.", icon=None)
                                        else:
                                            snapshot_cliente = rec_db.cliente
                                            qtd_excluidas = 0
                                            if not IS_PRODUCTION_APP:
                                                qtd_excluidas = session.query(CobrancaMensal).filter(
                                                    CobrancaMensal.empresa_id == emp_id,
                                                    CobrancaMensal.recorrente_id == rec_db.id,
                                                ).delete(synchronize_session=False)
                                            session.delete(rec_db)
                                            registrar_auditoria(
                                                session, emp_id, st.session_state["usuario_id"],
                                                "COBRANCA_RECORRENTE_EXCLUIDA", "CobrancaRecorrente", rec_exc_id,
                                                f"Cliente: {snapshot_cliente}; competências removidas: {qtd_excluidas}; ambiente: {APP_ENV}",
                                            )
                                            session.commit()
                                            st.cache_data.clear()
                                            st.session_state["recorrencias_editor_version"] += 1
                                            st.session_state["cobrancas_editor_version"] += 1
                                            st.success("Cobrança recorrente excluída.")
                                            st.rerun()
                                    except Exception:
                                        session.rollback()
                                        logger.exception("Falha ao excluir cobrança recorrente")
                                        st.error("Não foi possível excluir a cobrança recorrente.", icon=None)
                                    finally:
                                        session.close()
                else:
                    st.info(
                        "Nenhuma cobrança recorrente cadastrada.",
                        icon=None
                    )

            # ──────────────────────────────────────────────────────────────────────
            # CONTROLE MENSAL
            # ──────────────────────────────────────────────────────────────────────
            elif pagina_cobrancas == "Operação Mensal":
                st.markdown("### Controle mensal")
                competencias = opcoes_competencias(12, 18)
                comp_atual = hoje_local().strftime("%m/%Y")
                idx_atual = competencias.index(comp_atual) if comp_atual in competencias else 12
                mes_sel = st.selectbox(
                    "Competência",
                    competencias,
                    index=idx_atual,
                    key="cob_mes_competencia"
                )

                session = SessionLocal()
                recorrentes_ativos = session.query(CobrancaRecorrente).filter(
                    CobrancaRecorrente.empresa_id == emp_id,
                    CobrancaRecorrente.ativo == 1
                ).all()

                faltantes = []
                competencia_selecionada_data = competencia_para_data(mes_sel)
                for rec in recorrentes_ativos:
                    # Defesa adicional para dados legados: mesmo que uma recorrência tenha
                    # permanecido ativa por alguma versão anterior, contrato encerrado não
                    # pode voltar a gerar receita futura.
                    if rec.contrato_id is not None:
                        contrato_rec = tenant_get(session, Contrato, rec.contrato_id, emp_id)
                        if contrato_rec is None:
                            continue
                        if int(contrato_rec.ativo or 0) != 1:
                            continue
                        data_fim_rec = coerce_date(contrato_rec.data_fim)
                        if (
                            data_fim_rec is not None
                            and competencia_selecionada_data
                            > date(data_fim_rec.year, data_fim_rec.month, 1)
                        ):
                            continue

                    query_existe = session.query(CobrancaMensal).filter(
                        CobrancaMensal.empresa_id == emp_id,
                        CobrancaMensal.mes_ano == mes_sel,
                        CobrancaMensal.tipo == "Recorrente"
                    )
                    existe = query_existe.filter(
                        CobrancaMensal.recorrente_id == rec.id
                    ).first()
                    # Compatibilidade: cobranças geradas antes da criação de recorrente_id
                    # eram identificadas apenas por cliente/tipo.
                    if existe is None and rec.contrato_id is not None:
                        existe = query_existe.filter(
                            CobrancaMensal.contrato_id == rec.contrato_id
                        ).first()
                    if existe is None and rec.contrato_id is None:
                        # Compatibilidade apenas para recorrências realmente legadas,
                        # sem contrato associado. Evita misturar dois contratos do mesmo cliente.
                        existe = query_existe.filter(
                            CobrancaMensal.cliente == rec.cliente
                        ).first()
                    if existe is None:
                        faltantes.append(rec)

                if faltantes:
                    with st.container(border=True):
                        st.info(
                            f"{len(faltantes)} cobrança(s) recorrente(s) ainda não foram "
                            f"geradas para {mes_sel}.",
                            icon=None
                        )
                        if st.button(
                            f"Gerar cobranças de {mes_sel}",
                            icon=":material/autorenew:",
                            use_container_width=True,
                            key="btn_gerar_recorrencias_mes"
                        ):
                            ano, mes = map(int, reversed(mes_sel.split("/")))
                            novos = 0
                            for rec in faltantes:
                                dia_emissao = (
                                    rec.dia_emissao
                                    or (
                                        rec.data_base_emissao.day
                                        if rec.data_base_emissao else 1
                                    )
                                )
                                dia_vencimento = (
                                    rec.dia_vencimento
                                    or (
                                        rec.data_base_vencimento.day
                                        if rec.data_base_vencimento else 10
                                    )
                                )
                                valor = (
                                    Decimal("0.00")
                                    if rec.tipo_valor == "Variável"
                                    else decimal_monetario(rec.valor_mensal)
                                )

                                session.add(CobrancaMensal(
                                    empresa_id=emp_id,
                                    contrato_id=rec.contrato_id,
                                    recorrente_id=rec.id,
                                    mes_ano=mes_sel,
                                    tipo="Recorrente",
                                    cliente=rec.cliente,
                                    forma_cobranca=rec.forma_cobranca,
                                    valor_previsto=valor,
                                    emissao_prevista=get_valid_date(
                                        ano, mes, int(dia_emissao)
                                    ),
                                    vencimento=get_valid_date(
                                        ano, mes, int(dia_vencimento)
                                    ),
                                    status="Pendente de emissão",
                                    multa=float(rec.multa or 0),
                                    juros=float(rec.juros or 0),
                                    observacoes=rec.observacoes
                                ))
                                novos += 1

                            registrar_auditoria(
                                session, emp_id, st.session_state["usuario_id"],
                                "COBRANCAS_COMPETENCIA_GERADA", "CobrancaMensal", None,
                                f"Competência: {mes_sel}; cobranças geradas: {novos}",
                            )
                            try:
                                session.commit()
                            except IntegrityError:
                                session.rollback()
                                st.cache_data.clear()
                                st.warning(
                                    "A competência já foi gerada por outra operação. A lista será atualizada sem duplicar cobranças.",
                                    icon=None,
                                )
                                session.close()
                                st.rerun()
                            except Exception:
                                session.rollback()
                                logger.exception("Falha ao gerar cobranças recorrentes da competência")
                                st.error("Não foi possível gerar as cobranças desta competência.", icon=None)
                                session.close()
                                st.stop()
                            st.cache_data.clear()
                            st.success(
                                f"{novos} cobrança(s) gerada(s) para {mes_sel}."
                            )
                            session.close()
                            st.rerun()
                else:
                    st.caption(
                        "Todas as recorrências ativas já estão presentes nesta competência."
                    )

                session.close()

                df_mensal = carregar_dados_tabela(f"""
                    SELECT
                        id, contrato_id, recorrente_id, mes_ano, tipo, cliente,
                        forma_cobranca, valor_previsto, emissao_prevista,
                        vencimento, status, data_emissao, data_envio,
                        num_boleto, data_recebimento, multa, juros, valor_principal_liquidado, multa_aplicada, juros_aplicados, dias_atraso_liquidacao, valor_liquidado, liquidacao_congelada, liquidado_em, observacoes
                    FROM cobrancas_mensais
                    WHERE empresa_id = :empresa_id
                      AND mes_ano = :mes_sel
                    ORDER BY tipo, cliente
                """, emp_id, {"mes_sel": mes_sel})

                if df_mensal.empty:
                    st.info(
                        "Não há cobranças nesta competência.",
                        icon=None
                    )
                else:
                    df_mensal = df_mensal.copy()
                    df_mensal["status"] = (
                        df_mensal["status"]
                        .fillna("")
                        .apply(normalizar_status_cobranca)
                    )

                    # A data de recebimento é a evidência operacional do pagamento.
                    # Se ela estiver preenchida, o status efetivo passa a Recebida,
                    # exceto em cobranças explicitamente Canceladas ou Não cobrar.
                    df_mensal["status"] = df_mensal.apply(
                        lambda r: (
                            "Recebida"
                            if coerce_date(r.get("data_recebimento")) is not None
                            and normalizar_status_cobranca(r.get("status"))
                            not in ["Cancelada", "Não cobrar"]
                            else normalizar_status_cobranca(r.get("status"))
                        ),
                        axis=1,
                    )

                    df_mensal["_encargos"] = df_mensal.apply(
                        encargos_cobranca_exibicao, axis=1
                    )
                    df_mensal["dias_atraso"] = df_mensal["_encargos"].apply(
                        lambda x: int(x["dias_atraso"])
                    )
                    df_mensal["valor_multa_calculada"] = df_mensal["_encargos"].apply(
                        lambda x: float(x["valor_multa"])
                    )
                    df_mensal["valor_juros_calculados"] = df_mensal["_encargos"].apply(
                        lambda x: float(x["valor_juros"])
                    )
                    df_mensal["valor_atualizado"] = df_mensal["_encargos"].apply(
                        lambda x: float(x["valor_atualizado"])
                    )
                    df_mensal["liquidacao_status"] = df_mensal.apply(
                        lambda r: "Congelada"
                        if int(r.get("liquidacao_congelada") or 0) == 1 and pd.notna(r.get("valor_liquidado"))
                        else "Em aberto",
                        axis=1,
                    )

                    validas_mes = df_mensal[
                        ~df_mensal["status"].isin(["Cancelada", "Não cobrar"])
                    ].copy()
                    total_previsto = float(
                        validas_mes["valor_previsto"].fillna(0).sum()
                    )
                    pendentes_mes = validas_mes[
                        validas_mes["status"] == "Pendente de emissão"
                    ]
                    emitidas_mes = validas_mes[
                        validas_mes["status"].isin(["Emitida", "Enviada"])
                    ]
                    recebidas_mes = validas_mes[
                        validas_mes["status"] == "Recebida"
                    ]
                    atrasadas_mes = validas_mes[
                        (validas_mes["dias_atraso"] > 0)
                        & (validas_mes["status"] != "Recebida")
                    ]

                    k1, k2, k3, k4, k5 = st.columns(5)
                    k1.metric(
                        "Total previsto",
                        fmt_brl(total_previsto),
                        delta=f"{len(validas_mes)} cobrança(s)"
                    )
                    k2.metric(
                        "Pendente de emissão",
                        fmt_brl(float(pendentes_mes["valor_previsto"].fillna(0).sum())),
                        delta=f"{len(pendentes_mes)} cobrança(s)",
                        delta_color="off"
                    )
                    k3.metric(
                        "Emitido / enviado",
                        fmt_brl(float(emitidas_mes["valor_previsto"].fillna(0).sum())),
                        delta=f"{len(emitidas_mes)} cobrança(s)",
                        delta_color="off"
                    )
                    k4.metric(
                        "Recebido",
                        fmt_brl(float(recebidas_mes["valor_atualizado"].fillna(0).sum())),
                        delta=f"{len(recebidas_mes)} cobrança(s)",
                        delta_color="off"
                    )
                    k5.metric(
                        "Em atraso",
                        fmt_brl(float(atrasadas_mes["valor_previsto"].fillna(0).sum())),
                        delta=f"{len(atrasadas_mes)} cobrança(s)",
                        delta_color="inverse"
                    )

                    csv_m = convert_df_to_csv(
                        df_mensal[[
                            "tipo", "cliente", "forma_cobranca", "valor_previsto",
                            "emissao_prevista", "vencimento", "data_emissao",
                            "num_boleto", "status", "data_recebimento",
                            "dias_atraso", "valor_multa_calculada",
                            "valor_juros_calculados", "valor_atualizado", "observacoes"
                        ]]
                    )
                    st.download_button(
                        "Exportar competência",
                        csv_m,
                        f"cobrancas_{mes_sel.replace('/', '_')}.csv",
                        use_container_width=False,
                        key="download_cobrancas_mes"
                    )

                    COL_CONFIG_COB = {
                        "id": None,
                        "tipo": st.column_config.TextColumn(
                            "Tipo", disabled=True
                        ),
                        "cliente": st.column_config.TextColumn(
                            "Cliente", disabled=True
                        ),
                        "forma_cobranca": st.column_config.TextColumn(
                            "Forma", disabled=True
                        ),
                        "valor_previsto": st.column_config.TextColumn(
                            "Valor previsto (R$)",
                            help="Use o padrão brasileiro, por exemplo: 52.800,00"
                        ),
                        "emissao_prevista": st.column_config.DateColumn(
                            "Emissão prevista", disabled=True, format="DD/MM/YYYY"
                        ),
                        "vencimento": st.column_config.DateColumn(
                            "Vencimento", disabled=True, format="DD/MM/YYYY"
                        ),
                        "data_emissao": st.column_config.DateColumn(
                            "Data de emissão", format="DD/MM/YYYY"
                        ),
                        "num_boleto": st.column_config.TextColumn(
                            "Nº boleto"
                        ),
                        "status": st.column_config.SelectboxColumn(
                            "Status", options=STATUS_COBRANCA
                        ),
                        "liquidacao_status": st.column_config.TextColumn(
                            "Liquidação", disabled=True,
                            help="Congelada = principal, multa, juros e data de recebimento preservados como histórico."
                        ),
                        "data_envio": st.column_config.DateColumn(
                            "Data de envio", format="DD/MM/YYYY"
                        ),
                        "data_recebimento": st.column_config.DateColumn(
                            "Recebimento", format="DD/MM/YYYY"
                        ),
                        "dias_atraso": st.column_config.NumberColumn(
                            "Dias em atraso", disabled=True, format="%d"
                        ),
                        "multa": st.column_config.NumberColumn(
                            "Multa (%)", min_value=0.0, format="%.2f"
                        ),
                        "juros": st.column_config.NumberColumn(
                            "Juros/mês (%)", min_value=0.0, format="%.2f"
                        ),
                        "valor_multa_calculada": st.column_config.TextColumn(
                            "Multa calculada (R$)", disabled=True
                        ),
                        "valor_juros_calculados": st.column_config.TextColumn(
                            "Juros calculados (R$)", disabled=True
                        ),
                        "valor_atualizado": st.column_config.TextColumn(
                            "Valor atualizado (R$)", disabled=True
                        ),
                        "observacoes": st.column_config.TextColumn(
                            "Observações"
                        ),
                    }

                    COLS_COB = [
                        "id", "tipo", "cliente", "forma_cobranca", "valor_previsto",
                        "emissao_prevista", "vencimento", "data_emissao",
                        "num_boleto", "status", "liquidacao_status", "data_envio",
                        "data_recebimento", "dias_atraso", "multa", "juros",
                        "valor_multa_calculada", "valor_juros_calculados",
                        "valor_atualizado", "observacoes"
                    ]

                    st.caption(
                        "Após o recebimento, a liquidação financeira é congelada. Alterações posteriores em multa, "
                        "juros ou valor contratual não reescrevem o histórico já recebido."
                    )
                    st.markdown("### Cobranças recorrentes")
                    df_rec_mes = df_mensal[
                        df_mensal["tipo"] == "Recorrente"
                    ].copy()
                    df_rec_mes_editor = df_rec_mes[COLS_COB].copy()
                    df_rec_mes_editor = preparar_datas_para_editor(
                        df_rec_mes_editor,
                        [
                            "emissao_prevista", "vencimento", "data_emissao",
                            "data_envio", "data_recebimento"
                        ],
                    )
                    if not df_rec_mes_editor.empty:
                        df_rec_mes_editor["valor_previsto"] = (
                            df_rec_mes_editor["valor_previsto"]
                            .apply(lambda v: fmt_brl(float(v or 0)).replace("R$ ", ""))
                        )
                        for col_calc in [
                            "valor_multa_calculada", "valor_juros_calculados", "valor_atualizado"
                        ]:
                            df_rec_mes_editor[col_calc] = df_rec_mes_editor[col_calc].apply(
                                lambda v: fmt_brl(float(v or 0)).replace("R$ ", "")
                            )
                    ed_rec_mes = (
                        st.data_editor(
                            df_rec_mes_editor,
                            column_config=COL_CONFIG_COB,
                            use_container_width=True,
                            hide_index=True,
                            key=f"ed_rec_{mes_sel}_{st.session_state['cobrancas_editor_version']}"
                        )
                        if not df_rec_mes.empty
                        else None
                    )
                    if df_rec_mes.empty:
                        st.caption("Nenhuma cobrança recorrente nesta competência.")

                    st.markdown("### Cobranças pontuais")
                    df_pont_mes = df_mensal[
                        df_mensal["tipo"] == "Pontual"
                    ].copy()
                    df_pont_mes_editor = df_pont_mes[COLS_COB].copy()
                    df_pont_mes_editor = preparar_datas_para_editor(
                        df_pont_mes_editor,
                        [
                            "emissao_prevista", "vencimento", "data_emissao",
                            "data_envio", "data_recebimento"
                        ],
                    )
                    if not df_pont_mes_editor.empty:
                        df_pont_mes_editor["valor_previsto"] = (
                            df_pont_mes_editor["valor_previsto"]
                            .apply(lambda v: fmt_brl(float(v or 0)).replace("R$ ", ""))
                        )
                        for col_calc in [
                            "valor_multa_calculada", "valor_juros_calculados", "valor_atualizado"
                        ]:
                            df_pont_mes_editor[col_calc] = df_pont_mes_editor[col_calc].apply(
                                lambda v: fmt_brl(float(v or 0)).replace("R$ ", "")
                            )
                    ed_pont_mes = (
                        st.data_editor(
                            df_pont_mes_editor,
                            column_config=COL_CONFIG_COB,
                            use_container_width=True,
                            hide_index=True,
                            key=f"ed_pont_{mes_sel}_{st.session_state['cobrancas_editor_version']}"
                        )
                        if not df_pont_mes.empty
                        else None
                    )
                    if df_pont_mes.empty:
                        st.caption("Nenhuma cobrança pontual nesta competência.")

                    if st.button(
                        "Salvar alterações da competência",
                        icon=":material/save:",
                        use_container_width=True,
                        key=f"btn_salvar_comp_{mes_sel}"
                    ):
                        session = SessionLocal()
                        try:
                            alteracoes = 0
                            liquidacoes_novas = 0
                            liquidadas_preservadas = 0
                            for ed in [ed_rec_mes, ed_pont_mes]:
                                if ed is None:
                                    continue
                                for _, row in ed.iterrows():
                                    cob = tenant_get(
                                        session, CobrancaMensal, int(row["id"]), emp_id
                                    )
                                    if cob is None or cob.empresa_id != emp_id:
                                        continue

                                    cob.data_emissao = coerce_date(row.get("data_emissao"))
                                    cob.data_envio = coerce_date(row.get("data_envio"))
                                    cob.num_boleto = (
                                        str(row["num_boleto"]).strip()
                                        if pd.notna(row["num_boleto"])
                                        else None
                                    )
                                    cob.observacoes = (
                                        str(row["observacoes"]).strip()
                                        if pd.notna(row["observacoes"])
                                        else None
                                    )

                                    # Uma liquidação congelada é histórico financeiro: principal,
                                    # multa, juros, atraso e data de recebimento não são recalculados.
                                    if int(cob.liquidacao_congelada or 0) == 1 and cob.valor_liquidado is not None:
                                        cob.status = "Recebida"
                                        liquidadas_preservadas += 1
                                        alteracoes += 1
                                        continue

                                    principal = decimal_monetario(row["valor_previsto"])
                                    status_informado = normalizar_status_cobranca(row["status"])
                                    data_recebimento = coerce_date(row.get("data_recebimento"))
                                    multa_pct = float(row["multa"] or 0)
                                    juros_pct = float(row["juros"] or 0)

                                    if status_informado == "Recebida" and data_recebimento is None:
                                        raise ValueError(
                                            f"A cobrança #{cob.id} está marcada como Recebida, mas não possui data de recebimento."
                                        )

                                    if (
                                        data_recebimento is not None
                                        and status_informado not in ["Cancelada", "Não cobrar"]
                                    ):
                                        congelar_liquidacao(
                                            cob, principal, data_recebimento, multa_pct, juros_pct
                                        )
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "COBRANCA_LIQUIDADA", "CobrancaMensal", cob.id,
                                            f"Competência: {cob.mes_ano}; principal: {cob.valor_principal_liquidado}; "
                                            f"multa: {cob.multa_aplicada}; juros: {cob.juros_aplicados}; "
                                            f"valor liquidado: {cob.valor_liquidado}",
                                        )
                                        liquidacoes_novas += 1
                                    else:
                                        cob.valor_previsto = principal
                                        cob.status = status_informado
                                        cob.multa = multa_pct
                                        cob.juros = juros_pct
                                        cob.data_recebimento = None
                                    alteracoes += 1

                            registrar_auditoria(
                                session, emp_id, st.session_state["usuario_id"],
                                "COBRANCAS_COMPETENCIA_ATUALIZADA", "CobrancaMensal", None,
                                f"Competência: {mes_sel}; registros: {alteracoes}; "
                                f"novas liquidações: {liquidacoes_novas}; liquidações preservadas: {liquidadas_preservadas}",
                            )
                            session.commit()
                            st.cache_data.clear()
                            st.session_state["cobrancas_editor_version"] += 1
                            st.success("Competência atualizada. Liquidações recebidas foram congeladas no histórico.")
                            st.rerun()
                        except Exception:
                            session.rollback()
                            logger.exception("Falha ao salvar alterações da competência de cobrança")
                            st.error(
                                "Não foi possível salvar as alterações da competência. "
                                "Revise as datas e os valores informados.",
                                icon=None,
                            )
                        finally:
                            session.close()

                with st.expander("Nova cobrança pontual"):
                    pontual_form_version = st.session_state["pontual_form_version"]
                    pontual_form_key = f"{mes_sel}_{pontual_form_version}"
                    contratos_pontuais = {"Sem vínculo contratual": None}
                    if not df_contratos_fin.empty:
                        for _, row in df_contratos_fin.iterrows():
                            label = (
                                f"#{int(row['id'])} · {row['cliente']} · "
                                f"{row['modelo']} {row['placa']}"
                            )
                            contratos_pontuais[label] = int(row["id"])

                    p_vinculo_label = st.selectbox(
                        "Contrato relacionado (opcional)",
                        list(contratos_pontuais.keys()),
                        key=f"pont_vinc_{pontual_form_key}"
                    )
                    p_contrato_id = contratos_pontuais[p_vinculo_label]

                    contrato_pont = None
                    if p_contrato_id is not None and not df_contratos_fin.empty:
                        achou = df_contratos_fin[
                            df_contratos_fin["id"] == p_contrato_id
                        ]
                        if not achou.empty:
                            contrato_pont = achou.iloc[0]

                    pc1, pc2 = st.columns(2)
                    p_cli = pc1.text_input(
                        "Cliente",
                        value=(
                            str(contrato_pont["cliente"])
                            if contrato_pont is not None else ""
                        ),
                        disabled=(contrato_pont is not None),
                        key=f"pont_cliente_{pontual_form_key}_{p_contrato_id or 'manual'}"
                    )
                    p_form = pc2.selectbox(
                        "Forma de cobrança",
                        FORMAS_COBRANCA,
                        key=f"pont_forma_{pontual_form_key}"
                    )

                    ano_p, mes_p = map(int, reversed(mes_sel.split("/")))
                    pc3, pc4, pc5 = st.columns(3)
                    p_val = pc3.number_input(
                        "Valor previsto (R$)",
                        min_value=0.01,
                        step=100.0,
                        key=f"pont_valor_{pontual_form_key}"
                    )
                    p_emis = pc4.date_input(
                        "Emissão prevista",
                        value=get_valid_date(ano_p, mes_p, 1),
                        format="DD/MM/YYYY",
                        key=f"pont_emis_{pontual_form_key}"
                    )
                    p_venc = pc5.date_input(
                        "Vencimento",
                        value=get_valid_date(ano_p, mes_p, 10),
                        format="DD/MM/YYYY",
                        key=f"pont_venc_{pontual_form_key}"
                    )

                    pc6, pc7 = st.columns(2)
                    p_multa = pc6.number_input(
                        "Multa (%)",
                        min_value=0.0,
                        step=0.1,
                        value=2.0,
                        key=f"pont_multa_{pontual_form_key}"
                    )
                    p_juros = pc7.number_input(
                        "Juros (%)",
                        min_value=0.0,
                        step=0.1,
                        value=1.0,
                        key=f"pont_juros_{pontual_form_key}"
                    )
                    p_obs = st.text_area(
                        "Observações / orientações",
                        key=f"pont_obs_{pontual_form_key}"
                    )

                    if st.button(
                        "Adicionar cobrança pontual",
                        icon=":material/add:",
                        use_container_width=True,
                        key=f"btn_pont_{pontual_form_key}"
                    ):
                        if not str(p_cli or "").strip():
                            st.error("Informe o cliente.", icon=None)
                        else:
                            session = SessionLocal()
                            try:
                                cobranca_pontual = CobrancaMensal(
                                    empresa_id=emp_id,
                                    contrato_id=p_contrato_id,
                                    recorrente_id=None,
                                    mes_ano=mes_sel,
                                    tipo="Pontual",
                                    cliente=str(p_cli).strip(),
                                    forma_cobranca=p_form,
                                    valor_previsto=decimal_monetario(p_val),
                                    emissao_prevista=p_emis,
                                    vencimento=p_venc,
                                    status="Pendente de emissão",
                                    multa=float(p_multa),
                                    juros=float(p_juros),
                                    observacoes=p_obs.strip() or None
                                )
                                session.add(cobranca_pontual)
                                session.flush()
                                registrar_auditoria(
                                    session, emp_id, st.session_state["usuario_id"],
                                    "COBRANCA_PONTUAL_CRIADA", "CobrancaMensal", cobranca_pontual.id,
                                    f"Competência: {mes_sel}; valor: {cobranca_pontual.valor_previsto}",
                                )
                                session.commit()
                                st.cache_data.clear()
                                st.session_state["pontual_form_version"] += 1
                                st.session_state["cobrancas_editor_version"] += 1
                                st.success("Cobrança pontual adicionada.")
                                st.rerun()
                            finally:
                                session.close()

                if st.session_state.get("perfil") == "admin":
                    with st.expander("Excluir cobrança pontual — Zona restrita"):
                        df_pont_excluir = carregar_dados_tabela(
                            """
                            SELECT id, cliente, mes_ano, valor_previsto, status, data_recebimento,
                                   liquidacao_congelada, valor_liquidado
                            FROM cobrancas_mensais
                            WHERE empresa_id = :empresa_id
                              AND tipo = 'Pontual'
                              AND mes_ano = :mes_sel
                            ORDER BY id DESC
                            """,
                            emp_id,
                            {"mes_sel": mes_sel},
                        )

                        if df_pont_excluir.empty:
                            st.info("Nenhuma cobrança pontual nesta competência.", icon=None)
                        else:
                            op_pont_excluir = {
                                (
                                    f"#{int(r['id'])} · {r['cliente']} · "
                                    f"{fmt_brl(float(r['valor_liquidado'] if pd.notna(r['valor_liquidado']) else r['valor_previsto'] or 0))} · "
                                    f"{normalizar_status_cobranca(r['status'])}"
                                ): int(r["id"])
                                for _, r in df_pont_excluir.iterrows()
                            }
                            pont_exc_label = st.selectbox(
                                "Cobrança pontual para excluir",
                                list(op_pont_excluir.keys()),
                                key=f"pont_excluir_sel_{mes_sel}",
                            )
                            pont_exc_id = op_pont_excluir[pont_exc_label]
                            row_pont = df_pont_excluir[df_pont_excluir["id"] == pont_exc_id].iloc[0]
                            pont_liquidada = (
                                int(row_pont.get("liquidacao_congelada") or 0) == 1
                                or coerce_date(row_pont.get("data_recebimento")) is not None
                                or normalizar_status_cobranca(row_pont.get("status")) == "Recebida"
                            )

                            if pont_liquidada:
                                st.warning(
                                    (
                                        "Esta cobrança já possui liquidação. Em produção, histórico financeiro recebido não pode ser apagado."
                                        if IS_PRODUCTION_APP
                                        else "Esta cobrança já possui liquidação. Como este ambiente não é produção, ela pode ser removida apenas para limpeza de testes."
                                    ),
                                    icon=None,
                                )

                            confirm_pont = st.text_input(
                                f"Digite EXCLUIR {pont_exc_id} para confirmar",
                                key=f"confirmar_excluir_pont_{pont_exc_id}_{mes_sel}",
                            )
                            if st.button(
                                "Excluir cobrança pontual permanentemente",
                                type="primary",
                                use_container_width=True,
                                key=f"btn_excluir_pont_{pont_exc_id}_{mes_sel}",
                            ):
                                if confirm_pont.strip() != f"EXCLUIR {pont_exc_id}":
                                    st.error("Confirmação inválida.", icon=None)
                                elif IS_PRODUCTION_APP and pont_liquidada:
                                    st.error(
                                        "Cobrança liquidada não pode ser excluída em produção. "
                                        "Use um fluxo de cancelamento/estorno para preservar a rastreabilidade.",
                                        icon=None,
                                    )
                                else:
                                    session = SessionLocal()
                                    try:
                                        cob_db = tenant_get(
                                            session, CobrancaMensal, pont_exc_id, emp_id
                                        )
                                        if cob_db is None or str(cob_db.tipo) != "Pontual":
                                            st.error("Cobrança pontual não encontrada.", icon=None)
                                        else:
                                            snapshot = (
                                                f"Cliente: {cob_db.cliente}; competência: {cob_db.mes_ano}; "
                                                f"valor previsto: {cob_db.valor_previsto}; valor liquidado: {cob_db.valor_liquidado}; "
                                                f"status: {cob_db.status}; ambiente: {APP_ENV}"
                                            )
                                            session.delete(cob_db)
                                            registrar_auditoria(
                                                session, emp_id, st.session_state["usuario_id"],
                                                "COBRANCA_PONTUAL_EXCLUIDA", "CobrancaMensal", pont_exc_id, snapshot,
                                            )
                                            session.commit()
                                            st.cache_data.clear()
                                            st.session_state["cobrancas_editor_version"] += 1
                                            st.success("Cobrança pontual excluída.")
                                            st.rerun()
                                    except Exception:
                                        session.rollback()
                                        logger.exception("Falha ao excluir cobrança pontual")
                                        st.error("Não foi possível excluir a cobrança pontual.", icon=None)
                                    finally:
                                        session.close()

        # ══════════════════════════════════════════════════════════════════════════
        # CONTRATOS E LOCAÇÃO
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Contratos e Locação":
            aplicar_css_modulos_v11()

            df_veiculos = carregar_dados_tabela(f"""
                SELECT id, placa, modelo, status
                FROM veiculos
                WHERE empresa_id = :empresa_id AND COALESCE(ativo, 1)=1
                ORDER BY modelo, placa
            """, emp_id)

            df_contratos = carregar_dados_tabela(f"""
                SELECT
                    c.id,
                    c.veiculo_id,
                    c.cliente,
                    c.cnpj,
                    vp.placa AS placa_principal,
                    vp.modelo AS modelo_principal,
                    vp.status AS status_principal,
                    c.ativo,
                    c.data_inicio,
                    c.data_fim,
                    c.tipo_valor,
                    c.valor_mensal,
                    c.multa,
                    c.juros,
                    c.km_final,
                    c.usuario_lancamento,
                    s.id AS substituicao_id,
                    s.veiculo_substituto_id,
                    vr.placa AS placa_reserva,
                    vr.modelo AS modelo_reserva,
                    s.data_inicio AS inicio_substituicao
                FROM contratos c
                INNER JOIN veiculos vp ON c.veiculo_id = vp.id AND vp.empresa_id = c.empresa_id
                LEFT JOIN substituicoes_contrato s
                    ON s.contrato_id = c.id AND s.empresa_id = c.empresa_id AND s.ativo = 1
                LEFT JOIN veiculos vr
                    ON s.veiculo_substituto_id = vr.id AND vr.empresa_id = s.empresa_id
                WHERE c.empresa_id = :empresa_id
                ORDER BY c.ativo DESC, c.data_inicio DESC
            """, emp_id)

            if not df_contratos.empty:
                contratos_ativos_df = df_contratos[df_contratos["ativo"] == 1].copy()
                contratos_ativos_qtd = len(contratos_ativos_df)
                contratos_encerrados_qtd = int((df_contratos["ativo"] == 0).sum())
                receita_fixa_contratos = float(pd.to_numeric(
                    contratos_ativos_df.loc[
                        contratos_ativos_df["tipo_valor"] == "Fixo", "valor_mensal"
                    ], errors="coerce"
                ).fillna(0.0).sum())
                fim_contratos = pd.to_datetime(
                    contratos_ativos_df["data_fim"], errors="coerce"
                )
                vencendo_contratos = int((
                    fim_contratos.notna()
                    & (fim_contratos >= pd.Timestamp(hoje_local()))
                    & (fim_contratos <= pd.Timestamp(hoje_local() + timedelta(days=30)))
                ).sum())
                reservas_contratos = int(contratos_ativos_df["substituicao_id"].notna().sum())
            else:
                contratos_ativos_qtd = contratos_encerrados_qtd = 0
                vencendo_contratos = reservas_contratos = 0
                receita_fixa_contratos = 0.0

            module_hero(
                "Ciclo comercial",
                "Contratos e Locação",
                "Acompanhe a carteira vigente e acesse abertura, finalização ou substituição apenas quando necessário.",
                "Receita fixa mensal",
                fmt_brl(receita_fixa_contratos),
            )
            ct1, ct2, ct3, ct4 = st.columns(4)
            with ct1:
                module_stat_card("Contratos ativos", contratos_ativos_qtd, "carteira vigente")
            with ct2:
                module_stat_card("Vencendo em 30 dias", vencendo_contratos, "atenção comercial")
            with ct3:
                module_stat_card("Reservas em uso", reservas_contratos, "substituições temporárias")
            with ct4:
                module_stat_card("Encerrados", contratos_encerrados_qtd, "histórico preservado")

            pagina_contratos = st.session_state["pagina_contratos"]

            # ── Aba 1: Visão Geral ────────────────────────────────────────────────
            if pagina_contratos == "Visão de Contratos":
                if not df_contratos.empty:
                    df_exib = df_contratos.rename(columns={
                        "cliente": "Cliente",
                        "cnpj": "CNPJ",
                        "placa_principal": "Veículo Principal",
                        "placa_reserva": "Veículo Reserva",
                        "data_inicio": "Início",
                        "data_fim": "Fim",
                        "tipo_valor": "Tipo",
                        "valor_mensal": "Valor",
                        "multa": "Multa (%)",
                        "juros": "Juros (%)",
                        "usuario_lancamento": "Criado por",
                    }).copy()

                    df_exib["Início"] = pd.to_datetime(df_exib["Início"], errors="coerce").dt.strftime("%d/%m/%Y")
                    df_exib["Fim"] = pd.to_datetime(df_exib["Fim"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("—")
                    df_exib["Veículo Reserva"] = df_exib["Veículo Reserva"].fillna("—")
                    df_exib["Uso Atual"] = df_exib.apply(
                        lambda r: r["Veículo Reserva"] if r["Veículo Reserva"] != "—" else r["Veículo Principal"], axis=1
                    )
                    df_exib["Status"] = df_exib["ativo"].apply(lambda x: "Ativo" if x == 1 else "Baixado")

                    for col in ["Valor", "Multa (%)", "Juros (%)"]:
                        df_exib[col] = pd.to_numeric(df_exib[col], errors="coerce").fillna(0.0)

                    _, h2 = st.columns([4, 1])
                    with h2:
                        csv_ct = convert_df_to_csv(df_exib[[
                            "Cliente", "CNPJ", "Veículo Principal", "Veículo Reserva", "Uso Atual",
                            "Status", "Início", "Fim", "Tipo", "Valor"
                        ]])
                        st.download_button("Exportar Dados", csv_ct, "base_contratos.csv", "text/csv", use_container_width=True)

                    df_ativos = df_exib[df_exib["ativo"] == 1].copy()
                    df_encerrados = df_exib[df_exib["ativo"] == 0].copy()

                    if not df_ativos.empty:
                        st.markdown("**Carteira Vigente**")
                        df_ativos_exib = df_ativos.copy()
                        df_ativos_exib["Valor"] = df_ativos_exib.apply(
                            lambda r: "Variável" if r["Tipo"] == "Variável" else fmt_brl(float(r["Valor"] or 0)),
                            axis=1
                        )
                        df_ativos_exib["Multa (%)"] = df_ativos_exib["Multa (%)"].apply(
                            lambda v: f"{float(v or 0):.2f}%".replace(".", ",")
                        )
                        df_ativos_exib["Juros (%)"] = df_ativos_exib["Juros (%)"].apply(
                            lambda v: f"{float(v or 0):.2f}%".replace(".", ",")
                        )
                        st.dataframe(
                            df_ativos_exib[[
                                "Cliente", "CNPJ", "Veículo Principal", "Veículo Reserva", "Uso Atual",
                                "Status", "Início", "Fim", "Tipo", "Valor", "Multa (%)", "Juros (%)"
                            ]],
                            use_container_width=True,
                            hide_index=True
                        )

                    if not df_encerrados.empty:
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("**Arquivo Morto (Contratos Finalizados)**")
                        df_encerrados_exib = df_encerrados.copy()
                        df_encerrados_exib["Valor"] = df_encerrados_exib.apply(
                            lambda r: "Variável" if r["Tipo"] == "Variável" else fmt_brl(float(r["Valor"] or 0)),
                            axis=1
                        )
                        st.dataframe(
                            df_encerrados_exib[[
                                "Cliente", "CNPJ", "Veículo Principal", "Status", "Início", "Fim", "Tipo", "Valor"
                            ]],
                            use_container_width=True,
                            hide_index=True
                        )
                else:
                    st.info("Plataforma sem contratos firmados.", icon=None)

            # ── Aba 2: Novo Contrato ──────────────────────────────────────────────
            elif pagina_contratos == "Novo Contrato":
                contrato_form_version = st.session_state["contrato_form_version"]
                disponiveis_novo = df_veiculos[df_veiculos["status"] == "Disponível"].copy()
                if disponiveis_novo.empty:
                    st.warning("Não há veículo disponível para abertura de novo contrato.", icon=None)
                else:
                    with st.container(border=True):
                        opcoes_v = {f"{r['modelo']} ({r['placa']})": int(r['id']) for _, r in disponiveis_novo.iterrows()}
                        veiculo_sel = st.selectbox("Ativo a ser alocado", list(opcoes_v.keys()), key=f"nc_v_{contrato_form_version}")

                        ca, cb = st.columns(2)
                        cliente = ca.text_input("Locatário (Razão Social)", key=f"nc_cliente_{contrato_form_version}")
                        cnpj = cb.text_input("Documento (CNPJ/CPF)", key=f"nc_cnpj_{contrato_form_version}")
                        cc, cd = st.columns(2)
                        d_inicio = cc.date_input("Início da Vigência", format="DD/MM/YYYY", key=f"nc_inicio_{contrato_form_version}")
                        km_ini = cd.number_input("Odômetro de Saída", min_value=0.0, step=50.0, value=0.0, key=f"nc_km_ini_{contrato_form_version}")

                        st.markdown("---")
                        st.markdown("**Acordo Comercial**")
                        ce, cf = st.columns(2)
                        tipo_v = ce.selectbox("Formato de Receita", ["Fixo", "Variável"], key=f"nc_tipo_{contrato_form_version}")
                        valor_m = 0.0
                        comp_var_novo = None
                        valor_comp_var_novo = 0.0
                        valor_comp_var_novo_txt = ""

                        if tipo_v == "Fixo":
                            valor_m_txt = cf.text_input(
                                "Mensalidade (R$)",
                                value="",
                                placeholder="Ex.: 52.800,00",
                                key=f"nc_valor_{contrato_form_version}"
                            )
                            valor_m = parse_valor_cobranca(valor_m_txt)
                        else:
                            cf.info("Receita variável: não existe mensalidade fixa no contrato.")
                            cv1, cv2 = st.columns(2)
                            competencias_var = opcoes_competencias(12, 18)
                            comp_padrao = hoje_local().strftime("%m/%Y")
                            idx_comp = competencias_var.index(comp_padrao) if comp_padrao in competencias_var else 12
                            comp_var_novo = cv1.selectbox(
                                "Mês de referência",
                                competencias_var,
                                index=idx_comp,
                                key=f"nc_comp_var_{contrato_form_version}"
                            )
                            valor_comp_var_novo_txt = cv2.text_input(
                                "Valor previsto da competência (R$)",
                                value="",
                                placeholder="Ex.: 52.800,00",
                                key=f"nc_valor_comp_var_{contrato_form_version}"
                            )
                            valor_comp_var_novo = parse_valor_cobranca(valor_comp_var_novo_txt)
                            st.caption(
                                "Esse valor será registrado no Controle Mensal da competência selecionada. "
                                "Se ainda não houver regra de cobrança recorrente, ela poderá ser completada depois."
                            )
                        cg, ch = st.columns(2)
                        multa_c = cg.number_input("Cláusula de Atraso - Multa (%)", min_value=0.0, step=1.0, value=2.0, key=f"nc_multa_{contrato_form_version}")
                        juros_c = ch.number_input("Cláusula de Atraso - Juros/Mês (%)", min_value=0.0, step=0.1, value=1.0, key=f"nc_juros_{contrato_form_version}")

                        if st.button("Efetivar Alocação", use_container_width=True, key=f"btn_novo_contrato_{contrato_form_version}"):
                            if not cliente.strip():
                                st.error("Identificação do Locatário obrigatória.", icon=None)
                            else:
                                session = SessionLocal()
                                try:
                                    veiculo = tenant_get(session, Veiculo, opcoes_v[veiculo_sel], emp_id)
                                    if veiculo is None or veiculo.status != "Disponível":
                                        raise ValueError("O veículo selecionado não está mais disponível.")

                                    contrato = Contrato(
                                        empresa_id=emp_id, veiculo_id=veiculo.id, cliente=cliente.strip(), cnpj=cnpj.strip(),
                                        data_inicio=d_inicio, data_fim=None, km_inicial=km_ini, km_final=0.0, ativo=1,
                                        usuario_lancamento=st.session_state["nome"], tipo_valor=tipo_v,
                                        valor_mensal=decimal_monetario(valor_m) if tipo_v == "Fixo" else Decimal("0.00"), multa=multa_c, juros=juros_c
                                    )
                                    session.add(contrato)
                                    session.flush()
                                    if tipo_v == "Variável" and valor_comp_var_novo_txt.strip():
                                        salvar_valor_variavel_competencia(
                                            session, emp_id, contrato, comp_var_novo, valor_comp_var_novo
                                        )
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "VALOR_VARIAVEL_COMPETENCIA", "Contrato", contrato.id,
                                            f"Competência {comp_var_novo}; valor {valor_comp_var_novo:.2f}"
                                        )
                                    veiculo.status = "Alugado"
                                    session.commit()
                                    st.cache_data.clear()
                                    st.session_state["contrato_form_version"] += 1
                                    st.success("Contrato consolidado na base!")
                                    time.sleep(0.7)
                                    st.rerun()
                                except ValueError as e:
                                    session.rollback()
                                    st.error(str(e), icon=None)
                                except Exception:
                                    session.rollback()
                                    logger.exception("Falha em operação de contrato")
                                    st.error("Não foi possível concluir a operação.", icon=None)
                                finally:
                                    session.close()

            # ── Aba 3: Editar / Encerrar Contrato ─────────────────────────────────
            elif pagina_contratos == "Gestão de Contratos":
                if df_contratos.empty:
                    st.info("O módulo não localizou contratos para manutenção.", icon=None)
                else:
                    with st.container(border=True):
                        opcoes_ct = {
                            f"{r['cliente']} · {r['placa_principal']} ({'Vigente' if r['ativo'] == 1 else 'Baixado'})": int(r['id'])
                            for _, r in df_contratos.iterrows()
                        }
                        ct_sel = st.selectbox("Contrato", list(opcoes_ct.keys()), key="ec_contrato")
                        ct_id = opcoes_ct[ct_sel]
                        row_ct = df_contratos[df_contratos["id"] == ct_id].iloc[0]

                        ea, eb = st.columns(2)
                        e_cliente = ea.text_input("Locatário", value=str(row_ct["cliente"] or ""), key="ec_cli")
                        e_cnpj = eb.text_input("Documento", value=str(row_ct["cnpj"] or ""), key="ec_cnpj")
                        ec, ed = st.columns(2)
                        e_dinicio = ec.date_input("Início da Vigência", value=pd.to_datetime(row_ct["data_inicio"]).date(), key="ec_di")
                        e_ativo = ed.checkbox("Manter Status Vigente", value=(row_ct["ativo"] == 1), key="ec_ativo")

                        e_dfim = None
                        e_kmfim = float(row_ct["km_final"] or 0)
                        if not e_ativo:
                            ee, ef = st.columns(2)
                            dt_fim = pd.to_datetime(row_ct["data_fim"], errors="coerce")
                            e_dfim = ee.date_input("Baixa do Contrato", value=hoje_local() if pd.isna(dt_fim) else dt_fim.date(), key="ec_df")
                            e_kmfim = ef.number_input("Odômetro de Chegada", min_value=0.0, step=50.0, value=e_kmfim, key="ec_kmf")
                            st.info(
                                "Ao encerrar o contrato, o Kineo desativa a cobrança recorrente e cancela "
                                "automaticamente as competências futuras ainda não recebidas. O histórico "
                                "anterior e os valores originais são preservados.",
                                icon=":material/info:",
                            )

                        st.markdown("---")
                        eg, eh = st.columns(2)
                        e_tipo = eg.selectbox("Formato de Receita", ["Fixo", "Variável"], index=0 if row_ct["tipo_valor"] == "Fixo" else 1, key="ec_t")
                        e_val = 0.0
                        e_comp_var = None
                        e_val_comp_var = 0.0
                        e_val_comp_var_txt = ""

                        if e_tipo == "Fixo":
                            e_val_txt = eh.text_input(
                                "Mensalidade (R$)",
                                value=fmt_brl(float(row_ct["valor_mensal"] or 0)).replace("R$ ", ""),
                                placeholder="Ex.: 52.800,00",
                                key="ec_v"
                            )
                            e_val = parse_valor_cobranca(e_val_txt)
                        else:
                            eh.info("Receita variável: o valor é controlado por competência.")
                            ev1, ev2 = st.columns(2)
                            competencias_var = opcoes_competencias(12, 18)
                            comp_padrao = hoje_local().strftime("%m/%Y")
                            idx_comp = competencias_var.index(comp_padrao) if comp_padrao in competencias_var else 12
                            e_comp_var = ev1.selectbox(
                                "Mês de referência do pagamento",
                                competencias_var,
                                index=idx_comp,
                                key=f"ec_comp_var_{ct_id}"
                            )

                            session_comp = SessionLocal()
                            try:
                                mensal_existente = session_comp.query(CobrancaMensal).filter(
                                    CobrancaMensal.empresa_id == emp_id,
                                    CobrancaMensal.contrato_id == ct_id,
                                    CobrancaMensal.mes_ano == e_comp_var,
                                    CobrancaMensal.tipo == "Recorrente"
                                ).order_by(CobrancaMensal.id.desc()).first()
                                valor_existente_comp = float(mensal_existente.valor_previsto or 0) if mensal_existente else 0.0
                            finally:
                                session_comp.close()

                            e_val_comp_var_txt = ev2.text_input(
                                "Valor previsto da competência (R$)",
                                value=(fmt_brl(valor_existente_comp).replace("R$ ", "") if valor_existente_comp else ""),
                                placeholder="Ex.: 52.800,00",
                                key=f"ec_val_comp_var_{ct_id}_{e_comp_var}"
                            )
                            e_val_comp_var = parse_valor_cobranca(e_val_comp_var_txt)
                            if valor_existente_comp:
                                st.caption(
                                    f"Já existe valor para {e_comp_var}: {fmt_brl(valor_existente_comp)}. "
                                    "Ao salvar, ele será atualizado."
                                )
                            else:
                                st.caption(
                                    "O valor será gravado somente nesta competência e ficará disponível "
                                    "em Gestão de Cobranças → Controle Mensal."
                                )
                        ei, ej = st.columns(2)
                        e_multa = ei.number_input("Cláusula de Multa (%)", min_value=0.0, step=1.0, value=float(row_ct["multa"] or 0), key="ec_m")
                        e_juros = ej.number_input("Cláusula de Juros (%)", min_value=0.0, step=0.1, value=float(row_ct["juros"] or 0), key="ec_j")

                        b1, b2 = st.columns(2)
                        label_salvar_contrato = (
                            "Salvar contrato e competência" if e_tipo == "Variável"
                            else "Assinar Aditivo (Salvar)"
                        )
                        if b1.button(label_salvar_contrato, use_container_width=True, key="btn_salvar_contrato"):
                            session = SessionLocal()
                            try:
                                contrato = tenant_get(session, Contrato, ct_id, emp_id)
                                if contrato is None:
                                    raise ValueError("Contrato não encontrado.")

                                contrato.cliente = e_cliente.strip()
                                contrato.cnpj = e_cnpj.strip()
                                contrato.data_inicio = e_dinicio
                                contrato.tipo_valor = e_tipo
                                contrato.valor_mensal = decimal_monetario(e_val) if e_tipo == "Fixo" else Decimal("0.00")
                                contrato.multa = e_multa
                                contrato.juros = e_juros

                                if e_tipo == "Variável" and e_val_comp_var_txt.strip():
                                    salvar_valor_variavel_competencia(
                                        session, emp_id, contrato, e_comp_var, e_val_comp_var
                                    )
                                    registrar_auditoria(
                                        session, emp_id, st.session_state["usuario_id"],
                                        "VALOR_VARIAVEL_COMPETENCIA", "Contrato", contrato.id,
                                        f"Competência {e_comp_var}; valor {e_val_comp_var:.2f}"
                                    )

                                principal = tenant_get(session, Veiculo, contrato.veiculo_id, emp_id)
                                sub = session.query(SubstituicaoContrato).filter(
                                    SubstituicaoContrato.empresa_id == emp_id,
                                    SubstituicaoContrato.contrato_id == contrato.id,
                                    SubstituicaoContrato.ativo == 1
                                ).first()

                                if e_ativo:
                                    contrato.ativo = 1
                                    contrato.data_fim = None
                                    if principal is not None and sub is None:
                                        principal.status = "Alugado"
                                else:
                                    contrato.ativo = 0
                                    contrato.data_fim = e_dfim
                                    contrato.km_final = e_kmfim or 0.0
                                    resultado_cobrancas = encerrar_cobrancas_contrato(
                                        session, emp_id, contrato.id, e_dfim
                                    )
                                    registrar_auditoria(
                                        session, emp_id, st.session_state["usuario_id"],
                                        "CONTRATO_ENCERRADO", "Contrato", contrato.id,
                                        (
                                            f"Encerrado em {e_dfim.strftime('%d/%m/%Y')}; "
                                            f"recorrências desativadas: {resultado_cobrancas['recorrencias_desativadas']}; "
                                            f"cobranças futuras canceladas: {resultado_cobrancas['cobrancas_canceladas']}"
                                        ),
                                    )
                                    if sub is not None:
                                        finalizar_substituicao_contrato(session, sub, status_principal="Disponível")
                                    elif principal is not None:
                                        principal.status = "Disponível"

                                session.commit()
                                st.cache_data.clear()
                                if e_ativo:
                                    st.success("Base atualizada com sucesso!")
                                else:
                                    st.success(
                                        "Contrato encerrado. Cobranças futuras foram interrompidas sem apagar o histórico."
                                    )
                                time.sleep(0.7)
                                st.rerun()
                            except ValueError as e:
                                session.rollback()
                                st.error(str(e), icon=None)
                            except Exception:
                                session.rollback()
                                logger.exception("Falha em operação de frota/contrato")
                                st.error("Não foi possível concluir a operação.", icon=None)
                            finally:
                                session.close()

                        if st.session_state["perfil"] == "admin":
                            if b2.button(
                                "Excluir permanentemente",
                                use_container_width=True,
                                key="btn_excluir_contrato",
                                help="Disponível apenas para contratos sem histórico financeiro ou operacional.",
                            ):
                                session = SessionLocal()
                                try:
                                    contrato = tenant_get(session, Contrato, ct_id, emp_id)
                                    if contrato is None:
                                        raise ValueError("Contrato não encontrado.")

                                    pode_excluir, historico = contrato_pode_ser_excluido(
                                        session, emp_id, contrato.id
                                    )
                                    if not pode_excluir:
                                        st.error(
                                            "Este contrato possui histórico e não pode ser excluído permanentemente. "
                                            "Desmarque ‘Manter Status Vigente’, informe a data de baixa e salve para "
                                            "encerrá-lo preservando cobranças, custos e rastreabilidade.",
                                            icon=None,
                                        )
                                        st.caption(
                                            f"Histórico encontrado: {historico['cobrancas']} cobrança(s), "
                                            f"{historico['custos']} custo(s) e "
                                            f"{historico['substituicoes']} substituição(ões)."
                                        )
                                    else:
                                        principal = tenant_get(session, Veiculo, contrato.veiculo_id, emp_id)
                                        if principal is not None:
                                            principal.status = "Disponível"

                                        # Regras recorrentes são apenas configuração quando nunca houve
                                        # movimentação. Podem ser removidas junto com um contrato criado por engano.
                                        session.query(CobrancaRecorrente).filter(
                                            CobrancaRecorrente.empresa_id == emp_id,
                                            CobrancaRecorrente.contrato_id == contrato.id,
                                        ).delete(synchronize_session=False)

                                        contrato_id_excluido = contrato.id
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "CONTRATO_EXCLUIDO", "Contrato", contrato_id_excluido,
                                            "Exclusão permanente autorizada por ausência de histórico financeiro/operacional.",
                                        )
                                        session.delete(contrato)
                                        session.commit()
                                        st.cache_data.clear()
                                        st.success("Contrato sem histórico excluído permanentemente.")
                                        time.sleep(0.7)
                                        st.rerun()
                                except ValueError as e:
                                    session.rollback()
                                    st.error(str(e), icon=None)
                                except Exception:
                                    session.rollback()
                                    logger.exception("Falha em operação de contrato")
                                    st.error("Não foi possível concluir a operação.", icon=None)
                                finally:
                                    session.close()

            # ── Aba 4: Substituição / Manutenção ──────────────────────────────────
            elif pagina_contratos == "Substituições":
                contratos_ativos = df_contratos[df_contratos["ativo"] == 1].copy()
                if contratos_ativos.empty:
                    st.info("Não há contratos vigentes para substituição.", icon=None)
                else:
                    with st.container(border=True):
                        opcoes_sub_ct = {
                            f"{r['cliente']} · {r['modelo_principal']} ({r['placa_principal']})": int(r['id'])
                            for _, r in contratos_ativos.iterrows()
                        }
                        sub_ct_label = st.selectbox("Contrato vigente", list(opcoes_sub_ct.keys()), key="sub_ct_sel")
                        sub_ct_id = opcoes_sub_ct[sub_ct_label]
                        sub_row = contratos_ativos[contratos_ativos["id"] == sub_ct_id].iloc[0]

                        st.markdown(f"**Veículo principal:** {sub_row['modelo_principal']} ({sub_row['placa_principal']})")

                        if pd.notna(sub_row["substituicao_id"]):
                            st.warning(f"Substituição ativa: {sub_row['modelo_reserva']} ({sub_row['placa_reserva']}) está atendendo o cliente durante a manutenção.", icon=None)
                            if st.button("Retornar veículo principal ao contrato", use_container_width=True, key="btn_retorno_principal"):
                                session = SessionLocal()
                                try:
                                    sub = tenant_get(session, SubstituicaoContrato, int(sub_row["substituicao_id"]), emp_id)
                                    if sub is None or sub.ativo != 1:
                                        raise ValueError("A substituição já foi encerrada.")
                                    finalizar_substituicao_contrato(session, sub, status_principal="Alugado")
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Veículo principal retornou ao contrato e o reserva foi liberado.")
                                    time.sleep(0.7)
                                    st.rerun()
                                except ValueError as e:
                                    session.rollback()
                                    st.error(str(e), icon=None)
                                except Exception:
                                    session.rollback()
                                    logger.exception("Falha em operação de contrato")
                                    st.error("Não foi possível concluir a operação.", icon=None)
                                finally:
                                    session.close()
                        else:
                            disponiveis_sub = df_veiculos[
                                (df_veiculos["status"] == "Disponível") &
                                (df_veiculos["id"] != int(sub_row["veiculo_id"]))
                            ].copy()
                            if disponiveis_sub.empty:
                                st.warning("Não há veículo disponível para atuar como reserva.", icon=None)
                            else:
                                opcoes_reserva_ct = {
                                    f"{r['modelo']} ({r['placa']})": int(r['id'])
                                    for _, r in disponiveis_sub.iterrows()
                                }
                                reserva_ct_label = st.selectbox("Veículo reserva", list(opcoes_reserva_ct.keys()), key="sub_reserva_ct")
                                if st.button("Enviar principal para manutenção e ativar reserva", use_container_width=True, key="btn_iniciar_sub"):
                                    session = SessionLocal()
                                    try:
                                        contrato = tenant_get(session, Contrato, sub_ct_id, emp_id)
                                        principal = tenant_get(session, Veiculo, contrato.veiculo_id, emp_id) if contrato else None
                                        reserva = tenant_get(session, Veiculo, opcoes_reserva_ct[reserva_ct_label], emp_id)
                                        if contrato is None or principal is None or reserva is None:
                                            raise ValueError("Não foi possível carregar os dados da substituição.")
                                        iniciar_substituicao_contrato(
                                            session, emp_id, contrato, principal, reserva, st.session_state["nome"]
                                        )
                                        session.commit()
                                        st.cache_data.clear()
                                        st.success("Substituição ativada. O principal foi enviado para manutenção e o reserva assumiu o atendimento.")
                                        time.sleep(0.7)
                                        st.rerun()
                                    except ValueError as e:
                                        session.rollback()
                                        st.error(str(e), icon=None)
                                    except Exception:
                                        session.rollback()
                                        logger.exception("Falha em substituição de veículo")
                                        st.error("Não foi possível concluir a substituição.", icon=None)
                                    finally:
                                        session.close()

                        st.markdown("---")
                        historico = carregar_dados_tabela(f"""
                            SELECT
                                s.data_inicio, s.data_fim, s.ativo,
                                vp.placa AS principal, vr.placa AS reserva,
                                c.cliente, s.usuario_lancamento
                            FROM substituicoes_contrato s
                            INNER JOIN contratos c ON c.id = s.contrato_id AND c.empresa_id = s.empresa_id
                            INNER JOIN veiculos vp ON vp.id = s.veiculo_principal_id AND vp.empresa_id = s.empresa_id
                            INNER JOIN veiculos vr ON vr.id = s.veiculo_substituto_id AND vr.empresa_id = s.empresa_id
                            WHERE s.empresa_id = :empresa_id
                            ORDER BY s.data_inicio DESC, s.id DESC
                        """, emp_id)
                        if not historico.empty:
                            historico["data_inicio"] = pd.to_datetime(historico["data_inicio"], errors="coerce").dt.strftime("%d/%m/%Y")
                            historico["data_fim"] = pd.to_datetime(historico["data_fim"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("—")
                            historico["status"] = historico["ativo"].apply(lambda x: "Em andamento" if x == 1 else "Encerrada")
                            st.markdown("**Histórico de substituições**")
                            st.dataframe(
                                historico[["cliente", "principal", "reserva", "data_inicio", "data_fim", "status", "usuario_lancamento"]].rename(columns={
                                    "cliente": "Cliente", "principal": "Principal", "reserva": "Reserva",
                                    "data_inicio": "Início", "data_fim": "Fim", "status": "Status",
                                    "usuario_lancamento": "Responsável"
                                }),
                                use_container_width=True, hide_index=True
                            )

        # MEU PERFIL
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Pessoas e Acessos":
            is_admin = st.session_state.get("perfil") == "admin"
            aplicar_css_modulos_v11()

            df_pessoas_resumo = carregar_dados_tabela("""
                SELECT COUNT(id) AS total,
                       SUM(CASE WHEN COALESCE(ativo,1)=1 THEN 1 ELSE 0 END) AS ativos
                FROM motoristas
                WHERE empresa_id=:empresa_id
            """, emp_id)
            motoristas_total = int(pd.to_numeric(
                df_pessoas_resumo["total"], errors="coerce"
            ).fillna(0).iloc[0])
            motoristas_ativos = int(pd.to_numeric(
                df_pessoas_resumo["ativos"], errors="coerce"
            ).fillna(0).iloc[0])
            motoristas_inativos = max(motoristas_total - motoristas_ativos, 0)

            usuarios_total = usuarios_ativos = 0
            if is_admin:
                df_usuarios_resumo = carregar_dados_tabela("""
                    SELECT COUNT(id) AS total,
                           SUM(CASE WHEN COALESCE(ativo,1)=1 THEN 1 ELSE 0 END) AS ativos
                    FROM usuarios
                    WHERE empresa_id=:empresa_id
                """, emp_id)
                usuarios_total = int(pd.to_numeric(
                    df_usuarios_resumo["total"], errors="coerce"
                ).fillna(0).iloc[0])
                usuarios_ativos = int(pd.to_numeric(
                    df_usuarios_resumo["ativos"], errors="coerce"
                ).fillna(0).iloc[0])

            module_hero(
                "Equipe e segurança",
                "Pessoas e Acessos",
                (
                    "Visualize a equipe antes de acessar cadastros, credenciais e rotinas administrativas."
                    if is_admin else
                    "Visualize e mantenha os motoristas utilizados nas rotinas operacionais."
                ),
                "Pessoas cadastradas",
                motoristas_total + usuarios_total,
            )

            if is_admin:
                ps1, ps2, ps3, ps4 = st.columns(4)
                with ps1:
                    module_stat_card("Motoristas ativos", motoristas_ativos, "disponíveis nas rotinas")
                with ps2:
                    module_stat_card("Motoristas inativos", motoristas_inativos, "histórico preservado")
                with ps3:
                    module_stat_card("Usuários ativos", usuarios_ativos, "acessos liberados")
                with ps4:
                    module_stat_card("Credenciais", usuarios_total, "total de usuários")
            else:
                ps1, ps2, ps3 = st.columns(3)
                with ps1:
                    module_stat_card("Motoristas", motoristas_total, "cadastros da empresa")
                with ps2:
                    module_stat_card("Ativos", motoristas_ativos, "disponíveis nas rotinas")
                with ps3:
                    module_stat_card("Inativos", motoristas_inativos, "histórico preservado")

            if is_admin:
                pagina_pessoas = st.session_state["pagina_pessoas"]

                if pagina_pessoas == "Motoristas":
                    render_gestao_motoristas(emp_id)

                elif pagina_pessoas == "Usuários do Sistema":
                    render_gestao_usuarios(emp_id)
            else:
                # Operadores podem manter o cadastro operacional de motoristas,
                # mas não enxergam nem manipulam credenciais do sistema.
                render_gestao_motoristas(emp_id)


        elif tela_ativa == "Meu Perfil":
            aplicar_css_modulos_v11()
            df_perfil_atual = carregar_dados_tabela("""
                SELECT nome, login, email, perfil, ativo, ultimo_login
                FROM usuarios
                WHERE empresa_id=:empresa_id AND id=:usuario_id
            """, emp_id, {"usuario_id": int(st.session_state["usuario_id"])})
            perfil_atual = (
                df_perfil_atual.iloc[0].to_dict()
                if not df_perfil_atual.empty else {}
            )
            perfil_nome_raw = perfil_atual.get("nome")
            perfil_login_raw = perfil_atual.get("login")
            perfil_email_raw = perfil_atual.get("email")
            perfil_tipo_raw = perfil_atual.get("perfil")
            perfil_nome = str(
                st.session_state.get("nome") or "Usuário"
                if pd.isna(perfil_nome_raw) or not str(perfil_nome_raw or "").strip()
                else perfil_nome_raw
            )
            perfil_login = str(
                st.session_state.get("login") or "—"
                if pd.isna(perfil_login_raw) or not str(perfil_login_raw or "").strip()
                else perfil_login_raw
            )
            perfil_email = str(
                st.session_state.get("email") or "Não informado"
                if pd.isna(perfil_email_raw) or not str(perfil_email_raw or "").strip()
                else perfil_email_raw
            )
            perfil_tipo = str(
                st.session_state.get("perfil") or "operador"
                if pd.isna(perfil_tipo_raw) or not str(perfil_tipo_raw or "").strip()
                else perfil_tipo_raw
            ).title()
            perfil_ativo_num = pd.to_numeric(
                pd.Series([perfil_atual.get("ativo")]), errors="coerce"
            ).fillna(0).iloc[0]
            perfil_ativo = "Ativo" if int(perfil_ativo_num) == 1 else "Revogado"
            ultimo_acesso_perfil = (
                formatar_serie_datetime_local(
                    df_perfil_atual["ultimo_login"], "%d/%m/%Y %H:%M"
                ).iloc[0]
                if not df_perfil_atual.empty else "—"
            )
            avatar_perfil_bytes = ler_bytes_privado(avatar_path)
            if avatar_perfil_bytes:
                avatar_perfil_html = (
                    '<img src="data:image/png;base64,'
                    + base64.b64encode(avatar_perfil_bytes).decode()
                    + '">'
                )
            else:
                avatar_perfil_html = html.escape(perfil_nome[:1].upper() or "U")

            module_hero(
                "Conta pessoal",
                "Meu Perfil",
                "Consulte sua identidade no Kineo e acesse edição ou segurança somente quando necessário.",
                "Perfil de acesso",
                perfil_tipo,
            )

            tab_perfil_visao, tab_perfil_dados, tab_perfil_seguranca = st.tabs([
                "Visão geral",
                "Editar perfil",
                "Segurança da conta",
            ])

            with tab_perfil_visao:
                perfil_card_col, perfil_info_col = st.columns([1.15, 1])
                with perfil_card_col:
                    st.markdown(
                        f"""
                        <div class="kineo-account-card">
                            <div class="kineo-account-avatar">{avatar_perfil_html}</div>
                            <div>
                                <h2>{html.escape(perfil_nome)}</h2>
                                <p>{html.escape(perfil_email)}</p>
                                <span class="kineo-account-role">{html.escape(perfil_tipo)}</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with perfil_info_col:
                    with st.container(border=True):
                        st.markdown("**Informações da conta**")
                        st.markdown(
                            f"""
                            <div class="kineo-info-row"><span>Usuário</span><strong>{html.escape(perfil_login)}</strong></div>
                            <div class="kineo-info-row"><span>Status</span><strong>{html.escape(perfil_ativo)}</strong></div>
                            <div class="kineo-info-row"><span>Último acesso</span><strong>{html.escape(str(ultimo_acesso_perfil))}</strong></div>
                            """,
                            unsafe_allow_html=True,
                        )

            with tab_perfil_dados:
                with st.container(border=True):
                    c_p1, c_p2 = st.columns([1, 2.4])
                    with c_p1:
                        st.markdown("**Foto de perfil**")
                        if avatar_perfil_bytes:
                            st.image(avatar_perfil_bytes, use_container_width=True)
                        else:
                            st.info("Sem foto", icon=None)
                        novo_avatar = st.file_uploader(
                            "Alterar foto",
                            type=["png", "jpg", "jpeg"],
                            label_visibility="collapsed",
                            key="perfil_avatar_upload",
                        )
                        if st.button("Salvar imagem", use_container_width=True, key="perfil_salvar_avatar"):
                            if novo_avatar:
                                ok, erro, _avatar_ref = salvar_imagem_segura(
                                    novo_avatar, f"logos/avatars/avatar_{st.session_state['usuario_id']}.png", max_mb=5
                                )
                                if ok:
                                    session = SessionLocal()
                                    try:
                                        registrar_auditoria(
                                            session, emp_id, st.session_state["usuario_id"],
                                            "AVATAR_ATUALIZADO", "Usuario", st.session_state["usuario_id"],
                                        )
                                        session.commit()
                                    finally:
                                        session.close()
                                    st.success("Foto atualizada!")
                                    time.sleep(0.4)
                                    st.rerun()
                                else:
                                    st.error(erro, icon=None)
                            else:
                                st.error("Nenhuma imagem selecionada.", icon=None)

                    with c_p2:
                        st.markdown("**Nome de apresentação**")
                        st.caption("Este nome é exibido na navegação e nos registros operacionais.")
                        with st.form("form_meu_nome"):
                            novo_nome = st.text_input(
                                "Nome de exibição",
                                value=st.session_state["nome"],
                                max_chars=120,
                            )
                            if st.form_submit_button("Atualizar nome"):
                                novo_nome_limpo = str(novo_nome or "").strip()
                                if len(novo_nome_limpo) < 2:
                                    st.error("Informe um nome válido.", icon=None)
                                else:
                                    session = SessionLocal()
                                    try:
                                        u = tenant_get(session, Usuario, st.session_state["usuario_id"], emp_id)
                                        if u is None:
                                            st.error("Usuário não encontrado.", icon=None)
                                        else:
                                            u.nome = novo_nome_limpo
                                            registrar_auditoria(session, emp_id, u.id, "PERFIL_NOME_ATUALIZADO", "Usuario", u.id)
                                            session.commit()
                                            st.session_state["nome"] = novo_nome_limpo
                                            st.success("Nome atualizado!")
                                            time.sleep(0.4)
                                            st.rerun()
                                    except Exception:
                                        session.rollback()
                                        st.error("Não foi possível atualizar o nome.", icon=None)
                                    finally:
                                        session.close()

            with tab_perfil_seguranca:
                with st.container(border=True):
                    st.markdown("### Alterar senha")
                    st.caption(
                        f"Use uma frase-senha de {PASSWORD_MIN_LENGTH} a {PASSWORD_MAX_LENGTH} caracteres."
                    )
                    with st.form("form_minha_senha"):
                        senha_atual = st.text_input("Senha atual", type="password", max_chars=PASSWORD_MAX_LENGTH)
                        ns1 = st.text_input(
                            "Nova senha", type="password", max_chars=PASSWORD_MAX_LENGTH,
                            placeholder=f"Mínimo {PASSWORD_MIN_LENGTH} caracteres",
                        )
                        ns2 = st.text_input("Confirmar nova senha", type="password", max_chars=PASSWORD_MAX_LENGTH)
                        if st.form_submit_button("Atualizar senha"):
                            erros_senha = validar_nova_senha(
                                ns1, st.session_state.get("login", ""), st.session_state.get("nome", "")
                            )
                            if ns1 != ns2:
                                erros_senha.append("As novas senhas não coincidem.")
                            session = SessionLocal()
                            try:
                                u = tenant_get(session, Usuario, st.session_state["usuario_id"], emp_id)
                                if u is None or int(u.ativo or 0) != 1:
                                    st.error("Usuário não encontrado ou acesso revogado.", icon=None)
                                elif not verify_password(senha_atual, u.senha):
                                    st.error("A senha atual não confere.", icon=None)
                                elif verify_password(ns1, u.senha):
                                    st.error("A nova senha deve ser diferente da senha atual.", icon=None)
                                elif erros_senha:
                                    st.error("Não foi possível aceitar a senha: " + " ".join(erros_senha), icon=None)
                                else:
                                    u.senha = hash_password(ns1)
                                    u.must_change_password = 0
                                    u.senha_alterada_em = agora_utc()
                                    u.tentativas_login = 0
                                    u.bloqueado_ate = None
                                    registrar_auditoria(
                                        session, emp_id, u.id, "SENHA_ALTERADA", "Usuario", u.id,
                                        "Alteração pelo Meu Perfil",
                                    )
                                    session.commit()
                                    st.success("Senha alterada com sucesso.")
                            except Exception:
                                session.rollback()
                                st.error("Não foi possível alterar a senha.", icon=None)
                            finally:
                                session.close()

        # ══════════════════════════════════════════════════════════════════════════
        # POLÍTICA DE PRIVACIDADE E COOKIES
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Política de Privacidade":
            page_header(
                "Política de Privacidade",
                "Transparência sobre o tratamento de dados no ambiente Kineo."
            )

            st.caption(f"Última atualização: 1 de setembro de 2026 · Versão {PRIVACY_VERSION}")

            with st.container(border=True):
                st.markdown("### 1. Escopo")
                st.markdown(
                    "Esta política descreve como o **Kineo | Gestão de Frotas** trata "
                    "informações necessárias à administração corporativa de veículos, "
                    "contratos, custos, cobranças e usuários autorizados."
                )

                st.markdown("### 2. Dados tratados")
                st.markdown(
                    "Podem ser tratados dados de identificação e acesso de colaboradores; "
                    "dados cadastrais de motoristas necessários à operação, como matrícula, contato, "
                    "CNH e, quando houver necessidade operacional, CPF; informações cadastrais de empresas "
                    "e clientes; dados de veículos, quilometragem e manutenção; contratos e informações "
                    "financeiras operacionais; além de arquivos "
                    "enviados ao sistema, como comprovantes e documentos relacionados à operação."
                )

                st.markdown("### 3. Finalidades")
                st.markdown(
                    "Os dados são utilizados para autenticação e controle de acesso, gestão da frota, "
                    "acompanhamento de contratos e substituições de veículos, registro de custos, "
                    "cobranças, relatórios gerenciais, segurança do ambiente e manutenção de registros "
                    "necessários à operação da organização."
                )

                st.markdown("### 4. Bases legais e responsabilidades")
                st.markdown(
                    "O tratamento deve observar a **Lei Geral de Proteção de Dados (LGPD)** e outras "
                    "normas aplicáveis. Conforme o contexto, a organização responsável pelo ambiente "
                    "poderá tratar dados para execução de contratos, cumprimento de obrigações legais "
                    "ou regulatórias, exercício regular de direitos e legítimos interesses, quando "
                    "cabíveis. A definição da base legal aplicável a cada operação cabe à organização "
                    "responsável pelo uso do ambiente."
                )

                st.markdown("### 5. Sessão, cookies e preferências")
                st.markdown(
                    "O Kineo utiliza recursos técnicos necessários para manter a sessão autenticada, "
                    "proteger o acesso e preservar preferências de interface durante a utilização. "
                    "O aplicativo não implementa cookies próprios para publicidade comportamental. "
                    "Serviços de infraestrutura utilizados para hospedar a aplicação podem adotar "
                    "mecanismos técnicos próprios necessários ao funcionamento e à segurança da plataforma."
                )

                st.markdown("### 6. Compartilhamento")
                st.markdown(
                    "As informações devem permanecer restritas a usuários autorizados e a prestadores "
                    "de infraestrutura indispensáveis à operação do sistema, observados os contratos, "
                    "controles de acesso e deveres de confidencialidade aplicáveis."
                )

                st.markdown("### 7. Segurança e retenção")
                st.markdown(
                    "O acesso ao sistema é autenticado e separado por perfis e empresas. A retenção "
                    "de registros deve considerar a finalidade operacional, obrigações legais, "
                    "necessidades de auditoria e políticas internas da organização. Dados que deixem "
                    "de ser necessários devem ser eliminados ou anonimizados quando aplicável."
                )

                st.markdown("### 8. Direitos dos titulares")
                st.markdown(
                    "Quando aplicável, titulares podem solicitar informações sobre tratamento, acesso, "
                    "correção, anonimização, bloqueio, eliminação, portabilidade e demais direitos "
                    "previstos na LGPD. As solicitações devem ser encaminhadas ao canal oficial de "
                    "privacidade da organização responsável pelo ambiente Kineo."
                )

                st.markdown("### 9. Atualizações desta política")
                st.markdown(
                    "Esta política pode ser atualizada para refletir mudanças no sistema, na operação "
                    "ou em requisitos legais. A data de atualização será indicada no início desta página."
                )

            p1, p2 = st.columns([1, 1])
            if p1.button(
                "Voltar ao Painel Gerencial",
                icon=":material/arrow_back:",
                use_container_width=True,
                key="privacidade_voltar_painel"
            ):
                set_menu("Painel Gerencial")
                st.rerun()

            if st.session_state.get("privacidade_pendente"):
                if p2.button(
                    "Ciente e continuar",
                    icon=":material/check_circle:",
                    type="primary",
                    use_container_width=True,
                    key="privacidade_ciente_pagina"
                ):
                    registrar_ciencia_privacidade()
                    set_menu("Painel Gerencial")
                    st.rerun()
            else:
                if p2.button(
                    "Rever aviso de privacidade",
                    icon=":material/policy:",
                    use_container_width=True,
                    key="privacidade_rever_aviso"
                ):
                    st.session_state["privacidade_rever"] = True
                    st.session_state["privacidade_dialog_suspenso"] = False
                    st.rerun()


        # ══════════════════════════════════════════════════════════════════════════
        # CONFIGURAÇÕES (ADMIN)
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Configurações":
            aplicar_css_modulos_v11()

            if st.session_state["perfil"] != "admin":
                module_hero(
                    "Administração",
                    "Configurações",
                    "Esta área concentra identidade institucional e registros administrativos.",
                    "Acesso",
                    "Restrito",
                )
                st.error("Acesso Negado: privilégio administrativo requerido.", icon=None)
            else:
                session_config = SessionLocal()
                try:
                    empresa_config = session_config.get(Empresa, emp_id)
                    try:
                        eventos_auditoria = (
                            session_config.query(Auditoria)
                            .filter(Auditoria.empresa_id == emp_id)
                            .count()
                        )
                    except Exception:
                        session_config.rollback()
                        eventos_auditoria = 0
                finally:
                    session_config.close()

                nome_atual = (
                    empresa_config.nome_fantasia
                    if empresa_config and empresa_config.nome_fantasia else "Kineo"
                )
                logo_configurado = bool(empresa_config and empresa_config.logo_path)

                module_hero(
                    "Administração do ambiente",
                    "Configurações",
                    "Consulte a identidade institucional e os controles do ambiente antes de realizar alterações.",
                    "Ambiente",
                    str(APP_ENV or "Não informado").title(),
                )
                cf1, cf2, cf3, cf4 = st.columns(4)
                with cf1:
                    module_stat_card("Empresa", nome_atual, "identidade exibida no Kineo")
                with cf2:
                    module_stat_card("Logotipo", "Configurado" if logo_configurado else "Pendente", "branding institucional")
                with cf3:
                    module_stat_card("Auditoria", eventos_auditoria, "eventos registrados")
                with cf4:
                    module_stat_card("Perfil necessário", "Administrador", "acesso restrito")

                tab_config_visao, tab_logo, tab_auditoria = st.tabs([
                    "Visão geral",
                    "Identidade visual",
                    "Auditoria",
                ])

                with tab_config_visao:
                    cfg_identidade, cfg_seguranca = st.columns(2)
                    with cfg_identidade:
                        with st.container(border=True):
                            st.markdown("### Identidade institucional")
                            st.caption("Informações que representam a empresa na interface.")
                            st.markdown(
                                f"""
                                <div class="kineo-info-row"><span>Nome de exibição</span><strong>{html.escape(str(nome_atual))}</strong></div>
                                <div class="kineo-info-row"><span>Logotipo</span><strong>{'Configurado' if logo_configurado else 'Não configurado'}</strong></div>
                                """,
                                unsafe_allow_html=True,
                            )
                    with cfg_seguranca:
                        with st.container(border=True):
                            st.markdown("### Governança do ambiente")
                            st.caption("Controles administrativos já ativos nesta empresa.")
                            st.markdown(
                                f"""
                                <div class="kineo-info-row"><span>Isolamento</span><strong>Por empresa</strong></div>
                                <div class="kineo-info-row"><span>Eventos de auditoria</span><strong>{eventos_auditoria}</strong></div>
                                <div class="kineo-info-row"><span>Acesso</span><strong>Somente administradores</strong></div>
                                """,
                                unsafe_allow_html=True,
                            )

                with tab_logo:
                    with st.container(border=True):
                        st.markdown("**Identidade Visual da Empresa**")
                        st.caption("Atualize a Razão Social e o logotipo exibidos na interface.")

                        with st.form("form_branding"):
                            novo_nome = st.text_input(
                                "Razão Social / Nome de Exibição",
                                value=nome_atual,
                                max_chars=150,
                            )
                            logo_file = st.file_uploader(
                                "Logotipo",
                                type=["png", "jpg", "jpeg"],
                                help="PNG ou JPEG, até 5 MB.",
                            )

                            if st.form_submit_button("Atualizar Plataforma", use_container_width=True):
                                nome_limpo = str(novo_nome or "").strip()
                                if len(nome_limpo) < 2:
                                    st.error("Informe um nome válido.", icon=None)
                                else:
                                    session = SessionLocal()
                                    try:
                                        emp = session.get(Empresa, emp_id)
                                        if emp is None:
                                            st.error("Empresa não encontrada.", icon=None)
                                        else:
                                            emp.nome_fantasia = nome_limpo
                                            if logo_file:
                                                ok, erro, logo_ref = salvar_imagem_segura(
                                                    logo_file, f"logos/empresas/{emp_id}/logo.png", max_mb=5
                                                )
                                                if not ok:
                                                    raise ValueError(erro)
                                                emp.logo_path = logo_ref
                                            registrar_auditoria(
                                                session,
                                                emp_id,
                                                st.session_state["usuario_id"],
                                                "BRANDING_ATUALIZADO",
                                                "Empresa",
                                                emp_id,
                                            )
                                            session.commit()
                                            st.success("Branding atualizado com sucesso!")
                                            time.sleep(0.4)
                                            st.rerun()
                                    except ValueError as e:
                                        session.rollback()
                                        st.error(str(e), icon=None)
                                    except Exception:
                                        session.rollback()
                                        st.error("Não foi possível atualizar o branding.", icon=None)
                                    finally:
                                        session.close()

                with tab_auditoria:
                    st.caption("Últimos eventos de segurança e administração registrados para esta empresa.")
                    try:
                        df_audit = carregar_dados_tabela(
                            f"""
                            SELECT a.criado_em, a.acao, a.entidade, a.entidade_id,
                                   a.detalhes, COALESCE(u.nome, 'Usuário removido / sistema') AS usuario
                            FROM auditoria a
                            LEFT JOIN usuarios u ON u.id = a.usuario_id AND u.empresa_id = a.empresa_id
                            WHERE a.empresa_id = :empresa_id
                            ORDER BY a.criado_em DESC, a.id DESC
                            LIMIT 300
                            """,
                            emp_id,
                        )
                        if df_audit.empty:
                            st.info("Ainda não há eventos de auditoria registrados.", icon=None)
                        else:
                            df_audit["criado_em"] = formatar_serie_datetime_local(
                                df_audit["criado_em"], "%d/%m/%Y %H:%M:%S"
                            )
                            st.dataframe(
                                df_audit.rename(columns={
                                    "criado_em": "Data/Hora",
                                    "acao": "Ação",
                                    "entidade": "Entidade",
                                    "entidade_id": "ID",
                                    "detalhes": "Detalhes",
                                    "usuario": "Usuário",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )
                    except Exception:
                        st.warning(
                            "A tabela de auditoria ainda não está disponível neste banco. "
                            "Execute a migração V8 antes do deploy de produção.",
                            icon=None,
                        )

        # ══════════════════════════════════════════════════════════════════════════
        # 404 INTERNA / ESTADO DE NAVEGAÇÃO INVÁLIDO
        # ══════════════════════════════════════════════════════════════════════════
        else:
            st.markdown(
                """
                <div class="kineo-404">
                    <div class="kineo-404-code">404</div>
                    <h2>Página não encontrada</h2>
                    <p>
                        A área que você tentou acessar não existe ou não está disponível
                        neste ambiente. Use o botão abaixo para retornar ao painel principal.
                    </p>
                </div>
                """,
                unsafe_allow_html=True
            )

            _, col_404, _ = st.columns([1, 1.4, 1])
            with col_404:
                st.button(
                    "Voltar ao Painel Gerencial",
                    icon=":material/home:",
                    type="primary",
                    use_container_width=True,
                    on_click=set_menu,
                    args=("Painel Gerencial",),
                    key="btn_404_painel"
                )
