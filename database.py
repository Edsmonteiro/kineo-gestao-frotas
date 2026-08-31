from sqlalchemy import create_engine, Column, Integer, String, Float, Date
from sqlalchemy.orm import declarative_base, sessionmaker
import bcrypt

engine = create_engine('sqlite:///frota.db', connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Empresa(Base):
    __tablename__ = 'empresas'
    id = Column(Integer, primary_key=True)
    nome_fantasia = Column(String)
    cnpj = Column(String)
    logo_path = Column(String, nullable=True)

class Usuario(Base):
    __tablename__ = 'usuarios'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer)
    nome = Column(String)
    login = Column(String, unique=True)
    senha = Column(String)
    perfil = Column(String)

class Veiculo(Base):
    __tablename__ = 'veiculos'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer)
    placa = Column(String)
    modelo = Column(String)
    km_atual = Column(Float)
    status = Column(String)

class Contrato(Base):
    __tablename__ = 'contratos'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer)
    veiculo_id = Column(Integer)
    cliente = Column(String)
    cnpj = Column(String)
    data_inicio = Column(Date)
    data_fim = Column(Date, nullable=True)
    km_inicial = Column(Float)
    km_final = Column(Float, nullable=True)
    ativo = Column(Integer)
    usuario_lancamento = Column(String)
    # --- NOVOS CAMPOS FINANCEIROS DO CONTRATO ---
    tipo_valor = Column(String) # 'Fixo' ou 'Variável'
    valor_mensal = Column(Float, nullable=True)
    multa = Column(Float, nullable=True)
    juros = Column(Float, nullable=True)

class Custo(Base):
    __tablename__ = 'custos'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer)
    veiculo_id = Column(Integer)
    data_custo = Column(Date)
    categoria = Column(String)
    descricao = Column(String)
    valor_total = Column(Float)
    km_momento = Column(Float)
    litros = Column(Float, nullable=True)
    usuario_lancamento = Column(String)
    motorista = Column(String, nullable=True)
    comprovante = Column(String, nullable=True)
    forma_pagamento = Column(String)
    condicao_pagamento = Column(String, nullable=True)
    parcelas = Column(Integer, nullable=True)

class CobrancaRecorrente(Base):
    __tablename__ = 'cobrancas_recorrentes'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer)
    cliente = Column(String)
    forma_cobranca = Column(String)
    valor_mensal = Column(String)
    data_base_emissao = Column(Date)
    data_base_vencimento = Column(Date)
    observacoes = Column(String)

class CobrancaMensal(Base):
    __tablename__ = 'cobrancas_mensais'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer)
    mes_ano = Column(String)
    tipo = Column(String)
    cliente = Column(String)
    forma_cobranca = Column(String)
    valor_previsto = Column(Float, nullable=True)
    emissao_prevista = Column(Date)
    vencimento = Column(Date)
    data_emissao = Column(Date, nullable=True)
    num_boleto = Column(String, nullable=True)
    status = Column(String)
    data_recebimento = Column(Date, nullable=True)
    observacoes = Column(String, nullable=True)

Base.metadata.create_all(engine)

session = SessionLocal()
if not session.query(Empresa).first():
    nova_empresa = Empresa(nome_fantasia="LOC+ Rent a Car", cnpj="00.000.000/0001-00")
    session.add(nova_empresa)
    session.commit()
    
    senha_hash = bcrypt.hashpw("PRIMEIROACESSO".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    admin_padrao = Usuario(empresa_id=nova_empresa.id, nome="Administrador", login="admin", senha=senha_hash, perfil="admin")
    session.add(admin_padrao)
    session.commit()
session.close()