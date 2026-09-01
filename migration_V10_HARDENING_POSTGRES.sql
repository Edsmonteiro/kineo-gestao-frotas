-- Kineo V10 - Hardening de integridade, liquidação financeira e multiempresa
-- PostgreSQL / Neon
-- ORDEM: V8.1 -> V9 -> V10
-- Execute primeiro em HOMOLOGAÇÃO, com snapshot/backup antes de qualquer ambiente persistente.

BEGIN;

-- 1) Arquivamento seguro de veículos
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS ativo INTEGER NOT NULL DEFAULT 1;
UPDATE veiculos SET ativo = 1 WHERE ativo IS NULL;
CREATE INDEX IF NOT EXISTS ix_veiculos_empresa_ativo ON veiculos (empresa_id, ativo);

-- 2) Snapshot imutável da liquidação financeira
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS valor_principal_liquidado NUMERIC(14,2) NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS multa_aplicada NUMERIC(14,2) NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS juros_aplicados NUMERIC(14,2) NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS dias_atraso_liquidacao INTEGER NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS valor_liquidado NUMERIC(14,2) NULL;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS liquidacao_congelada INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cobrancas_mensais ADD COLUMN IF NOT EXISTS liquidado_em TIMESTAMP NULL;

-- Congela cobranças históricas que já possuem data de recebimento.
WITH calc AS (
    SELECT
        id,
        ROUND(COALESCE(valor_previsto, 0)::numeric, 2) AS principal,
        GREATEST(COALESCE(data_recebimento - vencimento, 0), 0) AS dias,
        COALESCE(multa, 0)::numeric AS pct_multa,
        COALESCE(juros, 0)::numeric AS pct_juros
    FROM cobrancas_mensais
    WHERE data_recebimento IS NOT NULL
      AND COALESCE(liquidacao_congelada, 0) = 0
      AND COALESCE(status, '') NOT IN ('Cancelada', 'Não cobrar')
), valores AS (
    SELECT
        id,
        principal,
        dias,
        CASE WHEN dias > 0 THEN ROUND(principal * pct_multa / 100, 2) ELSE 0::numeric END AS multa_val,
        CASE WHEN dias > 0 THEN ROUND(principal * pct_juros / 100 * dias / 30, 2) ELSE 0::numeric END AS juros_val
    FROM calc
)
UPDATE cobrancas_mensais c
SET
    valor_principal_liquidado = v.principal,
    multa_aplicada = v.multa_val,
    juros_aplicados = v.juros_val,
    dias_atraso_liquidacao = v.dias,
    valor_liquidado = ROUND(v.principal + v.multa_val + v.juros_val, 2),
    liquidacao_congelada = 1,
    liquidado_em = CURRENT_TIMESTAMP,
    status = 'Recebida'
FROM valores v
WHERE c.id = v.id;

-- 3) Pré-validação: a migration para se encontrar inconsistência que comprometa tenant isolation.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM contratos c JOIN veiculos v ON v.id = c.veiculo_id
        WHERE c.empresa_id <> v.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: contrato vinculado a veículo de outra empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM custos c JOIN veiculos v ON v.id = c.veiculo_id
        WHERE c.empresa_id <> v.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: custo vinculado a veículo de outra empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM custos c JOIN contratos ct ON ct.id = c.contrato_id
        WHERE c.contrato_id IS NOT NULL AND c.empresa_id <> ct.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: custo vinculado a contrato de outra empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM custos c JOIN motoristas m ON m.id = c.motorista_id
        WHERE c.motorista_id IS NOT NULL AND c.empresa_id <> m.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: custo vinculado a motorista de outra empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM cobrancas_recorrentes cr JOIN contratos c ON c.id = cr.contrato_id
        WHERE cr.contrato_id IS NOT NULL AND cr.empresa_id <> c.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: cobrança recorrente vinculada a contrato de outra empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM cobrancas_mensais cm JOIN contratos c ON c.id = cm.contrato_id
        WHERE cm.contrato_id IS NOT NULL AND cm.empresa_id <> c.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: cobrança mensal vinculada a contrato de outra empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM cobrancas_mensais cm JOIN cobrancas_recorrentes cr ON cr.id = cm.recorrente_id
        WHERE cm.recorrente_id IS NOT NULL AND cm.empresa_id <> cr.empresa_id
    ) THEN RAISE EXCEPTION 'V10 abortada: cobrança mensal vinculada a recorrência de outra empresa.'; END IF;
