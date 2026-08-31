import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import engine, SessionLocal, Veiculo, Contrato, Custo, Usuario, Empresa, CobrancaRecorrente, CobrancaMensal
from datetime import date, timedelta
import calendar
import os
import uuid
import bcrypt
import time
import base64

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
    padding: 2rem 2.5rem 2rem; 
    max-width: 1280px; 
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

[data-testid="stAppViewContainer"] > section.main {{
    padding-left: 82px !important;
}}

[data-testid="stSidebar"] .stScrollToBottomContainer > div:first-child {{
    display: flex;
    flex-direction: column;
    min-height: 100vh;
}}

.sidebar-brand-wrapper {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-left: -16px; 
    padding-left: 17px; 
    width: {SIDEBAR_WIDTH}; 
    margin-bottom: 1rem;
    padding-top: 1.5rem;
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

.sidebar-brand-text span {{ 
    color: #94A3B8; 
    font-size: 0.75rem; 
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

def toggle_pin():
    st.session_state["sidebar_pinned"] = not st.session_state["sidebar_pinned"]

def efetuar_logout():
    st.session_state["autenticado"] = False
    st.session_state["tela_config"] = False


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
                    <span>Gestão de Frotas</span>
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
                    <span>Gestão de Frotas</span>
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


    with st.spinner("Processando..."):

        # ══════════════════════════════════════════════════════════════════════════
        # PAINEL GERENCIAL
        # ══════════════════════════════════════════════════════════════════════════
        if tela_ativa == "Painel Gerencial":
            page_header("Painel Gerencial", "Resumo financeiro e operacional do período.")

            hoje          = date.today()
            mes_atual_str = hoje.strftime("%m/%Y")
            limite_dias   = hoje + timedelta(days=15)

            df_status    = carregar_dados_tabela(f"SELECT status, count(id) as qtd FROM veiculos WHERE empresa_id={emp_id} GROUP BY status", emp_id)
            df_custos    = carregar_dados_tabela(f"SELECT data_custo, categoria, valor_total FROM custos WHERE empresa_id={emp_id}", emp_id)
            df_cobrancas = carregar_dados_tabela(f"SELECT mes_ano, valor_previsto, status, vencimento FROM cobrancas_mensais WHERE empresa_id={emp_id}", emp_id)

            # ── Alertas ──────────────────────────────────────────────────────────
            alertas = []
            
            df_cont = carregar_dados_tabela(f"""
                SELECT v.placa, c.cliente, c.data_fim
                FROM contratos c JOIN veiculos v ON c.veiculo_id=v.id
                WHERE c.empresa_id={emp_id} AND c.ativo=1 AND c.data_fim IS NOT NULL
            """, emp_id)
            
            if not df_cont.empty:
                df_cont["data_fim"] = pd.to_datetime(df_cont["data_fim"]).dt.date
                for _, r in df_cont[(df_cont["data_fim"] >= hoje) & (df_cont["data_fim"] <= limite_dias)].iterrows():
                    dias = (r["data_fim"] - hoje).days
                    alertas.append(f"Contrato de **{r['placa']}** ({r['cliente']}) encerra em **{dias} dia(s)**.")

            df_v_km = carregar_dados_tabela(f"SELECT id, placa, km_atual FROM veiculos WHERE empresa_id={emp_id} AND km_atual>0", emp_id)
            
            df_manu = carregar_dados_tabela(f"""
                SELECT veiculo_id, MAX(km_momento) as ultimo_km FROM custos
                WHERE empresa_id={emp_id} AND categoria='Manutenção Preventiva' GROUP BY veiculo_id
            """, emp_id)
            
            for _, v in df_v_km.iterrows():
                ultimo_km = 0
                if not df_manu.empty and v["id"] in df_manu["veiculo_id"].values:
                    ultimo_km = df_manu[df_manu["veiculo_id"] == v["id"]]["ultimo_km"].values[0]
                
                km_rodado = v["km_atual"] - ultimo_km
                if km_rodado >= 9500:
                    alertas.append(f"Veículo **{v['placa']}** rodou **{km_rodado:,.0f} km** sem revisão preventiva.")

            if alertas:
                with st.container(border=True):
                    st.markdown("**Atenção Operacional**")
                    for a in alertas:
                        st.warning(a, icon=None)

            # ── KPIs ─────────────────────────────────────────────────────────────
            veiculos_totais = df_status['qtd'].sum() if not df_status.empty else 0
            veiculos_alugados = df_status[df_status['status'] == 'Alugado']['qtd'].sum() if not df_status.empty else 0
            taxa_ocupacao = (veiculos_alugados / veiculos_totais * 100) if veiculos_totais > 0 else 0
            
            custos_mes_atual = 0.0
            if not df_custos.empty:
                df_custos['mes_ano'] = pd.to_datetime(df_custos['data_custo']).dt.strftime('%m/%Y')
                custos_mes_atual = df_custos[df_custos['mes_ano'] == mes_atual_str]['valor_total'].sum()
                
            faturamento_mes_atual = 0.0
            inadimplencia_qtd = 0
            
            if not df_cobrancas.empty:
                faturamento_mes_atual = df_cobrancas[df_cobrancas['mes_ano'] == mes_atual_str]['valor_previsto'].sum()
                df_cobrancas['vencimento'] = pd.to_datetime(df_cobrancas['vencimento']).dt.date
                inadimplencia_qtd = len(df_cobrancas[(df_cobrancas['status'] == 'Pendente') & (df_cobrancas['vencimento'] < hoje)])
                
            saldo_mes = faturamento_mes_atual - custos_mes_atual

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Frota Total", veiculos_totais)
            c2.metric("Taxa de Ocupação", f"{taxa_ocupacao:.1f}%")
            c3.metric("Faturamento (Mês)", fmt_brl(faturamento_mes_atual))
            c4.metric("Despesas (Mês)", fmt_brl(custos_mes_atual))
            
            cor_saldo = "normal" if saldo_mes >= 0 else "inverse"
            c5.metric(
                "Saldo Líquido", 
                fmt_brl(saldo_mes), 
                delta=f"{inadimplencia_qtd} Atrasos", 
                delta_color="inverse" if inadimplencia_qtd > 0 else "off"
            )

            # ── Gráficos ─────────────────────────────────────────────────────────
            g1, g2 = st.columns(2)

            with g1:
                with st.container(border=True):
                    st.markdown("**Disponibilidade da Frota**")
                    if not df_status.empty:
                        fig = px.pie(
                            df_status, 
                            names="status", 
                            values="qtd", 
                            hole=0.6,
                            color_discrete_sequence=[PALETTE["indigo"], PALETTE["green"], PALETTE["slate"]]
                        )
                        fig.update_traces(textposition="outside", textinfo="label+percent")
                        fig.update_layout(**PLOTLY_LAYOUT, height=220, showlegend=False)
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.info("Nenhum veículo cadastrado.", icon=None)

            with g2:
                with st.container(border=True):
                    st.markdown("**Despesas por Categoria**")
                    if not df_custos.empty:
                        df_cat = df_custos.groupby("categoria")["valor_total"].sum().reset_index().sort_values("valor_total")
                        fig = px.bar(
                            df_cat, 
                            x="valor_total", 
                            y="categoria", 
                            orientation="h",
                            text="valor_total", 
                            color_discrete_sequence=[PALETTE["indigo"]]
                        )
                        fig.update_traces(texttemplate="R$ %{text:,.0f}", textposition="outside")
                        fig.update_layout(**PLOTLY_LAYOUT, height=220, xaxis=dict(visible=False), yaxis_title="")
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.info("Nenhuma despesa registrada.", icon=None)

            # ── Fluxo de caixa ────────────────────────────────────────────────────
            with st.container(border=True):
                st.markdown("**Fluxo de Caixa Mensal (Faturamento vs Despesas)**")
                frames = []
                
                if not df_custos.empty:
                    dc = df_custos.groupby("mes_ano")["valor_total"].sum().reset_index()
                    dc.columns = ["mes_ano", "Valor"]
                    dc["Tipo"] = "Despesas"
                    frames.append(dc)
                    
                if not df_cobrancas.empty:
                    df_cob_g = df_cobrancas.groupby("mes_ano")["valor_previsto"].sum().reset_index()
                    df_cob_g.columns = ["mes_ano", "Valor"]
                    df_cob_g["Tipo"] = "Faturamento"
                    frames.append(df_cob_g)

                if frames:
                    df_fluxo = pd.concat(frames)
                    df_fluxo["sort"] = pd.to_datetime(df_fluxo["mes_ano"], format="%m/%Y")
                    df_fluxo = df_fluxo.sort_values("sort")
                    
                    fig = px.bar(
                        df_fluxo, 
                        x="mes_ano", 
                        y="Valor", 
                        color="Tipo", 
                        barmode="group",
                        color_discrete_map={"Faturamento": PALETTE["green"], "Despesas": PALETTE["red"]},
                        text="Valor"
                    )
                    fig.update_traces(texttemplate="R$ %{text:,.0f}", textposition="outside")
                    fig.update_layout(
                        **PLOTLY_LAYOUT, 
                        height=280,
                        xaxis=dict(title="", type="category"),
                        yaxis=dict(visible=False),
                        legend=dict(title="", orientation="h", y=1.08, x=1, xanchor="right")
                    )
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("Nenhum dado financeiro para exibir.", icon=None)

        # ══════════════════════════════════════════════════════════════════════════
        # GESTÃO DE FROTA
        # ══════════════════════════════════════════════════════════════════════════
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
            
            tab_admin, tab_gastos, tab_saude = st.tabs(["Cadastro de veículos", "Análise de gastos", "Saúde da frota"])

            # ── Aba: Cadastro ─────────────────────────────────────────────────────
            with tab_admin:
                col_cad_tipo1, col_cad_tipo2 = st.tabs(["Cadastro Individual", "Importação em Massa (.xls / .xlsx)"])

                with col_cad_tipo1:
                    with st.container(border=True):
                        st.markdown("**Adicionar Novo Veículo**")
                        status_novo = st.selectbox("Status inicial", ["Disponível", "Alugado", "Manutenção"])
                        
                        with st.container():
                            ca, cb = st.columns(2)
                            placa  = ca.text_input("Placa", placeholder="ABC-1234")
                            modelo = cb.text_input("Modelo", placeholder="Ex: Fiat Cronos")
                            km     = st.number_input("KM atual", min_value=0.0, step=100.0, value=0.0)

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
                                            modelo=modelo, 
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

                        arquivo_xls = st.file_uploader("Selecione o arquivo Excel (.xls ou .xlsx)", type=["xls", "xlsx"])

                        if arquivo_xls:
                            try:
                                df_import = pd.read_excel(arquivo_xls)
                                # Normaliza colunas para minúsculas e remove espaços
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

                                            # Trata o KM: se não houver ou for nulo/inválido, considera 0.0
                                            km_val = 0.0
                                            if "km" in df_import.columns:
                                                try:
                                                    val_k = row["km"]
                                                    if pd.notna(val_k):
                                                        km_val = float(val_k)
                                                except:
                                                    km_val = 0.0

                                            # Verifica se a placa já existe para esta empresa
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

                                        st.success(f"Importação concluída! {sucessos} veículo(s) cadastrado(s) com sucesso. ({erros} linha(s) ignoradas por dados incompletos).")
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

            # ── Aba: Saúde ────────────────────────────────────────────────────────
            with tab_saude:
                if total == 0:
                    st.info("Nenhum veículo cadastrado.", icon=None)
                else:
                    ch1, ch2 = st.columns([4, 1])
                    ch1.markdown("**Diagnóstico de revisões preventivas**")
                    with ch2:
                        csv_f = convert_df_to_csv(df_veiculos[["placa", "modelo", "km_atual", "status"]])
                        st.download_button("Exportar frota", csv_f, "frota.csv", "text/csv", use_container_width=True)

                    df_custos_all = carregar_dados_tabela(f"SELECT * FROM custos WHERE empresa_id={emp_id}", emp_id)
                    saude = []
                    
                    for _, v in df_veiculos.iterrows():
                        cv = df_custos_all[df_custos_all["veiculo_id"] == v["id"]]
                        gasto_manut = cv[cv["categoria"].str.contains("Manutenção", na=False)]["valor_total"].sum() if not cv.empty else 0
                        gasto_comb  = cv[cv["categoria"] == "Combustível"]["valor_total"].sum() if not cv.empty else 0

                        km_mes = 0.0
                        if not cv.empty and cv["km_momento"].max() > 0:
                            min_dt = pd.to_datetime(cv["data_custo"]).min().date()
                            dias   = max((date.today() - min_dt).days, 1)
                            km_rod = cv["km_momento"].max() - cv[cv["km_momento"] > 0]["km_momento"].min()
                            if km_rod > 0: 
                                km_mes = (km_rod / dias) * 30

                        df_m      = cv[cv["categoria"] == "Manutenção Preventiva"]
                        ult_km_m  = df_m["km_momento"].max() if not df_m.empty else 0
                        km_rev    = v["km_atual"] - ult_km_m
                        status_s  = "URGENTE" if km_rev >= 9500 else ("ATENÇÃO" if km_rev >= 8000 else "OK")

                        saude.append({
                            "Placa":        v["placa"],
                            "Modelo":         v["modelo"],
                            "KM Atual":        int(v["km_atual"]),
                            "KM s/ revisão":   int(km_rev),
                            "Saúde":         status_s,
                            "Média KM/mês":    int(km_mes),
                            "Manutenção (R$)": round(gasto_manut, 2),
                            "Combustível (R$)": round(gasto_comb, 2),
                        })

                    df_saude = pd.DataFrame(saude)

                    def cor_saude(v):
                        return ("color:#065F46;background:#D1FAE5;font-weight:600;" if v == "OK"
                                else "color:#92400E;background:#FEF3C7;font-weight:600;" if v == "ATENÇÃO"
                                else "color:#991B1B;background:#FEE2E2;font-weight:600;")

                    if hasattr(df_saude.style, "map"): 
                        styled = df_saude.style.map(cor_saude, subset=["Saúde"])
                    else: 
                        styled = df_saude.style.applymap(cor_saude, subset=["Saúde"])

                    styled = styled.format({
                        "Manutenção (R$)":  "{:.2f}",
                        "Combustível (R$)": "{:.2f}",
                    })
                    
                    st.dataframe(styled, use_container_width=True, hide_index=True)

        # ══════════════════════════════════════════════════════════════════════════
        # GESTÃO DE CUSTOS
        # ══════════════════════════════════════════════════════════════════════════
        elif tela_ativa == "Gestão de Custos":
            page_header("Gestão de Custos", "Registre e acompanhe todas as despesas da frota.")

            df_veiculos = carregar_dados_tabela(f"SELECT id, placa, modelo FROM veiculos WHERE empresa_id={emp_id}", emp_id)
            if df_veiculos.empty:
                st.warning("Cadastre ao menos um veículo antes de registrar custos.", icon=None)
            else:
                opcoes_v = {f"{r['modelo']} ({r['placa']})": r["id"] for _, r in df_veiculos.iterrows()}

                with st.expander("Registrar nova despesa", expanded=True):
                    CATEGORIAS = [
                        "Combustível", "Manutenção Preventiva", "Manutenção Corretiva",
                        "Custos com Motorista", "Impostos/Documentação", "Multas", "Outros"
                    ]
                    cat = st.selectbox("Categoria", CATEGORIAS)

                    ca, cb, cc = st.columns(3)
                    veiculo_sel = ca.selectbox("Veículo", list(opcoes_v.keys()))
                    data_custo  = cb.date_input("Data (Compra ou 1ª Parcela)", format="DD/MM/YYYY")
                    km_atual    = cc.number_input("KM no momento", min_value=0.0, step=50.0, value=0.0)

                    cd, ce, cf = st.columns(3)
                    valor      = cd.number_input("Valor total (R$)", min_value=0.01, step=10.0, value=0.01)
                    descricao = ce.text_input("Descrição do serviço/peça")
                    litros    = cf.number_input("Litros abastecidos", min_value=0.1, step=5.0, value=0.1) if cat == "Combustível" else None

                    st.markdown("---")
                    cg, ch = st.columns(2)
                    forma_pag = cg.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "PR", "Cartão de Crédito"])
                    motorista = ch.text_input("Motorista responsável (opcional)")

                    condicao_pag = parcelas_q = None
                    if forma_pag == "Cartão de Crédito":
                        ci, cj = st.columns(2)
                        condicao_pag = ci.radio("Condição", ["À vista", "Parcelado"], horizontal=True)
                        if condicao_pag == "Parcelado":
                            parcelas_q = cj.number_input("Nº de parcelas", min_value=2, max_value=48, step=1)

                    arquivo = st.file_uploader("Anexar Comprovante (Imagem/PDF)", type=["png", "jpg", "jpeg", "pdf"])

                    if st.button("Lançar Despesa no Sistema", use_container_width=True):
                        km_val = km_atual or 0.0
                        session = SessionLocal()
                        v = session.get(Veiculo, opcoes_v[veiculo_sel])
                        
                        if km_val > 0 and km_val < v.km_atual:
                            st.error(f"KM não pode ser menor que o atual ({int(v.km_atual)} km).", icon=None)
                            session.close()
                        else:
                            comp_path = None
                            if arquivo:
                                ext = arquivo.name.rsplit(".", 1)[-1]
                                comp_path = os.path.join("comprovantes", f"comp_{uuid.uuid4().hex[:8]}.{ext}")
                                with open(comp_path, "wb") as f: 
                                    f.write(arquivo.getbuffer())

                            if forma_pag == "Cartão de Crédito" and condicao_pag == "Parcelado" and parcelas_q:
                                vp = valor / parcelas_q
                                for i in range(parcelas_q):
                                    dt_p = add_months(data_custo, i)
                                    desc_p = f"{descricao} (Parcela {i+1}/{parcelas_q})" if descricao else f"Parcela {i+1}/{parcelas_q}"
                                    session.add(Custo(
                                        empresa_id=emp_id, veiculo_id=v.id, data_custo=dt_p,
                                        categoria=cat, descricao=desc_p, valor_total=vp,
                                        km_momento=km_val if i == 0 else 0, litros=litros if i == 0 else None,
                                        usuario_lancamento=st.session_state["nome"],
                                        forma_pagamento=forma_pag, condicao_pagamento=condicao_pag,
                                        parcelas=parcelas_q, motorista=motorista,
                                        comprovante=comp_path if i == 0 else None
                                    ))
                            else:
                                session.add(Custo(
                                    empresa_id=emp_id, veiculo_id=v.id, data_custo=data_custo,
                                    categoria=cat, descricao=descricao, valor_total=valor,
                                    km_momento=km_val, litros=litros,
                                    usuario_lancamento=st.session_state["nome"],
                                    forma_pagamento=forma_pag, condicao_pagamento=condicao_pag,
                                    parcelas=parcelas_q, motorista=motorista, comprovante=comp_path
                                ))

                            if km_val > v.km_atual: 
                                v.km_atual = km_val
                                
                            session.commit()
                            session.close()
                            st.success("Lançamento efetuado!")
                            time.sleep(0.8)
                            st.rerun()

                if st.session_state["perfil"] == "admin":
                    with st.expander("Excluir registro financeiro"):
                        df_ex = carregar_dados_tabela(f"""
                            SELECT c.id, c.data_custo, v.placa, c.categoria, c.valor_total 
                            FROM custos c JOIN veiculos v ON c.veiculo_id=v.id 
                            WHERE c.empresa_id={emp_id} ORDER BY c.data_custo DESC
                        """, emp_id)
                        
                        if not df_ex.empty:
                            opcoes_c = {f"{pd.to_datetime(r['data_custo']).strftime('%d/%m/%Y')} · {r['placa']} · {r['categoria']} ({fmt_brl(r['valor_total'])})": r["id"] for _, r in df_ex.iterrows()}
                            custo_exc = st.selectbox("Selecione o lançamento", list(opcoes_c.keys()))
                            
                            if st.button("Excluir definitivamente", use_container_width=True):
                                session = SessionLocal()
                                session.query(Custo).filter(Custo.id == opcoes_c[custo_exc]).delete()
                                session.commit()
                                session.close()
                                st.rerun()

                # Tabela de custos
                df_custos = carregar_dados_tabela(f"""
                    SELECT c.id, c.data_custo as Data, v.placa as Placa, c.categoria as Categoria,
                           c.descricao as Descrição, c.valor_total as Valor,
                           c.forma_pagamento, c.condicao_pagamento, c.parcelas,
                           c.motorista as Motorista, c.comprovante
                    FROM custos c JOIN veiculos v ON c.veiculo_id=v.id
                    WHERE c.empresa_id={emp_id} ORDER BY c.data_custo DESC
                """, emp_id)

                if not df_custos.empty:
                    df_custos["Data"] = pd.to_datetime(df_custos["Data"]).dt.strftime("%d/%m/%Y")
                    df_custos["Pagamento"] = df_custos.apply(
                        lambda r: f"{r['forma_pagamento']} · {int(r['parcelas'])}x" 
                        if r["forma_pagamento"] == "Cartão de Crédito" and r["condicao_pagamento"] == "Parcelado" 
                        else r["forma_pagamento"], axis=1
                    )
                    df_custos["Anexo"] = df_custos["comprovante"].apply(lambda x: "Sim" if x else "Não")

                    h1, h2 = st.columns([4, 1])
                    with h2:
                        csv_c = convert_df_to_csv(df_custos[["Data", "Placa", "Categoria", "Descrição", "Valor", "Pagamento", "Motorista"]])
                        st.download_button("Exportar Base", csv_c, "custos_detalhados.csv", "text/csv", use_container_width=True)

                    st.dataframe(df_custos[["Data", "Placa", "Categoria", "Descrição", "Valor", "Pagamento", "Motorista", "Anexo"]], use_container_width=True, hide_index=True)

                    df_anexos = df_custos[df_custos["comprovante"].notna()]
                    if not df_anexos.empty:
                        with st.expander("Consultar Comprovantes Anexados"):
                            opcoes_anx = {f"{r['Data']} · {r['Placa']} ({fmt_brl(r['Valor'])})": r["comprovante"] for _, r in df_anexos.iterrows()}
                            anx_sel = st.selectbox("Selecione", list(opcoes_anx.keys()))
                            caminho = opcoes_anx[anx_sel]
                            if os.path.exists(caminho):
                                if caminho.endswith(".pdf"):
                                    with open(caminho, "rb") as f: 
                                        st.download_button("Baixar Documento PDF", f, caminho.split("/")[-1], "application/pdf")
                                else: 
                                    st.image(caminho, use_container_width=True)

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
            page_header("Gestão de Contratos", "Controle o ciclo de vida comercial da frota.")

            df_veiculos = carregar_dados_tabela(f"SELECT id, placa, modelo FROM veiculos WHERE empresa_id={emp_id}", emp_id)
            
            tab_visao, tab_novo, tab_editar = st.tabs(["Painel Comercial", "Abertura de Contrato", "Finalização / Aditivos"])
            
            # ── Aba 1: Visão Geral ────────────────────────────────────────────────
            with tab_visao:
                df_contratos = carregar_dados_tabela(f"""
                    SELECT c.id, c.cliente as Cliente, c.cnpj as CNPJ, v.placa as Placa, 
                           c.ativo, c.data_inicio as Início, c.data_fim as Fim, 
                           c.tipo_valor as Tipo, c.valor_mensal as Valor, 
                           c.multa as 'Multa (%)', c.juros as 'Juros (%)', c.km_final,
                           c.usuario_lancamento as 'Criado por'
                    FROM contratos c JOIN veiculos v ON c.veiculo_id = v.id 
                    WHERE c.empresa_id = {emp_id} ORDER BY c.ativo DESC, c.data_inicio DESC
                """, emp_id)
                
                if not df_contratos.empty:
                    df_contratos['Início'] = pd.to_datetime(df_contratos['Início']).dt.strftime('%d/%m/%Y')
                    df_contratos['Fim'] = pd.to_datetime(df_contratos['Fim']).dt.strftime('%d/%m/%Y').fillna("—")
                    
                    df_ativos = df_contratos[df_contratos["ativo"] == 1].copy()
                    df_encer  = df_contratos[df_contratos["ativo"] == 0].copy()
                    
                    def cor_ativo(v): return "color:#065F46; background:#D1FAE5; font-weight:bold;"
                    def cor_encer(v): return "color:#1E3A8A; background:#DBEAFE; font-weight:bold;"
                    
                    h1, h2 = st.columns([4, 1])
                    with h2:
                        csv_ct = convert_df_to_csv(df_contratos[['Cliente', 'CNPJ', 'Placa', 'ativo', 'Início', 'Fim', 'Tipo', 'Valor']])
                        st.download_button("Exportar Dados", data=csv_ct, file_name="base_contratos.csv", mime="text/csv", use_container_width=True)

                    if not df_ativos.empty:
                        df_ativos["Status"] = "Ativo"
                        st.markdown("**Carteira Vigente**")
                        df_exibicao_ativos = df_ativos[['Cliente', 'CNPJ', 'Placa', 'Status', 'Início', 'Fim', 'Tipo', 'Valor', 'Multa (%)', 'Juros (%)']]
                        
                        if hasattr(df_exibicao_ativos.style, "map"): 
                            styled_df_ativos = df_exibicao_ativos.style.map(cor_ativo, subset=['Status'])
                        else: 
                            styled_df_ativos = df_exibicao_ativos.style.applymap(cor_ativo, subset=['Status'])
                            
                        styled_df_ativos = styled_df_ativos.format({"Valor": "R$ {:.2f}", "Multa (%)": "{:.2f}%", "Juros (%)": "{:.2f}%"})
                        st.dataframe(styled_df_ativos, use_container_width=True, hide_index=True)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    if not df_encer.empty:
                        df_encer["Status"] = "Baixado"
                        st.markdown("**Arquivo Morto (Contratos Finalizados)**")
                        df_exibicao_encer = df_encer[['Cliente', 'CNPJ', 'Placa', 'Status', 'Início', 'Fim', 'Tipo', 'Valor', 'Multa (%)', 'Juros (%)']]
                        
                        if hasattr(df_exibicao_encer.style, "map"): 
                            styled_df_encer = df_exibicao_encer.style.map(cor_encer, subset=['Status'])
                        else: 
                            styled_df_encer = df_exibicao_encer.style.applymap(cor_encer, subset=['Status'])
                            
                        styled_df_encer = styled_df_encer.format({"Valor": "R$ {:.2f}", "Multa (%)": "{:.2f}%", "Juros (%)": "{:.2f}%"})
                        st.dataframe(styled_df_encer, use_container_width=True, hide_index=True)
                else:
                    st.info("Plataforma sem contratos firmados.", icon=None)

            # ── Aba 2: Novo Contrato ──────────────────────────────────────────────
            with tab_novo:
                if df_veiculos.empty:
                    st.warning("É necessária a aquisição de um veículo na plataforma antes da locação.", icon=None)
                else:
                    with st.container(border=True):
                        opcoes_v = {f"{row['modelo']} ({row['placa']})": row['id'] for _, row in df_veiculos.iterrows()}
                        veiculo_sel = st.selectbox("Ativo a ser alocado", list(opcoes_v.keys()), key="nc_v")
                        
                        ca, cb = st.columns(2)
                        cliente = ca.text_input("Locatário (Razão Social)")
                        cnpj = cb.text_input("Documento (CNPJ/CPF)")
                        
                        cc, cd = st.columns(2)
                        d_inicio = cc.date_input("Início da Vigência", format="DD/MM/YYYY")
                        km_ini = cd.number_input("Odômetro de Saída", min_value=0.0, step=50.0, value=0.0)
                        
                        st.markdown("---")
                        st.markdown("**Acordo Comercial**")
                        ce, cf = st.columns(2)
                        tipo_v = ce.selectbox("Formato de Receita", ["Fixo", "Variável"])
                        valor_m = cf.number_input("Mensalidade (R$)", min_value=0.0, step=100.0, value=0.0, disabled=(tipo_v == "Variável"))
                        
                        cg, ch = st.columns(2)
                        multa_c = cg.number_input("Cláusula de Atraso - Multa (%)", min_value=0.0, step=1.0, value=2.0)
                        juros_c = ch.number_input("Cláusula de Atraso - Juros/Mês (%)", min_value=0.0, step=0.1, value=1.0)
                        
                        st.markdown("---")
                        is_ativo = st.checkbox("Manter contrato em status Vigente", value=True)
                        d_fim = km_fim = None
                        if not is_ativo:
                            ci, cj = st.columns(2)
                            d_fim = ci.date_input("Baixa do Contrato", format="DD/MM/YYYY")
                            km_fim = cj.number_input("Odômetro de Chegada", min_value=0.0, step=50.0, value=0.0)
                            
                        if st.button("Efetivar Alocação", use_container_width=True):
                            if not cliente: 
                                st.error("Identificação do Locatário obrigatória.", icon=None)
                            else:
                                session = SessionLocal()
                                session.add(Contrato(
                                    empresa_id=emp_id, veiculo_id=opcoes_v[veiculo_sel], cliente=cliente, cnpj=cnpj, 
                                    data_inicio=d_inicio, data_fim=d_fim, km_inicial=km_ini, km_final=km_fim or 0.0, 
                                    ativo=1 if is_ativo else 0, usuario_lancamento=st.session_state['nome'],
                                    tipo_valor=tipo_v, valor_mensal=valor_m if tipo_v == "Fixo" else 0.0,
                                    multa=multa_c, juros=juros_c
                                ))
                                session.commit()
                                session.close()
                                st.success("Contrato consolidado na base!")
                                time.sleep(1)
                                st.rerun()

            # ── Aba 3: Editar / Encerrar Contrato ─────────────────────────────────
            with tab_editar:
                if 'df_contratos' in locals() and not df_contratos.empty:
                    with st.container(border=True):
                        opt_ct = {f"{r['Cliente']} · {r['Placa']} ({'Vigente' if r['ativo']==1 else 'Baixado'})": r["id"] for _, r in df_contratos.iterrows()}
                        ct_sel = st.selectbox("Apólice Alvo", list(opt_ct.keys()))
                        ct_id = opt_ct[ct_sel]
                        
                        row_ct = df_contratos[df_contratos["id"] == ct_id].iloc[0]
                        
                        c_ea, c_eb = st.columns(2)
                        e_cliente = c_ea.text_input("Locatário", value=row_ct['Cliente'], key="ec_cli")
                        e_cnpj = c_eb.text_input("Documento", value=row_ct['CNPJ'], key="ec_cnpj")
                        
                        c_ec, c_ed = st.columns(2)
                        try: 
                            dt_ini_val = pd.to_datetime(row_ct['Início'], format="%d/%m/%Y").date()
                        except: 
                            dt_ini_val = date.today()
                        
                        e_dinicio = c_ec.date_input("Início da Vigência", value=dt_ini_val, key="ec_di")
                        e_ativo = c_ed.checkbox("Manter Status Vigente", value=(row_ct['ativo'] == 1))
                        
                        e_dfim = e_kmfim = None
                        if not e_ativo:
                            c_ee, c_ef = st.columns(2)
                            try: 
                                dt_fim_val = pd.to_datetime(row_ct['Fim'], format="%d/%m/%Y").date()
                            except: 
                                dt_fim_val = date.today()
                            e_dfim = c_ee.date_input("Baixa do Contrato", value=dt_fim_val, key="ec_df")
                            e_kmfim = c_ef.number_input("Odômetro de Chegada", min_value=0.0, step=50.0, value=float(row_ct['km_final'] or 0), key="ec_kmf")
                        
                        st.markdown("---")
                        st.markdown("**Acordo Comercial**")
                        c_eg, c_eh = st.columns(2)
                        e_tipo = c_eg.selectbox("Formato de Receita", ["Fixo", "Variável"], index=0 if row_ct['Tipo'] == "Fixo" else 1, key="ec_t")
                        e_val = c_eh.number_input("Mensalidade (R$)", min_value=0.0, step=100.0, value=float(row_ct['Valor'] or 0), disabled=(e_tipo == "Variável"), key="ec_v")
                        
                        c_ei, c_ej = st.columns(2)
                        e_multa = c_ei.number_input("Cláusula de Multa (%)", min_value=0.0, step=1.0, value=float(row_ct['Multa (%)'] or 0), key="ec_m")
                        e_juros = c_ej.number_input("Cláusula de Juros (%)", min_value=0.0, step=0.1, value=float(row_ct['Juros (%)'] or 0), key="ec_j")
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        b_col1, b_col2 = st.columns(2)
                        
                        if b_col1.button("Assinar Aditivo (Salvar)", use_container_width=True):
                            session = SessionLocal()
                            c = session.get(Contrato, ct_id)
                            c.cliente = e_cliente
                            c.cnpj = e_cnpj
                            c.data_inicio = e_dinicio
                            c.ativo = 1 if e_ativo else 0
                            c.data_fim = e_dfim
                            c.km_final = e_kmfim or 0.0
                            c.tipo_valor = e_tipo
                            c.valor_mensal = e_val if e_tipo == "Fixo" else 0.0
                            c.multa = e_multa
                            c.juros = e_juros
                            session.commit()
                            session.close()
                            st.success("Base atualizada com sucesso!")
                            time.sleep(1)
                            st.rerun()
                            
                        if st.session_state['perfil'] == 'admin':
                            if b_col2.button("Expurgar do Banco de Dados", use_container_width=True):
                                session = SessionLocal()
                                session.query(Contrato).filter(Contrato.id == ct_id).delete()
                                session.commit()
                                session.close()
                                st.success("Registro removido.")
                                time.sleep(1)
                                st.rerun()
                else:
                    st.info("O módulo não localizou apólices para manutenção.", icon=None)

        # ══════════════════════════════════════════════════════════════════════════
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