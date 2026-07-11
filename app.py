import pandas as pd
import os
import streamlit as st
from groq import Groq
import sqlite3
import plotly.express as px
import json

client = Groq(api_key=os.environ["GROQ_API_KEY"])

def carregar_dados(ficheiro):
    sheets = pd.read_excel(ficheiro, sheet_name=None)
    return {nome: df for nome, df in sheets.items() if nome != "Resumo"}

def get_schema(dados):
    schema = ""
    for nome, df in dados.items():
        colunas = ", ".join([f"{col} ({str(df[col].dtype)})" for col in df.columns])
        schema += f"Tabela '{nome}': {colunas}\n\n"
    return schema

def run_query(dados, sql):
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

def agente(pergunta, historico, dados):
    schema = get_schema(dados)
    contexto = "".join([f"Utilizador: {t['pergunta']}\nResposta: {t['resposta']}\n\n" for t in historico])

    sql_gerado = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"""Base de dados SQLite:
{schema}

Histórico da conversa até agora:
{contexto}

Nova pergunta: {pergunta}

Responde APENAS com SQL, sem markdown, sem backticks."""}]
    ).choices[0].message.content.strip()

    resultado_df = run_query(dados, sql_gerado)

    if isinstance(resultado_df, str):
        return resultado_df, sql_gerado, None

    resultado_str = resultado_df.to_string(index=False)

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
            if tipo_grafico == "bar":
                grafico = px.bar(resultado_df, x=col_x, y=col_y, title=pergunta)
            elif tipo_grafico == "line":
                grafico = px.line(resultado_df, x=col_x, y=col_y, title=pergunta)
            elif tipo_grafico == "pie":
                grafico = px.pie(resultado_df, names=col_x, values=col_y, title=pergunta)

        return resposta_texto, sql_gerado, grafico

    except:
        return resultado_str, sql_gerado, None


# --- Inicializar session state ---
if "dados" not in st.session_state:
    st.session_state.dados = None
if "historico" not in st.session_state:
    st.session_state.historico = []
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

# --- Interface ---
st.set_page_config(page_title="FarmAgent", page_icon="💊", layout="wide")
st.title("💊 FarmAgent")
st.caption("Faz perguntas sobre os teus dados em linguagem natural")

with st.sidebar:
    st.header("📂 Carregar dados")
    ficheiro = st.file_uploader("Carrega um ficheiro Excel", type=["xlsx"])

    if ficheiro:
        novos_dados = carregar_dados(ficheiro)
        if st.session_state.dados is None:
            st.session_state.dados = novos_dados
            st.success(f"{len(novos_dados)} tabelas carregadas!")
        else:
            if st.button("🔄 Substituir dados actuais"):
                st.session_state.dados = novos_dados
                st.session_state.historico = []
                st.session_state.mensagens = []
                st.success("Dados substituídos!")

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

# --- Chat ---
if st.session_state.dados is None:
    st.info("👈 Começa por carregar um ficheiro Excel na barra lateral.")
else:
    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if "grafico" in msg and msg["grafico"] is not None:
                st.plotly_chart(msg["grafico"], use_container_width=True)

    if pergunta := st.chat_input("Faz uma pergunta sobre os dados..."):
        st.chat_message("user").write(pergunta)
        st.session_state.mensagens.append({"role": "user", "content": pergunta, "grafico": None})

        with st.spinner("A analisar..."):
            resposta, sql, grafico = agente(pergunta, st.session_state.historico, st.session_state.dados)

        with st.chat_message("assistant"):
            st.write(resposta)
            if grafico:
                st.plotly_chart(grafico, use_container_width=True)
            with st.expander("SQL gerado"):
                st.code(sql, language="sql")

        st.session_state.mensagens.append({"role": "assistant", "content": resposta, "grafico": grafico})
        st.session_state.historico.append({"pergunta": pergunta, "resposta": resposta})