END $$;

-- 4) Pré-validação de duplicidades antes de criar uniques.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM veiculos GROUP BY empresa_id, placa HAVING COUNT(*) > 1
    ) THEN RAISE EXCEPTION 'V10 abortada: existem placas duplicadas dentro da mesma empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM motoristas WHERE cpf IS NOT NULL AND BTRIM(cpf) <> ''
        GROUP BY empresa_id, cpf HAVING COUNT(*) > 1
    ) THEN RAISE EXCEPTION 'V10 abortada: existem CPFs de motorista duplicados na mesma empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM motoristas WHERE cnh IS NOT NULL AND BTRIM(cnh) <> ''
        GROUP BY empresa_id, cnh HAVING COUNT(*) > 1
    ) THEN RAISE EXCEPTION 'V10 abortada: existem CNHs duplicadas na mesma empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM motoristas WHERE matricula IS NOT NULL AND BTRIM(matricula) <> ''
        GROUP BY empresa_id, matricula HAVING COUNT(*) > 1
    ) THEN RAISE EXCEPTION 'V10 abortada: existem matrículas de motorista duplicadas na mesma empresa.'; END IF;

    IF EXISTS (
        SELECT 1 FROM cobrancas_mensais
        WHERE recorrente_id IS NOT NULL
        GROUP BY empresa_id, recorrente_id, mes_ano HAVING COUNT(*) > 1
    ) THEN RAISE EXCEPTION 'V10 abortada: existem recorrências duplicadas na mesma competência.'; END IF;

    IF EXISTS (
        SELECT 1 FROM cobrancas_mensais
        WHERE contrato_id IS NOT NULL AND tipo = 'Recorrente'
        GROUP BY empresa_id, contrato_id, mes_ano, tipo HAVING COUNT(*) > 1
    ) THEN RAISE EXCEPTION 'V10 abortada: existem cobranças recorrentes duplicadas por contrato/competência.'; END IF;
END $$;

-- 5) Placa passa a ser única POR EMPRESA, não globalmente.
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'veiculos'::regclass
          AND contype = 'u'
          AND pg_get_constraintdef(oid) = 'UNIQUE (placa)'
    LOOP
        EXECUTE format('ALTER TABLE veiculos DROP CONSTRAINT %I', r.conname);
    END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_veiculos_empresa_placa ON veiculos (empresa_id, placa);

-- 6) Identificadores de motorista únicos dentro de cada empresa quando informados.
CREATE UNIQUE INDEX IF NOT EXISTS uq_motoristas_empresa_cpf
    ON motoristas (empresa_id, cpf) WHERE cpf IS NOT NULL AND BTRIM(cpf) <> '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_motoristas_empresa_cnh
    ON motoristas (empresa_id, cnh) WHERE cnh IS NOT NULL AND BTRIM(cnh) <> '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_motoristas_empresa_matricula
    ON motoristas (empresa_id, matricula) WHERE matricula IS NOT NULL AND BTRIM(matricula) <> '';

-- 7) Anti-duplicidade financeira em concorrência.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cobrancas_recorrente_competencia
    ON cobrancas_mensais (empresa_id, recorrente_id, mes_ano)
    WHERE recorrente_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cobrancas_contrato_recorrente_competencia
    ON cobrancas_mensais (empresa_id, contrato_id, mes_ano, tipo)
    WHERE contrato_id IS NOT NULL AND tipo = 'Recorrente';

