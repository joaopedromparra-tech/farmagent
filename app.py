import pandas as pd
import os
import time
import streamlit as st
from groq import Groq
import sqlite3
import plotly.express as px
import json

client = Groq(api_key=os.environ["GROQ_API_KEY"])

EXCEL_PADRAO = "farmacia_complexa.xlsx"

PERGUNTAS_EXEMPLO = [
    "Quais os 5 produtos mais vendidos?",
    "Qual o total de vendas por mês?",
    "Quais clientes têm mais pontos de fidelidade?",
    "Que produtos têm stock abaixo do mínimo?",
]

PALAVRAS_PROIBIDAS = ["DROP", "DELETE", "UPDATE", "ALTER", "INSERT", "TRUNCATE", "ATTACH", "PRAGMA"]


@st.cache_data
def carregar_dados_ficheiro(ficheiro):
    sheets = pd.read_excel(ficheiro, sheet_name=None)
    return {nome: df for nome, df in sheets.items() if nome != "Resumo"}


def get_schema(dados):
    schema = ""
    for nome, df in dados.items():
        colunas = ", ".join([f"{col} ({str(df[col].dtype)})" for col in df.columns])
        schema += f"Tabela '{nome}': {colunas}\n\n"
    return schema


def sql_e_seguro(sql):
    sql_upper = sql.upper()
    return not any(palavra in sql_upper for palavra in PALAVRAS_PROIBIDAS)


def run_query(dados, sql):
    if not sql_e_seguro(sql):
        return "Operação não permitida: apenas consultas de leitura (SELECT) são aceites."

    conn = sqlite3.connect(":memory:")
    for nome, df in dados.items():
        df.to_sql(nome, conn, index=False, if_exists="replace")
    try:
        resultado = pd.read_sql_query(sql, conn)
        conn.close()
        return resultado
    except Exception as e:
        conn.close()
        return str(e)


def gerar_sql(pergunta, contexto, schema, erro_anterior=None, sql_anterior=None):
    prompt = f"""Base de dados SQLite:
{schema}

Histórico da conversa até agora:
{contexto}

Nova pergunta: {pergunta}

Responde APENAS com SQL, sem markdown, sem backticks."""

    if erro_anterior:
        prompt = f"""Base de dados SQLite:
{schema}

A tentativa anterior de gerar SQL para a pergunta "{pergunta}" falhou.
SQL tentado: {sql_anterior}
Erro obtido: {erro_anterior}

Corrige o SQL e responde APENAS com o SQL corrigido, sem markdown, sem backticks."""

    return client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    ).choices[0].message.content.strip()


def agente(pergunta, historico, dados, status):
    schema = get_schema(dados)
    contexto = "".join(
        [f"Utilizador: {t['pergunta']}\nResposta: {t['resposta']}\n\n" for t in historico]
    )

    status.update(label="A gerar consulta SQL...")
    sql_gerado = gerar_sql(pergunta, contexto, schema)
    resultado_df = run_query(dados, sql_gerado)

    # Auto-correção: se falhar, tenta corrigir uma vez
    if isinstance(resultado_df, str):
        status.update(label="A corrigir a consulta...")
        sql_corrigido = gerar_sql(pergunta, contexto, schema, erro_anterior=resultado_df, sql_anterior=sql_gerado)
        resultado_novo = run_query(dados, sql_corrigido)
        if not isinstance(resultado_novo, str):
            sql_gerado = sql_corrigido
            resultado_df = resultado_novo
        else:
            return resultado_novo, sql_gerado, None, None

    resultado_str = resultado_df.to_string(index=False)

    status.update(label="A preparar a resposta...")
    resposta_raw = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Histórico da conversa:
{contexto}

Pergunta atual: {pergunta}
Resultado SQL: {resultado_str}

Responde em JSON com este formato exato:
{{"resposta": "resposta completa em português considerando todo o histórico", "grafico": "bar|line|pie|none", "x": "coluna_x", "y": "coluna_y"}}

IMPORTANTE: Usa o histórico para dar respostas contextualizadas e comparativas quando relevante.
Responde APENAS com JSON, sem markdown."""}]
    ).choices[0].message.content.strip()

    try:
        resposta_raw = resposta_raw.replace("```json", "").replace("```", "").strip()
        dados_resposta = json.loads(resposta_raw)
        resposta_texto = dados_resposta.get("resposta", "")
        tipo_grafico = dados_resposta.get("grafico", "none")
        col_x = dados_resposta.get("x", "")
        col_y = dados_resposta.get("y", "")

        grafico = None
        if tipo_grafico != "none" and col_x in resultado_df.columns and col_y in resultado_df.columns:
            cores = px.colors.sequential.Teal
            if tipo_grafico == "bar":
                grafico = px.bar(resultado_df, x=col_x, y=col_y, title=pergunta, color_discrete_sequence=cores)
            elif tipo_grafico == "line":
                grafico = px.line(resultado_df, x=col_x, y=col_y, title=pergunta, color_discrete_sequence=cores)
            elif tipo_grafico == "pie":
                grafico = px.pie(resultado_df, names=col_x, values=col_y, title=pergunta, color_discrete_sequence=cores)

            if grafico:
                grafico.update_layout(
                    title_font_size=16,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=50, l=10, r=10, b=10),
                )

        return resposta_texto, sql_gerado, grafico, resultado_df
    except Exception:
        return resultado_str, sql_gerado, None, resultado_df


def calcular_kpis(dados):
    kpis = {}
    if "Vendas" in dados:
        vendas = dados["Vendas"]
        if "total" in vendas.columns:
            kpis["Vendas totais"] = f"{vendas['total'].sum():,.2f} €"
            kpis["Ticket médio"] = f"{vendas['total'].mean():,.2f} €"
    if "Produtos" in dados:
        produtos = dados["Produtos"]
        if "stock" in produtos.columns and "stock_minimo" in produtos.columns:
            abaixo_minimo = (produtos["stock"] < produtos["stock_minimo"]).sum()
            kpis["Produtos em rutura"] = int(abaixo_minimo)
    if "Clientes" in dados:
        kpis["Clientes registados"] = len(dados["Clientes"])
    return kpis


# ---------- Config da página ----------
st.set_page_config(page_title="FarmAgent", page_icon="💊", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0e1117; }
.farmagent-header {
    padding: 1.2rem 1.5rem;
    border-radius: 14px;
    background: linear-gradient(135deg, #0f766e 0%, #134e4a 100%);
    margin-bottom: 1.5rem;
}
.farmagent-header h1 { color: white; margin: 0; font-size: 2rem; }
.farmagent-header p { color: #ccfbf1; margin: 0.3rem 0 0 0; font-size: 0.95rem; }
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="farmagent-header">
    <h1>💊 FarmAgent</h1>
    <p>O teu assistente de dados para farmácia — pergunta em português, recebe respostas e gráficos automáticos.</p>
</div>
""", unsafe_allow_html=True)

