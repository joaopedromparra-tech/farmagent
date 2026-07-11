# 💊 FarmAgent

Assistente de dados para farmácia, alimentado por IA. Faz perguntas em português sobre os dados da tua farmácia — vendas, stock, clientes, fornecedores — e recebe respostas em linguagem natural com gráficos automáticos, sem escrever uma linha de SQL.

*🔗 Experimenta a app ao vivo:* [farmagent-9hnyletwjpwtquxiuqsacz.streamlit.app](https://farmagent-9hnyletwjpwtquxiuqsacz.streamlit.app)

<img width="1652" height="869" alt="image" src="https://github.com/user-attachments/assets/dd491617-ac5d-4ea0-ad10-5e1c58a854a1" />


---

## 🧠 O que faz

- Carrega um ficheiro Excel com várias folhas (produtos, clientes, vendas, fornecedores)
- Converte perguntas em português para consultas SQL automaticamente
- Gera respostas contextualizadas, com memória da conversa
- Cria gráficos automáticos (barras, linhas, circular) quando fizer sentido
- Mostra o SQL gerado, para transparência total
- Deteta e corrige automaticamente consultas SQL inválidas
- Bloqueia operações destrutivas — apenas leitura de dados é permitida
- Apresenta indicadores-chave (KPIs) da farmácia logo à entrada
- Permite exportar qualquer resultado em CSV

## 🛠️ Stack técnica

| Camada | Tecnologia |
|---|---|
| Interface | [Streamlit](https://streamlit.io) |
| LLM | [Groq API](https://groq.com) — llama-3.3-70b-versatile |
| Base de dados | SQLite (em memória) |
| Dados de entrada | Excel via pandas + openpyxl |
| Visualização | Plotly Express |
| Deploy | Streamlit Community Cloud |

## ⚙️ Como funciona

Excel (multi-folha)
        │
        ▼
  pandas → SQLite (em memória)
        │
        ▼
Pergunta em português ──► LLM gera SQL ──► valida e executa
        │                                        │
        ▼                                        ▼
  Histórico da conversa              Resultado → LLM interpreta
                                                  │
                                                  ▼
                                   Resposta em português + gráfico

Se a consulta SQL gerada falhar, o agente envia o erro de volta ao LLM e tenta corrigi-la automaticamente antes de desistir.

## 🚀 Correr localmente

git clone https://github.com/joaopedromparra-tech/farmagent.git
cd farmagent
pip install -r requirements.txt

Define a tua chave da Groq API (gratuita em [console.groq.com](https://console.groq.com)):

$env:GROQ_API_KEY = 'a-tua-chave'

Corre a app:

python -m streamlit run app.py

## 📂 Estrutura dos dados

A app espera um Excel com estas folhas (nomes exatos):

- *Produtos* — nome, categoria, laboratório, preços, stock, stock mínimo, validade
- *Clientes* — nome, NIF, contacto, pontos de fidelidade
- *Vendas* — data, cliente, produto, quantidade, desconto, total
- *Fornecedores* — nome, NIF, contacto, prazo de entrega

Um ficheiro de exemplo (farmacia_complexa.xlsx) já vem incluído no repositório e é carregado automaticamente ao abrir a app.

## ✅ Validação

Testado manualmente com um conjunto de perguntas típicas de uma farmácia (vendas por período, produtos mais vendidos, stock abaixo do mínimo, clientes com mais pontos de fidelidade, comparações entre meses). O agente inclui um mecanismo de auto-correção: quando o SQL gerado falha, tenta corrigir-se automaticamente antes de devolver um erro ao utilizador.

Próximo passo: documentar um conjunto de testes formal (perguntas vs. respostas esperadas) para medir taxa de acerto de forma sistemática.


## 💰 Custos estimados

A app usa a Groq API, que tem um tier gratuito generoso — para uso pessoal/portfolio o custo é praticamente zero. Numa versão com uso empresarial real (mais utilizadores, mais pedidos), a estimativa é:

- *Stack otimizada* (Groq + Streamlit Cloud gratuito): ~10 €/mês
- *Stack profissional completa* (base de dados dedicada, hosting próprio, LLM pago): ~185 €/mês

## 🗺️ Próximos passos

- [ ] Testes formais com conjunto de perguntas documentado
- [ ] Versionamento dos prompts do agente (separar do código)
- [ ] Migrar para PostgreSQL para persistência real
- [ ] Orquestração com LangGraph para agentes especializados (vendas, stock, clientes)
- [ ] Autenticação de utilizadores

## 👤 Autor

*João Pedro Parra* — farmacêutico em transição para Data Analytics & BI.

[LinkedIn](https://www.linkedin.com/in/joão-pedro-parra-904a58248)
