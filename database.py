import os
import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
import bcrypt

# ─── CONEXÃO COM BANCO DE DADOS ──────────────────────────────────────────────
DATABASE_URL = None

# Tenta buscar a URL do Neon nas Secrets de forma segura (evita crash se o arquivo não existir)
try:
    if hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
        DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    pass

# Se não achou na Secret, tenta nas variáveis de ambiente do sistema
if not DATABASE_URL and "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]

# Fallback local se não encontrar URL da nuvem
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///frota.db"

# Ajuste do prefixo para compatibilidade com SQLAlchemy caso venha como postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Criação do Engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ─── MODELOS DE DADOS ────────────────────────────────────────────────────────
class Empresa(Base):
    __tablename__ = "empresas"
    id = Column(Integer, primary_key=True, index=True)
    nome_fantasia = Column(String, default="Kineo")
    logo_path = Column(String, nullable=True)

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    nome = Column(String, nullable=False)
    login = Column(String, unique=True, nullable=False)
    senha = Column(String, nullable=False)
    perfil = Column(String, default="operador")

class Veiculo(Base):
    __tablename__ = "veiculos"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    placa = Column(String, unique=True, nullable=False)
    fabricante = Column(String, nullable=True)
    modelo = Column(String, nullable=False)
    ano_modelo = Column(Integer, nullable=True)
    versao = Column(String, nullable=True)
    motorizacao = Column(String, nullable=True)
    combustivel = Column(String, nullable=True)
    transmissao = Column(String, nullable=True)
    plano_manutencao_id = Column(Integer, nullable=True)
    km_atual = Column(Float, default=0.0)
    status = Column(String, default="Disponível")

class Contrato(Base):
    __tablename__ = "contratos"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    veiculo_id = Column(Integer, nullable=False)
    cliente = Column(String, nullable=False)
    cnpj = Column(String, nullable=True)
    data_inicio = Column(Date, nullable=False)
    data_fim = Column(Date, nullable=True)
    km_inicial = Column(Float, default=0.0)
    km_final = Column(Float, default=0.0)
    ativo = Column(Integer, default=1)
    usuario_lancamento = Column(String, nullable=True)
    tipo_valor = Column(String, default="Fixo")
    valor_mensal = Column(Float, default=0.0)
    multa = Column(Float, default=2.0)
    juros = Column(Float, default=1.0)

class SubstituicaoContrato(Base):
    __tablename__ = "substituicoes_contrato"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    contrato_id = Column(Integer, nullable=False)
    veiculo_principal_id = Column(Integer, nullable=False)
    veiculo_substituto_id = Column(Integer, nullable=False)
    data_inicio = Column(Date, nullable=False)
    data_fim = Column(Date, nullable=True)
    ativo = Column(Integer, default=1)
    usuario_lancamento = Column(String, nullable=True)

class Custo(Base):
    __tablename__ = "custos"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    veiculo_id = Column(Integer, nullable=False)
    data_custo = Column(Date, nullable=False)
    categoria = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    valor_total = Column(Float, nullable=False)
    km_momento = Column(Float, default=0.0)
    litros = Column(Float, nullable=True)
    usuario_lancamento = Column(String, nullable=True)
    forma_pagamento = Column(String, default="Pix")
    condicao_pagamento = Column(String, default="À vista")
    parcelas = Column(Integer, default=1)
    motorista = Column(String, nullable=True)
    comprovante = Column(String, nullable=True)
    tipo_manutencao = Column(String, nullable=True)
    plano_item_id = Column(Integer, nullable=True)

class PlanoManutencao(Base):
    __tablename__ = "planos_manutencao"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    nome = Column(String, nullable=False)
    fabricante = Column(String, nullable=True)
    modelo = Column(String, nullable=True)
    ano_modelo = Column(Integer, nullable=True)
    versao = Column(String, nullable=True)
    motorizacao = Column(String, nullable=True)
    combustivel = Column(String, nullable=True)
    transmissao = Column(String, nullable=True)
    ativo = Column(Integer, default=1)

class ItemPlanoManutencao(Base):
    __tablename__ = "itens_plano_manutencao"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    plano_id = Column(Integer, nullable=False)
    codigo_servico = Column(String, nullable=True)
    tipo_manutencao = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    intervalo_fabricante_km = Column(Float, nullable=True)
    intervalo_fabricante_meses = Column(Integer, nullable=True)
    intervalo_empresa_km = Column(Float, nullable=True)
    intervalo_empresa_meses = Column(Integer, nullable=True)
    ativo = Column(Integer, default=1)

class ManutencaoRealizada(Base):
    __tablename__ = "manutencoes_realizadas"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    veiculo_id = Column(Integer, nullable=False)
    plano_item_id = Column(Integer, nullable=False)
    custo_id = Column(Integer, nullable=True)
    data_execucao = Column(Date, nullable=True)
    km_execucao = Column(Float, nullable=True)
    observacoes = Column(String, nullable=True)
    origem = Column(String, default="Manual")

class CobrancaRecorrente(Base):
    __tablename__ = "cobrancas_recorrentes"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    cliente = Column(String, nullable=False)
    forma_cobranca = Column(String, nullable=False)
    valor_mensal = Column(String, nullable=False)
    data_base_emissao = Column(Date, nullable=False)
    data_base_vencimento = Column(Date, nullable=False)
    observacoes = Column(String, nullable=True)

