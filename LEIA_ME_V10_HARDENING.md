# Kineo V10 — Hardening técnico

Esta versão parte da V9.4 já validada funcionalmente. A V10 não adiciona novos módulos comerciais; ela endurece integridade, segurança e confiabilidade antes da homologação real.

## Arquivos

- `app_HARDENING_V10.py` → substituir temporariamente `app.py` no DEV local.
- `database_HARDENING_V10.py` → substituir temporariamente `database.py` no DEV local.
- `migration_V10_HARDENING_POSTGRES.sql` → **não executar na produção agora**. Executar primeiro no Neon/PostgreSQL de homologação, depois de V8.1 e V9.
- `requirements_V10_ADICIONAR.txt` → adicionar a linha ao `requirements.txt` existente.

## O que mudou

1. Veículos com histórico não são mais apagados. Eles são arquivados; exclusão física só é permitida para cadastro sem histórico.
2. `veiculos.ativo` separa frota operacional de veículos arquivados sem destruir histórico.
3. Cobranças recebidas passam a guardar snapshot da liquidação: principal, multa, juros, dias de atraso e valor liquidado.
4. Liquidações congeladas não são recalculadas se o contrato ou percentuais forem alterados depois.
5. Parcelamentos usam `Decimal` e preservam centavos. Ex.: R$ 100 / 3 = 33,33 + 33,33 + 33,34.
6. Regras de “hoje” usam `KINEO_TIMEZONE` (padrão `America/Fortaleza`), enquanto timestamps de auditoria/autenticação permanecem em UTC.
7. Banco ganha proteção multiempresa por FKs compostas `(empresa_id, id)`.
8. Placa passa a ser única por empresa, não globalmente.
9. CPF, CNH e matrícula de motorista passam a ter unicidade por empresa quando preenchidos.
10. Cobranças recorrentes ganham índices únicos para impedir duplicidade por concorrência.
11. Auditoria ampliada para liquidações, geração de competência, recorrências e exclusão de custos.
12. Comprovantes, logos e avatares passam por uma camada de storage. DEV pode usar disco local; homologação/produção exigem S3.
13. PostgreSQL/Neon exige SSL também em homologação.
14. Validação de schema gerenciado passa a conferir colunas V10, tipos financeiros, índices e FKs críticas.

## DEV local

Mantenha:

```powershell
$env:DATABASE_URL = "sqlite:///kineo_homolog_local.db"
$env:KINEO_ENV = "development"
```

No DEV, `KINEO_STORAGE_BACKEND` pode ficar ausente; o padrão será `local`.

Instale a dependência nova depois de adicioná-la ao `requirements.txt`:

```powershell
pip install -r requirements.txt
```

Depois:

```powershell
streamlit run app.py
```

O `database.py` faz apenas a evolução aditiva necessária no SQLite local e congela cobranças históricas que já possuam data de recebimento.

## HOMOLOGAÇÃO / PRODUÇÃO

Configuração mínima esperada:

```text
KINEO_ENV=homologacao            # ou production
DATABASE_URL=<PostgreSQL/Neon>
KINEO_TIMEZONE=America/Fortaleza
KINEO_STORAGE_BACKEND=s3
KINEO_S3_BUCKET=<bucket privado>
KINEO_S3_PREFIX=kineo
```

Credenciais AWS devem vir da role/credencial da infraestrutura, nunca do repositório.

A ordem de migrations é:

```text
migration_V8_1_SEGURANCA_POSTGRES.sql
↓
migration_V9_PESSOAS_MOTORISTAS_POSTGRES.sql
↓
migration_V10_HARDENING_POSTGRES.sql
```

A V10 aborta deliberadamente se encontrar duplicidades ou vínculos cruzados entre empresas. Isso é uma proteção: os dados precisam ser corrigidos antes da constraint ser instalada.

## Smoke tests impactados

1. Arquivar um veículo com histórico e confirmar que custos/contratos permanecem consultáveis.
2. Excluir um veículo fictício sem histórico.
3. Reativar veículo arquivado.
4. Receber cobrança 5 dias após vencimento e validar snapshot de multa/juros.
5. Alterar depois a multa do contrato e confirmar que a liquidação antiga não muda.
6. Testar R$ 100,00 em 3 parcelas e confirmar soma exata de R$ 100,00.
7. Gerar uma competência recorrente duas vezes/concorrentemente e confirmar ausência de duplicidade.
8. Confirmar que o Dashboard usa o valor liquidado congelado.
9. Confirmar que veículo arquivado não aparece para novos custos/contratos/manutenção operacional.
10. Em ambiente gerenciado, confirmar upload/download de comprovante via S3.

## Importante

Não executar a migration V10 no Neon de produção antes da homologação real e do snapshot/backup. Não fazer merge na `main` antes de passar os smoke tests acima.
