import streamlit as st
import pandas as pd
import requests
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- 1. CONFIGURAÇÕES GLOBAIS ---
VALOR_RODADA = 7.00
LIMITE_MAX_PAGAMENTOS = 10
PCT_PAGANTES = 0.25
SLUG_LIGA_PADRAO = "os-pia-do-cartola"
SENHA_ADMIN = "c@rtol@2026"
NOME_PLANILHA_GOOGLE = "Controle_Cartola_2026"

# Colunas OBRIGATÓRIAS (A ordem importa)
COLUNAS_ESPERADAS = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]

# --- 2. CONFIGURAÇÃO VISUAL (CSS) ---
st.set_page_config(page_title="Gestão Cartola PRO", layout="wide", page_icon="⚽")

def configurar_css():
    st.markdown("""
        <style>
            /* Ajuste do topo para não cortar */
            .block-container { padding-top: 3.5rem !important; }
            
            /* Botão Admin Flutuante (FIXO NO CANTO DIREITO) */
            .admin-floating-container {
                position: fixed;
                top: 60px;
                right: 25px;
                z-index: 9999;
                background-color: white;
                padding: 8px 12px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                border: 1px solid #e0e0e0;
                text-align: right;
            }
            
            /* Status Badge */
            .status-badge {
                font-size: 0.7rem;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                display: block;
                margin-top: 4px;
            }
            
            /* Ícone de Salvamento */
            @keyframes save_anim {
                0% { opacity: 0; transform: translateY(-20px) scale(0.8); }
                20% { opacity: 1; transform: translateY(0) scale(1.1); }
                80% { opacity: 1; transform: translateY(0) scale(1); }
                100% { opacity: 0; transform: translateY(-20px) scale(0.8); }
            }
            .save-icon-container {
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 100000;
                pointer-events: none;
                animation: save_anim 3s ease-in-out forwards;
                font-size: 3rem;
                filter: drop-shadow(0px 2px 5px rgba(0,0,0,0.3));
            }
        </style>
    """, unsafe_allow_html=True)

configurar_css()

def feedback_salvamento():
    st.markdown('<div class="save-icon-container">💾</div>', unsafe_allow_html=True)
    st.toast("✅ Banco de dados atualizado!", icon="☁️")

# --- 3. AUTENTICAÇÃO ---
if 'admin_unlocked' not in st.session_state:
    st.session_state['admin_unlocked'] = False

def verificar_senha():
    if st.session_state.get('senha_input') == SENHA_ADMIN:
        st.session_state['admin_unlocked'] = True
    else:
        st.toast("⛔ Senha incorreta!", icon="❌")

# --- 4. CONEXÃO GOOGLE SHEETS (AUTO-REPARO) ---
@st.cache_resource(ttl=30)
def conectar_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
        client = gspread.authorize(creds)
        sheet = client.open(NOME_PLANILHA_GOOGLE).sheet1
        return sheet
    except Exception as e:
        return None

def resetar_banco_dados():
    """Apaga tudo e cria os cabeçalhos corretos."""
    sheet = conectar_gsheets()
    if sheet:
        sheet.clear()
        sheet.append_row(COLUNAS_ESPERADAS)
        return True
    return False

def carregar_dados():
    sheet = conectar_gsheets()
    if not sheet: return pd.DataFrame(columns=COLUNAS_ESPERADAS), "Erro de Conexão"
    
    try:
        data = sheet.get_all_records()
        
        # CENÁRIO 1: PLANILHA VAZIA (CRIA CABEÇALHO SOZINHO)
        if not data:
            sheet.append_row(COLUNAS_ESPERADAS)
            return pd.DataFrame(columns=COLUNAS_ESPERADAS), "Planilha Reconstruída (Vazia)"
        
        # CENÁRIO 2: TEM DADOS
        df = pd.DataFrame(data)
        
        # Normalização de nomes de coluna (retira espaços)
        df.columns = [c.strip() for c in df.columns]
        
        # Garante que todas as colunas existem
        for col in COLUNAS_ESPERADAS:
            if col not in df.columns: df[col] = None
            
        # Tratamento de Tipos
        if "Valor" in df.columns:
            df["Valor"] = df["Valor"].astype(str).str.replace("R$", "", regex=False).str.replace(",", ".", regex=False)
            df["Valor"] = pd.to_numeric(df["Valor"], errors='coerce').fillna(0.0)
            
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
        df_save = df.reindex(columns=COLUNAS_ESPERADAS).fillna("")
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x is True else "FALSE")
        
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())

