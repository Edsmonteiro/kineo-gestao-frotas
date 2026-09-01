-- Kineo V8 — Segurança, auditoria e precisão financeira
-- PostgreSQL / Neon
-- Execute primeiro em HOMOLOGAÇÃO. Faça backup antes de executar em produção.

BEGIN;

-- 1) Segurança de usuários
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ativo INTEGER DEFAULT 1;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS must_change_password INTEGER DEFAULT 0;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS tentativas_login INTEGER DEFAULT 0;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bloqueado_ate TIMESTAMP NULL;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ultimo_login TIMESTAMP NULL;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS senha_alterada_em TIMESTAMP NULL;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS privacidade_versao_aceita VARCHAR NULL;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS privacidade_vista_em TIMESTAMP NULL;

UPDATE usuarios SET ativo = 1 WHERE ativo IS NULL;
UPDATE usuarios SET must_change_password = 0 WHERE must_change_password IS NULL;
UPDATE usuarios SET tentativas_login = 0 WHERE tentativas_login IS NULL;

-- 2) Vínculos financeiros já usados pela nova Gestão de Cobranças
ALTER TABLE custos ADD COLUMN IF NOT EXISTS contrato_id INTEGER NULL;

ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS contrato_id INTEGER NULL;
ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS tipo_valor VARCHAR DEFAULT 'Fixo';
ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS dia_emissao INTEGER NULL;
ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS dia_vencimento INTEGER NULL;
ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS multa FLOAT DEFAULT 2.0;
ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS juros FLOAT DEFAULT 1.0;
ALTER TABLE cobrancas_recorrentes ADD COLUMN IF NOT EXISTS ativo INTEGER DEFAULT 1;

ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS contrato_id INTEGER NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS recorrente_id INTEGER NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS data_envio DATE NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS multa FLOAT DEFAULT 2.0;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS juros FLOAT DEFAULT 1.0;

-- 3) Precisão monetária: evita ponto flutuante em valores financeiros
ALTER TABLE contratos
    ALTER COLUMN valor_mensal TYPE NUMERIC(14,2)
    USING ROUND(COALESCE(valor_mensal, 0)::numeric, 2);

ALTER TABLE custos
    ALTER COLUMN valor_total TYPE NUMERIC(14,2)
    USING ROUND(COALESCE(valor_total, 0)::numeric, 2);

ALTER TABLE cobrancas_mensais
    ALTER COLUMN valor_previsto TYPE NUMERIC(14,2)
    USING ROUND(COALESCE(valor_previsto, 0)::numeric, 2);

-- 4) Auditoria
CREATE TABLE IF NOT EXISTS auditoria (
    id SERIAL PRIMARY KEY,
    empresa_id INTEGER NULL,
    usuario_id INTEGER NULL,
    acao VARCHAR NOT NULL,
    entidade VARCHAR NULL,
    entidade_id INTEGER NULL,
    detalhes VARCHAR NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5) Índices operacionais / multiempresa
CREATE INDEX IF NOT EXISTS ix_usuarios_empresa_id ON usuarios (empresa_id);
CREATE INDEX IF NOT EXISTS ix_usuarios_ativo ON usuarios (ativo);
CREATE INDEX IF NOT EXISTS ix_veiculos_empresa_id ON veiculos (empresa_id);
CREATE INDEX IF NOT EXISTS ix_contratos_empresa_veiculo ON contratos (empresa_id, veiculo_id);
CREATE INDEX IF NOT EXISTS ix_custos_empresa_data ON custos (empresa_id, data_custo);
CREATE INDEX IF NOT EXISTS ix_custos_contrato_id ON custos (contrato_id);
CREATE INDEX IF NOT EXISTS ix_cobrancas_empresa_competencia ON cobrancas_mensais (empresa_id, mes_ano);
CREATE INDEX IF NOT EXISTS ix_cobrancas_contrato_id ON cobrancas_mensais (contrato_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_empresa_data ON auditoria (empresa_id, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_auditoria_usuario_id ON auditoria (usuario_id);

-- 6) Foreign Keys. NOT VALID preserva bancos legados com possíveis registros órfãos;
-- novos inserts/updates já passam a ser protegidos. Depois da auditoria dos dados,
-- as constraints podem ser validadas com ALTER TABLE ... VALIDATE CONSTRAINT.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_usuarios_empresa') THEN
        ALTER TABLE usuarios ADD CONSTRAINT fk_usuarios_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_veiculos_empresa') THEN
        ALTER TABLE veiculos ADD CONSTRAINT fk_veiculos_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contratos_empresa') THEN
        ALTER TABLE contratos ADD CONSTRAINT fk_contratos_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_contratos_veiculo') THEN
        ALTER TABLE contratos ADD CONSTRAINT fk_contratos_veiculo
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_custos_empresa') THEN
        ALTER TABLE custos ADD CONSTRAINT fk_custos_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_custos_veiculo') THEN
        ALTER TABLE custos ADD CONSTRAINT fk_custos_veiculo
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_custos_contrato') THEN
        ALTER TABLE custos ADD CONSTRAINT fk_custos_contrato
            FOREIGN KEY (contrato_id) REFERENCES contratos(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cobrancas_rec_empresa') THEN
        ALTER TABLE cobrancas_recorrentes ADD CONSTRAINT fk_cobrancas_rec_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cobrancas_rec_contrato') THEN
        ALTER TABLE cobrancas_recorrentes ADD CONSTRAINT fk_cobrancas_rec_contrato
            FOREIGN KEY (contrato_id) REFERENCES contratos(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cobrancas_mensais_empresa') THEN
        ALTER TABLE cobrancas_mensais ADD CONSTRAINT fk_cobrancas_mensais_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cobrancas_mensais_contrato') THEN
        ALTER TABLE cobrancas_mensais ADD CONSTRAINT fk_cobrancas_mensais_contrato
            FOREIGN KEY (contrato_id) REFERENCES contratos(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cobrancas_mensais_recorrente') THEN
        ALTER TABLE cobrancas_mensais ADD CONSTRAINT fk_cobrancas_mensais_recorrente
            FOREIGN KEY (recorrente_id) REFERENCES cobrancas_recorrentes(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_auditoria_empresa') THEN
        ALTER TABLE auditoria ADD CONSTRAINT fk_auditoria_empresa
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_auditoria_usuario') THEN
        ALTER TABLE auditoria ADD CONSTRAINT fk_auditoria_usuario
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL NOT VALID;
    END IF;
END $$;

COMMIT;
