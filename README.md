# Kineo · Sistema de Gestão de Frotas e Locações

Plataforma corporativa para controle operacional, comercial e financeiro de frotas de veículos e contratos de locação.

---

## Principais Módulos

- **Painel Gerencial:** Indicadores de ocupação da frota, faturamento previsto, despesas consolidadas e alertas preventivos (revisões e vencimento de contratos).
- **Gestão de Frota:** Cadastro e controle de veículos, histórico de manutenção, consumo de combustível e diagnóstico de saúde preventiva.
- **Gestão de Custos:** Lançamento detalhado de despesas (combustível, peças, serviços, multas), suporte a parcelamento no cartão e anexo de comprovantes.
- **Contratos e Locação:** Gestão de contratos ativos e encerrados, suporte a valores fixos e variáveis, regras de juros e multas por atraso.
- **Contas a Receber (Cobranças):** Matriz mensal de faturamento, geração automática por recorrência e controle de inadimplência.
- **Segurança & Branding:** Autenticação criptografada (bcrypt), controle de níveis de acesso (Admin/Operador) e personalização de identidade visual (marca e logotipo).

---

## Tecnologias Utilizadas

- **Linguagem:** Python
- **Interface:** Streamlit
- **Visualização de Dados:** Plotly
- **Manipulação de Dados:** Pandas
- **Persistência / ORM:** SQLAlchemy
- **Segurança:** Bcrypt

---

## Execução Local

1. Crie e ative o ambiente virtual:
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Linux/Mac:
   source venv/bin/activate