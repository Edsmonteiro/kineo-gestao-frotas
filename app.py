import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import (
    engine, SessionLocal, Veiculo, Contrato, SubstituicaoContrato, Custo, Usuario, Empresa,
    CobrancaRecorrente, CobrancaMensal, PlanoManutencao, ItemPlanoManutencao, ManutencaoRealizada
)
from datetime import date, timedelta
import calendar
import os
import uuid
import bcrypt
import time
import base64
from io import BytesIO

# ─── DIRETÓRIOS ──────────────────────────────────────────────────────────────
for pasta in ["comprovantes", "logos"]:
    os.makedirs(pasta, exist_ok=True)

# ─── SESSION STATE INICIAL ───────────────────────────────────────────────────
for key, default in [
    ("autenticado", False),
    ("forcar_troca_senha", False),
    ("tentativas_login", 0),
    ("bloqueado_ate", 0),
    ("tela_config", False),
    ("sidebar_pinned", False),
    ("cookies_aviso_visto", False),
    ("uploader_key", 0), # Chave para resetar o uploader de planilhas
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
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
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
        margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1),
        width 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}}

/*
   Quando a sidebar recolhida recebe hover, ela cresce para 260px.
   A variável abaixo faz a área principal acompanhar exatamente
   a mesma abertura, sem sobreposição.
*/
body:has([data-testid="stSidebar"]:hover) [data-testid="stAppViewContainer"] {{
    --kineo-sidebar-space: 260px;
}}

