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
if 'admin_unlocked' not in st.session_state: st.session_state['admin_unlocked'] = False

def verificar_senha():
    if st.session_state.get('senha_input') == SENHA_ADMIN:
        st.session_state['admin_unlocked'] = True
    else:
        st.toast("⛔ Senha incorreta!", icon="❌")

# --- 4. CONEXÃO GOOGLE SHEETS ---
@st.cache_resource(ttl=0)
def conectar_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        return client.open(NOME_PLANILHA_GOOGLE).sheet1
    except: return None

def resetar_banco_dados():
    sheet = conectar_gsheets()
    if sheet:
        sheet.clear()
        sheet.append_row(COLUNAS_ESPERADAS)
        return True
    return False

def carregar_dados():
    sheet = conectar_gsheets()
    if not sheet: return pd.DataFrame(columns=COLUNAS_ESPERADAS), "Erro Conexão"
    try:
        data = sheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=COLUNAS_ESPERADAS), "Vazio"
        
        df = pd.DataFrame(data)
        df.columns = [str(c).strip() for c in df.columns]

        if "Time" in df.columns: df = df[df["Time"].astype(str) != "Time"]
        if "Valor" in df.columns: df = df[df["Valor"].astype(str) != "Valor"]

        for col in COLUNAS_ESPERADAS:
            if col not in df.columns: df[col] = None
            
        if "Valor" in df.columns:
            df["Valor"] = pd.to_numeric(
                df["Valor"].astype(str).str.replace("R$", "", regex=False).str.replace(",", ".", regex=False),
                errors='coerce'
            ).fillna(0.0)
        
        if "Rodada" in df.columns:
            df["Rodada"] = pd.to_numeric(df["Rodada"], errors='coerce').fillna(0).astype(int)
            
        if "Pago" in df.columns:
            df["Pago"] = df["Pago"].astype(str).str.upper().apply(lambda x: True if x in ["TRUE", "VERDADEIRO", "SIM", "1"] else False)

        return df, "Sucesso"
    except Exception as e:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS), f"Erro Leitura: {e}"

def salvar_dados(df):
    sheet = conectar_gsheets()
    if sheet:
        df_save = df.reindex(columns=COLUNAS_ESPERADAS).copy()
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x is True else "FALSE")
        df_save["Data"] = df_save["Data"].astype(str).replace("nan", "")
        df_save["Valor"] = df_save["Valor"].fillna(0.0)
        df_save["Rodada"] = df_save["Rodada"].fillna(0).astype(int)
        df_save = df_save.fillna("")
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())

# --- 5. LÓGICA DE CÁLCULO ---
def buscar_api(slug):
    try:
        resp = requests.get(f"https://api.cartola.globo.com/ligas/{slug}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            return pd.DataFrame([{"Time": t['nome'], "Pontos": t['pontos']['rodada'] or 0.0} for t in resp.json()['times']])
    except: pass
    return None

def calcular(df_ranking, df_hist, rod):
    if df_ranking.empty: return [], [], [], 0, 0
    qtd = math.ceil(len(df_ranking) * PCT_PAGANTES)
    rank = df_ranking.sort_values("Pontos").reset_index(drop=True)
    
    conta = pd.Series(dtype=int)
    if not df_hist.empty and "Rodada" in df_hist.columns and "Valor" in df_hist.columns:
        validos = df_hist[(df_hist["Rodada"] != rod) & (df_hist["Valor"] > 0)]
        if not validos.empty: conta = validos["Time"].value_counts()
    
    devs, imune, salvos = [], [], []
    for _, r in rank.iterrows():
        t, p = r['Time'], r['Pontos']
        if len(devs) < qtd:
            if conta.get(t, 0) < LIMITE_MAX_PAGAMENTOS:
                devs.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rod, "Time": t, "Valor": VALOR_RODADA, "Pago": False, "Motivo": "Lanterna", "Pontos": p})
            else:
                imune.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rod, "Time": t, "Valor": 0.0, "Pago": True, "Motivo": "Imune (>10)", "Pontos": p})
        else:
            salvos.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rod, "Time": t, "Valor": 0.0, "Pago": True, "Motivo": "Salvo", "Pontos": p})
    return devs, imune, salvos, len(df_ranking), qtd

