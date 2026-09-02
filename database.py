import os
import secrets
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import streamlit as st
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    Numeric,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    Index,
    inspect,
    text,
    event,
)
from sqlalchemy.orm import sessionmaker, declarative_base
import bcrypt

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
    ARGON2_DISPONIVEL = True
except Exception:
    PasswordHasher = None
    InvalidHashError = VerificationError = VerifyMismatchError = Exception
    ARGON2_DISPONIVEL = False


# ─── CONFIGURAÇÃO / AMBIENTE ────────────────────────────────────────────────
def _secret_value(nome, default=None):
    try:
        if hasattr(st, "secrets") and nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    return os.getenv(nome, default)


DATABASE_URL = _secret_value("DATABASE_URL")
APP_ENV_EXPLICITO = str(_secret_value("KINEO_ENV", "")).strip().lower()

# Sem URL de banco, somente desenvolvimento local pode usar SQLite.
if not DATABASE_URL:
    if APP_ENV_EXPLICITO in {"production", "prod", "staging", "homolog", "homologacao", "homologação"}:
        raise RuntimeError(
            "DATABASE_URL não configurada. O Kineo não inicia ambientes de produção/homologação "
            "com banco SQLite implícito. Configure a conexão do banco antes de iniciar."
        )
    DATABASE_URL = "sqlite:///frota.db"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if APP_ENV_EXPLICITO:
    APP_ENV = APP_ENV_EXPLICITO
else:
    APP_ENV = "development" if DATABASE_URL.startswith("sqlite") else "production"

IS_PRODUCTION = APP_ENV in {"production", "prod"}
IS_HOMOLOG = APP_ENV in {"staging", "homolog", "homologacao", "homologação"}
IS_MANAGED_ENV = IS_PRODUCTION or IS_HOMOLOG

if IS_MANAGED_ENV and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError(
        "SQLite é permitido apenas em desenvolvimento local. Homologação/produção exigem PostgreSQL/Neon."
    )

# Homologação e produção devem reproduzir o mesmo processo controlado de schema.
# Somente DEV local pode executar evolução automática de estrutura.
_auto_migrate_cfg = str(_secret_value("KINEO_AUTO_MIGRATE", "")).strip().lower()
if IS_MANAGED_ENV:
    # Nunca executa DDL automático em homologação/produção, mesmo que uma variável
    # antiga tenha sido deixada configurada por engano.
    AUTO_MIGRATE = False
else:
    AUTO_MIGRATE = (
        _auto_migrate_cfg in {"1", "true", "yes", "sim"}
        if _auto_migrate_cfg
        else True
    )

if IS_MANAGED_ENV and not ARGON2_DISPONIVEL:
    raise RuntimeError(
        "argon2-cffi é obrigatório em homologação e produção. "
        "Instale as dependências antes de iniciar o Kineo."
    )

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _ativar_foreign_keys_sqlite(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    connect_args = {}
    if IS_MANAGED_ENV and "sslmode=" not in str(DATABASE_URL).lower():
        connect_args["sslmode"] = "require"
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        connect_args=connect_args,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utcnow():
    """Data/hora UTC sem timezone para compatibilidade uniforme SQLite/PostgreSQL."""
    return datetime.utcnow()


# ─── HASH DE SENHA ───────────────────────────────────────────────────────────
# Argon2id para novas credenciais. Bcrypt permanece aceito apenas para migração
# transparente de hashes antigos no próximo login bem-sucedido.
_PASSWORD_HASHER = (
    PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )
    if ARGON2_DISPONIVEL
    else None
)


def hash_password(senha: str) -> str:
    if not isinstance(senha, str) or not senha:
        raise ValueError("Senha inválida para geração de hash.")
    if ARGON2_DISPONIVEL:
        return _PASSWORD_HASHER.hash(senha)
    # Fallback compatível para não impedir o ambiente de desenvolvimento caso a
    # dependência ainda não tenha sido instalada. Produção deve instalar argon2-cffi.
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(senha: str, hash_salvo: str) -> bool:
    if not senha or not hash_salvo:
        return False
    if str(hash_salvo).startswith("$argon2"):
        if not ARGON2_DISPONIVEL:
            return False
        try:
            return bool(_PASSWORD_HASHER.verify(hash_salvo, senha))
        except (VerifyMismatchError, VerificationError, InvalidHashError, Exception):
            return False
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), str(hash_salvo).encode("utf-8"))
    except Exception:
        return False


