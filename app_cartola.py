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
SENHA_ADMIN = st.secrets["cartola"]["senha_admin"]
NOME_PLANILHA_GOOGLE = "Controle_Cartola_2026"
NOME_ABA_DADOS = "Dados"
NOME_ABA_CONFIG = "Config"
TOTAL_RODADAS_TURNO = 19
NOME_ABA_PERIODO = "Periodo"
PERIODO_INICIO_PADRAO = 1
PERIODO_FIM_PADRAO = 19
RODADA_MAXIMA = 380

COLUNAS_ESPERADAS = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Posição"]

# --- 2. SETUP VISUAL ---
st.set_page_config(page_title="Gestão Cartola PRO", layout="wide", page_icon="⚽")

def configurar_css():
    st.markdown("""
        <style>
            /* COMPORTAMENTO PADRÃO (DESKTOP) */
            .block-container { padding-top: 2rem !important; }
            
            /* COMPORTAMENTO RESPONSIVO (MOBILE) */
            @media (max-width: 768px) {
                /* Diminui os espaços em branco no topo e nas laterais */
                .block-container { padding-top: 1.5rem !important; padding-left: 1rem !important; padding-right: 1rem !important; }
                
                /* Diminui o título principal */
                h1 { font-size: 1.8rem !important; margin-bottom: 0.5rem !important; }
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
        return client.open(NOME_PLANILHA_GOOGLE).worksheet(NOME_ABA_DADOS)
    except: return None

def conectar_planilha_config():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        return client.open(NOME_PLANILHA_GOOGLE).worksheet(NOME_ABA_CONFIG)
    except: return None

def conectar_planilha_periodo():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        planilha = client.open(NOME_PLANILHA_GOOGLE)
        try:
            return planilha.worksheet(NOME_ABA_PERIODO)
        except Exception:
            ws = planilha.add_worksheet(title=NOME_ABA_PERIODO, rows=10, cols=5)
            ws.update_acell("A1", "Inicio")
            ws.update_acell("B1", "fim")
            ws.update_acell("A2", PERIODO_INICIO_PADRAO)
            ws.update_acell("B2", PERIODO_FIM_PADRAO)
            return ws
    except: return None

def carregar_periodo():
    """Le rodada de inicio (A2) e fim (B2) da aba Periodo, com validacao."""
    inicio, fim = PERIODO_INICIO_PADRAO, PERIODO_FIM_PADRAO
    ws = conectar_planilha_periodo()
    if ws:
        try:
            v_ini = ws.acell("A2").value
            v_fim = ws.acell("B2").value
            if v_ini not in (None, ""): inicio = int(float(str(v_ini).strip().replace(",", ".")))
            if v_fim not in (None, ""): fim = int(float(str(v_fim).strip().replace(",", ".")))
        except: pass
    inicio = max(1, min(inicio, RODADA_MAXIMA))
    fim = max(1, min(fim, RODADA_MAXIMA))
    if inicio > fim: inicio, fim = fim, inicio
    return inicio, fim

def salvar_periodo(inicio, fim):
    ws = conectar_planilha_periodo()
    if ws:
        try:
            ws.update_acell("A1", "Inicio")
            ws.update_acell("B1", "fim")
            ws.update_acell("A2", int(inicio))
            ws.update_acell("B2", int(fim))
            return True
        except Exception as e:
            st.error(f"Erro ao salvar periodo na aba {NOME_ABA_PERIODO}: {e}")
    return False

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

        if "Pontos" in df.columns and "Posição" not in df.columns:
            df.rename(columns={"Pontos": "Posição"}, inplace=True)

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

# --- 5. LÓGICA DE CÁLCULO E API ---
def obter_refresh_token():
    sheet_config = conectar_planilha_config()
    if sheet_config:
        try:
            val = sheet_config.acell('A2').value
            if val and len(val) > 50: return val.strip()
        except: pass
    return st.secrets["cartola"]["refresh_token"].strip()

def salvar_novo_refresh_token(novo_rt):
    sheet_config = conectar_planilha_config()
    if sheet_config:
        try:
            sheet_config.update_acell('A1', 'RefreshToken_Atualizado')
            sheet_config.update_acell('A2', novo_rt)
        except Exception as e:
            st.error(f"Erro ao salvar token no separador Config: {e}")

def gerar_token_fresco():
    try:
        refresh_token_atual = obter_refresh_token()
        url_auth = "https://goidc.globo.com/auth/realms/globo.com/protocol/openid-connect/token"
        payload = {
            'client_id': 'cartola-web@apps.globoid',
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token_atual
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }
        response = requests.post(url_auth, data=payload, headers=headers)
        
        if response.status_code == 200:
            dados = response.json()
            novo_access = dados.get('access_token')
            novo_refresh = dados.get('refresh_token')
            
            if novo_refresh and novo_refresh != refresh_token_atual:
                salvar_novo_refresh_token(novo_refresh)
                
            return novo_access
        else:
            st.error(f"Erro na renovação do token na Globo. Código: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Erro interno na renovação do token: {e}")
        return None

def buscar_api(slug):
    try:
        if "cartola" not in st.secrets or "refresh_token" not in st.secrets["cartola"]:
            st.error("⚠️ Refresh Token não configurado em [cartola] nos Secrets.")
            return None

        token = gerar_token_fresco()
        if not token:
            st.error("⚠️ O Refresh Token expirou ou é inválido. Atualize o ficheiro secrets.toml.")
            return None

        url = f"https://api.cartola.globo.com/auth/liga/{slug}"
        headers = { 'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0' }
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            dados = response.json()
            if dados and 'times' in dados:
                df_bruto = pd.DataFrame(dados['times'])
                df_export = pd.DataFrame()
                df_export['Time'] = df_bruto['nome_cartola']
                df_export['Posição'] = df_bruto['ranking'].apply(
                    lambda x: float(x.get('rodada')) if isinstance(x, dict) else 999.0
                )
                df_export = df_export.sort_values(by='Posição', ascending=True).reset_index(drop=True)
                return df_export
            return None
        else:
            st.error(f"Erro na comunicação com o Cartola: Código {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Erro ao tentar importar os dados: {e}")
        return None

def calcular(df_ranking, df_hist, rod):
    if df_ranking.empty: return [], [], [], 0, 0
    
    qtd = int((len(df_ranking) * PCT_PAGANTES) + 0.5)
    rank = df_ranking.sort_values("Posição", ascending=False).reset_index(drop=True)
    
    conta = pd.Series(dtype=int)
    if not df_hist.empty and "Rodada" in df_hist.columns and "Valor" in df_hist.columns:
        validos = df_hist[(df_hist["Rodada"] != rod) & (df_hist["Valor"] > 0)]
        if not validos.empty: conta = validos["Time"].value_counts()
    
    devs, imune, salvos = [], [], []
    for _, r in rank.iterrows():
        t, p = r['Time'], r['Posição']
        if len(devs) < qtd:
            if conta.get(t, 0) < LIMITE_MAX_PAGAMENTOS:
                devs.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rod, "Time": t, "Valor": VALOR_RODADA, "Pago": False, "Motivo": "Lanterna", "Posição": p})
            else:
                imune.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rod, "Time": t, "Valor": 0.0, "Pago": True, "Motivo": "Imune (>10)", "Posição": p})
        else:
            salvos.append({"Data": datetime.now().strftime("%Y-%m-%d"), "Rodada": rod, "Time": t, "Valor": 0.0, "Pago": True, "Motivo": "Salvo", "Posição": p})
    return devs, imune, salvos, len(df_ranking), qtd

# --- 6. INTERFACE ---
# Título Híbrido com Status Integrado
if st.session_state['admin_unlocked']:
    status_html = '<span style="font-size: 0.45em; color: #28a745; font-weight: normal; vertical-align: middle;">(Admin Ativo)</span>'
else:
    status_html = '<span style="font-size: 0.45em; color: #6c757d; font-weight: normal; vertical-align: middle;">(Visitante)</span>'

st.markdown(f'<h1 style="margin-bottom: 0;">⚽ Os Piá do Cartola {status_html}</h1>', unsafe_allow_html=True)

rodada_inicio, rodada_fim = carregar_periodo()
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
            todas_rodadas = [str(i) for i in range(rodada_inicio, rodada_fim + 1)]
            matrix = matrix.reindex(columns=todas_rodadas)
            matrix = matrix.astype(object)
            matrix = matrix.where(pd.notnull(matrix), None)

            cobrancas = df_fin[df_fin["Valor"] > 0]["Time"].value_counts().rename("Cobranças")
            disp = pd.DataFrame(index=df_fin["Time"].unique()).join(cobrancas).fillna(0).astype(int)
            disp = disp.join(matrix)
            disp.insert(0, "Status", disp["Cobranças"].apply(lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"))
            
            # Tabela Congelada mantida
            disp.index.name = "Time"
            disp = disp.sort_index()
            
            cfg = {
                "Status": st.column_config.TextColumn(width="small", disabled=True),
                "Cobranças": st.column_config.NumberColumn(width="small", disabled=True)
            }
            for c in todas_rodadas:
                cfg[c] = st.column_config.CheckboxColumn(f"{c}", width="small", disabled=not st.session_state['admin_unlocked'])
            
            edit = st.data_editor(disp, column_config=cfg, height=600, use_container_width=True)
            
            if st.session_state['admin_unlocked']:
                m = edit.reset_index().melt(id_vars=["Time"], value_vars=todas_rodadas, var_name="Rodada", value_name="Nv").dropna(subset=["Nv"])
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

# --- ABA 2: PENDÊNCIAS ---
with tab_pendencias:
    if valid_db:
        try:
            pg = df_fin[(df_fin["Pago"] == True) & (df_fin["Valor"] > 0)]["Valor"].sum()
            ab = df_fin[(df_fin["Pago"] == False) & (df_fin["Valor"] > 0)]["Valor"].sum()
            max_rod = int(df_fin["Rodada"].max()) if not df_fin["Rodada"].empty else 0

            # NOVO PLACAR CUSTOMIZADO (Força a exibição lado a lado no Mobile)
            placar_html = f"""
            <div style="display: flex; flex-direction: row; justify-content: space-around; align-items: center; background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #e9ecef;">
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 0.8rem; color: #6c757d; font-weight: bold; text-transform: uppercase; margin-bottom: 2px;">Pago</div>
                    <div style="font-size: 1.3rem; font-weight: bold; color: #28a745;">R$ {pg:.2f}</div>
                </div>
                <div style="text-align: center; flex: 1; border-left: 1px solid #dee2e6; border-right: 1px solid #dee2e6;">
                    <div style="font-size: 0.8rem; color: #6c757d; font-weight: bold; text-transform: uppercase; margin-bottom: 2px;">Aberto</div>
                    <div style="font-size: 1.3rem; font-weight: bold; color: #dc3545;">R$ {ab:.2f}</div>
                </div>
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 0.8rem; color: #6c757d; font-weight: bold; text-transform: uppercase; margin-bottom: 2px;">Última Rod</div>
                    <div style="font-size: 1.3rem; font-weight: bold; color: #212529;">{max_rod}</div>
                </div>
            </div>
            """
            st.markdown(placar_html, unsafe_allow_html=True)
            
            df_devs = df_fin[(df_fin["Valor"] > 0) & (df_fin["Pago"] == False)].copy()
            
            if not df_devs.empty:
                tabela_dev = df_devs.groupby("Time")["Valor"].sum().reset_index(name="Devendo")
                tabela_dev = tabela_dev.sort_values("Devendo", ascending=False).reset_index(drop=True)
                tabela_dev.index = tabela_dev.index + 1
                
                col_tab, col_vazio = st.columns([1, 2])
                with col_tab:
                    try:
                        # Mapa de Calor Restaurado
                        st.dataframe(
                            tabela_dev.style.format({"Devendo": "R$ {:.2f}"})
                            .background_gradient(cmap="Reds", subset=["Devendo"]),
                            use_container_width=True
                        )
                    except:
                        st.dataframe(tabela_dev.style.format({"Devendo": "R$ {:.2f}"}), use_container_width=True)
            else:
                st.success("Tudo pago! Ninguém devendo.")
        except Exception as e:
            st.error(f"Erro Pendências: {e}")
    else: st.info("Sem dados.")

# --- ABA 3: ADMIN ---
with tab_admin:
    # Login exclusivo na aba Admin
    if not st.session_state['admin_unlocked']: 
        st.info("🔒 Faça login para liberar as ferramentas de lançamento de rodadas.")
        st.text_input("Senha de Administrador:", type="password", key="senha_input", on_change=verificar_senha)
        st.stop()
    else:
        col_btn, _ = st.columns([1, 4])
        if col_btn.button("🔓 Encerrar Sessão (Sair)", use_container_width=True):
            st.session_state['admin_unlocked'] = False
            st.rerun()
        st.divider()
    
    with st.expander("🚨 Zona de Perigo"):
        if st.button("⚠️ RESETAR BANCO DE DADOS", type="primary"):
            if resetar_banco_dados(): st.success("Resetado!"); time.sleep(2); st.rerun()

    with st.expander("🗓️ Configurar Período de Rodadas"):
        st.caption(f"Período salvo atualmente: rodada {rodada_inicio} até {rodada_fim} (intervalo inclusivo). Salvo na aba '{NOME_ABA_PERIODO}' (A2 e B2).")
        cp1, cp2 = st.columns(2)
        novo_inicio = cp1.number_input("Rodada de Início", min_value=1, max_value=RODADA_MAXIMA, value=rodada_inicio, step=1, key="periodo_inicio")
        novo_fim = cp2.number_input("Rodada de Fim", min_value=1, max_value=RODADA_MAXIMA, value=rodada_fim, step=1, key="periodo_fim")
        if st.button("💾 Salvar Período"):
            if int(novo_inicio) > int(novo_fim):
                st.error("A rodada de início não pode ser maior que a rodada de fim.")
            elif salvar_periodo(int(novo_inicio), int(novo_fim)):
                st.toast("✅ Período atualizado!", icon="🗓️")
                time.sleep(1)
                st.rerun()

    st.divider()

    st.subheader("Lançar Rodada")
    c1, c2 = st.columns([2, 1])
    origem = c1.radio("Fonte:", ["Excel", "API"], horizontal=True)
    rod = c2.number_input("Rodada", rodada_inicio, rodada_fim, rodada_inicio)
    
    if 'temp' not in st.session_state: st.session_state['temp'] = pd.DataFrame(columns=["Time", "Posição"])
    
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
                mapa = {"Pontuação": "Posição", "Pts": "Posição", "Pontos": "Posição", "Pos": "Posição", "Nome": "Time", "Participante": "Time", "Equipe": "Time", "Cartoleiro": "Time"}
                x = x.rename(columns=mapa)
                if "Time" in x.columns:
                    col_p = "Posição" if "Posição" in x.columns else None
                    cols = ["Time", "Posição"] if col_p else ["Time"]
                    st.session_state['temp'] = x[cols]
                    if not col_p: st.session_state['temp']["Posição"] = 0.0
                    st.session_state['temp'] = st.session_state['temp'].fillna(0)
                else: st.error(f"Não achei coluna Time. Tem: {list(x.columns)}")
            except Exception as e: st.error(f"Erro Excel: {e}")
            
    st.session_state['temp'] = st.data_editor(st.session_state['temp'], num_rows="dynamic", use_container_width=True)
    
    if not st.session_state['temp'].empty and "Time" in st.session_state['temp'].columns:
        if "Posição" not in st.session_state['temp'].columns: st.session_state['temp']["Posição"] = 0.0
        
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