class CobrancaMensal(Base):
    __tablename__ = "cobrancas_mensais"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, default=1)
    mes_ano = Column(String, nullable=False)
    tipo = Column(String, default="Recorrente")
    cliente = Column(String, nullable=False)
    forma_cobranca = Column(String, nullable=False)
    valor_previsto = Column(Float, default=0.0)
    emissao_prevista = Column(Date, nullable=True)
    vencimento = Column(Date, nullable=True)
    status = Column(String, default="Pendente")
    data_emissao = Column(Date, nullable=True)
    num_boleto = Column(String, nullable=True)
    data_recebimento = Column(Date, nullable=True)
    observacoes = Column(String, nullable=True)

# ─── INICIALIZAÇÃO / MIGRAÇÃO DO BANCO ───────────────────────────────────────
Base.metadata.create_all(bind=engine)

def garantir_colunas_contratos():
    """Mantém bancos antigos compatíveis com o modelo atual de contratos."""
    inspector = inspect(engine)
    if "contratos" not in inspector.get_table_names():
        return

    existentes = {c["name"] for c in inspector.get_columns("contratos")}
    necessarias = {
        "empresa_id": "INTEGER DEFAULT 1",
        "veiculo_id": "INTEGER",
        "cliente": "VARCHAR",
        "cnpj": "VARCHAR",
        "data_inicio": "DATE",
        "data_fim": "DATE",
        "km_inicial": "FLOAT DEFAULT 0.0",
        "km_final": "FLOAT DEFAULT 0.0",
        "ativo": "INTEGER DEFAULT 1",
        "usuario_lancamento": "VARCHAR",
        "tipo_valor": "VARCHAR DEFAULT 'Fixo'",
        "valor_mensal": "FLOAT DEFAULT 0.0",
        "multa": "FLOAT DEFAULT 2.0",
        "juros": "FLOAT DEFAULT 1.0",
    }

    faltantes = {nome: tipo for nome, tipo in necessarias.items() if nome not in existentes}
    if not faltantes:
        return

    with engine.begin() as conn:
        for nome, tipo in faltantes.items():
            conn.execute(text(f'ALTER TABLE contratos ADD COLUMN "{nome}" {tipo}'))

def garantir_colunas_substituicoes():
    """Mantém a tabela de substituições compatível em deploys futuros."""
    inspector = inspect(engine)
    if "substituicoes_contrato" not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        return

    existentes = {c["name"] for c in inspector.get_columns("substituicoes_contrato")}
    necessarias = {
        "empresa_id": "INTEGER DEFAULT 1",
        "contrato_id": "INTEGER",
        "veiculo_principal_id": "INTEGER",
        "veiculo_substituto_id": "INTEGER",
        "data_inicio": "DATE",
        "data_fim": "DATE",
        "ativo": "INTEGER DEFAULT 1",
        "usuario_lancamento": "VARCHAR",
    }

    faltantes = {nome: tipo for nome, tipo in necessarias.items() if nome not in existentes}
    if not faltantes:
        return

    with engine.begin() as conn:
        for nome, tipo in faltantes.items():
            conn.execute(text(f'ALTER TABLE substituicoes_contrato ADD COLUMN "{nome}" {tipo}'))

def garantir_colunas_veiculos():
    """Adiciona os metadados usados para associar veículos a planos de manutenção."""
    inspector = inspect(engine)
    if "veiculos" not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        return

    existentes = {c["name"] for c in inspector.get_columns("veiculos")}
    necessarias = {
        "fabricante": "VARCHAR",
        "ano_modelo": "INTEGER",
        "versao": "VARCHAR",
        "motorizacao": "VARCHAR",
        "combustivel": "VARCHAR",
        "transmissao": "VARCHAR",
        "plano_manutencao_id": "INTEGER",
    }

    with engine.begin() as conn:
        for nome, tipo in necessarias.items():
            if nome not in existentes:
                conn.execute(text(f'ALTER TABLE veiculos ADD COLUMN "{nome}" {tipo}'))


def garantir_colunas_custos():
    """Mantém custos antigos compatíveis com o vínculo estruturado de manutenção."""
    inspector = inspect(engine)
    if "custos" not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        return

    existentes = {c["name"] for c in inspector.get_columns("custos")}
    necessarias = {
        "tipo_manutencao": "VARCHAR",
        "plano_item_id": "INTEGER",
    }

    with engine.begin() as conn:
        for nome, tipo in necessarias.items():
            if nome not in existentes:
                conn.execute(text(f'ALTER TABLE custos ADD COLUMN "{nome}" {tipo}'))


garantir_colunas_contratos()
garantir_colunas_substituicoes()
garantir_colunas_veiculos()
garantir_colunas_custos()

def inicializar_dados():
    session = SessionLocal()
    # Cria a primeira empresa caso não exista
    if not session.query(Empresa).first():
        session.add(Empresa(id=1, nome_fantasia="Kineo", logo_path=None))
        session.commit()

    # Cria o usuário admin inicial caso não exista
    if not session.query(Usuario).first():
        senha_hash = bcrypt.hashpw(b"PRIMEIROACESSO", bcrypt.gensalt()).decode()
        session.add(Usuario(
            empresa_id=1,
            nome="Administrador",
            login="admin",
            senha=senha_hash,
            perfil="admin"
        ))
        session.commit()
    session.close()

inicializar_dados()