def password_needs_rehash(hash_salvo: str) -> bool:
    if not hash_salvo:
        return True
    if not str(hash_salvo).startswith("$argon2"):
        return ARGON2_DISPONIVEL
    if not ARGON2_DISPONIVEL:
        return False
    try:
        return _PASSWORD_HASHER.check_needs_rehash(hash_salvo)
    except Exception:
        return True


def gerar_senha_temporaria() -> str:
    """Gera credencial temporária aleatória, forte e exibida somente uma vez."""
    return secrets.token_urlsafe(12)


# ─── MODELOS DE DADOS ────────────────────────────────────────────────────────
class Empresa(Base):
    __tablename__ = "empresas"
    id = Column(Integer, primary_key=True, index=True)
    nome_fantasia = Column(String, default="Kineo")
    logo_path = Column(String, nullable=True)


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("empresa_id", "id", name="uq_usuarios_empresa_id"),)
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    nome = Column(String, nullable=False)
    login = Column(String, unique=True, nullable=False, index=True)
    # V10.3: e-mail pertence ao mesmo registro/tenant do usuário.
    # Permanece nullable para compatibilidade com contas legadas até o cadastro administrativo.
    email = Column(String(254), nullable=True)
    senha = Column(String, nullable=False)
    perfil = Column(String, default="operador")
    ativo = Column(Integer, default=1, nullable=False)
    must_change_password = Column(Integer, default=0, nullable=False)
    tentativas_login = Column(Integer, default=0, nullable=False)
    bloqueado_ate = Column(DateTime, nullable=True)
    ultimo_login = Column(DateTime, nullable=True)
    senha_alterada_em = Column(DateTime, nullable=True)
    privacidade_versao_aceita = Column(String, nullable=True)
    privacidade_vista_em = Column(DateTime, nullable=True)


# E-mail normalizado em lowercase na aplicação e único globalmente na fase atual.
# O índice parcial mantém múltiplos NULLs para usuários legados ainda sem e-mail.
Index(
    "uq_usuarios_email",
    Usuario.email,
    unique=True,
    sqlite_where=text("email IS NOT NULL"),
    postgresql_where=text("email IS NOT NULL"),
)


class Veiculo(Base):
    __tablename__ = "veiculos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_veiculos_empresa_id"),
        UniqueConstraint("empresa_id", "placa", name="uq_veiculos_empresa_placa"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    placa = Column(String, nullable=False)
    fabricante = Column(String, nullable=True)
    modelo = Column(String, nullable=False)
    ano_modelo = Column(Integer, nullable=True)
    versao = Column(String, nullable=True)
    motorizacao = Column(String, nullable=True)
    combustivel = Column(String, nullable=True)
    transmissao = Column(String, nullable=True)
    plano_manutencao_id = Column(Integer, ForeignKey("planos_manutencao.id"), nullable=True)
    km_atual = Column(Float, default=0.0)
    status = Column(String, default="Disponível")
    ativo = Column(Integer, default=1, nullable=False, index=True)


class Contrato(Base):
    __tablename__ = "contratos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_contratos_empresa_id"),
        ForeignKeyConstraint(
            ["empresa_id", "veiculo_id"],
            ["veiculos.empresa_id", "veiculos.id"],
            name="fk_contratos_tenant_veiculo",
        ),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    veiculo_id = Column(Integer, ForeignKey("veiculos.id"), nullable=False, index=True)
    cliente = Column(String, nullable=False)
    cnpj = Column(String, nullable=True)
    data_inicio = Column(Date, nullable=False)
    data_fim = Column(Date, nullable=True)
    km_inicial = Column(Float, default=0.0)
    km_final = Column(Float, default=0.0)
    ativo = Column(Integer, default=1)
    usuario_lancamento = Column(String, nullable=True)
    tipo_valor = Column(String, default="Fixo")
    valor_mensal = Column(Numeric(14, 2), default=Decimal("0.00"))
    multa = Column(Float, default=2.0)
    juros = Column(Float, default=1.0)


