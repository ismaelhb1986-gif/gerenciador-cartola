import streamlit as st
import pandas as pd
import requests
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import random

# --- CONFIGURAÇÕES ---
VALOR_RODADA = 7.00
LIMITE_MAX_PAGAMENTOS = 10
PCT_PAGANTES = 0.25
SLUG_LIGA_PADRAO = "os-pia-do-cartola"
SENHA_ADMIN = "c@rtol@2026"
NOME_PLANILHA_GOOGLE = "Controle_Cartola_2026" 

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="Gestão Cartola", layout="wide")

def configurar_estilo():
    st.markdown("""
        <style>
            /* Ajuste do container principal para evitar cortes */
            .block-container { 
                padding-top: 2rem !important; 
                padding-bottom: 2rem; 
            }
            
            /* Ajuste específico para o Popover (Botão Admin) */
            div[data-testid="stPopover"] {
                width: 100%;
                min-width: 150px;
            }
            
            /* Estilo do status do usuário */
            .user-status {
                font-size: 0.85rem;
                color: #555;
                text-align: right;
                margin-top: 5px;
                font-family: sans-serif;
            }

            /* Forçar botões a ocuparem largura total na barra lateral/topo */
            .stButton button { width: 100%; }

            /* Animação do Disquete (FIXO NO CANTO) */
            @keyframes fade_in_right {
                0% { opacity: 0; transform: translateX(20px); }
                20% { opacity: 1; transform: translateX(0); }
                80% { opacity: 1; transform: translateX(0); }
                100% { opacity: 0; transform: translateX(20px); }
            }
            .icon-save {
                position: fixed;
                top: 80px;
                right: 30px;
                font-size: 3.5rem;
                z-index: 999999;
                pointer-events: none;
                animation: fade_in_right 2.5s ease-in-out forwards;
            }
        </style>
    """, unsafe_allow_html=True)

configurar_estilo()

# --- FUNÇÃO VISUAL: DISQUETE ---
def mostrar_disquete():
    st.markdown('<div class="icon-save">💾</div>', unsafe_allow_html=True)

# --- AUTENTICAÇÃO E SESSÃO ---
if 'admin_unlocked' not in st.session_state:
    st.session_state['admin_unlocked'] = False

def verificar_senha():
    if st.session_state.get('input_senha') == SENHA_ADMIN:
        st.session_state['admin_unlocked'] = True
        st.session_state['erro_senha'] = False
    else:
        st.session_state['erro_senha'] = True

def logout():
    st.session_state['admin_unlocked'] = False

# --- GOOGLE SHEETS CONEXÃO ---
@st.cache_resource
def conectar_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    except:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        except:
            return None
    client = gspread.authorize(creds)
    try:
        return client.open(NOME_PLANILHA_GOOGLE).sheet1
    except:
        return None

def carregar_dados():
    sheet = conectar_gsheets()
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            if "Pago" in df.columns:
                df["Pago"] = df["Pago"].apply(lambda x: str(x).upper() == "TRUE")
            if "Valor" in df.columns:
                df["Valor"] = pd.to_numeric(df["Valor"]).fillna(0.0)
            return df
    return pd.DataFrame(columns=["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"])

def salvar_dados(df):
    sheet = conectar_gsheets()
    if sheet:
        colunas = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]
        for col in colunas:
            if col not in df.columns: df[col] = ""
        df_save = df[colunas].copy()
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x else "FALSE")
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())

# --- LÓGICA DO CARTOLA ---
def buscar_api(slug):
    url = f"https://api.cartola.globo.com/ligas/{slug}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return pd.DataFrame([{"Time": t['nome'], "Pontos": t['pontos']['rodada'] or 0.0} for t in data['times']])
    except: return None

def calcular_logica(df_ranking, df_hist, rodada):
    total_participantes = len(df_ranking)
    if total_participantes == 0: return [], [], [], 0, 0
    qtd_pagantes = math.ceil(total_participantes * PCT_PAGANTES)
    ranking = df_ranking.sort_values(by="Pontos", ascending=True).reset_index(drop=True)
    hist_passado = df_hist[df_hist["Rodada"] != rodada]
    contagem = hist_passado[hist_passado["Valor"] > 0]["Time"].value_counts()
    devedores, imunes, salvos = [], [], []
    for i, row in ranking.iterrows():
        time, pontos = row['Time'], row['Pontos']
        if len(devedores) < qtd_pagantes:
            if contagem.get(time, 0) < LIMITE_MAX_PAGAMENTOS:
                devedores.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rodada, "Time": time, "Valor": VALOR_RODADA, "Pago": False, "Motivo": "Lanterna", "Pontos": pontos})
            else:
                imunes.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rodada, "Time": time, "Valor": 0.0, "Pago": True, "Motivo": "Imune (>10)", "Pontos": pontos})
        else:
            salvos.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rodada, "Time": time, "Valor": 0.0, "Pago": True, "Motivo": "Salvo", "Pontos": pontos})
    return devedores, imunes, salvos, total_participantes, qtd_pagantes

# --- TOPO DA PÁGINA ---
col_t1, col_t2 = st.columns([3, 1])
with col_t1:
    st.title("⚽ Os Piá do Cartola")
with col_t2:
    if not st.session_state['admin_unlocked']:
        # Popover corrigido para não cortar
        with st.popover("🔒 Acessar Admin", use_container_width=True):
            st.text_input("Senha:", type="password", key="input_senha", on_change=verificar_senha)
            if st.session_state.get('erro_senha'):
                st.error("Incorreta")
        st.markdown("<div class='user-status'>Modo: <b>Cartoleiro</b></div>", unsafe_allow_html=True)
    else:
        if st.button("Sair do Admin"):
            logout()
            st.rerun()
        st.markdown("<div class='user-status' style='color:green;'>Modo: <b>ADMIN</b></div>", unsafe_allow_html=True)

