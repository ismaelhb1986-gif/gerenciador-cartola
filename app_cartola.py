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
NOME_PLANILHA_GOOGLE = "Controle_Cartola_2026" # Crie uma planilha com este nome exato

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="Gestão Cartola", layout="wide")

def configurar_estilo():
    st.markdown("""
        <style>
            .block-container { padding-top: 2rem; padding-bottom: 2rem; }
            .stButton button { width: 100%; }
            /* Esconde menu padrão do Streamlit */
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            
            /* Status Login */
            .user-status {
                font-size: 0.8rem;
                color: #666;
                text-align: right;
                padding-bottom: 10px;
            }
        </style>
    """, unsafe_allow_html=True)

configurar_estilo()

# --- AUTENTICAÇÃO E SESSÃO ---
if 'admin_unlocked' not in st.session_state:
    st.session_state['admin_unlocked'] = False

def verificar_senha():
    """Callback para verificar senha"""
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
    """Conecta ao Google Sheets usando st.secrets ou arquivo local"""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # Tenta pegar dos Segredos do Streamlit Cloud
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    except:
        # Fallback: Tenta arquivo local (para você testar no PC)
        # Renomeie seu arquivo JSON baixado para "credentials.json"
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        except Exception as e:
            st.error(f"Erro de Credenciais: {e}. Configure os Secrets ou o arquivo JSON.")
            return None

    client = gspread.authorize(creds)
    try:
        sheet = client.open(NOME_PLANILHA_GOOGLE).sheet1
        return sheet
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Planilha '{NOME_PLANILHA_GOOGLE}' não encontrada! Crie ela no seu Drive e compartilhe com o email do bot.")
        return None

def carregar_dados():
    sheet = conectar_gsheets()
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            # Converte tipos
            if "Pago" in df.columns:
                df["Pago"] = df["Pago"].astype(bool) # Google Sheets salva como TRUE/FALSE texto
            if "Valor" in df.columns:
                df["Valor"] = pd.to_numeric(df["Valor"]).fillna(0.0)
            return df
    return pd.DataFrame(columns=["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"])

def salvar_dados(df):
    sheet = conectar_gsheets()
    if sheet:
        # Prepara DF para envio (converte bool para string compatível json/sheets se necessário, mas gspread lida bem)
        # Garante colunas
        colunas = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]
        for col in colunas:
            if col not in df.columns:
                df[col] = ""
        
        # Converte booleanos explicitamente para evitar erros
        df_save = df[colunas].copy()
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x else "FALSE")
        
        # Limpa e reescreve (método update bruto, mas seguro para volumes pequenos)
        sheet.clear()
        sheet.update([df_save.columns.values.tolist()] + df_save.values.tolist())

# --- LÓGICA DO CARTOLA (Mantida) ---
def buscar_api(slug):
    url = f"https://api.cartola.globo.com/ligas/{slug}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if 'times' in data:
                return pd.DataFrame([{
                    "Time": t['nome'],
                    "Pontos": t['pontos']['rodada'] or 0.0
                } for t in data['times']])
    except:
        pass
    return None

def calcular_logica(df_ranking, df_hist, rodada):
    total_participantes = len(df_ranking)
    if total_participantes == 0: return [], [], [], 0, 0
    
    qtd_pagantes = math.ceil(total_participantes * PCT_PAGANTES)
    ranking = df_ranking.sort_values(by="Pontos", ascending=True).reset_index(drop=True)
    
    hist_passado = df_hist[df_hist["Rodada"] != rodada]
    pagamentos_reais = hist_passado[hist_passado["Valor"] > 0]
    contagem = pagamentos_reais["Time"].value_counts()
    
    devedores = []
    imunes = []
    salvos = [] 
    
    for i, row in ranking.iterrows():
        time = row['Time']
        pontos = row['Pontos']
        
        if len(devedores) < qtd_pagantes:
            if contagem.get(time, 0) < LIMITE_MAX_PAGAMENTOS:
                devedores.append({
                    "Data": datetime.now().strftime("%Y-%m-%d"),
                    "Rodada": rodada,
                    "Time": time,
                    "Valor": VALOR_RODADA,
                    "Pago": False,
                    "Motivo": "Lanterna",
                    "Pontos": pontos
                })
            else:
                imunes.append({
                    "Data": datetime.now().strftime("%Y-%m-%d"),
                    "Rodada": rodada,
                    "Time": time,
                    "Valor": 0.0,
                    "Pago": True,
                    "Motivo": "Imune (>10)",
                    "Pontos": pontos
                })
        else:
            salvos.append({
                "Data": datetime.now().strftime("%Y-%m-%d"),
                "Rodada": rodada,
                "Time": time,
                "Valor": 0.0,
                "Pago": True,
                "Motivo": "Salvo",
                "Pontos": pontos
            })
            
    return devedores, imunes, salvos, total_participantes, qtd_pagantes

