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

# Definição estrita das colunas para evitar erros de chave
COLUNAS_DB = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]

# --- 2. CONFIGURAÇÃO DE UI/UX (CSS AVANÇADO) ---
st.set_page_config(page_title="Gestão Cartola PRO", layout="wide", page_icon="⚽")

def aplicar_estilo_pro():
    st.markdown("""
        <style>
            /* Ajuste fino do container principal */
            .block-container { padding-top: 3.5rem !important; }
            
            /* --- BOTÃO ADMIN FLUTUANTE (FIXO ABSOLUTO) --- */
            /* Isso garante que ele NUNCA saia do lugar ou empurre o título */
            .admin-floating-container {
                position: fixed;
                top: 60px; /* Ajuste conforme a barra do Streamlit */
                right: 25px;
                z-index: 9999;
                background-color: white;
                padding: 5px;
                border-radius: 8px;
                box-shadow: 0px 2px 10px rgba(0,0,0,0.1);
            }
            
            /* Status do usuário */
            .status-badge {
                font-size: 0.75rem;
                font-weight: bold;
                text-align: center;
                margin-top: 5px;
                display: block;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            /* Animação do Disquete */
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
            
            /* Melhoria nas tabelas */
            [data-testid="stDataFrameResizable"] { border: 1px solid #f0f2f6; border-radius: 5px; }
        </style>
    """, unsafe_allow_html=True)

aplicar_estilo_pro()

def feedback_salvamento():
    st.markdown('<div class="save-icon-container">💾</div>', unsafe_allow_html=True)
    st.toast("✅ Dados sincronizados com sucesso!", icon="☁️")

# --- 3. AUTENTICAÇÃO ---
if 'admin_unlocked' not in st.session_state:
    st.session_state['admin_unlocked'] = False

def verificar_senha():
    if st.session_state.get('senha_input') == SENHA_ADMIN:
        st.session_state['admin_unlocked'] = True
    else:
        st.toast("⛔ Senha incorreta!", icon="❌")

# --- 4. CONEXÃO ROBUSTA (GOOGLE SHEETS) ---
@st.cache_resource(ttl=60)
def conectar_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Tenta pegar dos secrets
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            # Fallback local
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
            
        client = gspread.authorize(creds)
        # Tenta abrir, se não existir, avisa mas não quebra o app inteiro
        return client.open(NOME_PLANILHA_GOOGLE).sheet1
    except Exception as e:
        return None

def carregar_dados_blindado():
    """Carrega dados e garante que a estrutura do DataFrame esteja correta."""
    sheet = conectar_gsheets()
    if sheet:
        try:
            data = sheet.get_all_records()
            if data:
                df = pd.DataFrame(data)
                
                # Normalização de tipos (Evita erros de soma/comparação)
                if "Pago" in df.columns:
                    df["Pago"] = df["Pago"].apply(lambda x: str(x).upper() == "TRUE")
                if "Valor" in df.columns:
                    df["Valor"] = pd.to_numeric(df["Valor"], errors='coerce').fillna(0.0)
                if "Rodada" in df.columns:
                    df["Rodada"] = pd.to_numeric(df["Rodada"], errors='coerce').fillna(0).astype(int)
                    
                # Garante que todas as colunas existem (mesmo que vazias)
                for col in COLUNAS_DB:
                    if col not in df.columns:
                        df[col] = None
                        
                return df
        except Exception:
            pass # Se der erro na leitura, retorna DF vazio padronizado
            
    return pd.DataFrame(columns=COLUNAS_DB)

def salvar_dados_blindado(df):
    sheet = conectar_gsheets()
    if sheet:
        # Garante ordem e estrutura
        df_save = df.reindex(columns=COLUNAS_DB).fillna("")
        
        # Converte booleanos para string (Google Sheets prefere "TRUE"/"FALSE")
        df_save["Pago"] = df_save["Pago"].apply(lambda x: "TRUE" if x is True else "FALSE")
        
        # Atualização em Batch (Mais rápida e segura)
        lista_dados = [df_save.columns.values.tolist()] + df_save.values.tolist()
        sheet.clear()
        sheet.update(lista_dados)

# --- 5. LÓGICA DE NEGÓCIO ---
def buscar_api(slug):
    try:
        url = f"https://api.cartola.globo.com/ligas/{slug}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return pd.DataFrame([{"Time": t['nome'], "Pontos": t['pontos']['rodada'] or 0.0} for t in data['times']])
    except:
        return None
    return None

