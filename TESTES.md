# Testes automatizados do Kineo

## Preparação

No PowerShell, com a branch de testes atualizada e o ambiente virtual ativado:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Executar a suíte

```powershell
python -m pytest
```

Os testes desta etapa são isolados: não usam credenciais, não acessam o banco de produção e não iniciam a interface Streamlit.

## Verificação complementar

```powershell
python -m py_compile app.py database.py kineo_core.py
```
