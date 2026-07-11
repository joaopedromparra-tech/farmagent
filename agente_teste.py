import sqlite3
import pandas as pd
import os
from groq import Groq

# --- 1. Configurar Groq ---
client = Groq(api_key=os.environ["GROQ_API_KEY"])

# --- 2. Carregar Excel para SQLite ---
def carregar_excel(ficheiro_excel):
    conn = sqlite3.connect(":memory:")
    sheets = pd.read_excel(ficheiro_excel, sheet_name=None)
    
    for nome_sheet, df in sheets.items():
        if nome_sheet == "Resumo":
            continue
        df.to_sql(nome_sheet, conn, index=False, if_exists="replace")
        print(f"✓ Tabela '{nome_sheet}' carregada — {len(df)} registos")
    
    return conn

# --- 3. Obter schema de todas as tabelas ---
def get_schema(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    tabelas = cursor.fetchall()
    return "\n\n".join([t[0] for t in tabelas if t[0]])

# --- 4. Executar SQL ---
def run_query(conn, sql):
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        resultado = cursor.fetchall()
        if not resultado:
            return "Nenhum resultado encontrado."
        return resultado
    except Exception as e:
        return f"Erro SQL: {e}"

# --- 5. O agente ---
def agente(pergunta, historico, conn):
    schema = get_schema(conn)

    contexto = ""
    for turno in historico:
        contexto += f"Utilizador: {turno['pergunta']}\n"
        contexto += f"Resposta: {turno['resposta']}\n\n"

    prompt_sql = f"""Tens acesso a uma base de dados SQLite com estas tabelas:

{schema}

Histórico da conversa:
{contexto}

Nova pergunta: {pergunta}

Responde APENAS com a query SQL, sem explicações, sem markdown, sem backticks."""

    sql_gerado = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt_sql}]
    ).choices[0].message.content.strip()

    print(f"\nSQL gerado: {sql_gerado}")
    resultado = run_query(conn, sql_gerado)
    print(f"Resultado bruto: {resultado}")

    prompt_resposta = f"""Histórico da conversa:
{contexto}

A pergunta foi: {pergunta}
O resultado SQL foi: {resultado}
Responde de forma clara e concisa em português."""

    resposta_final = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt_resposta}]
    ).choices[0].message.content.strip()

    return resposta_final


# --- 6. Main ---
print("A carregar Excel...\n")
conn = carregar_excel("farmacia_complexa.xlsx")

historico = []
print("\nAgente SQL pronto! Escreve 'sair' para terminar.\n")

while True:
    pergunta = input("A tua pergunta: ")
    if pergunta.lower() == "sair":
        break

    resposta = agente(pergunta, historico, conn)
    print(f"\nResposta: {resposta}\n")

    historico.append({
        "pergunta": pergunta,
        "resposta": resposta
    })