# --- FEEDBACK VISUAL ---
def mostrar_disquete():
    st.markdown("""
        <style>
        @keyframes fade { 0% {opacity:0; top:-50px;} 20% {opacity:1; top:20px;} 80% {opacity:1; top:20px;} 100% {opacity:0; top:-50px;} }
        .save-icon { position:fixed; left:50%; transform:translateX(-50%); top:-50px; font-size:3rem; z-index:9999; animation: fade 2.5s forwards; }
        </style>
        <div class="save-icon">💾</div>
    """, unsafe_allow_html=True)

# --- BARRA DE TOPO (LOGIN) ---
col_t1, col_t2 = st.columns([4, 1])

with col_t1:
    st.title("⚽ Os Piá do Cartola")

with col_t2:
    if not st.session_state['admin_unlocked']:
        # Modo Cartoleiro (Default)
        with st.popover("🔒 Acessar Admin"):
            st.text_input("Senha Admin:", type="password", key="input_senha", on_change=verificar_senha)
            if st.session_state.get('erro_senha'):
                st.error("Senha incorreta")
        st.markdown("<div class='user-status'>Modo: <b>Cartoleiro</b> (Leitura)</div>", unsafe_allow_html=True)
    else:
        # Modo Admin
        if st.button("Sair do Admin"):
            logout()
            st.rerun()
        st.markdown("<div class='user-status' style='color:green;'>Modo: <b>ADMINISTRADOR</b> (Edição)</div>", unsafe_allow_html=True)

# --- CARREGA DADOS ---
# Adiciona um loader visual
with st.spinner("Sincronizando com Google Sheets..."):
    df_fin = carregar_dados()

# --- TABS (ORDEM SOLICITADA: RESUMO PRIMEIRO) ---
tab_resumo, tab_pendencias, tab_admin = st.tabs(["📋 Resumo Geral", "💰 Controle de Pendências", "⚙️ Área Admin"])

# ==============================================================================
# ABA 1: RESUMO GERAL (MATRIZ) - ABERTA PARA TODOS, MAS EDIÇÃO RESTRITA
# ==============================================================================
with tab_resumo:
    st.caption("Visão geral de todas as rodadas.")
    
    if not df_fin.empty:
        # Prepara Matriz
        todos_times = df_fin["Time"].unique()
        df_view = df_fin.copy()
        
        # Visualização: Transforma valores para Bool ou None
        df_view["Pago_View"] = df_view.apply(lambda x: None if x["Valor"] == 0 else x["Pago"], axis=1)
        
        matrix = df_view.pivot_table(index="Time", columns="Rodada", values="Pago_View", aggfunc="last")
        
        # Contagem
        dividas_reais = df_fin[df_fin["Valor"] > 0]
        contagem = dividas_reais["Time"].value_counts().rename("Vezes")
        
        df_display = pd.DataFrame(index=todos_times)
        df_display = df_display.join(contagem).fillna(0).astype(int)
        df_display = df_display.join(matrix)
        
        # Coluna Status
        df_display.insert(0, "Status", df_display["Vezes"].apply(
            lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"
        ))
        
        # Garante colunas
        for i in range(1, 20):
            if i not in df_display.columns: df_display[i] = None
            
        df_display.index.name = "Time"
        df_display = df_display.reset_index().sort_values("Time")

        # Config Colunas
        cfg = {
            "Time": st.column_config.TextColumn("Time", width="medium", disabled=True),
            "Status": st.column_config.TextColumn("Status", width="small", disabled=True),
            "Vezes": st.column_config.NumberColumn("#", width="small", disabled=True),
        }
        for i in range(1, 20):
            # AQUI ESTÁ A MÁGICA: disabled=True se não for admin
            cfg[str(i)] = st.column_config.CheckboxColumn(
                f"{i}", 
                width="small", 
                disabled=not st.session_state['admin_unlocked'] 
            )

        # Editor
        df_editado = st.data_editor(
            df_display,
            column_config=cfg,
            height=600,
            use_container_width=True,
            hide_index=True
        )

        # SALVAMENTO (SÓ EXECUTA SE FOR ADMIN)
        if st.session_state['admin_unlocked']:
            try:
                if "Time" not in df_editado.columns: df_editado = df_editado.reset_index()
                cols_nums = [c for c in df_editado.columns if str(c).isdigit()]
                df_melt = df_editado.melt(id_vars=["Time"], value_vars=cols_nums, var_name="Rodada", value_name="Novo_Status")
                df_melt = df_melt.dropna(subset=["Novo_Status"])
                
                if not df_melt.empty:
                    mudou = False
                    # Compara com DF original
                    for _, row in df_melt.iterrows():
                        mask = (df_fin["Time"] == row["Time"]) & (df_fin["Rodada"] == int(row["Rodada"])) & (df_fin["Valor"] > 0)
                        if mask.any():
                            idx = df_fin[mask].index[0]
                            # Verifica se o estado mudou
                            if bool(df_fin.at[idx, "Pago"]) != bool(row["Novo_Status"]):
                                df_fin.at[idx, "Pago"] = bool(row["Novo_Status"])
                                mudou = True
                    
                    if mudou:
                        salvar_dados(df_fin)
                        mostrar_disquete()
                        time.sleep(1)
                        st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")
        else:
            # Se tentar editar sem ser admin (visual warning, embora esteja disabled)
            pass

    else:
        st.info("Nenhum dado. Peça ao Admin para lançar a Rodada 1.")

