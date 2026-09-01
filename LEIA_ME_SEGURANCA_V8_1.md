# Kineo — Homologação V8 de Segurança

Esta versão parte da V7 da nova Gestão de Cobranças e adiciona endurecimento de segurança sem ser destinada a `commit/push` direto em produção.

## Principais mudanças

- Argon2id para novas senhas, mantendo leitura de bcrypt legado e rehash transparente após login.
- Política de senha: 6–20 caracteres, bloqueio de senhas comuns e de senha contendo login/nome.
- Senha temporária aleatória e única; `PRIMEIROACESSO` deixa de ser usado para novos usuários/resets.
- Troca de senha disponível a todos os perfis e exige a senha atual.
- Tentativas e bloqueio de login persistidos no banco.
- Timeout de sessão configurável (`KINEO_SESSION_TIMEOUT_MINUTES`, padrão 30 min).
- Ciência da Política de Privacidade gravada por usuário e por versão; o aviso não reaparece a cada login.
- Auditoria de eventos sensíveis.
- `tenant_get()` e reforço de consultas/joins por `empresa_id`.
- Consultas tabulares parametrizam `empresa_id` e os demais filtros variáveis da nova Gestão de Cobranças.
- Validação de uploads por tamanho/extensão/assinatura básica; avatar e logo são reprocessados como PNG.
- Valores principais (`contratos.valor_mensal`, `custos.valor_total`, `cobrancas_mensais.valor_previsto`) passam a `NUMERIC(14,2)` em bancos novos.
- Produção não usa fallback SQLite silencioso e não executa `ALTER TABLE` automaticamente.

## Para testar localmente

1. Mantenha seu banco de homologação local (`sqlite:///kineo_homolog_local.db`) configurado no terminal.
2. Instale a nova dependência:

   `pip install "argon2-cffi>=25.1.0,<26"`

3. Substitua temporariamente os arquivos por:
   - `app_SEGURANCA_HOMOLOG_V8.py` -> `app.py`
   - `database_SEGURANCA_HOMOLOG_V8.py` -> `database.py`
4. Rode `streamlit run app.py`.
5. Não faça commit/push ainda.

Em SQLite existente, as novas colunas de segurança são acrescentadas automaticamente. Para validar também o schema `NUMERIC(14,2)` desde o zero, crie um novo banco local de homologação.

## Antes da produção

- Adicionar `argon2-cffi` ao `requirements.txt` real.
- Criar ambiente/banco de homologação separado.
- Executar `migration_V8_SEGURANCA_POSTGRES.sql` primeiro na homologação e validar backup/rollback.
- Configurar `KINEO_ENV="production"` na produção.
- Manter `KINEO_AUTO_MIGRATE="false"` na produção.
- Migrar comprovantes/logos para storage persistente/privado (por exemplo S3) antes de clientes reais.
- Formalizar migrações com Alembic antes das próximas evoluções de schema.

## Testes mínimos desta V8

- Login correto e incorreto; bloquear após 5 falhas e confirmar que nova aba/navegador não remove o bloqueio.
- Login de usuário antigo bcrypt; após login, confirmar que segue funcionando.
- Criar usuário e conferir senha temporária aleatória + troca obrigatória.
- Testar senha curta, senha comum, senha contendo login, confirmação diferente e frase-senha válida.
- Trocar senha pelo Meu Perfil usando senha atual incorreta/correta.
- Confirmar aviso de privacidade; sair e entrar novamente: não deve reaparecer na mesma versão.
- Alterar `PRIVACY_VERSION` em homologação para testar reapresentação do aviso.
- Revogar usuário e confirmar impossibilidade de login.
- Conferir aba Configurações > Auditoria.
- Testar upload de avatar/logo/comprovante válido e arquivo inválido/maior que o limite.
- Repetir Gestão de Cobranças, Custos, Contratos, Frota e Manutenção para verificar regressões.