# --- DADOS ---
with st.spinner("Sincronizando..."):
    df_fin = carregar_dados()

tab_resumo, tab_pendencias, tab_admin = st.tabs(["📋 Resumo Geral", "💰 Pendências", "⚙️ Admin"])

# --- ABA 1: RESUMO ---
with tab_resumo:
    if not df_fin.empty:
        todos_times = df_fin["Time"].unique()
        df_view = df_fin.copy()
        df_view["PV"] = df_view.apply(lambda x: None if x["Valor"] == 0 else x["Pago"], axis=1)
        matrix = df_view.pivot_table(index="Time", columns="Rodada", values="PV", aggfunc="last")
        contagem = df_fin[df_fin["Valor"] > 0]["Time"].value_counts().rename("Vezes")
        df_display = pd.DataFrame(index=todos_times).join(contagem).fillna(0).astype(int).join(matrix)
        df_display.insert(0, "Status", df_display["Vezes"].apply(lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"))
        for i in range(1, 20):
            if i not in df_display.columns: df_display[i] = None
        df_display.index.name = "Time"
        df_display = df_display.reset_index().sort_values("Time")
        cfg = {"Time": st.column_config.TextColumn("Time", width="medium", disabled=True),
               "Status": st.column_config.TextColumn("Status", width="small", disabled=True),
               "Vezes": st.column_config.NumberColumn("#", width="small", disabled=True)}
        for i in range(1, 20):
            cfg[str(i)] = st.column_config.CheckboxColumn(f"{i}", width="small", disabled=not st.session_state['admin_unlocked'])
        df_editado = st.data_editor(df_display, column_config=cfg, height=500, use_container_width=True, hide_index=True)
        if st.session_state['admin_unlocked']:
            cols_r = [c for c in df_editado.columns if str(c).isdigit()]
            df_m = df_editado.melt(id_vars=["Time"], value_vars=cols_r, var_name="Rodada", value_name="NS").dropna(subset=["NS"])
            if not df_m.empty:
                mudou = False
                for _, row in df_m.iterrows():
                    m = (df_fin["Time"] == row["Time"]) & (df_fin["Rodada"] == int(row["Rodada"])) & (df_fin["Valor"] > 0)
                    if m.any():
                        idx = df_fin[m].index[0]
                        if bool(df_fin.at[idx, "Pago"]) != bool(row["NS"]):
                            df_fin.at[idx, "Pago"] = bool(row["NS"]); mudou = True
                if mudou:
                    salvar_dados(df_fin); mostrar_disquete(); time.sleep(1); st.rerun()
    else: st.info("Sem dados.")

# --- ABA 2: PENDÊNCIAS ---
with tab_pendencias:
    if not df_fin.empty:
        p, a = df_fin[df_fin["Pago"]==True]["Valor"].sum(), df_fin[df_fin["Pago"]==False]["Valor"].sum()
        k1, k2, k3 = st.columns(3)
        k1.metric("Arrecadado", f"R$ {p:.2f}"); k2.metric("Em Aberto", f"R$ {a:.2f}", delta=-a); k3.metric("Rodadas", df_fin["Rodada"].max() if not df_fin.empty else 0)
        st.divider()
        res = df_fin[df_fin["Valor"] > 0].groupby("Time").agg(Dívidas=("Pago", lambda x: (~x).sum()), Total=("Valor", lambda x: x[~df_fin.loc[x.index, "Pago"]].sum()))
        devs = res[res["Total"] > 0].sort_values("Total", ascending=False)
        if not devs.empty: st.dataframe(devs.style.format({"Total": "R$ {:.2f}"}).background_gradient(cmap="Reds"), use_container_width=True)
        else: st.success("Tudo em dia!")

# --- ABA 3: ADMIN ---
with tab_admin:
    if not st.session_state['admin_unlocked']:
        st.warning("Área restrita ao Administrador."); st.stop()
    c1, c2 = st.columns([2, 1])
    modo = c1.radio("Fonte:", ["Excel / Manual", "API Cartola"], horizontal=True)
    rod = c2.number_input("Rodada", 1, 38, 1)
    if 'dados_live' not in st.session_state: st.session_state['dados_live'] = pd.DataFrame([{"Time": "Exemplo", "Pontos": 0.0}])
    if modo == "API Cartola":
        slug = st.text_input("Slug", SLUG_LIGA_PADRAO)
        if st.button("Buscar API"):
            res = buscar_api(slug)
            if res is not None: st.session_state['dados_live'] = res; st.rerun()
    else:
        f = st.file_uploader("Excel", ["xlsx"])
        if f:
            try:
                x = pd.read_excel(f); x.columns = [c.capitalize().strip() for c in x.columns]
                st.session_state['dados_live'] = x
            except: pass
        st.session_state['dados_live'] = st.data_editor(st.session_state['dados_live'], num_rows="dynamic", use_container_width=True, height=200)
    if not st.session_state['dados_live'].empty:
        st.divider()
        d, i, s, t, p = calcular_logica(st.session_state['dados_live'], df_fin, rod)
        st.write(f"Rodada {rod}: {p} pagantes identificados.")
        if st.button("✅ Confirmar Lançamento"):
            df_l = df_fin[df_fin["Rodada"] != rod]
            df_final = pd.concat([df_l, pd.DataFrame(d + i + s)], ignore_index=True)
            salvar_dados(df_final); mostrar_disquete(); st.success("Salvo!"); time.sleep(1.5); st.rerun()