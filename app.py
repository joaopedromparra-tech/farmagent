import pandas as pd
import os
import time
import streamlit as st
from groq import Groq
import sqlite3
import plotly.express as px
import json

client = Groq(api_key=os.environ["GROQ_API_KEY"])

DEFAULT_EXCEL = "farmacia_complexa.xlsx"

EXAMPLE_QUESTIONS = [
    "What are the 5 best-selling products?",
    "What are total sales by month?",
    "Which customers have the most loyalty points?",
    "Which products are below minimum stock?",
]

FORBIDDEN_KEYWORDS = ["DROP", "DELETE", "UPDATE", "ALTER", "INSERT", "TRUNCATE", "ATTACH", "PRAGMA"]

CHART_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToAdd": ["toggleFullscreen"],
}


@st.cache_data
def load_data(file):
    sheets = pd.read_excel(file, sheet_name=None)
    return {name: df for name, df in sheets.items() if name != "Resumo"}


def get_schema(data):
    schema = ""
    for name, df in data.items():
        cols = ", ".join([f"{col} ({str(df[col].dtype)})" for col in df.columns])
        schema += f"Table '{name}': {cols}\n\n"
    return schema


def sql_is_safe(sql):
    sql_upper = sql.upper()
    return not any(word in sql_upper for word in FORBIDDEN_KEYWORDS)


def run_query(data, sql):
    if not sql_is_safe(sql):
        return "Operation not allowed: only read-only (SELECT) queries are accepted."

    conn = sqlite3.connect(":memory:")
    for name, df in data.items():
        df.to_sql(name, conn, index=False, if_exists="replace")
    try:
        result = pd.read_sql_query(sql, conn)
        conn.close()
        return result
    except Exception as e:
        conn.close()
        return str(e)


def generate_sql(question, context, schema, previous_error=None, previous_sql=None):
    prompt = f"""SQLite database:
{schema}

Conversation history so far:
{context}

New question: {question}

Reply ONLY with SQL, no markdown, no backticks."""

    if previous_error:
        prompt = f"""SQLite database:
{schema}

The previous attempt to generate SQL for the question "{question}" failed.
Attempted SQL: {previous_sql}
Error received: {previous_error}

Fix the SQL and reply ONLY with the corrected SQL, no markdown, no backticks."""

    return client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    ).choices[0].message.content.strip()


def pick_chart(result_df):
    """Decide chart type locally from the shape of the result, no extra LLM call needed."""
    if result_df is None or len(result_df.columns) != 2 or len(result_df) < 2:
        return None

    col_x, col_y = result_df.columns[0], result_df.columns[1]
    if not pd.api.types.is_numeric_dtype(result_df[col_y]):
        return None

    is_date_like = "date" in col_x.lower() or "data" in col_x.lower() or pd.api.types.is_datetime64_any_dtype(result_df[col_x])
    colors = px.colors.sequential.Teal

    if is_date_like:
        fig = px.line(result_df, x=col_x, y=col_y, color_discrete_sequence=colors)
    elif len(result_df) <= 12:
        fig = px.bar(result_df, x=col_x, y=col_y, color_discrete_sequence=colors)
    else:
        return None

    fig.update_layout(
        title_font_size=16,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=30, l=10, r=10, b=10),
    )
    return fig


def stream_answer(question, context, result_str):
    prompt = f"""Conversation history:
{context}

Current question: {question}
SQL result: {result_str}

Answer the question in clear, natural English. Use the conversation history for
context and comparisons when relevant. Do not mention SQL or databases explicitly
in your answer, just give the business answer. Keep it concise (2-4 sentences
unless the data calls for more detail)."""

    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def cache_key(question, data):
    fingerprint = "|".join(f"{name}:{len(df)}" for name, df in data.items())
    return f"{question.strip().lower()}::{fingerprint}"


def run_agent(question, history, data, status):
    schema = get_schema(data)
    context = "".join([f"User: {t['question']}\nAnswer: {t['answer']}\n\n" for t in history])

    status.update(label="Generating SQL query...")
    sql = generate_sql(question, context, schema)
    result_df = run_query(data, sql)

    if isinstance(result_df, str):
        status.update(label="Fixing the query...")
        fixed_sql = generate_sql(question, context, schema, previous_error=result_df, previous_sql=sql)
        new_result = run_query(data, fixed_sql)
        if not isinstance(new_result, str):
            sql = fixed_sql
            result_df = new_result
        else:
            return new_result, sql, None, None

    result_str = result_df.to_string(index=False)
    chart = pick_chart(result_df)
    return result_str, sql, chart, result_df