/* Força a barra lateral a colar no topo, removendo o gap nativo do Streamlit */
[data-testid="stSidebar"] .stScrollToBottomContainer > div:first-child {{
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    padding-top: 2rem !important; 
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
    margin-left: 1px !important; 
    margin-bottom: 8px !important;
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

[data-testid="stSidebar"] .stButton > button span.material-symbols-rounded {{ 
    font-size: 1.6rem !important; 
    margin-right: 16px !important; 
}}

[data-testid="stSidebar"] .stButton > button p {{ 
    opacity: {TEXT_OPACITY}; 
    visibility: {TEXT_VISIBILITY};
    transition: opacity 0.2s; 
    font-weight: 500 !important; 
}}

[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background-color: #1E293B !important; 
    color: #FFFFFF !important;
    border-left: 4px solid #6366F1 !important; 
    border-radius: 0 8px 8px 0 !important; 
    margin-left: -16px !important; 
    padding-left: 29px !important; 
}}

/* Link discreto de Privacidade/Cookies no rodapé operacional da sidebar */
[data-testid="stSidebar"] .st-key-nav_privacidade button {{
    height: 36px !important;
    min-height: 36px !important;
    color: #64748B !important;
    font-size: 0.75rem !important;
    margin-top: 2px !important;
    margin-bottom: 4px !important;
}}

[data-testid="stSidebar"] .st-key-nav_privacidade button:hover {{
    color: #CBD5E1 !important;
    background-color: rgba(255,255,255,0.04) !important;
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

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button {{
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

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button * {{
    display: none !important; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button:hover {{
    background-color: rgba(255, 255, 255, 0.08) !important; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button {{
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

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button p {{
    display: none !important; 
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button span {{
    margin: 0 !important;
    font-size: 1.5rem !important;
}}

[data-testid="stSidebar"]:hover {{
    width: 260px !important; 
    min-width: 260px !important; 
    max-width: 260px !important;
    box-shadow: 4px 0 20px rgba(0,0,0,0.4);
}}

[data-testid="stSidebar"]:hover .stButton > button {{
    width: calc(100% - 34px) !important;
}}

[data-testid="stSidebar"]:hover .sidebar-brand-wrapper, 
[data-testid="stSidebar"]:hover .profile-wrapper {{
    width: 260px !important;
}}

[data-testid="stSidebar"]:hover [data-testid="stVerticalBlock"] > div:nth-last-child(2) button,
.sidebar-pinned[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(2) button {{
    width: 180px !important; 
}}

[data-testid="stSidebar"]:hover .sidebar-brand-text, 
[data-testid="stSidebar"]:hover .profile-text, 
[data-testid="stSidebar"]:hover .stButton > button p {{
    opacity: 1 !important;
    visibility: visible !important;
}}

[data-testid="stSidebar"]:hover [data-testid="stVerticalBlock"] > div:nth-last-child(1) button,
.sidebar-pinned[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button {{
    opacity: 1 !important; 
    pointer-events: auto !important;
}}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-last-child(1) button:hover {{
    background: rgba(239, 68, 68, 0.15) !important; 
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
</style>
"""
st.markdown(css_template, unsafe_allow_html=True)


# ─── HELPERS & CACHE DE CONSULTAS (OTIMIZAÇÃO DE PERFORMANCE) ───────────────
@st.cache_data(ttl=60)
def carregar_dados_tabela(query, empresa_id):
    """Função otimizada com cache do Streamlit para agilizar a navegação entre telas."""
    return pd.read_sql(query, engine)

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

def page_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div class="page-header">
        <h1>{title}</h1>
        {"<p>" + subtitle + "</p>" if subtitle else ""}
    </div>
    """, unsafe_allow_html=True)

def fmt_brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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
        WHERE empresa_id={empresa_id} AND plano_manutencao_id IS NOT NULL
        ORDER BY modelo, placa
    """, empresa_id)

    if df_v.empty:
        return pd.DataFrame()

    df_itens = carregar_dados_tabela(f"""
        SELECT i.id, i.plano_id, i.codigo_servico, i.tipo_manutencao, i.descricao,
               i.intervalo_fabricante_km, i.intervalo_fabricante_meses,
               i.intervalo_empresa_km, i.intervalo_empresa_meses
        FROM itens_plano_manutencao i
        WHERE i.empresa_id={empresa_id} AND COALESCE(i.ativo, 1)=1
    """, empresa_id)

    if df_itens.empty:
        return pd.DataFrame()

    df_hist = carregar_dados_tabela(f"""
        SELECT id, veiculo_id, plano_item_id, custo_id, data_execucao, km_execucao, origem
        FROM manutencoes_realizadas
        WHERE empresa_id={empresa_id}
    """, empresa_id)

    registros = []
    hoje = date.today()

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
                    Veiculo.empresa_id == empresa_id
                ).first()
                if veiculo and veiculo.placa.upper() != placa:
                    ignorados.append(f"Linha {idx + 2}: placa diferente do veículo selecionado")
                    continue
            else:
                veiculo = session.query(Veiculo).filter(
                    Veiculo.empresa_id == empresa_id,
                    Veiculo.placa == placa
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
        data_inicio=date.today(),
        data_fim=None,
        ativo=1,
        usuario_lancamento=usuario
    )
    session.add(substituicao)
    veiculo_principal.status = "Manutenção"
    veiculo_substituto.status = "Alugado"
    return substituicao

def finalizar_substituicao_contrato(session, substituicao, status_principal="Alugado"):
    principal = session.get(Veiculo, substituicao.veiculo_principal_id)
    substituto = session.get(Veiculo, substituicao.veiculo_substituto_id)

    substituicao.ativo = 0
    substituicao.data_fim = date.today()

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

def set_config():
    st.session_state["tela_config"] = True
    st.session_state["ultimo_menu"] = "Configurações"

def set_perfil():
    st.session_state["tela_config"] = False
    st.session_state["ultimo_menu"] = "Meu Perfil"

def set_privacidade():
    st.session_state["tela_config"] = False
    st.session_state["ultimo_menu"] = "Política de Privacidade"

def toggle_pin():
    st.session_state["sidebar_pinned"] = not st.session_state["sidebar_pinned"]

def efetuar_logout():
    st.session_state["autenticado"] = False
    st.session_state["tela_config"] = False
    st.session_state["cookies_aviso_visto"] = False


def _conteudo_aviso_cookies():
    st.markdown(
        "O Kineo utiliza recursos técnicos de sessão e preferências necessários "
        "para autenticação, segurança e funcionamento da interface. "
        "O aplicativo não implementa cookies próprios de publicidade comportamental."
    )
    st.caption(
        "Este aviso é apresentado uma vez por sessão de acesso. "
        "Mais detalhes estão disponíveis na Política de Privacidade."
    )

    c_cookie_1, c_cookie_2 = st.columns(2)

    if c_cookie_1.button(
        "Entendi e continuar",
        type="primary",
        use_container_width=True,
        key="cookie_entendi"
    ):
        st.session_state["cookies_aviso_visto"] = True
        st.rerun()

    if c_cookie_2.button(
        "Política de Privacidade",
        use_container_width=True,
        key="cookie_privacidade"
    ):
        st.session_state["cookies_aviso_visto"] = True
        set_privacidade()
        st.rerun()


if hasattr(st, "dialog"):
    aviso_cookies = st.dialog(
        "Privacidade e cookies",
        width="small"
    )(_conteudo_aviso_cookies)
else:
    # Fallback para versões antigas do Streamlit.
    aviso_cookies = _conteudo_aviso_cookies


# ══════════════════════════════════════════════════════════════════════════════
# 1 · TELA DE LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state["autenticado"]:
    st.markdown("<br><br>", unsafe_allow_html=True)
    
    col_l, col_c, col_r = st.columns([1, 1.1, 1])
    
    with col_c:
        st.markdown("""
        <div style="text-align:center; margin-bottom:2rem;">
            <div style="font-size:2.5rem; font-weight:800; letter-spacing:-0.04em; color:#111827;">
                Kineo
            </div>
            <div style="font-size:0.875rem; color:#6B7280; margin-top:0.25rem;">
                Gestão corporativa de frotas
            </div>
        </div>
        """, unsafe_allow_html=True)

        if time.time() < st.session_state["bloqueado_ate"]:
            segundos = int(st.session_state["bloqueado_ate"] - time.time())
            st.error(f"Acesso bloqueado. Aguarde {segundos}s.")
            
        else:
            with st.container(border=True):
                st.markdown("<p style='font-weight:600; margin-bottom:0.25rem;'>Acesse sua conta</p>", unsafe_allow_html=True)
                
                with st.form("login_form"):
                    usuario_input = st.text_input("Login", placeholder="Usuário")
                    senha_input   = st.text_input("Senha", type="password", placeholder="••••••••")
                    
                    submitted = st.form_submit_button("Entrar", use_container_width=True)

                if submitted:
                    with st.spinner("Autenticando..."):
                        time.sleep(0.3)
                        session = SessionLocal()
                        user = session.query(Usuario).filter(Usuario.login == usuario_input).first()

                        if user and bcrypt.checkpw(senha_input.encode(), user.senha.encode()):
                            st.session_state.update({
                                "tentativas_login": 0,
                                "autenticado": True,
                                "usuario_id": user.id,
                                "empresa_id": user.empresa_id,
                                "nome": user.nome,
                                "perfil": user.perfil,
                                "forcar_troca_senha": bcrypt.checkpw(b"PRIMEIROACESSO", user.senha.encode()),
                                "ultimo_menu": "Painel Gerencial",
                                "tela_config": False
                            })
                            session.close()
                            st.rerun()
                            
                        else:
                            st.session_state["tentativas_login"] += 1
                            restantes = 5 - st.session_state["tentativas_login"]
                            
                            if st.session_state["tentativas_login"] >= 5:
                                st.session_state["bloqueado_ate"] = time.time() + 180
                                st.error("Bloqueio de segurança ativo por 3 minutos.")
                            else:
                                st.error(f"Credenciais inválidas. {restantes} tentativas restantes.")
                                
                            session.close()

# ══════════════════════════════════════════════════════════════════════════════
# 2 · TROCA DE SENHA OBRIGATÓRIA
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state["forcar_troca_senha"]:
    st.markdown("<br><br>", unsafe_allow_html=True)
    
    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    
    with col_c:
        with st.container(border=True):
            st.markdown("### Defina sua senha")
            st.info("Primeiro acesso detectado. Crie uma senha pessoal e intransferível.")
            
            with st.form("form_troca"):
                nova = st.text_input("Nova senha", type="password", placeholder="Mínimo 4 caracteres")
                conf = st.text_input("Confirmação", type="password", placeholder="Repita a chave")
                
                if st.form_submit_button("Salvar e entrar", use_container_width=True):
                    if len(nova) < 4:
                        st.error("A senha deve ter pelo menos 4 caracteres.")
                    elif nova == "PRIMEIROACESSO":
                        st.error("Não é possível utilizar a senha padrão de fábrica.")
                    elif nova != conf:
                        st.error("As senhas informadas não coincidem.")
                    else:
                        session = SessionLocal()
                        user = session.get(Usuario, st.session_state["usuario_id"])
                        user.senha = bcrypt.hashpw(nova.encode(), bcrypt.gensalt()).decode()
                        session.commit()
                        session.close()
                        
                        st.session_state["forcar_troca_senha"] = False
                        st.success("Senha atualizada!")
                        time.sleep(0.8)
                        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 3 · APP PRINCIPAL (HOVER SIDEBAR)
# ══════════════════════════════════════════════════════════════════════════════
else:
    emp_id = st.session_state["empresa_id"]
    tela_ativa = st.session_state.get("ultimo_menu", "Painel Gerencial")

    # Caminho do Avatar Pessoal do Usuário Logado
    avatar_path = os.path.join("logos", f"avatar_{st.session_state['usuario_id']}.png")

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        session_logo = SessionLocal()
        empresa_atual = session_logo.get(Empresa, emp_id)
        session_logo.close()

        # Renderização Logo Dinâmica
        if empresa_atual and empresa_atual.logo_path and os.path.exists(empresa_atual.logo_path):
            with open(empresa_atual.logo_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            
            st.markdown(f"""
            <div class="sidebar-brand-wrapper">
                <img src="data:image/jpeg;base64,{encoded_string}" class="sidebar-logo-img">
                <div class="sidebar-brand-text">
                    <h2>{empresa_atual.nome_fantasia}</h2>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            nome_emp = empresa_atual.nome_fantasia if empresa_atual else "Kineo"
            letra = nome_emp[0].upper()
            
            st.markdown(f"""
            <div class="sidebar-brand-wrapper">
                <div class="sidebar-logo-img">{letra}</div>
                <div class="sidebar-brand-text">
                    <h2>{nome_emp}</h2>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Itens Principais do Menu
        MENU_ITEMS = [
            ("Painel Gerencial", ":material/bar_chart:"),
            ("Gestão de Frota", ":material/directions_car:"),
            ("Gestão de Custos", ":material/account_balance_wallet:"),
            ("Contratos e Locação", ":material/description:"),
            ("Gestão de Cobranças", ":material/request_quote:")
        ]

        for label, icon in MENU_ITEMS:
            is_active = (tela_ativa == label)
            st.button(
                label, 
                icon=icon, 
                type="primary" if is_active else "secondary", 
                use_container_width=True, 
                on_click=set_menu, 
                args=(label,), 
                key=f"nav_{label}"
            )

        # Divisor Flexbox invisível que empurra o resto para baixo
        st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)

        # Ações Inferiores (Pin e Configurações rebaixados e colados no perfil)
        pin_lbl = "Desafixar Menu" if st.session_state["sidebar_pinned"] else "Fixar Menu"
        pin_icn = ":material/keep_off:" if st.session_state["sidebar_pinned"] else ":material/push_pin:"
        
        st.button(
            pin_lbl, 
            icon=pin_icn, 
            use_container_width=True, 
            on_click=toggle_pin, 
            key="nav_pin"
        )

        if st.session_state["perfil"] == "admin":
            is_cfg = (tela_ativa == "Configurações")
            st.button(
                "Configurações", 
                icon=":material/settings:", 
                type="primary" if is_cfg else "secondary", 
                use_container_width=True, 
                on_click=set_config, 
                key="nav_cfg"
            )

        # Privacidade/Cookies: acesso discreto, disponível para todos os perfis
        st.button(
            "Privacidade · Cookies",
            icon=":material/policy:",
            type="primary" if tela_ativa == "Política de Privacidade" else "secondary",
            use_container_width=True,
            on_click=set_privacidade,
            key="nav_privacidade"
        )

        # Espaço protetor estrito para acomodar exatamente a altura do perfil sem gerar scroll
        st.markdown('<div style="height: 85px;"></div>', unsafe_allow_html=True)

        # Renderização do Avatar do Usuário (Rodapé HTML - Sem Placeholder)
        if os.path.exists(avatar_path):
            with open(avatar_path, "rb") as image_file:
                encoded_avatar = base64.b64encode(image_file.read()).decode()
            avatar_html = f'<img src="data:image/png;base64,{encoded_avatar}" class="profile-avatar" style="object-fit: cover;">'
        else:
            letra_inicial = st.session_state["nome"][0].upper() if st.session_state.get("nome") else "U"
            avatar_html = f'<div class="profile-avatar">{letra_inicial}</div>'

        st.markdown(f"""
        <div class="profile-wrapper">
            {avatar_html}
            <div class="profile-text">
                <strong>{st.session_state['nome']}</strong>
                <span>{st.session_state['perfil'].title()}</span>
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

    # Transparência sobre sessão/cookies: uma vez por login/sessão.
    if not st.session_state.get("cookies_aviso_visto", False):
        aviso_cookies()


    with st.spinner("Processando..."):

        # ══════════════════════════════════════════════════════════════════════════
        # PAINEL GERENCIAL
        # ══════════════════════════════════════════════════════════════════════════
        if tela_ativa == "Painel Gerencial":
            page_header(
                "Painel Gerencial",
                "Visão executiva da operação, contratos e desempenho financeiro."
            )

            hoje = date.today()
            mes_atual_str = hoje.strftime("%m/%Y")
            primeiro_dia_mes = hoje.replace(day=1)
            mes_anterior_str = (primeiro_dia_mes - timedelta(days=1)).strftime("%m/%Y")
            limite_30_dias = hoje + timedelta(days=30)

            # ── Consultas principais ──────────────────────────────────────────────
            df_status = carregar_dados_tabela(f"""
                SELECT status, COUNT(id) AS qtd
                FROM veiculos
                WHERE empresa_id={emp_id}
                GROUP BY status
            """, emp_id)

            df_veiculos_dash = carregar_dados_tabela(f"""
                SELECT id, placa, modelo, km_atual, status
                FROM veiculos
                WHERE empresa_id={emp_id}
            """, emp_id)

            df_custos = carregar_dados_tabela(f"""
                SELECT c.id, c.veiculo_id, c.data_custo, c.categoria, c.valor_total,
                       v.placa, v.modelo
                FROM custos c
                LEFT JOIN veiculos v ON v.id=c.veiculo_id
                WHERE c.empresa_id={emp_id}
            """, emp_id)

            df_cobrancas = carregar_dados_tabela(f"""
                SELECT mes_ano, valor_previsto, status, vencimento
                FROM cobrancas_mensais
                WHERE empresa_id={emp_id}
            """, emp_id)

            df_contratos_dash = carregar_dados_tabela(f"""
                SELECT c.id, c.veiculo_id, c.cliente, c.data_inicio, c.data_fim,
                       c.ativo, c.tipo_valor, c.valor_mensal, v.placa, v.modelo
                FROM contratos c
                INNER JOIN veiculos v ON v.id=c.veiculo_id
                WHERE c.empresa_id={emp_id}
            """, emp_id)

            try:
                df_substituicoes_dash = carregar_dados_tabela(f"""
                    SELECT s.id, s.contrato_id, s.veiculo_principal_id,
                           s.veiculo_substituto_id, s.data_inicio, s.data_fim, s.ativo,
                           vp.placa AS placa_principal,
                           vs.placa AS placa_substituto,
                           c.cliente
                    FROM substituicoes_contrato s
                    INNER JOIN contratos c ON c.id=s.contrato_id
                    INNER JOIN veiculos vp ON vp.id=s.veiculo_principal_id
                    INNER JOIN veiculos vs ON vs.id=s.veiculo_substituto_id
                    WHERE s.empresa_id={emp_id} AND s.ativo=1
                """, emp_id)
            except Exception:
                df_substituicoes_dash = pd.DataFrame()

            # ── Tratamento dos dados ──────────────────────────────────────────────
            if not df_custos.empty:
                df_custos["data_custo"] = pd.to_datetime(df_custos["data_custo"], errors="coerce")
                df_custos["mes_ano"] = df_custos["data_custo"].dt.strftime("%m/%Y")
                df_custos["valor_total"] = pd.to_numeric(df_custos["valor_total"], errors="coerce").fillna(0.0)

            if not df_cobrancas.empty:
                df_cobrancas["valor_previsto"] = pd.to_numeric(df_cobrancas["valor_previsto"], errors="coerce").fillna(0.0)
                df_cobrancas["vencimento"] = pd.to_datetime(df_cobrancas["vencimento"], errors="coerce")

            if not df_contratos_dash.empty:
                df_contratos_dash["data_inicio"] = pd.to_datetime(df_contratos_dash["data_inicio"], errors="coerce")
                df_contratos_dash["data_fim"] = pd.to_datetime(df_contratos_dash["data_fim"], errors="coerce")
                df_contratos_dash["valor_mensal"] = pd.to_numeric(df_contratos_dash["valor_mensal"], errors="coerce").fillna(0.0)

            def qtd_status(nome):
                if df_status.empty:
                    return 0
                valores = df_status.loc[df_status["status"] == nome, "qtd"]
                return int(valores.sum()) if not valores.empty else 0

            def variacao_mes(atual, anterior):
                atual = float(atual or 0)
                anterior = float(anterior or 0)
                if anterior == 0:
                    return None if atual == 0 else "Novo no mês"
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
                contratos_ativos_df = df_contratos_dash[df_contratos_dash["ativo"] == 1].copy()
                contratos_ativos = len(contratos_ativos_df)
                if not contratos_ativos_df.empty:
                    contratos_vencendo_30 = len(contratos_ativos_df[
                        contratos_ativos_df["data_fim"].notna()
                        & (contratos_ativos_df["data_fim"].dt.date >= hoje)
                        & (contratos_ativos_df["data_fim"].dt.date <= limite_30_dias)
                    ])
                    receita_contratada = contratos_ativos_df.loc[
                        contratos_ativos_df["tipo_valor"] == "Fixo", "valor_mensal"
                    ].sum()

            reservas_em_uso = len(df_substituicoes_dash) if not df_substituicoes_dash.empty else 0

            # ── Indicadores financeiros ───────────────────────────────────────────
            custos_mes_atual = 0.0
            custos_mes_anterior = 0.0
            if not df_custos.empty:
                custos_mes_atual = df_custos.loc[df_custos["mes_ano"] == mes_atual_str, "valor_total"].sum()
                custos_mes_anterior = df_custos.loc[df_custos["mes_ano"] == mes_anterior_str, "valor_total"].sum()

            faturamento_mes_atual = 0.0
            faturamento_mes_anterior = 0.0
            inadimplencia_qtd = 0
            if not df_cobrancas.empty:
                faturamento_mes_atual = df_cobrancas.loc[df_cobrancas["mes_ano"] == mes_atual_str, "valor_previsto"].sum()
                faturamento_mes_anterior = df_cobrancas.loc[df_cobrancas["mes_ano"] == mes_anterior_str, "valor_previsto"].sum()
                inadimplencia_qtd = len(df_cobrancas[
                    (df_cobrancas["status"] == "Pendente")
                    & df_cobrancas["vencimento"].notna()
                    & (df_cobrancas["vencimento"].dt.date < hoje)
                ])

            saldo_mes = faturamento_mes_atual - custos_mes_atual

            # ── KPIs principais ───────────────────────────────────────────────────
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Frota Total", veiculos_totais, delta=f"{veiculos_disponiveis} disponíveis")
            c2.metric("Taxa de Ocupação", f"{taxa_ocupacao:.1f}%", delta=f"{veiculos_alugados} alugados")
            c3.metric("Faturamento (Mês)", fmt_brl(faturamento_mes_atual), delta=variacao_mes(faturamento_mes_atual, faturamento_mes_anterior))
            c4.metric("Despesas (Mês)", fmt_brl(custos_mes_atual), delta=variacao_mes(custos_mes_atual, custos_mes_anterior), delta_color="inverse")
            c5.metric(
                "Saldo Líquido",
                fmt_brl(saldo_mes),
                delta=f"{inadimplencia_qtd} atraso(s)",
                delta_color="inverse" if inadimplencia_qtd > 0 else "off"
            )

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Alertas e manutenção preventiva ───────────────────────────────────
            alertas = []
            if contratos_vencendo_30:
                alertas.append(("Contratos próximos do vencimento", f"{contratos_vencendo_30} contrato(s) vencem nos próximos 30 dias."))
            if veiculos_manutencao:
                alertas.append(("Veículos em manutenção", f"{veiculos_manutencao} veículo(s) estão indisponíveis para operação."))
            if reservas_em_uso:
                alertas.append(("Reservas em operação", f"{reservas_em_uso} veículo(s) reserva atendem contratos temporariamente."))
            if inadimplencia_qtd:
                alertas.append(("Cobranças vencidas", f"{inadimplencia_qtd} cobrança(s) estão pendentes e vencidas."))

            diag_dashboard = diagnostico_manutencao(emp_id)
            revisoes_proximas = []
            if not diag_dashboard.empty:
                diag_alerta = diag_dashboard[diag_dashboard["Status"].isin(["VENCIDO", "PRÓXIMO", "ATENÇÃO"])].copy()
                prioridade_dash = {"VENCIDO": 0, "PRÓXIMO": 1, "ATENÇÃO": 2}
                diag_alerta["_ordem"] = diag_alerta["Status"].map(prioridade_dash)
                diag_alerta = diag_alerta.sort_values(["_ordem", "Faltam KM", "Faltam Dias"], na_position="last")
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
                # Compatibilidade temporária: veículos ainda sem plano continuam usando o alerta genérico legado.
                df_v_km = carregar_dados_tabela(f"""
                    SELECT id, placa, km_atual
                    FROM veiculos
                    WHERE empresa_id={emp_id} AND km_atual>0
                """, emp_id)
                df_manu = carregar_dados_tabela(f"""
                    SELECT veiculo_id, MAX(km_momento) AS ultimo_km
                    FROM custos
                    WHERE empresa_id={emp_id} AND categoria='Manutenção Preventiva'
                    GROUP BY veiculo_id
                """, emp_id)
                for _, v in df_v_km.iterrows():
                    ultimo_km = 0.0
                    if not df_manu.empty and v["id"] in df_manu["veiculo_id"].values:
                        serie = df_manu.loc[df_manu["veiculo_id"] == v["id"], "ultimo_km"]
                        if not serie.empty and pd.notna(serie.iloc[0]):
                            ultimo_km = float(serie.iloc[0])
                    km_rodado = float(v["km_atual"] or 0) - ultimo_km
                    if km_rodado >= 9500:
                        revisoes_proximas.append({
                            "placa": v["placa"], "servico": "Revisão preventiva",
                            "status": "PRÓXIMO", "detalhe": f"{km_rodado:,.0f} km desde a última preventiva"
                        })

            if revisoes_proximas:
                veiculos_alerta = len({r["placa"] for r in revisoes_proximas})
                primeiro = revisoes_proximas[0]
                alertas.append((
                    "Manutenção preventiva",
                    f"{veiculos_alerta} veículo(s) exigem atenção. {primeiro['placa']} · {primeiro['servico']} ({primeiro['status']})."
                ))

            if alertas:
                with st.container(border=True):
                    st.markdown("### Atenção Operacional")
                    st.caption("Itens que merecem acompanhamento da gestão.")
                    cols_alerta = st.columns(min(len(alertas), 4))
                    for idx, (titulo, descricao) in enumerate(alertas[:4]):
                        with cols_alerta[idx]:
                            st.markdown(f"""
                            <div style="min-height:96px;padding:14px;border:1px solid #E5E7EB;border-radius:10px;background:#F8FAFC;">
                                <div style="font-size:11px;color:#64748B;text-transform:uppercase;font-weight:600;margin-bottom:6px;">{titulo}</div>
                                <div style="font-size:13px;font-weight:600;color:#111827;line-height:1.35;">{descricao}</div>
                            </div>
                            """, unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)

            # ── Linha principal: frota + contratos ─────────────────────────────────
            col_frota, col_contratos = st.columns([1.15, 1])

            with col_frota:
                with st.container(border=True):
                    st.markdown("### Disponibilidade da Frota")
                    st.caption("Distribuição atual dos veículos por status.")

                    if veiculos_totais > 0:
                        df_pizza = pd.DataFrame({
                            "Status": ["Disponível", "Alugado", "Manutenção"],
                            "Quantidade": [veiculos_disponiveis, veiculos_alugados, veiculos_manutencao]
                        })
                        df_pizza = df_pizza[df_pizza["Quantidade"] > 0]

                        fig_frota = px.pie(
                            df_pizza,
                            names="Status",
                            values="Quantidade",
                            hole=0.68,
                            color="Status",
                            color_discrete_map={
                                "Disponível": PALETTE["green"],
                                "Alugado": PALETTE["indigo"],
                                "Manutenção": PALETTE["amber"]
                            }
                        )
                        fig_frota.update_traces(textposition="outside", textinfo="label+value")
                        fig_frota.add_annotation(
                            text=f"<b>{veiculos_totais}</b><br>veículos",
                            x=0.5, y=0.5, showarrow=False, font=dict(size=18)
                        )
                        fig_frota.update_layout(**PLOTLY_LAYOUT, height=255, showlegend=False)
                        st.plotly_chart(fig_frota, use_container_width=True, config={"displayModeBar": False})

                        f1, f2, f3 = st.columns(3)
                        f1.metric("Disponíveis", veiculos_disponiveis)
                        f2.metric("Alugados", veiculos_alugados)
                        f3.metric("Manutenção", veiculos_manutencao)
                    else:
                        st.info("Nenhum veículo cadastrado.", icon=None)

            with col_contratos:
                with st.container(border=True):
                    st.markdown("### Carteira de Contratos")
                    st.caption("Resumo comercial dos contratos vigentes.")
                    st.metric("Receita Mensal Contratada", fmt_brl(receita_contratada))

                    ct1, ct2 = st.columns(2)
                    ct1.metric("Contratos Ativos", contratos_ativos)
                    ct2.metric("Vencendo em 30 dias", contratos_vencendo_30)

                    ct3, ct4 = st.columns(2)
                    ct3.metric("Reservas em Uso", reservas_em_uso)
                    ct4.metric("Frota em Manutenção", veiculos_manutencao)

                    if reservas_em_uso > 0:
                        st.markdown("---")
                        st.markdown("**Substituições temporárias em andamento**")
                        for _, r in df_substituicoes_dash.head(4).iterrows():
                            st.caption(f"{r['cliente']} · {r['placa_principal']} → {r['placa_substituto']}")

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Linha adaptativa: financeiro + saúde da frota ──────────────────────
            col_fin, col_saude = st.columns([1.35, 1])

            with col_fin:
                with st.container(border=True):
                    if not df_custos.empty or not df_cobrancas.empty:
                        st.markdown("### Evolução Financeira")
                        st.caption("Faturamento e despesas ao longo dos meses.")

                        frames_fluxo = []

                        if not df_custos.empty:
                            dc = df_custos.groupby("mes_ano")["valor_total"].sum().reset_index()
                            dc.columns = ["mes_ano", "valor"]
                            dc["tipo"] = "Despesas"
                            frames_fluxo.append(dc)

                        if not df_cobrancas.empty:
                            dr = df_cobrancas.groupby("mes_ano")["valor_previsto"].sum().reset_index()
                            dr.columns = ["mes_ano", "valor"]
                            dr["tipo"] = "Faturamento"
                            frames_fluxo.append(dr)

                        df_fluxo = pd.concat(frames_fluxo, ignore_index=True)
                        df_fluxo["data_ordem"] = pd.to_datetime(df_fluxo["mes_ano"], format="%m/%Y", errors="coerce")
                        df_fluxo = df_fluxo.dropna(subset=["data_ordem"]).sort_values("data_ordem")

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
                                    "Faturamento": PALETTE["green"],
                                    "Despesas": PALETTE["red"]
                                }
                            )
                            fig_fluxo.update_traces(texttemplate="R$ %{text:,.0f}", textposition="outside")
                            fig_fluxo.update_layout(
                                **PLOTLY_LAYOUT,
                                height=285,
                                xaxis=dict(title="", type="category"),
                                yaxis=dict(title="", tickprefix="R$ "),
                                legend=dict(title="", orientation="h", y=1.10, x=1, xanchor="right")
                            )
                            st.plotly_chart(fig_fluxo, use_container_width=True, config={"displayModeBar": False})
                        else:
                            st.info("Ainda não há histórico mensal suficiente.", icon=None)
                    else:
                        st.markdown("### Visão Financeira")
                        st.caption("Resumo compacto enquanto ainda não há movimentação financeira.")

                        vf1, vf2 = st.columns(2)
                        vf1.metric("Receita no mês", fmt_brl(faturamento_mes_atual))
                        vf2.metric("Despesa no mês", fmt_brl(custos_mes_atual))

                        vf3, vf4 = st.columns(2)
                        vf3.metric("Saldo do mês", fmt_brl(saldo_mes))
                        vf4.metric("Cobranças vencidas", inadimplencia_qtd)

                        st.info(
                            "Cadastre despesas ou cobranças para habilitar o gráfico de evolução mensal.",
                            icon=None
                        )

            with col_saude:
                with st.container(border=True):
                    st.markdown("### Saúde da Frota")
                    st.caption("Indicadores para manutenção e disponibilidade.")

                    qtd_revisao = len({r["placa"] for r in revisoes_proximas})
                    veiculos_saudaveis = max(veiculos_totais - veiculos_manutencao - qtd_revisao, 0)

                    s1, s2 = st.columns(2)
                    s1.metric("Operação Normal", veiculos_saudaveis)
                    s2.metric("Em Manutenção", veiculos_manutencao)

                    s3, s4 = st.columns(2)
                    s3.metric("Revisão Próxima", qtd_revisao)
                    s4.metric("Reservas em Uso", reservas_em_uso)

                    if revisoes_proximas:
                        st.markdown("---")
                        st.markdown("**Veículos que exigem atenção**")
                        for revisao in revisoes_proximas[:4]:
                            st.caption(
                                f"{revisao['placa']} · {revisao['servico']} · "
                                f"{revisao['status']} · {revisao['detalhe']}"
                            )
                    elif veiculos_manutencao == 0:
                        st.success("Nenhum alerta crítico de manutenção.", icon=None)

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Linha final adaptativa: custos ou ações rápidas ─────────────────────
            if not df_custos.empty:
                col_custos, col_acoes = st.columns([1.35, 1])

                with col_custos:
                    with st.container(border=True):
                        st.markdown("### Maiores Custos por Veículo")
                        st.caption("Veículos com maior impacto financeiro.")

                        df_gastos = (
                            df_custos.groupby(["veiculo_id", "placa", "modelo"], dropna=False)["valor_total"]
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
                                color_discrete_sequence=[PALETTE["indigo"]]
                            )
                            fig_gastos.update_traces(texttemplate="R$ %{text:,.0f}", textposition="outside")
                            fig_gastos.update_layout(
                                **PLOTLY_LAYOUT,
                                height=245,
                                xaxis=dict(title="", visible=False),
                                yaxis=dict(title="")
                            )
                            st.plotly_chart(fig_gastos, use_container_width=True, config={"displayModeBar": False})

                with col_acoes:
                    with st.container(border=True):
                        st.markdown("### Ações Rápidas")
                        st.caption("Atalhos para as rotinas mais frequentes.")

                        st.button(
                            "Registrar despesa",
                            icon=":material/add_card:",
                            use_container_width=True,
                            on_click=set_menu,
                            args=("Gestão de Custos",),
                            key="dash_acao_custos"
                        )
                        st.button(
                            "Abrir contrato",
                            icon=":material/description:",
                            use_container_width=True,
                            on_click=set_menu,
                            args=("Contratos e Locação",),
                            key="dash_acao_contratos"
                        )
                        st.button(
                            "Gerenciar frota",
                            icon=":material/directions_car:",
                            use_container_width=True,
                            on_click=set_menu,
                            args=("Gestão de Frota",),
                            key="dash_acao_frota"
                        )
            else:
                col_resumo, col_acoes = st.columns([1.35, 1])

                with col_resumo:
                    with st.container(border=True):
                        st.markdown("### Resumo Operacional")
                        st.caption("Situação atual da operação em um único bloco.")

                        ro1, ro2, ro3 = st.columns(3)
                        ro1.metric("Disponíveis", veiculos_disponiveis)
                        ro2.metric("Contratos ativos", contratos_ativos)
                        ro3.metric("Reservas em uso", reservas_em_uso)

                        st.info(
                            "Nenhuma despesa registrada. O ranking de custos aparecerá aqui após os primeiros lançamentos.",
                            icon=None
                        )

                with col_acoes:
                    with st.container(border=True):
                        st.markdown("### Ações Rápidas")
                        st.caption("Comece pelas operações que alimentam o painel.")

                        st.button(
                            "Registrar primeira despesa",
                            icon=":material/add_card:",
                            use_container_width=True,
                            on_click=set_menu,
                            args=("Gestão de Custos",),
                            key="dash_acao_primeiro_custo"
                        )
                        st.button(
                            "Abrir contrato",
                            icon=":material/description:",
                            use_container_width=True,
                            on_click=set_menu,
                            args=("Contratos e Locação",),
                            key="dash_acao_primeiro_contrato"
                        )
                        st.button(
                            "Gerenciar frota",
                            icon=":material/directions_car:",
                            use_container_width=True,
                            on_click=set_menu,
                            args=("Gestão de Frota",),
                            key="dash_acao_gerenciar_frota"

                        )

        elif tela_ativa == "Gestão de Frota":
            page_header("Gestão de Frota", "Cadastro, saúde e análise de gastos por veículo.")

            df_veiculos = carregar_dados_tabela(f"SELECT * FROM veiculos WHERE empresa_id={emp_id}", emp_id)
            total = len(df_veiculos)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Frota total",    total)
            c2.metric("Disponíveis",    len(df_veiculos[df_veiculos["status"] == "Disponível"])  if total else 0)
            c3.metric("Em contrato",    len(df_veiculos[df_veiculos["status"] == "Alugado"])     if total else 0)
            c4.metric("Em manutenção",  len(df_veiculos[df_veiculos["status"] == "Manutenção"])  if total else 0)

            st.markdown("<br>", unsafe_allow_html=True)
            
            tab_admin, tab_status, tab_gastos, tab_planos, tab_saude = st.tabs(["Cadastro de veículos", "Alterar status", "Análise de gastos", "Planos de manutenção", "Saúde da frota"])

            # ── Aba: Cadastro ─────────────────────────────────────────────────────
            with tab_admin:
                col_cad_tipo1, col_cad_tipo2 = st.tabs(["Cadastro Individual", "Importação em Massa (.xls / .xlsx)"])

                with col_cad_tipo1:
                    with st.container(border=True):
                        st.markdown("**Adicionar Novo Veículo**")
                        status_novo = st.selectbox("Status inicial", ["Disponível", "Alugado", "Manutenção"])
                        
                        with st.container():
                            ca, cb, cc = st.columns([0.9, 1.15, 0.7])
                            placa = ca.text_input("Placa", placeholder="ABC-1234")
                            fabricante = cb.text_input("Fabricante", placeholder="Ex.: Fiat")
                            ano_modelo = cc.number_input("Ano/modelo", min_value=1900, max_value=2100, step=1, value=date.today().year)

                            cm1, cm2, cm3 = st.columns(3)
                            modelo = cm1.text_input("Modelo", placeholder="Ex.: Argo")
                            versao = cm2.text_input("Versão (opcional)", placeholder="Ex.: Drive")
                            motorizacao = cm3.text_input("Motorização (opcional)", placeholder="Ex.: 1.0 Firefly")

                            cm4, cm5, cm6 = st.columns(3)
                            combustivel_veiculo = cm4.selectbox("Combustível", ["Não informado", "Flex", "Gasolina", "Etanol", "Diesel", "Elétrico", "Híbrido"], key="frota_combustivel_novo")
                            transmissao = cm5.selectbox("Transmissão", ["Não informado", "Manual", "Automática", "Automatizada", "CVT"], key="frota_transmissao_novo")
                            km = cm6.number_input("KM atual", min_value=0.0, step=100.0, value=0.0)

                            d_inicio = km_ini = d_fim = km_fim = cliente = cnpj_v = tipo_v = None
                            valor_m = multa_c = juros_c = 0.0
                            is_ativo = False
                            
                            if status_novo == "Alugado":
                                st.markdown("---")
                                st.markdown("**Dados do contrato**")
                                c1, c2 = st.columns(2)
                                cliente  = c1.text_input("Razão Social do Cliente")
                                cnpj_v   = c2.text_input("CNPJ")
                                
                                c3, c4   = st.columns(2)
                                d_inicio = c3.date_input("Início do contrato", format="DD/MM/YYYY")
                                km_ini   = c4.number_input("KM na entrega", min_value=0.0, step=50.0, value=0.0)
                                
                                st.markdown("**Dados Financeiros do Contrato**")
                                cf1, cf2 = st.columns(2)
                                tipo_v = cf1.selectbox("Tipo de Cobrança", ["Fixo", "Variável"], key="frota_tipo")
                                valor_m = cf2.number_input("Valor Mensal (R$)", min_value=0.0, step=100.0, value=0.0, disabled=(tipo_v == "Variável"), key="frota_val")
                                
                                cf3, cf4 = st.columns(2)
                                multa_c = cf3.number_input("Multa por Atraso (%)", min_value=0.0, step=1.0, value=2.0, key="frota_mul")
                                juros_c = cf4.number_input("Juros ao Mês (%)", min_value=0.0, step=0.1, value=1.0, key="frota_jur")

                                st.markdown("<br>", unsafe_allow_html=True)
                                is_ativo = st.checkbox("Contrato em andamento", value=True)
                                
                                if not is_ativo:
                                    c5, c6 = st.columns(2)
                                    d_fim  = c5.date_input("Data de devolução", format="DD/MM/YYYY")
                                    km_fim = c6.number_input("KM na devolução", min_value=0.0, step=50.0, value=0.0)

                            if st.button("Salvar Veículo", use_container_width=True):
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
                                            session.add(Contrato(
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
                                                valor_mensal=valor_m if tipo_v == "Fixo" else 0.0,
                                                multa=multa_c, 
                                                juros=juros_c
                                            ))
                                            
                                        session.commit()
                                        session.close()
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
                                df_import = pd.read_excel(arquivo_xls)
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
                                        session.close()

                                        st.success(f"Importação concluída! {sucessos} veículo(s) cadastrado(s) com sucesso. ({erros} ignorados).")
                                        # Atualiza a key do uploader para limpá-lo, o st.rerun() voltará para a aba de Cadastro Individual
                                        st.session_state["uploader_key"] += 1
                                        time.sleep(1.5)
                                        st.rerun()

                            except Exception as e:
                                st.error(f"Erro ao ler o arquivo Excel: {e}", icon=None)

                if st.session_state["perfil"] == "admin" and total > 0:
                    with st.expander("Excluir veículo — Zona restrita"):
                        st.caption("Ação irreversível. Remove o veículo e todo o histórico financeiro.")
                        
                        opcoes_v = {f"{r['modelo']} ({r['placa']})": r["id"] for _, r in df_veiculos.iterrows()}
                        v_excluir = st.selectbox("Veículo para excluir", list(opcoes_v.keys()))
                        confirmar = st.checkbox(f"Confirmo a exclusão permanente de {v_excluir}.")
                        
                        if st.button("Excluir permanentemente", use_container_width=True):
                            if confirmar:
                                session = SessionLocal()
                                vid = opcoes_v[v_excluir]
                                for M in [Custo, Contrato, Veiculo]:
                                    q = session.query(M)
                                    if M is Veiculo: 
                                        q = q.filter(M.id == vid)
                                    else:            
                                        q = q.filter(M.veiculo_id == vid)
                                    q.delete()
                                session.commit()
                                session.close()
                                st.success("Veículo excluído.")
                                st.rerun()
                            else:
                                st.error("Marque a confirmação para prosseguir.", icon=None)

            # ── Aba: Alterar Status ────────────────────────────────────────────────
            with tab_status:
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
                                veiculo = session.get(Veiculo, veiculo_status_id)
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
                                        reserva = session.get(Veiculo, reserva_id)
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
                            except Exception as e:
                                session.rollback()
                                st.error(str(e), icon=None)
                            finally:
                                session.close()

            # ── Aba: Gastos ───────────────────────────────────────────────────────
            with tab_gastos:
                if total == 0:
                    st.info("Nenhum veículo cadastrado.", icon=None) 
                else:
                    df_custos_all = carregar_dados_tabela(f"SELECT * FROM custos WHERE empresa_id={emp_id}", emp_id)
                    
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
                                            fig = px.bar(
                                                df_comb, 
                                                x="Mes_Ano", 
                                                y="valor_total", 
                                                text="valor_total", 
                                                color_discrete_sequence=[PALETTE["green"]]
                                            )
                                            fig.update_traces(texttemplate="R$ %{text:,.0f}", textposition="outside")
                                            fig.update_layout(
                                                **PLOTLY_LAYOUT, 
                                                title_text="Combustível", 
                                                height=220, 
                                                xaxis=dict(title="", type="category"), 
                                                yaxis=dict(visible=False)
                                            )
                                            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                                        else:
                                            st.caption("Sem abastecimentos.")
                                            
                                    with gb:
                                        if not df_outr.empty:
                                            fig = px.bar(
                                                df_outr, 
                                                x="Mes_Ano", 
                                                y="valor_total", 
                                                color="categoria", 
                                                color_discrete_sequence=[PALETTE["indigo"], PALETTE["amber"], PALETTE["slate"]]
                                            )
                                            fig.update_layout(
                                                **PLOTLY_LAYOUT, 
                                                title_text="Manutenção e Outros", 
                                                height=220, 
                                                xaxis=dict(title="", type="category"), 
                                                yaxis=dict(visible=False)
                                            )
                                            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                                        else:
                                            st.caption("Sem outras despesas.")
                                else:
                                    st.caption("Veículo sem histórico financeiro.")

            # ── Aba: Planos de manutenção ─────────────────────────────────────────
            with tab_planos:
                st.markdown("### Planos de manutenção")
                st.caption(
                    "Cadastre o plano uma vez por configuração de veículo e reutilize-o em todas as placas compatíveis. "
                    "O histórico permanece individual por veículo."
                )

                df_planos = carregar_dados_tabela(f"""
                    SELECT id, nome, fabricante, modelo, ano_modelo, versao, motorizacao,
                           combustivel, transmissao, ativo
                    FROM planos_manutencao
                    WHERE empresa_id={emp_id}
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
                            WHERE i.empresa_id={emp_id} AND i.plano_id={int(atual_plano_id)} AND COALESCE(i.ativo,1)=1
                            ORDER BY i.tipo_manutencao
                        """, emp_id)
                    else:
                        df_itens_modelo = pd.DataFrame()

                    if not df_itens_modelo.empty:
                        df_hist_modelo = carregar_dados_tabela(f"""
                            SELECT plano_item_id, data_execucao, km_execucao, id
                            FROM manutencoes_realizadas
                            WHERE empresa_id={emp_id} AND veiculo_id={veiculo_plano_id}
                            ORDER BY id DESC
                        """, emp_id)
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
                            df_pi = pd.read_excel(arquivo_plano_ind, sheet_name="Planos")
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
                        except Exception as e:
                            st.error(f"Não foi possível ler/importar o plano: {e}", icon=None)

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
                            df_pm = pd.read_excel(arquivo_massivo, sheet_name="Planos")
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
                        except Exception as e:
                            st.error(f"Não foi possível ler/importar a planilha: {e}", icon=None)

                with planos_existentes:
                    if df_planos.empty:
                        st.info("Nenhum plano-base cadastrado ainda.", icon=None)
                    else:
                        df_contagem_itens = carregar_dados_tabela(f"""
                            SELECT plano_id, COUNT(*) AS itens
                            FROM itens_plano_manutencao
                            WHERE empresa_id={emp_id} AND COALESCE(ativo,1)=1
                            GROUP BY plano_id
                        """, emp_id)
                        df_contagem_veiculos = carregar_dados_tabela(f"""
                            SELECT plano_manutencao_id AS plano_id, COUNT(*) AS veiculos
                            FROM veiculos
                            WHERE empresa_id={emp_id} AND plano_manutencao_id IS NOT NULL
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
            with tab_saude:
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
            page_header(
                "Gestão de Custos",
                "Registre despesas e gerencie os lançamentos financeiros da frota."
            )

            df_veiculos = carregar_dados_tabela(f"""
                SELECT id, placa, modelo, km_atual, status, plano_manutencao_id
                FROM veiculos
                WHERE empresa_id={emp_id}
                ORDER BY modelo, placa
            """, emp_id)

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

                tab_lancar, tab_lancamentos = st.tabs([
                    "Registrar despesa",
                    "Lançamentos financeiros"
                ])

                # ──────────────────────────────────────────────────────────────
                # REGISTRAR DESPESA
                # ──────────────────────────────────────────────────────────────
                with tab_lancar:
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
                            key="custos_categoria"
                        )

                        veiculo_sel = c2.selectbox(
                            "Veículo",
                            list(opcoes_v.keys()),
                            key="custos_veiculo"
                        )

                        data_custo = c3.date_input(
                            "Data",
                            format="DD/MM/YYYY",
                            key="custos_data"
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

                        d1, d2, d3 = st.columns([1, 1, 1])

                        valor = d1.number_input(
                            "Valor total (R$)",
                            min_value=0.01,
                            step=10.0,
                            value=0.01,
                            key="custos_valor"
                        )

                        km_atual = d2.number_input(
                            "KM no momento",
                            min_value=0.0,
                            step=50.0,
                            value=km_cadastrado,
                            key=f"custos_km_{veiculo_id_sel}"
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
                                key="custos_litros"
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
                                    WHERE empresa_id={emp_id} AND plano_id={int(plano_id_veiculo)} AND COALESCE(ativo,1)=1
                                    ORDER BY tipo_manutencao
                                """, emp_id)
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
                                    key="custos_tipo_manutencao"
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
                                    key="custos_tipo_manutencao_livre"
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
                            key="custos_descricao"
                        )

                        st.markdown("---")

                        p1, p2 = st.columns(2)

                        forma_pag = p1.selectbox(
                            "Forma de pagamento",
                            FORMAS_PAGAMENTO,
                            key="custos_forma_pagamento"
                        )

                        motorista = p2.text_input(
                            "Motorista responsável (opcional)",
                            key="custos_motorista"
                        )

                        condicao_pag = None
                        parcelas_q = None

                        if forma_pag == "Cartão de Crédito":
                            pc1, pc2 = st.columns(2)

                            condicao_pag = pc1.radio(
                                "Condição",
                                ["À vista", "Parcelado"],
                                horizontal=True,
                                key="custos_condicao_pagamento"
                            )

                            if condicao_pag == "Parcelado":
                                parcelas_q = pc2.number_input(
                                    "Nº de parcelas",
                                    min_value=2,
                                    max_value=48,
                                    step=1,
                                    value=2,
                                    key="custos_parcelas"
                                )

                        st.markdown("**Comprovante**")
                        arquivo = st.file_uploader(
                            "Anexar imagem ou PDF",
                            type=["png", "jpg", "jpeg", "pdf"],
                            label_visibility="collapsed",
                            key="custos_comprovante"
                        )

                        acao_col1, acao_col2 = st.columns([4, 1.2])

                        with acao_col2:
                            salvar_custo = st.button(
                                "Registrar despesa",
                                icon=":material/add_card:",
                                use_container_width=True,
                                key="btn_registrar_custo"
                            )

                        if salvar_custo:
                            km_val = float(km_atual or 0.0)
                            session = SessionLocal()

                            try:
                                veiculo_db = session.get(
                                    Veiculo,
                                    veiculo_id_sel
                                )

                                if veiculo_db is None:
                                    st.error(
                                        "O veículo selecionado não foi encontrado.",
                                        icon=None
                                    )

                                else:
                                    comp_path = None

                                    if arquivo:
                                        ext = arquivo.name.rsplit(".", 1)[-1]
                                        comp_path = os.path.join(
                                            "comprovantes",
                                            f"comp_{uuid.uuid4().hex[:8]}.{ext}"
                                        )

                                        with open(comp_path, "wb") as f:
                                            f.write(arquivo.getbuffer())

                                    custo_manutencao_base_id = None

                                    if (
                                        forma_pag == "Cartão de Crédito"
                                        and condicao_pag == "Parcelado"
                                        and parcelas_q
                                    ):
                                        valor_parcela = valor / parcelas_q

                                        for i in range(int(parcelas_q)):
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

                                            custo_parcela = Custo(
                                                empresa_id=emp_id,
                                                veiculo_id=veiculo_db.id,
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
                                        custo_unico = Custo(
                                            empresa_id=emp_id,
                                            veiculo_id=veiculo_db.id,
                                            data_custo=data_custo,
                                            categoria=cat,
                                            descricao=descricao,
                                            valor_total=valor,
                                            km_momento=km_val,
                                            litros=litros,
                                            usuario_lancamento=(
                                                st.session_state["nome"]
                                            ),
                                            forma_pagamento=forma_pag,
                                            condicao_pagamento=condicao_pag,
                                            parcelas=parcelas_q,
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

                                    session.commit()
                                    st.cache_data.clear()
                                    st.success(
                                        "Despesa registrada com sucesso."
                                    )
                                    time.sleep(0.5)
                                    st.rerun()

                            except Exception:
                                session.rollback()
                                st.error(
                                    "Não foi possível registrar a despesa.",
                                    icon=None
                                )

                            finally:
                                session.close()

                # ──────────────────────────────────────────────────────────────
                # LANÇAMENTOS FINANCEIROS
                # ──────────────────────────────────────────────────────────────
                with tab_lancamentos:
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
                            c.motorista,
                            c.comprovante,
                            c.usuario_lancamento
                        FROM custos c
                        JOIN veiculos v
                            ON c.veiculo_id = v.id
                        WHERE c.empresa_id = {emp_id}
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

                            filtros1, filtros2, filtros3, filtros4 = st.columns(
                                [1, 1.25, 1.15, 1]
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

                            df_filtrado = df_custos.copy()
                            hoje_custos = date.today()

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
                                    "motorista",
                                    "Comprovante"
                                ]].rename(columns={
                                    "categoria": "Categoria",
                                    "descricao": "Descrição",
                                    "motorista": "Motorista"
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

                                        if caminho and os.path.exists(
                                            caminho
                                        ):
                                            if caminho.lower().endswith(
                                                ".pdf"
                                            ):
                                                with open(
                                                    caminho,
                                                    "rb"
                                                ) as f:
                                                    st.download_button(
                                                        "Baixar PDF",
                                                        f,
                                                        os.path.basename(
                                                            caminho
                                                        ),
                                                        "application/pdf",
                                                        key=(
                                                            "custos_baixar_pdf"
                                                        )
                                                    )
                                            else:
                                                st.image(
                                                    caminho,
                                                    use_container_width=True
                                                )
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

                                                custo_db = session.get(
                                                    Custo,
                                                    custo_id
                                                )

                                                if custo_db is None:
                                                    st.warning(
                                                        "O lançamento "
                                                        "selecionado não foi "
                                                        "encontrado.",
                                                        icon=None
                                                    )

                                                else:
                                                    historicos_vinculados = session.query(ManutencaoRealizada).filter(
                                                        ManutencaoRealizada.empresa_id == emp_id,
                                                        ManutencaoRealizada.custo_id == custo_db.id
                                                    ).all()
                                                    for historico in historicos_vinculados:
                                                        session.delete(historico)
                                                    session.delete(custo_db)
                                                    session.commit()
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
            page_header("Contas a Receber", "Módulo de faturamento, boletos e inadimplência.")

            tab_mensal, tab_cadastro = st.tabs(["Painel do Mês Atual", "Contratos Recorrentes"])

            with tab_mensal:
                meses = [(date.today().replace(day=1) + timedelta(days=31 * i)).strftime("%m/%Y") for i in range(-2, 4)]
                mes_sel = st.selectbox("Competência", meses, index=2)

                session = SessionLocal()

                if st.button(f"Sincronizar Recorrências de {mes_sel}", use_container_width=True):
                    recorrentes = session.query(CobrancaRecorrente).filter_by(empresa_id=emp_id).all()
                    novos = 0
                    for rec in recorrentes:
                        existe = session.query(CobrancaMensal).filter_by(empresa_id=emp_id, mes_ano=mes_sel, cliente=rec.cliente, tipo="Recorrente").first()
                        if not existe:
                            try: 
                                vf = float(rec.valor_mensal.replace("R$", "").replace(".", "").replace(",", ".").strip())
                            except: 
                                vf = 0.0
                            
                            ano, mes = map(int, reversed(mes_sel.split("/")))
                            
                            session.add(CobrancaMensal(
                                empresa_id=emp_id, 
                                mes_ano=mes_sel, 
                                tipo="Recorrente", 
                                cliente=rec.cliente, 
                                forma_cobranca=rec.forma_cobranca,
                                valor_previsto=vf, 
                                emissao_prevista=get_valid_date(ano, mes, rec.data_base_emissao.day), 
                                vencimento=get_valid_date(ano, mes, rec.data_base_vencimento.day), 
                                status="Pendente", 
                                observacoes=rec.observacoes
                            ))
                            novos += 1
                            
                    session.commit()
                    if novos: 
                        st.success(f"{novos} faturas alocadas na grade.")
                    else:     
                        st.info("Grade já atualizada com as recorrências ativas.", icon=None)

                df_mensal = carregar_dados_tabela(f"SELECT * FROM cobrancas_mensais WHERE empresa_id={emp_id} AND mes_ano='{mes_sel}'", emp_id)

                if df_mensal.empty:
                    with st.container(border=True): 
                        st.info("Sem previsões para este mês. Sincronize a grade.", icon=None)
                else:
                    tot = df_mensal["valor_previsto"].sum()
                    k1, k2, k3, k4, k5 = st.columns([1.5, 1, 1, 1, 1])
                    k1.metric("Previsão Total", fmt_brl(tot))
                    k2.metric("Aguardando", len(df_mensal[df_mensal["status"] == "Pendente"]))
                    k3.metric("Faturadas", len(df_mensal[df_mensal["status"] == "Emitida"]))
                    k4.metric("Liquidadas", len(df_mensal[df_mensal["status"] == "Recebida"]))
                    with k5:
                        csv_m = convert_df_to_csv(df_mensal[["tipo","cliente","forma_cobranca","valor_previsto","status"]])
                        st.download_button("Baixar Dados", csv_m, f"fat_{mes_sel.replace('/','_')}.csv", use_container_width=True)

                    COL_CONFIG = lambda label_val: {
                        "id": None, 
                        "cliente": st.column_config.TextColumn("Cliente", disabled=True), 
                        "forma_cobranca": st.column_config.TextColumn("Via", disabled=True),
                        "valor_previsto": st.column_config.NumberColumn(label_val, format="%.2f"), 
                        "emissao_prevista": st.column_config.DateColumn("D. Emissão", disabled=True),
                        "vencimento": st.column_config.DateColumn("Vencimento", disabled=True), 
                        "status": st.column_config.SelectboxColumn("Status", options=["Pendente","Emitida","Recebida"]),
                        "data_emissao": st.column_config.DateColumn("NF/Boleto Emitido"), 
                        "num_boleto": st.column_config.TextColumn("Código"),
                        "data_recebimento": st.column_config.DateColumn("Liquidação"), 
                        "observacoes": st.column_config.TextColumn("Notas internas"),
                    }
                    
                    COLS_EDIT = ["id","cliente","forma_cobranca","valor_previsto","emissao_prevista","vencimento","data_emissao","num_boleto","status","data_recebimento","observacoes"]

                    st.markdown("**Matriz de Faturamento Fixo**")
                    df_rec = df_mensal[df_mensal["tipo"] == "Recorrente"].copy()
                    ed_rec = st.data_editor(df_rec[COLS_EDIT], column_config=COL_CONFIG("R$ Previsto"), use_container_width=True, hide_index=True, key="ed_rec") if not df_rec.empty else None

                    st.markdown("**Serviços Extras e Locações Pontuais**")
                    df_pont = df_mensal[df_mensal["tipo"] == "Pontual"].copy()
                    ed_pont = st.data_editor(df_pont[COLS_EDIT], column_config=COL_CONFIG("R$ Previsto"), use_container_width=True, hide_index=True, key="ed_pont") if not df_pont.empty else None

                    if st.button("Gravar status da matriz", use_container_width=True):
                        for ed, _ in [(ed_rec, df_rec), (ed_pont, df_pont)]:
                            if ed is not None:
                                for _, row in ed.iterrows():
                                    cob = session.get(CobrancaMensal, row["id"])
                                    for campo in ["valor_previsto","data_emissao","num_boleto","status","data_recebimento","observacoes"]: 
                                        setattr(cob, campo, row[campo])
                        session.commit()
                        st.success("Atualização concluída.")
                        st.rerun()

                with st.expander("Inserir fatura avulsa nesta competência"):
                    pc1, pc2 = st.columns(2)
                    p_cli  = pc1.text_input("Tomador do Serviço")
                    p_form = pc2.selectbox("Via de Cobrança", ["Boleto","Nota fiscal + boleto","Pix","Cartão","Outro"])
                    
                    pc3, pc4, pc5 = st.columns(3)
                    p_val  = pc3.number_input("Valor Fechado (R$)", min_value=0.01, step=10.0)
                    p_emis = pc4.date_input("Agendar Emissão")
                    p_venc = pc5.date_input("Vencimento Limite")
                    
                    p_obs  = st.text_input("Detalhes da operação")

                    if st.button("Lançar Fatura Avulsa", use_container_width=True):
                        if not p_cli: 
                            st.error("O campo Cliente é obrigatório.", icon=None)
                        else:
                            session.add(CobrancaMensal(
                                empresa_id=emp_id, mes_ano=mes_sel, tipo="Pontual", 
                                cliente=p_cli, forma_cobranca=p_form, valor_previsto=p_val, 
                                emissao_prevista=p_emis, vencimento=p_venc, status="Pendente", observacoes=p_obs
                            ))
                            session.commit()
                            st.success("Lançamento adicionado à grade.")
                            st.rerun()
                            
                session.close()

            with tab_cadastro:
                st.info("Cadastre os contratos ativos da empresa. Esses dados atuarão como motor de geração para as matrizes mensais futuras.", icon=None)
                with st.form("form_recorrente", clear_on_submit=True):
                    r1, r2 = st.columns(2)
                    c_cli  = r1.text_input("Razão Social do Cliente")
                    c_form = r2.selectbox("Padrão de Faturamento", ["Boleto","Nota fiscal + boleto","Pix","Cartão","Outro"])
                    
                    r3, r4, r5 = st.columns(3)
                    c_val  = r3.text_input("R$ Mensal", placeholder="Ex: 2000 ou Variável")
                    c_de   = r4.date_input("Dia padrão para NF")
                    c_dv   = r5.date_input("Dia padrão de Corte")
                    
                    c_obs  = st.text_input("Instruções ao financeiro")

                    if st.form_submit_button("Salvar no Motor de Recorrência", use_container_width=True):
                        if not c_cli: 
                            st.error("Razão Social obrigatória.", icon=None)
                        else:
                            session = SessionLocal()
                            session.add(CobrancaRecorrente(
                                empresa_id=emp_id, cliente=c_cli, forma_cobranca=c_form, 
                                valor_mensal=c_val, data_base_emissao=c_de, 
                                data_base_vencimento=c_dv, observacoes=c_obs
                            ))
                            session.commit()
                            session.close()
                            st.success("Motor alimentado.")
                            st.rerun()

                df_rec_all = carregar_dados_tabela(f"SELECT cliente, forma_cobranca, valor_mensal, data_base_emissao, data_base_vencimento, observacoes FROM cobrancas_recorrentes WHERE empresa_id={emp_id}", emp_id)
                
                if not df_rec_all.empty:
                    st.dataframe(df_rec_all.rename(columns={
                        "cliente":"Tomador", "forma_cobranca":"Via", "valor_mensal":"Custo Base", 
                        "data_base_emissao":"Emissão NF", "data_base_vencimento":"Corte", "observacoes":"Notas"
                    }), use_container_width=True, hide_index=True)

        # ══════════════════════════════════════════════════════════════════════════
        # CONTRATOS E LOCAÇÃO
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Contratos e Locação":
            page_header("Gestão de Contratos", "Controle o ciclo de vida comercial da frota e as substituições temporárias.")

            df_veiculos = carregar_dados_tabela(f"""
                SELECT id, placa, modelo, status
                FROM veiculos
                WHERE empresa_id = {emp_id}
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
                INNER JOIN veiculos vp ON c.veiculo_id = vp.id
                LEFT JOIN substituicoes_contrato s
                    ON s.contrato_id = c.id AND s.ativo = 1
                LEFT JOIN veiculos vr
                    ON s.veiculo_substituto_id = vr.id
                WHERE c.empresa_id = {emp_id}
                ORDER BY c.ativo DESC, c.data_inicio DESC
            """, emp_id)

            tab_visao, tab_novo, tab_editar, tab_substituicao = st.tabs([
                "Painel Comercial",
                "Abertura de Contrato",
                "Finalização / Aditivos",
                "Substituição / Manutenção"
            ])

            # ── Aba 1: Visão Geral ────────────────────────────────────────────────
            with tab_visao:
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
                        st.dataframe(
                            df_ativos[[
                                "Cliente", "CNPJ", "Veículo Principal", "Veículo Reserva", "Uso Atual",
                                "Status", "Início", "Fim", "Tipo", "Valor", "Multa (%)", "Juros (%)"
                            ]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                                "Multa (%)": st.column_config.NumberColumn(format="%.2f%%"),
                                "Juros (%)": st.column_config.NumberColumn(format="%.2f%%"),
                            }
                        )

                    if not df_encerrados.empty:
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown("**Arquivo Morto (Contratos Finalizados)**")
                        st.dataframe(
                            df_encerrados[[
                                "Cliente", "CNPJ", "Veículo Principal", "Status", "Início", "Fim", "Tipo", "Valor"
                            ]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={"Valor": st.column_config.NumberColumn(format="R$ %.2f")}
                        )
                else:
                    st.info("Plataforma sem contratos firmados.", icon=None)

            # ── Aba 2: Novo Contrato ──────────────────────────────────────────────
            with tab_novo:
                disponiveis_novo = df_veiculos[df_veiculos["status"] == "Disponível"].copy()
                if disponiveis_novo.empty:
                    st.warning("Não há veículo disponível para abertura de novo contrato.", icon=None)
                else:
                    with st.container(border=True):
                        opcoes_v = {f"{r['modelo']} ({r['placa']})": int(r['id']) for _, r in disponiveis_novo.iterrows()}
                        veiculo_sel = st.selectbox("Ativo a ser alocado", list(opcoes_v.keys()), key="nc_v")

                        ca, cb = st.columns(2)
                        cliente = ca.text_input("Locatário (Razão Social)", key="nc_cliente")
                        cnpj = cb.text_input("Documento (CNPJ/CPF)", key="nc_cnpj")
                        cc, cd = st.columns(2)
                        d_inicio = cc.date_input("Início da Vigência", format="DD/MM/YYYY", key="nc_inicio")
                        km_ini = cd.number_input("Odômetro de Saída", min_value=0.0, step=50.0, value=0.0, key="nc_km_ini")

                        st.markdown("---")
                        st.markdown("**Acordo Comercial**")
                        ce, cf = st.columns(2)
                        tipo_v = ce.selectbox("Formato de Receita", ["Fixo", "Variável"], key="nc_tipo")
                        valor_m = cf.number_input("Mensalidade (R$)", min_value=0.0, step=100.0, value=0.0, disabled=(tipo_v == "Variável"), key="nc_valor")
                        cg, ch = st.columns(2)
                        multa_c = cg.number_input("Cláusula de Atraso - Multa (%)", min_value=0.0, step=1.0, value=2.0, key="nc_multa")
                        juros_c = ch.number_input("Cláusula de Atraso - Juros/Mês (%)", min_value=0.0, step=0.1, value=1.0, key="nc_juros")

                        if st.button("Efetivar Alocação", use_container_width=True, key="btn_novo_contrato"):
                            if not cliente.strip():
                                st.error("Identificação do Locatário obrigatória.", icon=None)
                            else:
                                session = SessionLocal()
                                try:
                                    veiculo = session.get(Veiculo, opcoes_v[veiculo_sel])
                                    if veiculo is None or veiculo.status != "Disponível":
                                        raise ValueError("O veículo selecionado não está mais disponível.")

                                    contrato = Contrato(
                                        empresa_id=emp_id, veiculo_id=veiculo.id, cliente=cliente.strip(), cnpj=cnpj.strip(),
                                        data_inicio=d_inicio, data_fim=None, km_inicial=km_ini, km_final=0.0, ativo=1,
                                        usuario_lancamento=st.session_state["nome"], tipo_valor=tipo_v,
                                        valor_mensal=valor_m if tipo_v == "Fixo" else 0.0, multa=multa_c, juros=juros_c
                                    )
                                    session.add(contrato)
                                    veiculo.status = "Alugado"
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Contrato consolidado na base!")
                                    time.sleep(0.7)
                                    st.rerun()
                                except Exception as e:
                                    session.rollback()
                                    st.error(str(e), icon=None)
                                finally:
                                    session.close()

            # ── Aba 3: Editar / Encerrar Contrato ─────────────────────────────────
            with tab_editar:
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
                            e_dfim = ee.date_input("Baixa do Contrato", value=date.today() if pd.isna(dt_fim) else dt_fim.date(), key="ec_df")
                            e_kmfim = ef.number_input("Odômetro de Chegada", min_value=0.0, step=50.0, value=e_kmfim, key="ec_kmf")

                        st.markdown("---")
                        eg, eh = st.columns(2)
                        e_tipo = eg.selectbox("Formato de Receita", ["Fixo", "Variável"], index=0 if row_ct["tipo_valor"] == "Fixo" else 1, key="ec_t")
                        e_val = eh.number_input("Mensalidade (R$)", min_value=0.0, step=100.0, value=float(row_ct["valor_mensal"] or 0), disabled=(e_tipo == "Variável"), key="ec_v")
                        ei, ej = st.columns(2)
                        e_multa = ei.number_input("Cláusula de Multa (%)", min_value=0.0, step=1.0, value=float(row_ct["multa"] or 0), key="ec_m")
                        e_juros = ej.number_input("Cláusula de Juros (%)", min_value=0.0, step=0.1, value=float(row_ct["juros"] or 0), key="ec_j")

                        b1, b2 = st.columns(2)
                        if b1.button("Assinar Aditivo (Salvar)", use_container_width=True, key="btn_salvar_contrato"):
                            session = SessionLocal()
                            try:
                                contrato = session.get(Contrato, ct_id)
                                if contrato is None:
                                    raise ValueError("Contrato não encontrado.")

                                contrato.cliente = e_cliente.strip()
                                contrato.cnpj = e_cnpj.strip()
                                contrato.data_inicio = e_dinicio
                                contrato.tipo_valor = e_tipo
                                contrato.valor_mensal = e_val if e_tipo == "Fixo" else 0.0
                                contrato.multa = e_multa
                                contrato.juros = e_juros

                                principal = session.get(Veiculo, contrato.veiculo_id)
                                sub = session.query(SubstituicaoContrato).filter(
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
                                    if sub is not None:
                                        finalizar_substituicao_contrato(session, sub, status_principal="Disponível")
                                    elif principal is not None:
                                        principal.status = "Disponível"

                                session.commit()
                                st.cache_data.clear()
                                st.success("Base atualizada com sucesso!")
                                time.sleep(0.7)
                                st.rerun()
                            except Exception as e:
                                session.rollback()
                                st.error(str(e), icon=None)
                            finally:
                                session.close()

                        if st.session_state["perfil"] == "admin":
                            if b2.button("Expurgar do Banco de Dados", use_container_width=True, key="btn_excluir_contrato"):
                                session = SessionLocal()
                                try:
                                    contrato = session.get(Contrato, ct_id)
                                    if contrato is None:
                                        raise ValueError("Contrato não encontrado.")
                                    principal = session.get(Veiculo, contrato.veiculo_id)
                                    sub = session.query(SubstituicaoContrato).filter(
                                        SubstituicaoContrato.contrato_id == contrato.id,
                                        SubstituicaoContrato.ativo == 1
                                    ).first()
                                    if sub is not None:
                                        finalizar_substituicao_contrato(session, sub, status_principal="Disponível")
                                    elif principal is not None:
                                        principal.status = "Disponível"
                                    session.query(SubstituicaoContrato).filter(SubstituicaoContrato.contrato_id == contrato.id).delete()
                                    session.delete(contrato)
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Registro removido.")
                                    time.sleep(0.7)
                                    st.rerun()
                                except Exception as e:
                                    session.rollback()
                                    st.error(str(e), icon=None)
                                finally:
                                    session.close()

            # ── Aba 4: Substituição / Manutenção ──────────────────────────────────
            with tab_substituicao:
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
                                    sub = session.get(SubstituicaoContrato, int(sub_row["substituicao_id"]))
                                    if sub is None or sub.ativo != 1:
                                        raise ValueError("A substituição já foi encerrada.")
                                    finalizar_substituicao_contrato(session, sub, status_principal="Alugado")
                                    session.commit()
                                    st.cache_data.clear()
                                    st.success("Veículo principal retornou ao contrato e o reserva foi liberado.")
                                    time.sleep(0.7)
                                    st.rerun()
                                except Exception as e:
                                    session.rollback()
                                    st.error(str(e), icon=None)
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
                                        contrato = session.get(Contrato, sub_ct_id)
                                        principal = session.get(Veiculo, contrato.veiculo_id) if contrato else None
                                        reserva = session.get(Veiculo, opcoes_reserva_ct[reserva_ct_label])
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
                                    except Exception as e:
                                        session.rollback()
                                        st.error(str(e), icon=None)
                                    finally:
                                        session.close()

                        st.markdown("---")
                        historico = carregar_dados_tabela(f"""
                            SELECT
                                s.data_inicio, s.data_fim, s.ativo,
                                vp.placa AS principal, vr.placa AS reserva,
                                c.cliente, s.usuario_lancamento
                            FROM substituicoes_contrato s
                            INNER JOIN contratos c ON c.id = s.contrato_id
                            INNER JOIN veiculos vp ON vp.id = s.veiculo_principal_id
                            INNER JOIN veiculos vr ON vr.id = s.veiculo_substituto_id
                            WHERE s.empresa_id = {emp_id}
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

        # MEU PERFIL (NOVO)
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Meu Perfil":
            page_header("Meu Perfil", "Gerencie seus dados pessoais e de acesso.")
            
            with st.container(border=True):
                c_p1, c_p2 = st.columns([1, 3])
                
                with c_p1:
                    st.markdown("**Foto de Perfil**")
                    if os.path.exists(avatar_path):
                        st.image(avatar_path, use_container_width=True)
                    else:
                        st.info("Sem foto", icon=None)
                        
                    novo_avatar = st.file_uploader("Alterar foto", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
                    if st.button("Salvar Imagem", use_container_width=True):
                        if novo_avatar:
                            with open(avatar_path, "wb") as f:
                                f.write(novo_avatar.getbuffer())
                            st.success("Foto atualizada!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("Nenhuma imagem selecionada.", icon=None)

                with c_p2:
                    st.markdown("**Informações de Apresentação**")
                    with st.form("form_meu_nome"):
                        novo_nome = st.text_input("Nome de Exibição", value=st.session_state['nome'])
                        
                        if st.form_submit_button("Atualizar Nome"):
                            session = SessionLocal()
                            u = session.get(Usuario, st.session_state["usuario_id"])
                            u.nome = novo_nome
                            session.commit()
                            session.close()
                            
                            st.session_state['nome'] = novo_nome
                            st.success("Nome atualizado!")
                            time.sleep(0.5)
                            st.rerun()

                    if st.session_state["perfil"] == "admin":
                        st.markdown("---")
                        st.markdown("**Segurança da Conta**")
                        with st.form("form_minha_senha"):
                            ns1 = st.text_input("Nova Senha", type="password")
                            ns2 = st.text_input("Confirmar Senha", type="password")
                            
                            if st.form_submit_button("Atualizar Senha"):
                                if len(ns1) < 4 or ns1 != ns2:
                                    st.error("As senhas não coincidem ou são curtas demais.", icon=None)
                                else:
                                    session = SessionLocal()
                                    u = session.get(Usuario, st.session_state["usuario_id"])
                                    u.senha = bcrypt.hashpw(ns1.encode(), bcrypt.gensalt()).decode()
                                    session.commit()
                                    session.close()
                                    st.success("Senha alterada com sucesso!")

        # ══════════════════════════════════════════════════════════════════════════
        # POLÍTICA DE PRIVACIDADE E COOKIES
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Política de Privacidade":
            page_header(
                "Política de Privacidade",
                "Transparência sobre o tratamento de dados no ambiente Kineo."
            )

            st.caption("Última atualização: 31 de agosto de 2026")

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
                    "informações cadastrais de empresas e clientes; dados de veículos, quilometragem "
                    "e manutenção; contratos e informações financeiras operacionais; além de arquivos "
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

            if p2.button(
                "Rever aviso de cookies",
                icon=":material/cookie:",
                use_container_width=True,
                key="privacidade_rever_cookies"
            ):
                st.session_state["cookies_aviso_visto"] = False
                st.rerun()


        # ══════════════════════════════════════════════════════════════════════════
        # CONFIGURAÇÕES (ADMIN)
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Configurações":
            page_header("Configurações Globais", "Definições administrativas e de segurança do sistema.")

            if st.session_state["perfil"] != "admin":
                st.error("Acesso Negado: Privilégio administrativo requerido.", icon=None)
            else:
                tab_users, tab_logo = st.tabs(["Controle de Acessos", "Branding Institucional"])

                with tab_users:
                    df_users = carregar_dados_tabela(f"SELECT id, nome, login, perfil FROM usuarios WHERE empresa_id={emp_id}", emp_id)
                    st.dataframe(df_users.rename(columns={"nome": "Nome", "login": "Login", "perfil": "Perfil"}).drop(columns=["id"]), use_container_width=True, hide_index=True)

                    sub1, sub2, sub3 = st.tabs(["Nova Credencial", "Gestão de Credencial", "Reset de Fator"])

                    with sub1:
                        with st.form("form_novo_user", clear_on_submit=True):
                            ua, ub = st.columns(2)
                            u_nome   = ua.text_input("Colaborador")
                            u_login  = ub.text_input("Login Sistêmico")
                            u_perfil = st.selectbox("Camada de Acesso", ["operador", "admin"])
                            
                            if st.form_submit_button("Aprovar Credencial", use_container_width=True):
                                if not u_nome or not u_login: 
                                    st.error("Identificação incompleta.", icon=None)
                                else:
                                    session = SessionLocal()
                                    if session.query(Usuario).filter(Usuario.login == u_login).first(): 
                                        st.error("Identificador de login em uso.", icon=None)
                                    else:
                                        h = bcrypt.hashpw(b"PRIMEIROACESSO", bcrypt.gensalt()).decode()
                                        session.add(Usuario(empresa_id=emp_id, nome=u_nome, login=u_login, senha=h, perfil=u_perfil))
                                        session.commit()
                                        session.close()
                                        st.success(f"Permissão concedida. Chave de entrada: PRIMEIROACESSO")
                                        st.rerun()

                    with sub2:
                        opt_u = {f"{r['nome']} ({r['login']})": r["id"] for _, r in df_users.iterrows()}
                        u_sel = st.selectbox("Alvo da modificação", list(opt_u.keys()))
                        
                        if u_sel:
                            uid   = opt_u[u_sel]
                            row_u = df_users[df_users["id"] == uid].iloc[0]
                            e_nom = st.text_input("Nome",  value=row_u["nome"])
                            e_log = st.text_input("Login", value=row_u["login"])
                            e_prf = st.selectbox("Perfil", ["operador","admin"], index=0 if row_u["perfil"]=="operador" else 1)
                            
                            ba, bb = st.columns(2)
                            if ba.button("Salvar Modificação", use_container_width=True):
                                session = SessionLocal()
                                if session.query(Usuario).filter(Usuario.login == e_log, Usuario.id != uid).first(): 
                                    st.error("Conflito de logins na base.", icon=None)
                                else:
                                    u = session.get(Usuario, uid)
                                    u.nome = e_nom
                                    u.login = e_log
                                    u.perfil = e_prf
                                    session.commit()
                                    session.close()
                                    st.success("Atualizado!")
                                    st.rerun()
                                    
                            if bb.button("Revogar Acesso (Excluir)", use_container_width=True):
                                if uid == st.session_state["usuario_id"]: 
                                    st.error("Tentativa de bloqueio sistêmico negada.", icon=None)
                                else:
                                    session = SessionLocal()
                                    session.query(Usuario).filter(Usuario.id == uid).delete()
                                    session.commit()
                                    session.close()
                                    st.success("Acesso revogado.")
                                    st.rerun()

                    with sub3:
                        opt_r = {f"{r['nome']} ({r['login']})": r["id"] for _, r in df_users.iterrows()}
                        u_rst = st.selectbox("Usuário Alvo", list(opt_r.keys()))
                        
                        if st.button("Forçar Chave Padrão", use_container_width=True):
                            session = SessionLocal()
                            u = session.get(Usuario, opt_r[u_rst])
                            u.senha = bcrypt.hashpw(b"PRIMEIROACESSO", bcrypt.gensalt()).decode()
                            session.commit()
                            session.close()
                            st.success(f"Fator de entrada restaurado para as configurações de fábrica.")

                with tab_logo:
                    with st.container(border=True):
                        st.markdown("**Identidade Visual da Empresa**")
                        st.caption("Atualize a Razão Social e o logotipo exibidos na interface.")
                        
                        with st.form("form_branding"):
                            session_nome = SessionLocal()
                            empresa_b = session_nome.get(Empresa, emp_id)
                            nome_atual = empresa_b.nome_fantasia if empresa_b else "Kineo"
                            session_nome.close()
                            
                            novo_nome = st.text_input("Razão Social / Nome de Exibição", value=nome_atual)
                            logo_file = st.file_uploader("Logotipo (Vetor/Imagem)", type=["png","jpg","jpeg"])
                            
                            if st.form_submit_button("Atualizar Plataforma", use_container_width=True):
                                session = SessionLocal()
                                emp = session.get(Empresa, emp_id)
                                emp.nome_fantasia = novo_nome
                                
                                if logo_file:
                                    ext = logo_file.name.rsplit(".", 1)[-1]
                                    path = os.path.join("logos", f"logo_{emp_id}.{ext}")
                                    with open(path, "wb") as f: 
                                        f.write(logo_file.getbuffer())
                                    emp.logo_path = path
                                    
                                session.commit()
                                session.close()
                                
                                st.success("Branding atualizado com sucesso!")
                                time.sleep(0.5)
                                st.rerun()

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