# --- 5. CÁLCULOS ---
def buscar_api(slug):
    try:
        url = f"https://api.cartola.globo.com/ligas/{slug}"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            return pd.DataFrame([{"Time": t['nome'], "Pontos": t['pontos']['rodada'] or 0.0} for t in resp.json()['times']])
    except: pass
    return None

def calcular(df_ranking, df_hist, rod):
    if df_ranking.empty: return [], [], [], 0, 0
    
    qtd = math.ceil(len(df_ranking) * PCT_PAGANTES)
    rank = df_ranking.sort_values("Pontos").reset_index(drop=True)
    
    conta = pd.Series(dtype=int)
    if not df_hist.empty:
        # Filtra histórico válido para contagem
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

# --- BOTÃO ADMIN FLUTUANTE ---
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

# --- CARREGAMENTO ---
df_fin, status_msg = carregar_dados()

tab1, tab2, tab3 = st.tabs(["📋 Resumo", "💰 Pendências", "⚙️ Painel Admin"])

# --- ABA 1: RESUMO GERAL ---
with tab1:
    if not df_fin.empty and "Time" in df_fin.columns:
        try:
            # 1. Prepara dados visuais
            df_v = df_fin.copy()
            df_v["V"] = df_v.apply(lambda x: None if x["Valor"] == 0 else x["Pago"], axis=1)
            
            # 2. Pivot Table
            matrix = df_v.pivot_table(index="Time", columns="Rodada", values="V", aggfunc="last")
            
            # 3. Contagem de Cobranças Reais
            cobrancas = df_fin[df_fin["Valor"] > 0]["Time"].value_counts().rename("Cobranças")
            
            # 4. Join Final
            disp = pd.DataFrame(index=df_fin["Time"].unique()).join(cobrancas).fillna(0).astype(int).join(matrix)
            disp.insert(0, "Status", disp["Cobranças"].apply(lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"))
            
            # 5. Garante colunas 1 a 20
            for i in range(1, 20): 
                if i not in disp.columns: disp[i] = None
            
            disp.index.name = "Time"; disp = disp.reset_index().sort_values("Time")
            
            # 6. Configuração Editor
            cfg = {"Time": st.column_config.TextColumn(disabled=True), 
                   "Status": st.column_config.TextColumn(width="small", disabled=True), 
                   "Cobranças": st.column_config.NumberColumn(width="small", disabled=True)}
            
            for i in range(1, 20): 
                cfg[str(i)] = st.column_config.CheckboxColumn(f"{i}", width="small", disabled=not st.session_state['admin_unlocked'])
            
            edit = st.data_editor(disp, column_config=cfg, height=600, use_container_width=True, hide_index=True)
            
            # 7. Salvamento (Apenas se Admin)
            if st.session_state['admin_unlocked']:
                m = edit.melt(id_vars=["Time"], value_vars=[c for c in edit.columns if str(c).isdigit()], var_name="Rodada", value_name="Nv").dropna(subset=["Nv"])
                if not m.empty:
                    change = False
                    for _, r in m.iterrows():
                        mask = (df_fin["Time"]==r["Time"]) & (df_fin["Rodada"]==int(r["Rodada"])) & (df_fin["Valor"]>0)
                        if mask.any():
                            idx = df_fin[mask].index[0]
                            if bool(df_fin.at[idx, "Pago"]) != bool(r["Nv"]):
                                df_fin.at[idx, "Pago"] = bool(r["Nv"]); change = True
                    if change: salvar_dados(df_fin); feedback_salvamento(); time.sleep(1); st.rerun()
        
        except Exception as e:
            st.warning("Aguardando dados estruturados... Vá ao Painel Admin para começar.")
    else:
        st.info("👋 Banco de dados limpo! Vá em '⚙️ Painel Admin' para lançar a Rodada 1.")

# --- ABA 2: PENDÊNCIAS ---
with tab2:
    if not df_fin.empty and "Valor" in df_fin.columns:
        pg = df_fin[df_fin["Pago"]==True]["Valor"].sum()
        ab = df_fin[df_fin["Pago"]==False]["Valor"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Pago", f"R$ {pg:.2f}"); c2.metric("Aberto", f"R$ {ab:.2f}"); c3.metric("Rodadas", int(df_fin["Rodada"].max()) if "Rodada" in df_fin.columns else 0)
        st.divider()
        
        devs = df_fin[df_fin["Valor"]>0].groupby("Time").agg(Devendo=("Valor", lambda x: x[~df_fin.loc[x.index, "Pago"]].sum()))
        lista = devs[devs["Devendo"]>0].sort_values("Devendo", ascending=False)
        
        if not lista.empty: st.dataframe(lista.style.format("R$ {:.2f}").background_gradient(cmap="Reds"), use_container_width=True)
        else: st.success("Ninguém devendo!")
    else: st.info("Sem dados financeiros.")

# --- ABA 3: ADMIN ---
with tab3:
    if not st.session_state['admin_unlocked']: st.warning("Faça login no botão superior direito."); st.stop()
    
    # FERRAMENTA DE RESET
    with st.expander("🚨 Zona de Perigo (Resetar Tudo)"):
        st.warning("Isso apaga TODOS os dados da planilha e começa do zero.")
        if st.button("⚠️ ZERAR BANCO DE DADOS", type="primary"):
            if resetar_banco_dados():
                st.success("Banco de dados resetado e cabeçalhos criados!"); time.sleep(2); st.rerun()
    
    st.divider()
    
    # LANÇAMENTO
    st.subheader("Lançar Rodada")
    c1, c2 = st.columns([2, 1])
    origem = c1.radio("Fonte:", ["Excel", "API"], horizontal=True)
    rod = c2.number_input("Rodada", 1, 38, 1)
    
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
                x = x.rename(columns={"Pontuação": "Pontos", "Nome": "Time", "Participante": "Time", "Times": "Time"})
                if "Time" in x.columns:
                    col_p = "Pontos" if "Pontos" in x.columns else None
                    cols = ["Time", "Pontos"] if col_p else ["Time"]
                    st.session_state['temp'] = x[cols]
                    if not col_p: st.session_state['temp']["Pontos"] = 0.0
            except: st.error("Erro Excel")
            
    st.session_state['temp'] = st.data_editor(st.session_state['temp'], num_rows="dynamic", use_container_width=True)
    
    if not st.session_state['temp'].empty and "Time" in st.session_state['temp'].columns:
        if "Pontos" not in st.session_state['temp'].columns: st.session_state['temp']["Pontos"] = 0.0
        
        d, i, s, t, p = calcular(st.session_state['temp'], df_fin, rod)
        st.write(f"**Resultado:** {p} pagantes de {t} times.")
        
        if st.button("💾 Salvar Rodada"):
            old = df_fin[df_fin["Rodada"]!=rod] if "Rodada" in df_fin.columns else pd.DataFrame(columns=COLUNAS_ESPERADAS)
            new = pd.concat([old, pd.DataFrame(d+i+s)], ignore_index=True)
            salvar_dados(new); feedback_salvamento(); time.sleep(2); st.rerun()