# --- 6. INTERFACE ---
st.title("⚽ Os Piá do Cartola")

with st.container():
    st.markdown('<div class="admin-floating-container">', unsafe_allow_html=True)
    if not st.session_state['admin_unlocked']:
        with st.popover("🔒 Login Admin", use_container_width=True):
            st.text_input("Senha:", type="password", key="senha_input", on_change=verificar_senha)
        st.markdown('<span class="status-badge" style="color:#999;">Visitante</span>', unsafe_allow_html=True)
    else:
        if st.button("🔓 Sair"): st.session_state['admin_unlocked'] = False; st.rerun()
        st.markdown('<span class="status-badge" style="color:#28a745;">Admin Ativo</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

df_fin, status_msg = carregar_dados()

tab_resumo, tab_pendencias, tab_admin = st.tabs(["📋 Resumo", "💰 Pendências", "⚙️ Painel Admin"])

# --- ABA 1: RESUMO ---
with tab_resumo:
    valid_db = not df_fin.empty and "Time" in df_fin.columns and "Valor" in df_fin.columns
    if valid_db:
        try:
            df_v = df_fin.copy()
            df_v["V"] = df_v.apply(lambda x: None if x["Valor"] == 0 else x["Pago"], axis=1)
            df_v["Rodada_Str"] = df_v["Rodada"].astype(int).astype(str)
            matrix = df_v.pivot_table(index="Time", columns="Rodada_Str", values="V", aggfunc="last")
            todas_rodadas = [str(i) for i in range(1, TOTAL_RODADAS_TURNO + 1)]
            matrix = matrix.reindex(columns=todas_rodadas)
            matrix = matrix.astype(object)
            matrix = matrix.where(pd.notnull(matrix), None)

            cobrancas = df_fin[df_fin["Valor"] > 0]["Time"].value_counts().rename("Cobranças")
            disp = pd.DataFrame(index=df_fin["Time"].unique()).join(cobrancas).fillna(0).astype(int)
            disp = disp.join(matrix)
            disp.insert(0, "Status", disp["Cobranças"].apply(lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"))
            disp.index.name = "Time"
            disp = disp.reset_index().sort_values("Time")
            
            cfg = {
                "Time": st.column_config.TextColumn(disabled=True),
                "Status": st.column_config.TextColumn(width="small", disabled=True),
                "Cobranças": st.column_config.NumberColumn(width="small", disabled=True)
            }
            for c in todas_rodadas:
                cfg[c] = st.column_config.CheckboxColumn(f"{c}", width="small", disabled=not st.session_state['admin_unlocked'])
            
            edit = st.data_editor(disp, column_config=cfg, height=600, use_container_width=True, hide_index=True)
            
            if st.session_state['admin_unlocked']:
                m = edit.melt(id_vars=["Time"], value_vars=todas_rodadas, var_name="Rodada", value_name="Nv").dropna(subset=["Nv"])
                if not m.empty:
                    change = False
                    for _, r in m.iterrows():
                        mask = (df_fin["Time"]==r["Time"]) & (df_fin["Rodada"]==int(r["Rodada"])) & (df_fin["Valor"]>0)
                        if mask.any():
                            idx = df_fin[mask].index[0]
                            if bool(df_fin.at[idx, "Pago"]) != bool(r["Nv"]):
                                df_fin.at[idx, "Pago"] = bool(r["Nv"]); change = True
                    if change: salvar_dados(df_fin); st.toast("✅ Atualizado!", icon="☁️"); time.sleep(1); st.rerun()
        except Exception as e: st.error(f"Erro Visualização Resumo: {e}")
    else: st.info("Banco de dados vazio. Aguardando lançamentos do Admin.")

# --- ABA 2: PENDÊNCIAS (ATUALIZADO) ---
with tab_pendencias:
    if valid_db:
        try:
            pg = df_fin[(df_fin["Pago"] == True) & (df_fin["Valor"] > 0)]["Valor"].sum()
            ab = df_fin[(df_fin["Pago"] == False) & (df_fin["Valor"] > 0)]["Valor"].sum()
            max_rod = int(df_fin["Rodada"].max()) if not df_fin["Rodada"].empty else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Pago", f"R$ {pg:.2f}")
            c2.metric("Aberto", f"R$ {ab:.2f}")
            c3.metric("Última Rodada", max_rod)
            
            st.divider()
            
            df_devs = df_fin[(df_fin["Valor"] > 0) & (df_fin["Pago"] == False)].copy()
            
            if not df_devs.empty:
                tabela_dev = df_devs.groupby("Time")["Valor"].sum().reset_index(name="Devendo")
                # Ordena e reseta o index
                tabela_dev = tabela_dev.sort_values("Devendo", ascending=False).reset_index(drop=True)
                # Ajusta para começar em 1
                tabela_dev.index = tabela_dev.index + 1
                
                # Layout compacto (1/3 tabela, 2/3 vazio)
                col_tab, col_vazio = st.columns([1, 2])
                with col_tab:
                    try:
                        st.dataframe(tabela_dev.style.format({"Devendo": "R$ {:.2f}"}).background_gradient(cmap="Reds"))
                    except:
                        st.dataframe(tabela_dev.style.format({"Devendo": "R$ {:.2f}"}))
            else:
                st.success("Tudo pago! Ninguém devendo.")
        except Exception as e:
            st.error(f"Erro Pendências: {e}")
    else: st.info("Sem dados.")

# --- ABA 3: ADMIN ---
with tab_admin:
    if not st.session_state['admin_unlocked']: 
        st.warning("🔒 Faça login no canto superior direito.")
        st.stop()
    
    with st.expander("🚨 Zona de Perigo"):
        if st.button("⚠️ RESETAR BANCO DE DADOS", type="primary"):
            if resetar_banco_dados(): st.success("Resetado!"); time.sleep(2); st.rerun()

    st.subheader("Lançar Rodada")
    c1, c2 = st.columns([2, 1])
    origem = c1.radio("Fonte:", ["Excel", "API"], horizontal=True)
    rod = c2.number_input("Rodada", 1, TOTAL_RODADAS_TURNO, 1)
    
    if 'temp' not in st.session_state: st.session_state['temp'] = pd.DataFrame(columns=["Time", "Pontos"])
    
    if origem == "API":
        slug = st.text_input("Slug", SLUG_LIGA_PADRAO)
        if st.button("Buscar API"):
            r = buscar_api(slug)
            if r is not None: st.session_state['temp'] = r; st.rerun()
            else: st.error("Erro API")
    else:
        f = st.file_uploader("Excel", ["xlsx"])
        if f:
            try:
                x = pd.read_excel(f)
                x.columns = [str(c).strip().title() for c in x.columns]
                mapa = {"Pontuação": "Pontos", "Pts": "Pontos", "Nome": "Time", "Participante": "Time", "Equipe": "Time", "Cartoleiro": "Time"}
                x = x.rename(columns=mapa)
                if "Time" in x.columns:
                    col_p = "Pontos" if "Pontos" in x.columns else None
                    cols = ["Time", "Pontos"] if col_p else ["Time"]
                    st.session_state['temp'] = x[cols]
                    if not col_p: st.session_state['temp']["Pontos"] = 0.0
                    st.session_state['temp'] = st.session_state['temp'].fillna(0)
                else: st.error(f"Não achei coluna Time. Tem: {list(x.columns)}")
            except Exception as e: st.error(f"Erro Excel: {e}")
            
    st.session_state['temp'] = st.data_editor(st.session_state['temp'], num_rows="dynamic", use_container_width=True)
    
    if not st.session_state['temp'].empty and "Time" in st.session_state['temp'].columns:
        if "Pontos" not in st.session_state['temp'].columns: st.session_state['temp']["Pontos"] = 0.0
        
        try:
            d, i, s, t, p = calcular(st.session_state['temp'], df_fin, rod)
            st.info(f"Simulação: {p} pagantes de {t} times.")
            
            if st.button("💾 Salvar Rodada"):
                if not df_fin.empty and "Rodada" in df_fin.columns:
                     df_limpo = df_fin[df_fin["Rodada"] != rod]
                else:
                     df_limpo = pd.DataFrame(columns=COLUNAS_ESPERADAS)
                     
                new = pd.concat([df_limpo, pd.DataFrame(d+i+s)], ignore_index=True)
                salvar_dados(new)
                st.toast("✅ Salvo!", icon="☁️")
                time.sleep(2)
                st.rerun()
        except Exception as e:
            st.error(f"Erro cálculo: {e}")