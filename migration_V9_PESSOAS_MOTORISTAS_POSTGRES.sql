-- Kineo V9 - Pessoas e Acessos / Motoristas
-- Executar APENAS em PostgreSQL/Neon de HOMOLOGAÇÃO primeiro.
-- Pré-requisito: schema V8.1 de segurança já aplicado.
-- Faça backup/snapshot antes de executar em qualquer ambiente persistente.

BEGIN;

CREATE TABLE IF NOT EXISTS motoristas (
    id SERIAL PRIMARY KEY,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id),
    nome VARCHAR NOT NULL,
    cpf VARCHAR NULL,
    matricula VARCHAR NULL,
    telefone VARCHAR NULL,
    cnh VARCHAR NULL,
    categoria_cnh VARCHAR NULL,
    validade_cnh DATE NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    observacoes VARCHAR NULL,
    usuario_id INTEGER NULL REFERENCES usuarios(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_motoristas_empresa_id ON motoristas (empresa_id);
CREATE INDEX IF NOT EXISTS ix_motoristas_nome ON motoristas (nome);
CREATE INDEX IF NOT EXISTS ix_motoristas_validade_cnh ON motoristas (validade_cnh);
CREATE INDEX IF NOT EXISTS ix_motoristas_ativo ON motoristas (ativo);
CREATE INDEX IF NOT EXISTS ix_motoristas_usuario_id ON motoristas (usuario_id);
CREATE INDEX IF NOT EXISTS ix_motoristas_empresa_ativo ON motoristas (empresa_id, ativo);

ALTER TABLE custos
    ADD COLUMN IF NOT EXISTS motorista_id INTEGER NULL;

CREATE INDEX IF NOT EXISTS ix_custos_motorista_id ON custos (motorista_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_custos_motorista_id'
    ) THEN
        ALTER TABLE custos
            ADD CONSTRAINT fk_custos_motorista_id
            FOREIGN KEY (motorista_id)
            REFERENCES motoristas(id)
            ON DELETE SET NULL;
    END IF;
END $$;

-- O campo custos.motorista (texto) é preservado propositalmente para manter
-- compatibilidade e histórico dos lançamentos antigos. Novos lançamentos passam
-- a gravar motorista_id e também um snapshot textual do nome.

COMMIT;
