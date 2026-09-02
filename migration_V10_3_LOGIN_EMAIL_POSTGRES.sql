-- Kineo V10.3 — Login por e-mail ou usuário
-- Executar SOMENTE após validar em DEV e HOMOLOGAÇÃO.
-- Em ambientes gerenciados, KINEO_AUTO_MIGRATE deve permanecer false.

BEGIN;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS email VARCHAR(254);

-- Normaliza qualquer valor já existente antes de criar a unicidade.
UPDATE usuarios
SET email = LOWER(BTRIM(email))
WHERE email IS NOT NULL
  AND email <> LOWER(BTRIM(email));

UPDATE usuarios
SET email = NULL
WHERE email IS NOT NULL
  AND BTRIM(email) = '';

-- Um e-mail identifica uma única credencial na fase atual.
-- NULL continua permitido para usuários legados até o administrador cadastrar o e-mail.
CREATE UNIQUE INDEX IF NOT EXISTS uq_usuarios_email
    ON usuarios (email)
    WHERE email IS NOT NULL;

COMMIT;

-- Validação somente leitura:
-- SELECT column_name, data_type, character_maximum_length
-- FROM information_schema.columns
-- WHERE table_schema='public' AND table_name='usuarios' AND column_name='email';
--
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname='public' AND indexname='uq_usuarios_email';