class SubstituicaoContrato(Base):
    __tablename__ = "substituicoes_contrato"
    __table_args__ = (
        ForeignKeyConstraint(["empresa_id", "contrato_id"], ["contratos.empresa_id", "contratos.id"], name="fk_substituicoes_tenant_contrato"),
        ForeignKeyConstraint(["empresa_id", "veiculo_principal_id"], ["veiculos.empresa_id", "veiculos.id"], name="fk_substituicoes_tenant_principal"),
        ForeignKeyConstraint(["empresa_id", "veiculo_substituto_id"], ["veiculos.empresa_id", "veiculos.id"], name="fk_substituicoes_tenant_substituto"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=False, index=True)
    veiculo_principal_id = Column(Integer, ForeignKey("veiculos.id"), nullable=False)
    veiculo_substituto_id = Column(Integer, ForeignKey("veiculos.id"), nullable=False)
    data_inicio = Column(Date, nullable=False)
    data_fim = Column(Date, nullable=True)
    ativo = Column(Integer, default=1)
    usuario_lancamento = Column(String, nullable=True)


class Motorista(Base):
    __tablename__ = "motoristas"
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_motoristas_empresa_id"),
        UniqueConstraint("empresa_id", "cpf", name="uq_motoristas_empresa_cpf"),
        UniqueConstraint("empresa_id", "cnh", name="uq_motoristas_empresa_cnh"),
        UniqueConstraint("empresa_id", "matricula", name="uq_motoristas_empresa_matricula"),
        ForeignKeyConstraint(["empresa_id", "usuario_id"], ["usuarios.empresa_id", "usuarios.id"], name="fk_motoristas_tenant_usuario"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    nome = Column(String, nullable=False, index=True)
    cpf = Column(String, nullable=True)
    matricula = Column(String, nullable=True)
    telefone = Column(String, nullable=True)
    cnh = Column(String, nullable=True)
    categoria_cnh = Column(String, nullable=True)
    validade_cnh = Column(Date, nullable=True, index=True)
    ativo = Column(Integer, default=1, nullable=False, index=True)
    observacoes = Column(String, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)


class Custo(Base):
    __tablename__ = "custos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_custos_empresa_id"),
        ForeignKeyConstraint(["empresa_id", "veiculo_id"], ["veiculos.empresa_id", "veiculos.id"], name="fk_custos_tenant_veiculo"),
        ForeignKeyConstraint(["empresa_id", "contrato_id"], ["contratos.empresa_id", "contratos.id"], name="fk_custos_tenant_contrato"),
        ForeignKeyConstraint(["empresa_id", "motorista_id"], ["motoristas.empresa_id", "motoristas.id"], name="fk_custos_tenant_motorista"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    veiculo_id = Column(Integer, ForeignKey("veiculos.id"), nullable=False, index=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=True, index=True)
    motorista_id = Column(Integer, ForeignKey("motoristas.id"), nullable=True, index=True)
    data_custo = Column(Date, nullable=False, index=True)
    categoria = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    valor_total = Column(Numeric(14, 2), nullable=False)
    km_momento = Column(Float, default=0.0)
    litros = Column(Float, nullable=True)
    usuario_lancamento = Column(String, nullable=True)
    forma_pagamento = Column(String, default="Pix")
    condicao_pagamento = Column(String, default="À vista")
    parcelas = Column(Integer, default=1)
    # Campo textual legado preservado como snapshot/histórico. Novos lançamentos usam motorista_id.
    motorista = Column(String, nullable=True)
    comprovante = Column(String, nullable=True)
    tipo_manutencao = Column(String, nullable=True)
    plano_item_id = Column(Integer, ForeignKey("itens_plano_manutencao.id"), nullable=True)


class PlanoManutencao(Base):
    __tablename__ = "planos_manutencao"
    __table_args__ = (UniqueConstraint("empresa_id", "id", name="uq_planos_empresa_id"),)
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
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
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_itens_plano_empresa_id"),
        ForeignKeyConstraint(["empresa_id", "plano_id"], ["planos_manutencao.empresa_id", "planos_manutencao.id"], name="fk_itens_plano_tenant_plano"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    plano_id = Column(Integer, ForeignKey("planos_manutencao.id"), nullable=False, index=True)
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
    __table_args__ = (
        ForeignKeyConstraint(["empresa_id", "veiculo_id"], ["veiculos.empresa_id", "veiculos.id"], name="fk_manutencoes_tenant_veiculo"),
        ForeignKeyConstraint(["empresa_id", "plano_item_id"], ["itens_plano_manutencao.empresa_id", "itens_plano_manutencao.id"], name="fk_manutencoes_tenant_item"),
        ForeignKeyConstraint(["empresa_id", "custo_id"], ["custos.empresa_id", "custos.id"], name="fk_manutencoes_tenant_custo"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    veiculo_id = Column(Integer, ForeignKey("veiculos.id"), nullable=False, index=True)
    plano_item_id = Column(Integer, ForeignKey("itens_plano_manutencao.id"), nullable=False)
    custo_id = Column(Integer, ForeignKey("custos.id"), nullable=True)
    data_execucao = Column(Date, nullable=True)
    km_execucao = Column(Float, nullable=True)
    observacoes = Column(String, nullable=True)
    origem = Column(String, default="Manual")


class CobrancaRecorrente(Base):
    __tablename__ = "cobrancas_recorrentes"
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_cobrancas_rec_empresa_id"),
        ForeignKeyConstraint(["empresa_id", "contrato_id"], ["contratos.empresa_id", "contratos.id"], name="fk_cobrancas_rec_tenant_contrato"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=True, index=True)
    cliente = Column(String, nullable=False)
    forma_cobranca = Column(String, nullable=False)
    tipo_valor = Column(String, default="Fixo")
    # Mantido como texto para preservar compatibilidade com a opção "Variável".
    valor_mensal = Column(String, nullable=False)
    data_base_emissao = Column(Date, nullable=False)
    data_base_vencimento = Column(Date, nullable=False)
    dia_emissao = Column(Integer, nullable=True)
    dia_vencimento = Column(Integer, nullable=True)
    multa = Column(Float, default=2.0)
    juros = Column(Float, default=1.0)
    ativo = Column(Integer, default=1)
    observacoes = Column(String, nullable=True)


class CobrancaMensal(Base):
    __tablename__ = "cobrancas_mensais"
    __table_args__ = (
        UniqueConstraint("empresa_id", "id", name="uq_cobrancas_mensais_empresa_id"),
        ForeignKeyConstraint(["empresa_id", "contrato_id"], ["contratos.empresa_id", "contratos.id"], name="fk_cobrancas_mensais_tenant_contrato"),
        ForeignKeyConstraint(["empresa_id", "recorrente_id"], ["cobrancas_recorrentes.empresa_id", "cobrancas_recorrentes.id"], name="fk_cobrancas_mensais_tenant_recorrente"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), default=1, nullable=False, index=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=True, index=True)
    recorrente_id = Column(Integer, ForeignKey("cobrancas_recorrentes.id"), nullable=True, index=True)
    mes_ano = Column(String, nullable=False, index=True)
    tipo = Column(String, default="Recorrente")
    cliente = Column(String, nullable=False)
    forma_cobranca = Column(String, nullable=False)
    valor_previsto = Column(Numeric(14, 2), default=Decimal("0.00"))
    emissao_prevista = Column(Date, nullable=True)
    vencimento = Column(Date, nullable=True, index=True)
    status = Column(String, default="Pendente de emissão")
    data_emissao = Column(Date, nullable=True)
    data_envio = Column(Date, nullable=True)
    num_boleto = Column(String, nullable=True)
    data_recebimento = Column(Date, nullable=True)
    multa = Column(Float, default=2.0)
    juros = Column(Float, default=1.0)
    valor_principal_liquidado = Column(Numeric(14, 2), nullable=True)
    multa_aplicada = Column(Numeric(14, 2), nullable=True)
    juros_aplicados = Column(Numeric(14, 2), nullable=True)
    dias_atraso_liquidacao = Column(Integer, nullable=True)
    valor_liquidado = Column(Numeric(14, 2), nullable=True)
    liquidacao_congelada = Column(Integer, default=0, nullable=False)
    liquidado_em = Column(DateTime, nullable=True)
    observacoes = Column(String, nullable=True)


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (
        ForeignKeyConstraint(["empresa_id", "usuario_id"], ["usuarios.empresa_id", "usuarios.id"], name="fk_auditoria_tenant_usuario"),
    )
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    acao = Column(String, nullable=False, index=True)
    entidade = Column(String, nullable=True)
    entidade_id = Column(Integer, nullable=True)
    detalhes = Column(String, nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False, index=True)


Index("ix_custos_empresa_data", Custo.empresa_id, Custo.data_custo)
Index("ix_cobrancas_empresa_competencia", CobrancaMensal.empresa_id, CobrancaMensal.mes_ano)
Index("ix_contratos_empresa_veiculo", Contrato.empresa_id, Contrato.veiculo_id)
Index("ix_motoristas_empresa_ativo", Motorista.empresa_id, Motorista.ativo)
Index("ix_veiculos_empresa_ativo", Veiculo.empresa_id, Veiculo.ativo)
Index(
    "uq_cobrancas_recorrente_competencia",
    CobrancaMensal.empresa_id, CobrancaMensal.recorrente_id, CobrancaMensal.mes_ano,
    unique=True,
    sqlite_where=text("recorrente_id IS NOT NULL"),
    postgresql_where=text("recorrente_id IS NOT NULL"),
)
Index(
    "uq_cobrancas_contrato_recorrente_competencia",
    CobrancaMensal.empresa_id, CobrancaMensal.contrato_id, CobrancaMensal.mes_ano, CobrancaMensal.tipo,
    unique=True,
    sqlite_where=text("contrato_id IS NOT NULL AND tipo = 'Recorrente'"),
    postgresql_where=text("contrato_id IS NOT NULL AND tipo = 'Recorrente'"),
)


# ─── MIGRAÇÃO COMPATÍVEL / SOMENTE QUANDO AUTORIZADA ─────────────────────────
def _garantir_colunas(tabela, necessarias):
    inspector = inspect(engine)
    if tabela not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        return
    existentes = {c["name"] for c in inspector.get_columns(tabela)}
    with engine.begin() as conn:
        for nome, tipo in necessarias.items():
            if nome not in existentes:
                conn.execute(text(f'ALTER TABLE {tabela} ADD COLUMN "{nome}" {tipo}'))


def garantir_colunas_usuarios():
    _garantir_colunas("usuarios", {
        "email": "VARCHAR(254)",
        "ativo": "INTEGER DEFAULT 1",
        "must_change_password": "INTEGER DEFAULT 0",
        "tentativas_login": "INTEGER DEFAULT 0",
        "bloqueado_ate": "TIMESTAMP",
        "ultimo_login": "TIMESTAMP",
        "senha_alterada_em": "TIMESTAMP",
        "privacidade_versao_aceita": "VARCHAR",
        "privacidade_vista_em": "TIMESTAMP",
    })


def garantir_indice_tenant_usuarios_sqlite():
    """Atualiza bancos SQLite legados para a FK composta de auditoria.

    A aplicação só executa esta correção estrutural no modo de migração local.
    Ambientes gerenciados continuam usando migrations controladas.
    """
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "usuarios" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_usuarios_empresa_id "
            "ON usuarios (empresa_id, id)"
        ))


def garantir_colunas_contratos():
    _garantir_colunas("contratos", {
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
        "valor_mensal": "NUMERIC(14,2) DEFAULT 0.00",
        "multa": "FLOAT DEFAULT 2.0",
        "juros": "FLOAT DEFAULT 1.0",
    })


def garantir_colunas_substituicoes():
    _garantir_colunas("substituicoes_contrato", {
        "empresa_id": "INTEGER DEFAULT 1",
        "contrato_id": "INTEGER",
        "veiculo_principal_id": "INTEGER",
        "veiculo_substituto_id": "INTEGER",
        "data_inicio": "DATE",
        "data_fim": "DATE",
        "ativo": "INTEGER DEFAULT 1",
        "usuario_lancamento": "VARCHAR",
    })


def garantir_colunas_veiculos():
    _garantir_colunas("veiculos", {
        "fabricante": "VARCHAR",
        "ano_modelo": "INTEGER",
        "versao": "VARCHAR",
        "motorizacao": "VARCHAR",
        "combustivel": "VARCHAR",
        "transmissao": "VARCHAR",
        "plano_manutencao_id": "INTEGER",
        "ativo": "INTEGER DEFAULT 1",
    })


def garantir_colunas_custos():
    _garantir_colunas("custos", {
        "contrato_id": "INTEGER",
        "motorista_id": "INTEGER",
        "tipo_manutencao": "VARCHAR",
        "plano_item_id": "INTEGER",
    })


def garantir_colunas_cobrancas_recorrentes():
    _garantir_colunas("cobrancas_recorrentes", {
        "contrato_id": "INTEGER",
        "tipo_valor": "VARCHAR DEFAULT 'Fixo'",
        "dia_emissao": "INTEGER",
        "dia_vencimento": "INTEGER",
        "multa": "FLOAT DEFAULT 2.0",
        "juros": "FLOAT DEFAULT 1.0",
        "ativo": "INTEGER DEFAULT 1",
    })


def garantir_colunas_cobrancas_mensais():
    _garantir_colunas("cobrancas_mensais", {
        "contrato_id": "INTEGER",
        "recorrente_id": "INTEGER",
        "data_envio": "DATE",
        "multa": "FLOAT DEFAULT 2.0",
        "juros": "FLOAT DEFAULT 1.0",
        "valor_principal_liquidado": "NUMERIC(14,2)",
        "multa_aplicada": "NUMERIC(14,2)",
        "juros_aplicados": "NUMERIC(14,2)",
        "dias_atraso_liquidacao": "INTEGER",
        "valor_liquidado": "NUMERIC(14,2)",
        "liquidacao_congelada": "INTEGER DEFAULT 0",
        "liquidado_em": "TIMESTAMP",
    })


def normalizar_dados_legados():
    session = SessionLocal()
    try:
        alterou = False
        for user in session.query(Usuario).all():
            if user.email:
                email_normalizado = str(user.email).strip().lower()
                if email_normalizado != user.email:
                    user.email = email_normalizado or None
                    alterou = True
            if user.ativo is None:
                user.ativo = 1
                alterou = True
            if user.tentativas_login is None:
                user.tentativas_login = 0
                alterou = True
            if user.must_change_password is None:
                user.must_change_password = 1 if verify_password("PRIMEIROACESSO", user.senha) else 0
                alterou = True
            # Usuários que ainda usam a antiga chave global são forçados a trocá-la.
            if verify_password("PRIMEIROACESSO", user.senha) and user.must_change_password != 1:
                user.must_change_password = 1
                alterou = True

        for rec in session.query(CobrancaRecorrente).all():
            if rec.dia_emissao is None and rec.data_base_emissao is not None:
                rec.dia_emissao = rec.data_base_emissao.day
                alterou = True
            if rec.dia_vencimento is None and rec.data_base_vencimento is not None:
                rec.dia_vencimento = rec.data_base_vencimento.day
                alterou = True
            if not rec.tipo_valor:
                valor_txt = str(rec.valor_mensal or "").strip().lower()
                rec.tipo_valor = "Variável" if "vari" in valor_txt else "Fixo"
                alterou = True
            if rec.ativo is None:
                rec.ativo = 1
                alterou = True
            if rec.multa is None:
                rec.multa = 2.0
                alterou = True
            if rec.juros is None:
                rec.juros = 1.0
                alterou = True

        for veiculo in session.query(Veiculo).all():
            if veiculo.ativo is None:
                veiculo.ativo = 1
                alterou = True

        for cob in session.query(CobrancaMensal).all():
            if cob.multa is None:
                cob.multa = 2.0
                alterou = True
            if cob.juros is None:
                cob.juros = 1.0
                alterou = True
            if cob.liquidacao_congelada is None:
                cob.liquidacao_congelada = 0
                alterou = True

            # V10: congela liquidações legadas já recebidas para que mudanças futuras
            # de multa/juros não reescrevam o histórico financeiro.
            if cob.data_recebimento is not None and cob.valor_liquidado is None:
                principal = Decimal(str(cob.valor_previsto or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                dias = 0
                if cob.vencimento is not None:
                    dias = max((cob.data_recebimento - cob.vencimento).days, 0)
                pct_multa = Decimal(str(cob.multa or 0))
                pct_juros = Decimal(str(cob.juros or 0))
                multa_val = (principal * pct_multa / Decimal("100") if dias > 0 else Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                juros_val = (principal * pct_juros / Decimal("100") * Decimal(dias) / Decimal("30") if dias > 0 else Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                cob.valor_principal_liquidado = principal
                cob.multa_aplicada = multa_val
                cob.juros_aplicados = juros_val
                cob.dias_atraso_liquidacao = dias
                cob.valor_liquidado = (principal + multa_val + juros_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                cob.liquidacao_congelada = 1
                cob.liquidado_em = datetime.utcnow()
                cob.status = "Recebida"
                alterou = True

        if alterou:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def validar_schema_gerenciado():
    """Falha cedo se homologação/produção iniciar antes da migração controlada."""
    if not IS_MANAGED_ENV:
        return
    inspector = inspect(engine)
    tabelas = set(inspector.get_table_names())
    requeridas = {
        "usuarios": {
            "ativo", "must_change_password", "tentativas_login", "bloqueado_ate",
            "ultimo_login", "senha_alterada_em", "privacidade_versao_aceita",
            "privacidade_vista_em", "email",
        },
        "veiculos": {"ativo"},
        "custos": {"contrato_id", "motorista_id"},
        "cobrancas_recorrentes": {
            "contrato_id", "tipo_valor", "dia_emissao", "dia_vencimento", "multa", "juros", "ativo"
        },
        "cobrancas_mensais": {
            "contrato_id", "recorrente_id", "data_envio", "multa", "juros",
            "valor_principal_liquidado", "multa_aplicada", "juros_aplicados",
            "dias_atraso_liquidacao", "valor_liquidado", "liquidacao_congelada", "liquidado_em"
        },
    }
    problemas = []
    for tabela, colunas in requeridas.items():
        if tabela not in tabelas:
            problemas.append(f"tabela ausente: {tabela}")
            continue
        existentes = {c["name"] for c in inspector.get_columns(tabela)}
        faltantes = sorted(colunas - existentes)
        if faltantes:
            problemas.append(f"{tabela}: faltam {', '.join(faltantes)}")
    if "auditoria" not in tabelas:
        problemas.append("tabela ausente: auditoria")
    if "motoristas" not in tabelas:
        problemas.append("tabela ausente: motoristas")

    # V10 também valida tipos financeiros, índices únicos e FKs de isolamento por tenant.
    for tabela, coluna in [
        ("contratos", "valor_mensal"),
        ("custos", "valor_total"),
        ("cobrancas_mensais", "valor_previsto"),
        ("cobrancas_mensais", "valor_liquidado"),
    ]:
        if tabela in tabelas:
            tipos = {c["name"]: str(c["type"]).lower() for c in inspector.get_columns(tabela)}
            tipo = tipos.get(coluna, "")
            if coluna in tipos and not any(x in tipo for x in ("numeric", "decimal")):
                problemas.append(f"{tabela}.{coluna}: tipo financeiro deve ser NUMERIC/DECIMAL")

    indices_obrigatorios = {
        "usuarios": {"uq_usuarios_email"},
        "veiculos": {"uq_veiculos_empresa_placa"},
        "cobrancas_mensais": {
            "uq_cobrancas_recorrente_competencia",
            "uq_cobrancas_contrato_recorrente_competencia",
        },
        "motoristas": {
            "uq_motoristas_empresa_cpf",
            "uq_motoristas_empresa_cnh",
            "uq_motoristas_empresa_matricula",
        },
    }
    for tabela, nomes in indices_obrigatorios.items():
        if tabela in tabelas:
            existentes_idx = {i.get("name") for i in inspector.get_indexes(tabela)}
            ausentes = sorted(n for n in nomes if n not in existentes_idx)
            if ausentes:
                problemas.append(f"{tabela}: faltam índices/uniques V10: {', '.join(ausentes)}")

    fks_tenant_obrigatorias = {
        "contratos": {"fk_contratos_tenant_veiculo"},
        "custos": {"fk_custos_tenant_veiculo", "fk_custos_tenant_contrato", "fk_custos_tenant_motorista"},
        "cobrancas_recorrentes": {"fk_cobrancas_rec_tenant_contrato"},
        "cobrancas_mensais": {"fk_cobrancas_mensais_tenant_contrato", "fk_cobrancas_mensais_tenant_recorrente"},
    }
    for tabela, nomes in fks_tenant_obrigatorias.items():
        if tabela in tabelas:
            existentes_fk = {f.get("name") for f in inspector.get_foreign_keys(tabela)}
            ausentes = sorted(n for n in nomes if n not in existentes_fk)
            if ausentes:
                problemas.append(f"{tabela}: faltam FKs multiempresa V10: {', '.join(ausentes)}")

    if problemas:
        raise RuntimeError(
            "Banco de homologação/produção ainda não foi migrado/validado para o schema V10.3. "
            "Execute as migrations V8.1, V9, V10 e V10.3 na ordem antes do deploy. Detalhes: " + " | ".join(problemas)
        )


def inicializar_dados():
    session = SessionLocal()
    try:
        if not session.query(Empresa).first():
            session.add(Empresa(id=1, nome_fantasia="Kineo", logo_path=None))
            session.commit()

        if not session.query(Usuario).first():
            senha_bootstrap = _secret_value("KINEO_BOOTSTRAP_ADMIN_PASSWORD")
            if not senha_bootstrap:
                if IS_MANAGED_ENV:
                    raise RuntimeError(
                        "Banco sem usuário administrador. Defina KINEO_BOOTSTRAP_ADMIN_PASSWORD "
                        "somente para a inicialização controlada do primeiro administrador."
                    )
                senha_bootstrap = gerar_senha_temporaria()
                print("\n[KINEO DEV] Credencial temporária do administrador criada.")
                print("[KINEO DEV] Login: admin")
                print(f"[KINEO DEV] Senha temporária: {senha_bootstrap}\n")

            session.add(Usuario(
                empresa_id=1,
                nome="Administrador",
                login="admin",
                senha=hash_password(str(senha_bootstrap)),
                perfil="admin",
                ativo=1,
                must_change_password=1,
                tentativas_login=0,
            ))
            session.commit()
    finally:
        session.close()


if AUTO_MIGRATE:
    Base.metadata.create_all(bind=engine)
    garantir_colunas_usuarios()
    garantir_indice_tenant_usuarios_sqlite()
    garantir_colunas_contratos()
    garantir_colunas_substituicoes()
    garantir_colunas_veiculos()
    garantir_colunas_custos()
    garantir_colunas_cobrancas_recorrentes()
    garantir_colunas_cobrancas_mensais()
    Base.metadata.create_all(bind=engine)  # cria novas tabelas/índices somente em DEV local
    normalizar_dados_legados()

# Em homologação/produção, o schema deve estar previamente migrado; a inicialização não executa DDL.
validar_schema_gerenciado()
inicializar_dados()