def calcular_quem_paga(df_ranking, df_hist, rodada):
    if df_ranking.empty: return [], [], [], 0, 0
    
    total = len(df_ranking)
    qtd_pagantes = math.ceil(total * PCT_PAGANTES)
    
    # Ordena ranking
    ranking = df_ranking.sort_values(by="Pontos", ascending=True).reset_index(drop=True)
    
    # Calcula histórico (Ignora a rodada atual para não contar duplicado se reprocessar)
    contagem = pd.Series(dtype=int)
    if not df_hist.empty:
        # Filtra apenas dívidas REAIS (>0) passadas
        hist_valido = df_hist[
            (df_hist["Rodada"] != rodada) & 
            (df_hist["Valor"] > 0)
        ]
        if not hist_valido.empty:
            contagem = hist_valido["Time"].value_counts()
    
    devedores, imunes, salvos = [], [], []
    
    for _, row in ranking.iterrows():
        time_nome = row['Time']
        pts = row['Pontos']
        
        # Lógica de seleção
        if len(devedores) < qtd_pagantes:
            ja_pagou_n_vezes = contagem.get(time_nome, 0)
            
            if ja_pagou_n_vezes < LIMITE_MAX_PAGAMENTOS:
                devedores.append({
                    "Data": datetime.now().strftime("%Y-%m-%d"), 
                    "Rodada": rodada, "Time": time_nome, "Valor": VALOR_RODADA, 
                    "Pago": False, "Motivo": "Lanterna", "Pontos": pts
                })
            else:
                imunes.append({
                    "Data": datetime.now().strftime("%Y-%m-%d"), 
                    "Rodada": rodada, "Time": time_nome, "Valor": 0.0, 
                    "Pago": True, "Motivo": "Imune (>10)", "Pontos": pts
                })
        else:
            salvos.append({
                "Data": datetime.now().strftime("%Y-%m-%d"), 
                "Rodada": rodada, "Time": time_nome, "Valor": 0.0, 
                "Pago": True, "Motivo": "Salvo", "Pontos": pts
            })
            
    return devedores, imunes, salvos, total, qtd_pagantes

# --- 6. LAYOUT PRINCIPAL ---

# 6.1. Cabeçalho e Botão Admin Flutuante
st.title("⚽ Os Piá do Cartola")