# ==============================================================================
# ABA 2: PENDÊNCIAS - APENAS LEITURA PARA TODOS
# ==============================================================================
with tab_pendencias:
    if not df_fin.empty:
        total_pago = df_fin[(df_fin["Valor"] > 0) & (df_fin["Pago"] == True)]["Valor"].sum()
        total_aberto = df_fin[(df_fin["Valor"] > 0) & (df_fin["Pago"] == False)]["Valor"].sum()
        
        k1, k2, k3 = st.columns(3)
        k1.metric("💰 Arrecadado", f"R$ {total_pago:.2f}")
        k2.metric("🔴 A Receber", f"R$ {total_aberto:.2f}", delta=-total_aberto)
        k3.metric("Última Rodada", df_fin["Rodada"].max() if pd.notna(df_fin["Rodada"].max()) else 0)
        
        st.divider()
        
        resumo = df_fin[df_fin["Valor"] > 0].groupby("Time").agg(
            Pendentes=("Pago", lambda x: (~x).sum()),
            Valor_Aberto=("Valor", lambda x: x[~df_fin.loc[x.index, "Pago"]].sum())
        )
        devedores = resumo[resumo["Valor_Aberto"] > 0].sort_values("Valor_Aberto", ascending=False)
        
        if not devedores.empty:
            st.dataframe(devedores.style.format({"Valor_Aberto": "R$ {:.2f}"}).background_gradient(cmap="Reds"), use_container_width=True)
        else:
            st.success("Tudo em dia!")
    else:
        st.info("Sem dados.")

# ==============================================================================
# ABA 3: ÁREA ADMIN - PROTEGIDA
# ==============================================================================
with tab_admin:
    if not st.session_state['admin_unlocked']:
        st.warning("⚠️ Esta área é restrita. Faça login no canto superior direito.")
        st.stop() # Para a execução aqui se não for admin
    
    st.subheader("⚙️ Lançamento de Rodada")
    
    c1, c2 = st.columns([2, 1])
    modo = c1.radio("Fonte:", ["Excel / Manual", "API Cartola"], horizontal=True)
    rodada = c2.number_input("Rodada Nº", 1, 38, 1)
    
    if 'dados_live' not in st.session_state:
        st.session_state['dados_live'] = pd.DataFrame([{"Time": "Exemplo", "Pontos": 0.0}])

    # INPUTS
    if modo == "API Cartola":
        slug = st.text_input("Slug da Liga", SLUG_LIGA_PADRAO)
        if st.button("Buscar API"):
            res = buscar_api(slug)
            if res is not None: 
                st.session_state['dados_live'] = res
                st.rerun()
            else: st.error("Erro API")
    else:
        file = st.file_uploader("Excel (.xlsx)", ["xlsx"])
        if file:
            try:
                x = pd.read_excel(file)
                x.columns = [c.capitalize().strip() for c in x.columns]
                st.session_state['dados_live'] = x
            except: pass
        
        st.session_state['dados_live'] = st.data_editor(st.session_state['dados_live'], num_rows="dynamic", use_container_width=True, height=200)

    # CÁLCULO E SALVAMENTO
    if not st.session_state['dados_live'].empty:
        st.divider()
        if not df_fin.empty and rodada in df_fin["Rodada"].values:
            st.warning(f"⚠️ Rodada {rodada} será substituída!")
            
        devs, imunes, salvos, tot, pag = calcular_logica(st.session_state['dados_live'], df_fin, rodada)
        
        cols = st.columns(3)
        cols[0].metric("Participantes", tot)
        cols[1].metric("Pagantes", pag)
        cols[2].metric("Valor", f"R$ {VALOR_RODADA:.2f}")
        
        st.write("Quem paga:")
        st.dataframe(pd.DataFrame(devs)[["Time", "Pontos", "Valor"]] if devs else pd.DataFrame(), use_container_width=True)
        
        if st.button("✅ Confirmar Lançamento"):
            # Limpa rodada antiga e salva nova
            df_limpo = df_fin[df_fin["Rodada"] != rodada]
            todos = devs + imunes + salvos
            df_final = pd.concat([df_limpo, pd.DataFrame(todos)], ignore_index=True)
            
            salvar_dados(df_final)
            mostrar_disquete()
            st.success("Salvo no Google Sheets!")
            time.sleep(1.5)
            st.rerun()