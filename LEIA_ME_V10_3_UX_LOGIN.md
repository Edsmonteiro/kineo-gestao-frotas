# Kineo V10.3 — UX Login

Pacote de implementação preparado a partir da V10.2 homologada.

## Arquivos

- `app_UX_LOGIN_V10_3.py` → candidato a `app.py` em DEV.
- `database_UX_LOGIN_V10_3.py` → candidato a `database.py` em DEV.
- `assets/kineo_login_frota.png` → asset visual da tela pública.
- `migration_V10_3_LOGIN_EMAIL_POSTGRES.sql` → aplicar primeiro em HOMOLOGAÇÃO.
- `requirements_V10_3_ADICIONAR.txt` → adicionar a dependência ao requirements real.
- `AGENTS.md` → regra de Issue → branch → PR → homologação → produção.
- `ISSUE_UX_LOGIN_V10_3.md` → corpo sugerido da Issue.
- `PR_UX_LOGIN_V10_3.md` → descrição sugerida do PR.

## Segurança

A função “Lembrar meu usuário/e-mail” grava somente o identificador no `localStorage`.
Ela não grava senha, hash, token, `empresa_id`, perfil ou sessão.

O timeout de sessão já existente continua sendo aplicado normalmente.

## Compatibilidade

Usuários legados sem e-mail continuam entrando pelo campo `login`.
Novos usuários devem receber um e-mail válido no cadastro administrativo.

## Ordem recomendada

1. Criar Issue.
2. Criar branch `feature/<issue>-ux-login-email`.
3. Testar em DEV.
4. Adicionar dependência ao `requirements.txt`.
5. Abrir PR mencionando a Issue.
6. Aplicar migration no banco de HOMOLOGAÇÃO.
7. Testar autenticação e isolamento multiempresa.
8. Somente após aprovação, promover para produção.