def calculate_kpis(data):
    kpis = {}
    if "Vendas" in data:
        sales = data["Vendas"]
        if "Total" in sales.columns:
            kpis["Total Sales"] = f"€{sales['Total'].sum():,.2f}"
            kpis["Avg. Ticket"] = f"€{sales['Total'].mean():,.2f}"
    if "Produtos" in data:
        products = data["Produtos"]
        if "Stock" in products.columns and "Stock_Minimo" in products.columns:
            low_stock = (products["Stock"] < products["Stock_Minimo"]).sum()
            kpis["Low Stock Items"] = int(low_stock)
    if "Clientes" in data:
        kpis["Registered Customers"] = len(data["Clientes"])
    return kpis


@st.dialog("Chart — Full View", width="large")
def show_chart_modal(fig):
    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)


# ---------- Page config ----------
st.set_page_config(page_title="FarmAgent", page_icon="💊", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0e1117; }
.farmagent-header {
    padding: 1.4rem 1.6rem;
    border-radius: 16px;
    background: linear-gradient(135deg, #0f766e 0%, #134e4a 100%);
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 20px rgba(15, 118, 110, 0.25);
}
.farmagent-header h1 { color: white; margin: 0; font-size: 2.1rem; }
.farmagent-header p { color: #ccfbf1; margin: 0.35rem 0 0 0; font-size: 0.97rem; }
.empty-state {
    text-align: center;
    padding: 3rem 1.5rem;
    border: 1px dashed #2d3748;
    border-radius: 16px;
    background-color: #131720;
    margin-top: 1rem;
}
.empty-state .icon { font-size: 2.5rem; }
.empty-state h3 { color: #e6edf3; margin: 0.6rem 0 0.3rem 0; }
.empty-state p { color: #8b949e; margin: 0; font-size: 0.92rem; }
div[data-testid="stButton"] button {
    border-radius: 10px;
    border: 1px solid #1f6f65;
    transition: all 0.15s ease;
}
div[data-testid="stButton"] button:hover {
    border-color: #14b8a6;
    color: #14b8a6;
    transform: translateY(-1px);
}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="farmagent-header">
    <h1>💊 FarmAgent</h1>
    <p>Your AI-powered pharmacy data assistant — ask questions in plain English, get answers and charts instantly.</p>
</div>
""", unsafe_allow_html=True)

with st.expander("ℹ️ How it works"):
    st.markdown("""
FarmAgent turns your Excel spreadsheet into a queryable database and lets an LLM
(Groq's Llama 3.3 70B) translate your questions into SQL on the fly.

1. *You ask* a question in plain English
2. The *LLM generates SQL* against an in-memory SQLite database built from your spreadsheet
3. If the query fails, the agent *automatically retries* with the error fed back to the model
4. The result is turned into a *natural-language answer*, streamed back to you in real time
5. A *chart is chosen automatically* based on the shape of the result — no extra AI call needed

All generated SQL is read-only by design — no destructive operations are ever allowed to run.
""")

# ---------- State ----------
if "data" not in st.session_state:
    st.session_state.data = None
if "history" not in st.session_state:
    st.session_state.history = []
if "messages" not in st.session_state:
    st.session_state.messages = []
if "using_sample" not in st.session_state:
    st.session_state.using_sample = False
if "cache" not in st.session_state:
    st.session_state.cache = {}

if st.session_state.data is None and os.path.exists(DEFAULT_EXCEL):
    st.session_state.data = load_data(DEFAULT_EXCEL)
    st.session_state.using_sample = True

# ---------- Sidebar ----------
with st.sidebar:
    st.header("📂 Data")

    if st.session_state.using_sample:
        st.success("Using sample data from a fictional pharmacy.")

    uploaded_file = st.file_uploader("Upload your own Excel file", type=["xlsx"])
    if uploaded_file:
        new_data = load_data(uploaded_file)
        if st.button("🔄 Replace current data"):
            st.session_state.data = new_data
            st.session_state.using_sample = False
            st.session_state.history = []
            st.session_state.messages = []
            st.session_state.cache = {}
            st.success("Data replaced!")
            st.rerun()

    if st.session_state.data:
        st.divider()
        st.subheader("📊 Loaded tables")
        for name, df in st.session_state.data.items():
            st.caption(f"• {name}: {len(df)} rows")
        st.divider()
        if st.button("🗑️ Clear conversation"):
            st.session_state.history = []
            st.session_state.messages = []
            st.rerun()

    st.divider()
    st.caption("Built by João Pedro Parra 🧪")

# ---------- Main body ----------
if st.session_state.data is None:
    st.markdown("""
    <div class="empty-state">
        <div class="icon">📂</div>
        <h3>No data loaded yet</h3>
        <p>Upload an Excel file in the sidebar to get started.</p>
    </div>
    """, unsafe_allow_html=True)
else:
    kpis = calculate_kpis(st.session_state.data)
    if kpis:
        kpi_cols = st.columns(len(kpis))
        for col, (name, value) in zip(kpi_cols, kpis.items()):
            col.metric(name, value)
        st.divider()

    if not st.session_state.messages:
        st.write("*Try asking:*")
        cols = st.columns(len(EXAMPLE_QUESTIONS))
        for col, example in zip(cols, EXAMPLE_QUESTIONS):
            if col.button(example, use_container_width=True):
                st.session_state["pending_question"] = example

    for i, msg in enumerate(st.session_state.messages):
        avatar = "💊" if msg["role"] == "assistant" else "🧑"
        with st.chat_message(msg["role"], avatar=avatar):
            st.write(msg["content"])
            if msg.get("chart") is not None:
                c1, c2 = st.columns([6, 1])
                with c1:
                    st.plotly_chart(msg["chart"], use_container_width=True, key=f"chart_{i}", config=CHART_CONFIG)
                with c2:
                    if hasattr(st, "dialog") and st.button("⛶ Expand", key=f"expand_{i}"):
                        show_chart_modal(msg["chart"])
            if msg.get("table") is not None:
                st.download_button(
                    "⬇️ Download results (CSV)",
                    msg["table"].to_csv(index=False).encode("utf-8"),
                    file_name="farmagent_results.csv",
                    mime="text/csv",
                    key=f"download_{i}",
                )

    question = st.chat_input("Ask a question about the data...")
    if not question and "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if question:
        st.chat_message("user", avatar="🧑").write(question)
        st.session_state.messages.append({"role": "user", "content": question, "chart": None, "table": None})

        key = cache_key(question, st.session_state.data)
        cached = st.session_state.cache.get(key)
        start = time.time()

        with st.chat_message("assistant", avatar="💊"):
            if cached:
                st.write(cached["answer"])
                answer_text = cached["answer"]
                sql, chart, table = cached["sql"], cached["chart"], cached["table"]
                st.caption("⚡ Cached response")
            else:
                with st.status("Analyzing...", expanded=False) as status:
                    result_str, sql, chart, table = run_agent(
                        question, st.session_state.history, st.session_state.data, status
                    )
                    status.update(label="Done", state="complete")

                if table is None and isinstance(result_str, str) and chart is None:
                    # Query failed even after auto-fix
                    st.write(result_str)
                    answer_text = result_str
                else:
                    context = "".join(
                        [f"User: {t['question']}\nAnswer: {t['answer']}\n\n" for t in st.session_state.history]
                    )
                    answer_text = st.write_stream(stream_answer(question, context, result_str))

            if chart:
                c1, c2 = st.columns([6, 1])
                with c1:
                    st.plotly_chart(chart, use_container_width=True, key=f"chart_new_{len(st.session_state.messages)}", config=CHART_CONFIG)
                with c2:
                    if hasattr(st, "dialog") and st.button("⛶ Expand", key=f"expand_new_{len(st.session_state.messages)}"):
                        show_chart_modal(chart)
            if table is not None and not isinstance(table, str):
                st.download_button(
                    "⬇️ Download results (CSV)",
                    table.to_csv(index=False).encode("utf-8"),
                    file_name="farmagent_results.csv",
                    mime="text/csv",
                    key=f"download_new_{len(st.session_state.messages)}",
                )
            with st.expander("Generated SQL"):
                st.code(sql, language="sql")
            duration = time.time() - start
            st.caption(f"⏱️ Answered in {duration:.1f}s")

        st.session_state.messages.append({
            "role": "assistant", "content": answer_text, "chart": chart,
            "table": table if not isinstance(table, str) else None
        })
        st.session_state.history.append({"question": question, "answer": answer_text})

        if not cached:
            st.session_state.cache[key] = {"answer": answer_text, "sql": sql, "chart": chart, "table": table}