-- 8) Chaves compostas de tenant exigem pares (empresa_id,id) referenciáveis.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_usuarios_empresa_id') THEN
        ALTER TABLE usuarios ADD CONSTRAINT uq_usuarios_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_veiculos_empresa_id') THEN
        ALTER TABLE veiculos ADD CONSTRAINT uq_veiculos_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_contratos_empresa_id') THEN
        ALTER TABLE contratos ADD CONSTRAINT uq_contratos_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_motoristas_empresa_id') THEN
        ALTER TABLE motoristas ADD CONSTRAINT uq_motoristas_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_custos_empresa_id') THEN
        ALTER TABLE custos ADD CONSTRAINT uq_custos_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_planos_empresa_id') THEN
        ALTER TABLE planos_manutencao ADD CONSTRAINT uq_planos_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_itens_plano_empresa_id') THEN
        ALTER TABLE itens_plano_manutencao ADD CONSTRAINT uq_itens_plano_empresa_id UNIQUE (empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_cobrancas_rec_empresa_id') THEN
        ALTER TABLE cobrancas_recorrentes ADD CONSTRAINT uq_cobrancas_rec_empresa_id UNIQUE (empresa_id,id);
    END IF;
END $$;

-- 9) FKs compostas: o PostgreSQL também impede vínculos cruzados entre empresas.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contratos_tenant_veiculo') THEN
        ALTER TABLE contratos ADD CONSTRAINT fk_contratos_tenant_veiculo
            FOREIGN KEY (empresa_id,veiculo_id) REFERENCES veiculos(empresa_id,id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_substituicoes_tenant_contrato') THEN
        ALTER TABLE substituicoes_contrato ADD CONSTRAINT fk_substituicoes_tenant_contrato
            FOREIGN KEY (empresa_id,contrato_id) REFERENCES contratos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_substituicoes_tenant_principal') THEN
        ALTER TABLE substituicoes_contrato ADD CONSTRAINT fk_substituicoes_tenant_principal
            FOREIGN KEY (empresa_id,veiculo_principal_id) REFERENCES veiculos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_substituicoes_tenant_substituto') THEN
        ALTER TABLE substituicoes_contrato ADD CONSTRAINT fk_substituicoes_tenant_substituto
            FOREIGN KEY (empresa_id,veiculo_substituto_id) REFERENCES veiculos(empresa_id,id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_motoristas_tenant_usuario') THEN
        ALTER TABLE motoristas ADD CONSTRAINT fk_motoristas_tenant_usuario
            FOREIGN KEY (empresa_id,usuario_id) REFERENCES usuarios(empresa_id,id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_custos_tenant_veiculo') THEN
        ALTER TABLE custos ADD CONSTRAINT fk_custos_tenant_veiculo
            FOREIGN KEY (empresa_id,veiculo_id) REFERENCES veiculos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_custos_tenant_contrato') THEN
        ALTER TABLE custos ADD CONSTRAINT fk_custos_tenant_contrato
            FOREIGN KEY (empresa_id,contrato_id) REFERENCES contratos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_custos_tenant_motorista') THEN
        ALTER TABLE custos ADD CONSTRAINT fk_custos_tenant_motorista
            FOREIGN KEY (empresa_id,motorista_id) REFERENCES motoristas(empresa_id,id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_itens_plano_tenant_plano') THEN
        ALTER TABLE itens_plano_manutencao ADD CONSTRAINT fk_itens_plano_tenant_plano
            FOREIGN KEY (empresa_id,plano_id) REFERENCES planos_manutencao(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_manutencoes_tenant_veiculo') THEN
        ALTER TABLE manutencoes_realizadas ADD CONSTRAINT fk_manutencoes_tenant_veiculo
            FOREIGN KEY (empresa_id,veiculo_id) REFERENCES veiculos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_manutencoes_tenant_item') THEN
        ALTER TABLE manutencoes_realizadas ADD CONSTRAINT fk_manutencoes_tenant_item
            FOREIGN KEY (empresa_id,plano_item_id) REFERENCES itens_plano_manutencao(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_manutencoes_tenant_custo') THEN
        ALTER TABLE manutencoes_realizadas ADD CONSTRAINT fk_manutencoes_tenant_custo
            FOREIGN KEY (empresa_id,custo_id) REFERENCES custos(empresa_id,id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_cobrancas_rec_tenant_contrato') THEN
        ALTER TABLE cobrancas_recorrentes ADD CONSTRAINT fk_cobrancas_rec_tenant_contrato
            FOREIGN KEY (empresa_id,contrato_id) REFERENCES contratos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_cobrancas_mensais_tenant_contrato') THEN
        ALTER TABLE cobrancas_mensais ADD CONSTRAINT fk_cobrancas_mensais_tenant_contrato
            FOREIGN KEY (empresa_id,contrato_id) REFERENCES contratos(empresa_id,id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_cobrancas_mensais_tenant_recorrente') THEN
        ALTER TABLE cobrancas_mensais ADD CONSTRAINT fk_cobrancas_mensais_tenant_recorrente
            FOREIGN KEY (empresa_id,recorrente_id) REFERENCES cobrancas_recorrentes(empresa_id,id);
    END IF;
END $$;

COMMIT;
