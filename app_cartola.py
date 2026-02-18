import streamlit as st
import pandas as pd
import requests
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- 1. CONFIGURAÇÕES ---
VALOR_RODADA = 7.00
LIMITE_MAX_PAGAMENTOS = 10
PCT_PAGANTES = 0.25
SLUG_LIGA_PADRAO = "os-pia-do-cartola"
SENHA_ADMIN = "c@rtol@2026"
NOME_PLANILHA_GOOGLE = "Controle_Cartola_2026"
TOTAL_RODADAS_TURNO = 19

COLUNAS_ESPERADAS = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]

# --- 2. SETUP VISUAL ---
st.set_page_config(page_title="Gestão Cartola PRO", layout="wide", page_icon="⚽")

def configurar_css():
    st.markdown("""
        <style>
            .block-container { padding-top: 3.5rem !important; }
            .admin-floating-container {
                position: fixed; top: 60px; right: 25px; z-index: 9999;
                background-color: white; padding: 8px 12px;
                border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                border: 1px solid #e0e0e0; text-align: right;
            }
            .status-badge {
                font-size: 0.7rem; font-weight: bold; text-transform: uppercase;
                letter-spacing: 1px; display: block; margin-top: 4px;
            }
        </style>
    """, unsafe_allow_html=True)

configurar_css()

# --- 3. AUTENTICAÇÃO ---
if 'admin_unlocked' not in st.session_state:
    st.session_state['admin_unlocked'] = False

def verificar_senha():
    if st.session_state.get('senha_input') == SENHA_ADMIN:
        st.session_state['admin_unlocked'] = True
    else:
        st.toast("⛔ Senha incorreta!", icon="❌")

# --- 4. GOOGLE SHEETS ---
@st.cache_resource(ttl=0)
def conectar_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(
                dict(st.secrets["gcp_service_account"]), scope
            )
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                "credentials.json", scope
            )
        client = gspread.authorize(creds)
        return client.open(NOME_PLANILHA_GOOGLE).sheet1
    except:
        return None

def resetar_banco_dados():
    sheet = conectar_gsheets()
    if sheet:
        sheet.clear()
        sheet.append_row(COLUNAS_ESPERADAS)
        return True
    return False

def carregar_dados():
    sheet = conectar_gsheets()
    if not sheet:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS), "Erro Conexão"

    try:
        data = sheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=COLUNAS_ESPERADAS), "Vazio"

        df = pd.DataFrame(data)
        df.columns = [str(c).strip() for c in df.columns]

        for col in COLUNAS_ESPERADAS:
            if col not in df.columns:
                df[col] = None

        df["Valor"] = pd.to_numeric(
            df["Valor"].astype(str)
            .str.replace("R$", "", regex=False)
            .str.replace(",", ".", regex=False),
            errors="coerce"
        ).fillna(0.0)

        df["Rodada"] = pd.to_numeric(df["Rodada"], errors="coerce").fillna(0).astype(int)

        df["Pago"] = (
            df["Pago"]
            .astype(str)
            .str.upper()
            .apply(lambda x: True if x in ["TRUE", "VERDADEIRO", "SIM", "1"] else False)
        )

        return df, "Sucesso"

    except Exception as e:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS), f"Erro: {e}"

def salvar_dados(df):
    sheet = conectar_gsheets()
    if sheet:
        df_save = df.reindex(columns=COLUNAS_ESPERADAS).copy()
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x else "FALSE")
        df_save["Data"] = df_save["Data"].astype(str).replace("nan", "")
        df_save["Valor"] = df_save["Valor"].fillna(0.0)
        df_save["Rodada"] = df_save["Rodada"].fillna(0).astype(int)
        df_save = df_save.fillna("")
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())

# --- 5. API AUTENTICADA (NOVA VERSÃO) ---
def buscar_api(slug):
    try:
        token = st.secrets["cartola"]["token"].strip()

        url = f"https://api.cartola.globo.com/auth/liga/{slug}"

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            dados = response.json()

            if "times" not in dados:
                return None

            df_bruto = pd.DataFrame(dados["times"])

            df_export = pd.DataFrame()
            df_export["Time"] = df_bruto["nome_cartola"]
            df_export["Pontos"] = df_bruto["ranking"].apply(
                lambda x: x.get("rodada") if isinstance(x, dict) else 0.0
            )

            return df_export

        else:
            st.error(f"Erro API: {response.status_code}")
            return None

    except Exception as e:
        st.error(f"Erro autenticação API: {e}")
        return None

# --- 6. CÁLCULO ---
def calcular(df_ranking, df_hist, rod):
    if df_ranking.empty:
        return [], [], [], 0, 0

    qtd = math.ceil(len(df_ranking) * PCT_PAGANTES)
    rank = df_ranking.sort_values("Pontos").reset_index(drop=True)

    conta = pd.Series(dtype=int)
    if not df_hist.empty:
        validos = df_hist[(df_hist["Rodada"] != rod) & (df_hist["Valor"] > 0)]
        if not validos.empty:
            conta = validos["Time"].value_counts()

    devs, imune, salvos = [], [], []

    for _, r in rank.iterrows():
        t, p = r["Time"], r["Pontos"]

        if len(devs) < qtd:
            if conta.get(t, 0) < LIMITE_MAX_PAGAMENTOS:
                devs.append({
                    "Data": datetime.now().strftime("%Y-%m-%d"),
                    "Rodada": rod,
                    "Time": t,
                    "Valor": VALOR_RODADA,
                    "Pago": False,
                    "Motivo": "Lanterna",
                    "Pontos": p
                })
            else:
                imune.append({
                    "Data": datetime.now().strftime("%Y-%m-%d"),
                    "Rodada": rod,
                    "Time": t,
                    "Valor": 0.0,
                    "Pago": True,
                    "Motivo": "Imune (>10)",
                    "Pontos": p
                })
        else:
            salvos.append({
                "Data": datetime.now().strftime("%Y-%m-%d"),
                "Rodada": rod,
                "Time": t,
                "Valor": 0.0,
                "Pago": True,
                "Motivo": "Salvo",
                "Pontos": p
            })

    return devs, imune, salvos, len(df_ranking), qtd