# Container Flutuante (Renderizado fora do fluxo normal via CSS)
with st.container():
    st.markdown('<div class="admin-floating-container">', unsafe_allow_html=True)
    if not st.session_state['admin_unlocked']:
        # Layout Login
        with st.popover("🔒 Acessar Admin", use_container_width=True):
            st.text_input("Senha:", type="password", key="senha_input", on_change=verificar_senha)
        st.markdown('<span class="status-badge" style="color:#666;">Visitante</span>', unsafe_allow_html=True)
    else:
        # Layout Logged In
        if st.button("🔓 Sair", key="btn_logout"):
            st.session_state['admin_unlocked'] = False
            st.rerun()
        st.markdown('<span class="status-badge" style="color:#28a745;">Admin Ativo</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# 6.2. Carregamento de Dados (Com tratamento de erro visual)
df_fin = carregar_dados_blindado()

# 6.3. Abas
tab_resumo, tab_pendencias, tab_admin = st.tabs(["📋 Resumo Geral", "💰 Pendências", "⚙️ Painel Admin"])

# --- ABA RESUMO (Protegida contra vazios) ---
with tab_resumo:
    # Verificação PRO: Só tenta renderizar se tiver dados REAIS
    tem_dados = not df_fin.empty and len(df_fin) > 0 and "Time" in df_fin.columns
    
    if tem_dados:
        # Preparação segura da matriz
        df_view = df_fin.copy()
        # Lógica visual: Se Valor=0 (Salvo), mostra None (Vazio). Se >0, mostra Checkbox (True/False)
        df_view["Visual"] = df_view.apply(lambda x: None if x["Valor"] == 0 else x["Pago"], axis=1)
        
        try:
            # Pivotamento
            matrix = df_view.pivot_table(index="Time", columns="Rodada", values="Visual", aggfunc="last")
            
            # Contagem de Pagamentos
            dividas = df_fin[df_fin["Valor"] > 0]
            if not dividas.empty:
                contagem = dividas["Time"].value_counts().rename("Cobranças")
            else:
                contagem = pd.Series(name="Cobranças")
            
            # Junção
            df_display = pd.DataFrame(index=df_fin["Time"].unique()).join(contagem).fillna(0).astype(int).join(matrix)
            
            # Coluna Status
            df_display.insert(0, "Status", df_display["Cobranças"].apply(
                lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"
            ))
            
            # Garante colunas 1..20
            for i in range(1, 20):
                if i not in df_display.columns: df_display[i] = None
                
            # Ordenação
            df_display.index.name = "Time"
            df_display = df_display.reset_index().sort_values("Time")
            
            # Configuração do Editor
            cfg = {
                "Time": st.column_config.TextColumn("Time", disabled=True),
                "Status": st.column_config.TextColumn("Status", width="small", disabled=True),
                "Cobranças": st.column_config.NumberColumn("#", width="small", disabled=True)
            }
            # Checkboxes: Desabilitados se não for admin
            is_disabled = not st.session_state['admin_unlocked']
            for i in range(1, 20):
                cfg[str(i)] = st.column_config.CheckboxColumn(f"{i}", width="small", disabled=is_disabled)
                
            st.caption("Legenda: **Vazio** = Salvo | **☐** = Pendente | **☑** = Pago")
            
            # EDITOR
            df_editado = st.data_editor(
                df_display, 
                column_config=cfg, 
                height=600, 
                use_container_width=True, 
                hide_index=True
            )
            
            # SALVAMENTO (SÓ SE ADMIN ESTIVER LOGADO)
            if not is_disabled:
                # Detecta mudanças comparando com DF original
                cols_rodadas = [c for c in df_editado.columns if str(c).isdigit()]
                df_melt = df_editado.melt(id_vars=["Time"], value_vars=cols_rodadas, var_name="Rodada", value_name="Novo_Status")
                df_melt = df_melt.dropna(subset=["Novo_Status"]) # Pega só o que é checkbox (True/False)
                
                if not df_melt.empty:
                    mudou_algo = False
                    for _, row in df_melt.iterrows():
                        # Busca no DF original
                        mask = (
                            (df_fin["Time"] == row["Time"]) & 
                            (df_fin["Rodada"] == int(row["Rodada"])) & 
                            (df_fin["Valor"] > 0)
                        )
                        if mask.any():
                            idx = df_fin[mask].index[0]
                            status_antigo = bool(df_fin.at[idx, "Pago"])
                            status_novo = bool(row["Novo_Status"])
                            
                            if status_antigo != status_novo:
                                df_fin.at[idx, "Pago"] = status_novo
                                mudou_algo = True
                    
                    if mudou_algo:
                        salvar_dados_blindado(df_fin)
                        feedback_salvamento()
                        time.sleep(1)
                        st.rerun()

        except Exception as e:
            st.error(f"Erro ao montar visualização: {e}")
            
    else:
        st.info("👋 O banco de dados está vazio. Aguardando o Administrador lançar a 1ª Rodada.")
        st.markdown("**Dica para o Admin:** Vá na aba '⚙️ Painel Admin' e faça o upload ou importação.")


# --- ABA PENDÊNCIAS (Protegida) ---
with tab_pendencias:
    tem_valores = not df_fin.empty and "Valor" in df_fin.columns and df_fin["Valor"].sum() > 0
    
    if tem_valores:
        pagos = df_fin[df_fin["Pago"] == True]["Valor"].sum()
        abertos = df_fin[df_fin["Pago"] == False]["Valor"].sum()
        max_rodada = int(df_fin["Rodada"].max()) if "Rodada" in df_fin.columns else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Arrecadado", f"R$ {pagos:.2f}")
        c2.metric("🔴 A Receber", f"R$ {abertos:.2f}", delta=-abertos if abertos > 0 else None)
        c3.metric("Rodadas Jogadas", max_rodada)
        
        st.divider()
        
        # Tabela de Devedores
        # Filtra apenas quem tem valor > 0
        df_devs = df_fin[df_fin["Valor"] > 0]
        
        # Agrupa
        resumo = df_devs.groupby("Time").agg(
            Total_Aberto=("Valor", lambda x: x[~df_fin.loc[x.index, "Pago"]].sum())
        )
        
        # Filtra apenas quem deve
        lista_final = resumo[resumo["Total_Aberto"] > 0].sort_values("Total_Aberto", ascending=False)
        
        if not lista_final.empty:
            st.subheader("🚨 Lista de Devedores")
            st.dataframe(
                lista_final.style.format("R$ {:.2f}").background_gradient(cmap="Reds"), 
                use_container_width=True
            )
        else:
            st.balloons()
            st.success("Tudo pago! Ninguém deve nada na liga. 🏆")
            
    else:
        st.info("Nenhuma pendência financeira registrada até o momento.")

# --- ABA ADMIN (Funcional) ---
with tab_admin:
    if not st.session_state['admin_unlocked']:
        st.warning("🔒 Acesso Negado. Faça login no canto superior direito.")
        st.stop()
        
    st.subheader("⚙️ Lançamento de Nova Rodada")
    
    col_a, col_b = st.columns([2, 1])
    origem = col_a.radio("Origem:", ["Excel / Manual", "API Cartola"], horizontal=True)
    rodada_input = col_b.number_input("Número da Rodada:", 1, 38, 1)
    
    # Session state para dados temporários
    if 'dados_temp' not in st.session_state:
        st.session_state['dados_temp'] = pd.DataFrame(columns=["Time", "Pontos"])
    
    # --- INPUTS ---
    if origem == "API Cartola":
        slug = st.text_input("Slug da Liga:", SLUG_LIGA_PADRAO)
        if st.button("Buscar Dados API"):
            res = buscar_api(slug)
            if res is not None:
                st.session_state['dados_temp'] = res
                st.rerun()
            else:
                st.error("Erro ao buscar API. Verifique o Slug ou se a liga é aberta.")
    else:
        file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])
        if file:
            try:
                # Leitura robusta do Excel
                df_x = pd.read_excel(file)
                # Limpeza de nomes de colunas (remove espaços e padroniza)
                df_x.columns = [str(c).strip().title() for c in df_x.columns]
                
                # Mapeamento flexível
                mapa = {"Pontuação": "Pontos", "Nome": "Time", "Participante": "Time", "Times": "Time"}
                df_x = df_x.rename(columns=mapa)
                
                if "Time" in df_x.columns:
                    # Seleciona só o necessário
                    cols_to_keep = ["Time", "Pontos"] if "Pontos" in df_x.columns else ["Time"]
                    st.session_state['dados_temp'] = df_x[cols_to_keep]
                    st.success("✅ Excel carregado com sucesso!")
                else:
                    st.error("Erro: Não encontrei a coluna 'Time' no Excel.")
            except Exception as e:
                st.error(f"Erro ao processar arquivo: {e}")

        st.caption("Verifique ou digite os dados abaixo:")
        st.session_state['dados_temp'] = st.data_editor(
            st.session_state['dados_temp'], 
            num_rows="dynamic", 
            use_container_width=True,
            key="editor_admin"
        )

    # --- CÁLCULO E SAVE ---
    if not st.session_state['dados_temp'].empty and "Time" in st.session_state['dados_temp'].columns:
        st.divider()
        
        # Verifica se tem pontos (se não tiver, assume 0 para não quebrar)
        if "Pontos" not in st.session_state['dados_temp'].columns:
             st.session_state['dados_temp']["Pontos"] = 0.0
             
        devs, imunes, salvos, total, pags = calcular_quem_paga(st.session_state['dados_temp'], df_fin, rodada_input)
        
        st.markdown(f"**Simulação:** {pags} pagantes de {total} times.")
        
        # Alerta de substituição
        if not df_fin.empty and rodada_input in df_fin["Rodada"].values:
            st.warning(f"⚠️ Atenção: A rodada {rodada_input} JÁ EXISTE. Ao confirmar, os dados anteriores serão apagados.")
        
        col_btn1, col_btn2 = st.columns([1, 4])
        if col_btn1.button("💾 Gravar Rodada", type="primary"):
            # 1. Remove dados antigos dessa rodada
            df_limpo = df_fin[df_fin["Rodada"] != rodada_input]
            
            # 2. Cria novos registros
            novos_registros = devs + imunes + salvos
            
            # 3. Concatena
            df_final = pd.concat([df_limpo, pd.DataFrame(novos_registros)], ignore_index=True)
            
            # 4. Salva
            salvar_dados_blindado(df_final)
            feedback_salvamento()
            st.success(f"Rodada {rodada_input} salva com sucesso!")
            time.sleep(2)
            st.rerun()