# ---------- Estado ----------
if "dados" not in st.session_state:
    st.session_state.dados = None
if "historico" not in st.session_state:
    st.session_state.historico = []
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []
if "usando_exemplo" not in st.session_state:
    st.session_state.usando_exemplo = False

if st.session_state.dados is None and os.path.exists(EXCEL_PADRAO):
    st.session_state.dados = carregar_dados_ficheiro(EXCEL_PADRAO)
    st.session_state.usando_exemplo = True

# ---------- Sidebar ----------
with st.sidebar:
    st.header("📂 Dados")

    if st.session_state.usando_exemplo:
        st.success("A usar dados de exemplo de uma farmácia fictícia.")

    ficheiro = st.file_uploader("Carrega o teu próprio ficheiro Excel", type=["xlsx"])
    if ficheiro:
        novos_dados = carregar_dados_ficheiro(ficheiro)
        if st.button("🔄 Substituir dados atuais"):
            st.session_state.dados = novos_dados
            st.session_state.usando_exemplo = False
            st.session_state.historico = []
            st.session_state.mensagens = []
            st.success("Dados substituídos!")
            st.rerun()

    if st.session_state.dados:
        st.divider()
        st.subheader("📊 Tabelas carregadas")
        for nome, df in st.session_state.dados.items():
            st.caption(f"• {nome}: {len(df)} linhas")
        st.divider()
        if st.button("🗑️ Limpar conversa"):
            st.session_state.historico = []
            st.session_state.mensagens = []
            st.rerun()

    st.divider()
    st.caption("Feito por João Pedro Parra 🧪")

# ---------- Corpo principal ----------
if st.session_state.dados is None:
    st.info("👈 Carrega um ficheiro Excel na barra lateral para começar.")
else:
    kpis = calcular_kpis(st.session_state.dados)
    if kpis:
        cols_kpi = st.columns(len(kpis))
        for col, (nome, valor) in zip(cols_kpi, kpis.items()):
            col.metric(nome, valor)
        st.divider()

    if not st.session_state.mensagens:
        st.write("*Experimenta perguntar:*")
        cols = st.columns(len(PERGUNTAS_EXEMPLO))
        for col, pergunta_exemplo in zip(cols, PERGUNTAS_EXEMPLO):
            if col.button(pergunta_exemplo, use_container_width=True):
                st.session_state["pergunta_pendente"] = pergunta_exemplo

    for i, msg in enumerate(st.session_state.mensagens):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("grafico") is not None:
                st.plotly_chart(msg["grafico"], use_container_width=True, key=f"grafico_{i}")
            if msg.get("tabela") is not None:
                st.download_button(
                    "⬇️ Descarregar resultados (CSV)",
                    msg["tabela"].to_csv(index=False).encode("utf-8"),
                    file_name="resultado_farmagent.csv",
                    mime="text/csv",
                    key=f"download_{i}",
                )

    pergunta = st.chat_input("Faz uma pergunta sobre os dados...")
    if not pergunta and "pergunta_pendente" in st.session_state:
        pergunta = st.session_state.pop("pergunta_pendente")

    if pergunta:
        st.chat_message("user").write(pergunta)
        st.session_state.mensagens.append({"role": "user", "content": pergunta, "grafico": None, "tabela": None})

        inicio = time.time()
        with st.status("A analisar...", expanded=False) as status:
            resposta, sql, grafico, tabela = agente(pergunta, st.session_state.historico, st.session_state.dados, status)
            status.update(label="Concluído", state="complete")
        duracao = time.time() - inicio

        with st.chat_message("assistant"):
            st.write(resposta)
            if grafico:
                st.plotly_chart(grafico, use_container_width=True, key=f"grafico_novo_{len(st.session_state.mensagens)}")
            if tabela is not None and not isinstance(tabela, str):
                st.download_button(
                    "⬇️ Descarregar resultados (CSV)",
                    tabela.to_csv(index=False).encode("utf-8"),
                    file_name="resultado_farmagent.csv",
                    mime="text/csv",
                    key=f"download_novo_{len(st.session_state.mensagens)}",
                )
            with st.expander("SQL gerado"):
                st.code(sql, language="sql")
            st.caption(f"⏱️ Resposta gerada em {duracao:.1f}s")

        st.session_state.mensagens.append({
            "role": "assistant", "content": resposta, "grafico": grafico,
            "tabela": tabela if not isinstance(tabela, str) else None
        })
        st.session_state.historico.append({"pergunta": pergunta, "resposta": resposta})