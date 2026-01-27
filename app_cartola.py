import streamlit as st
import pandas as pd
import requests
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

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
            /* Aumenta o espaço no topo para não cortar o botão */
            .block-container { 
                padding-top: 3.5rem !important; 
            }
            
            /* Status do usuário discreto */
            .user-status {
                font-size: 0.75rem;
                color: #888;
                text-align: right;
                margin-bottom: 5px;
            }

            /* Estilo do Disquete Fixo */
            @keyframes fade_save {
                0% { opacity: 0; transform: translateY(-20px); }
                20% { opacity: 1; transform: translateY(0); }
                80% { opacity: 1; transform: translateY(0); }
                100% { opacity: 0; transform: translateY(-20px); }
            }
            .icon-save {
                position: fixed;
                top: 20px;
                right: 20px;
                font-size: 3rem;
                z-index: 1000000;
                animation: fade_save 2.5s forwards;
            }
        </style>
    """, unsafe_allow_html=True)

configurar_estilo()

def mostrar_disquete():
    st.markdown('<div class="icon-save">💾</div>', unsafe_allow_html=True)

# --- SISTEMA DE SENHA ---
if 'admin_unlocked' not in st.session_state:
    st.session_state['admin_unlocked'] = False

def verificar_senha():
    if st.session_state.get('input_senha') == SENHA_ADMIN:
        st.session_state['admin_unlocked'] = True
    else:
        st.error("Senha incorreta!")

# --- CONEXÃO GOOGLE SHEETS ---
@st.cache_resource
def conectar_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Tenta secrets do Streamlit Cloud primeiro
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
            return df
    return pd.DataFrame(columns=["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"])

def salvar_dados(df):
    sheet = conectar_gsheets()
    if sheet:
        colunas = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]
        df_save = df.reindex(columns=colunas).fillna("")
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x == True else "FALSE")
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())

# --- LÓGICA CORE ---
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
    
    # Busca histórico real para limite
    contagem = pd.Series(dtype=int)
    if not df_hist.empty:
        hist_passado = df_hist[(df_hist["Rodada"] != rodada) & (df_hist["Valor"] > 0)]
        contagem = hist_passado["Time"].value_counts()
        
    devedores, imunes, salvos = [], [], []
    for _, row in ranking.iterrows():
        time, pontos = row['Time'], row['Pontos']
        if len(devedores) < qtd_pagantes:
            if contagem.get(time, 0) < LIMITE_MAX_PAGAMENTOS:
                devedores.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rodada, "Time": time, "Valor": VALOR_RODADA, "Pago": False, "Motivo": "Lanterna", "Pontos": pontos})
            else:
                imunes.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rodada, "Time": time, "Valor": 0.0, "Pago": True, "Motivo": "Imune (>10)", "Pontos": pontos})
        else:
            salvos.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rodada, "Time": time, "Valor": 0.0, "Pago": True, "Motivo": "Salvo", "Pontos": pontos})
    return devedores, imunes, salvos, total_participantes, qtd_pagantes

# --- TOPO COMPACTO ---
col_tit, col_adm = st.columns([4, 1])
with col_tit:
    st.title("⚽ Os Piá do Cartola")
with col_adm:
    if not st.session_state['admin_unlocked']:
        # Botão pequeno no canto
        with st.popover("🔒 Admin"):
            st.text_input("Senha:", type="password", key="input_senha", on_change=verificar_senha)
        st.markdown("<div class='user-status'>Cartoleiro</div>", unsafe_allow_html=True)
    else:
        if st.button("🔓 Sair"):
            st.session_state['admin_unlocked'] = False
            st.rerun()
        st.markdown("<div class='user-status' style='color:green'><b>ADMIN</b></div>", unsafe_allow_html=True)

# --- CARREGA DADOS ---
df_fin = carregar_dados()

tab_resumo, tab_pendencias, tab_admin = st.tabs(["📋 Resumo Geral", "💰 Pendências", "⚙️ Painel Admin"])

# --- ABA 1: RESUMO ---
with tab_resumo:
    if not df_fin.empty and "Time" in df_fin.columns:
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
        
        cfg = {"Time": st.column_config.TextColumn("Time", disabled=True),
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
    else: st.info("Aguardando o primeiro lançamento da temporada.")

# --- ABA 2: PENDÊNCIAS ---
with tab_pendencias:
    if not df_fin.empty and "Valor" in df_fin.columns:
        p = df_fin[df_fin["Pago"]==True]["Valor"].sum()
        a = df_fin[df_fin["Pago"]==False]["Valor"].sum()
        k1, k2, k3 = st.columns(3)
        k1.metric("💰 Arrecadado", f"R$ {p:.2f}")
        k2.metric("🔴 Em Aberto", f"R$ {a:.2f}", delta=-a if a > 0 else None)
        k3.metric("Rodadas", int(df_fin["Rodada"].max()) if not df_fin.empty else 0)
        
        st.divider()
        res = df_fin[df_fin["Valor"] > 0].groupby("Time").agg(Total=("Valor", lambda x: x[~df_fin.loc[x.index, "Pago"]].sum()))
        devs = res[res["Total"] > 0].sort_values("Total", ascending=False)
        if not devs.empty: st.dataframe(devs.style.format({"Total": "R$ {:.2f}"}).background_gradient(cmap="Reds"), use_container_width=True)
        else: st.success("Tudo pago! 🍺")
    else: st.info("Sem pendências registradas.")

# --- ABA 3: ADMIN ---
with tab_admin:
    if not st.session_state['admin_unlocked']:
        st.warning("Acesso restrito. Use o botão no topo para entrar.")
        st.stop()
        
    c1, c2 = st.columns([2, 1])
    modo = c1.radio("Fonte:", ["Excel / Manual", "API Cartola"], horizontal=True)
    rod = c2.number_input("Rodada", 1, 38, 1)
    
    if 'dados_live' not in st.session_state: st.session_state['dados_live'] = pd.DataFrame(columns=["Time", "Pontos"])
    
    if modo == "API Cartola":
        slug = st.text_input("Slug da Liga", SLUG_LIGA_PADRAO)
        if st.button("Puxar API"):
            res = buscar_api(slug)
            if res is not None: st.session_state['dados_live'] = res; st.rerun()
    else:
        f = st.file_uploader("Subir planilha Excel", ["xlsx"])
        if f:
            try:
                x = pd.read_excel(f)
                # Limpa nomes de colunas
                x.columns = [str(c).strip().title() for c in x.columns]
                # Padroniza para encontrar as colunas certas
                x = x.rename(columns={"Pontuação": "Pontos", "Nome": "Time"})
                if "Time" in x.columns:
                    st.session_state['dados_live'] = x[["Time", "Pontos"]] if "Pontos" in x.columns else x
                    st.success("Planilha carregada!")
            except: st.error("Erro ao ler colunas. Use 'Time' e 'Pontos'.")
            
        st.session_state['dados_live'] = st.data_editor(st.session_state['dados_live'], num_rows="dynamic", use_container_width=True)

    if not st.session_state['dados_live'].empty:
        st.divider()
        d, i, s, t, p = calcular_logica(st.session_state['dados_live'], df_fin, rod)
        st.write(f"**Resultado:** {p} pagantes calculados de {t} times.")
        
        if st.button("🚀 Confirmar e Enviar para Nuvem"):
            df_l = df_fin[df_fin["Rodada"] != rod]
            df_final = pd.concat([df_l, pd.DataFrame(d + i + s)], ignore_index=True)
            salvar_dados(df_final); mostrar_disquete(); st.success("Dados enviados ao Google Sheets!"); time.sleep(1.5); st.rerun()