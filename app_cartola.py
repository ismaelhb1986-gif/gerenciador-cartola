import streamlit as st
import pandas as pd
import requests
import math
import os
import random
from datetime import datetime

# --- CONFIGURAÇÕES ---
ARQUIVO_DEBITOS = "controle_financeiro.csv"
VALOR_RODADA = 7.00
LIMITE_MAX_PAGAMENTOS = 10
PCT_PAGANTES = 0.25
SLUG_LIGA_PADRAO = "os-pia-do-cartola"

# --- CSS: LAYOUT COMPACTO & NOTIFICAÇÃO FIXA ---
def configurar_estilo_visual():
    st.markdown("""
        <style>
               /* Remove margens do topo */
               .block-container {
                    padding-top: 1.5rem;
                    padding-bottom: 1rem;
                }
               /* Compacta textos e tabelas */
               h1 { font-size: 1.8rem !important; margin-bottom: 0rem !important; }
               div[data-testid="stDataEditor"] table { font-size: 0.9rem; }
               td, th { padding: 4px !important; }
               
               /* Animação do Disquete (FIXO NA TELA) */
               @keyframes fade_in_right {
                   0% { opacity: 0; transform: translateX(20px); }
                   20% { opacity: 1; transform: translateX(0); }
                   80% { opacity: 1; transform: translateX(0); }
                   100% { opacity: 0; transform: translateX(20px); }
               }
               
               .icon-save {
                   position: fixed; /* Fixo em relação à janela do navegador */
                   top: 80px;       /* Distância do topo (abaixo do cabeçalho do Streamlit) */
                   right: 30px;     /* Distância da direita */
                   font-size: 3.5rem;
                   z-index: 999999; /* Garante que fique POR CIMA de tudo */
                   pointer-events: none;
                   animation: fade_in_right 2.5s ease-in-out forwards;
                   filter: drop-shadow(2px 2px 4px rgba(0,0,0,0.3));
               }
        </style>
    """, unsafe_allow_html=True)

# --- FUNÇÃO VISUAL: FEEDBACK DE SALVAMENTO ---
def mostrar_disquete():
    """Mostra um disquete fixo no canto superior direito da tela visível."""
    st.markdown('<div class="icon-save">💾</div>', unsafe_allow_html=True)

# --- FUNÇÕES DE ARQUIVO ---
def carregar_dados():
    if os.path.exists(ARQUIVO_DEBITOS):
        df = pd.read_csv(ARQUIVO_DEBITOS)
        df["Pago"] = df["Pago"].astype(bool)
        df["Valor"] = df["Valor"].fillna(0.0).astype(float)
        return df
    else:
        return pd.DataFrame(columns=["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"])

def salvar_dados(df):
    colunas = ["Data", "Rodada", "Time", "Valor", "Pago", "Motivo", "Pontos"]
    for col in colunas:
        if col not in df.columns:
            df[col] = None
    df[colunas].to_csv(ARQUIVO_DEBITOS, index=False)

# --- FUNÇÕES DO CARTOLA ---
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

# --- INTERFACE ---
st.set_page_config(page_title="Gestão Cartola", layout="wide")
configurar_estilo_visual()

st.title("⚽ Os Piá do Cartola")

df_fin = carregar_dados()

tab1, tab2, tab3 = st.tabs(["🚀 Lançamento", "📋 Resumo Geral", "💰 Controle de Pendências"])

# --- TAB 1: LANÇAMENTO AUTOMÁTICO ---
with tab1:
    c1, c2 = st.columns([2, 1])
    modo = c1.radio("Fonte:", ["Excel / Manual", "API Cartola"], horizontal=True)
    rodada = c2.number_input("Rodada Nº", 1, 38, 1)
    
    if 'dados_live' not in st.session_state:
        st.session_state['dados_live'] = pd.DataFrame([{"Time": "Exemplo", "Pontos": 0.0}])

    if modo == "API Cartola":
        slug = st.text_input("Slug da Liga", SLUG_LIGA_PADRAO)
        if st.button("Buscar na API"):
            with st.spinner("Buscando..."):
                res_api = buscar_api(slug)
                if res_api is not None: 
                    st.session_state['dados_live'] = res_api
                    st.rerun()
                else: st.error("Erro ao buscar dados.")
    else:
        file = st.file_uploader("Solte o Excel aqui (.xlsx)", ["xlsx"])
        if file:
            try:
                df_excel = pd.read_excel(file)
                df_excel.columns = [c.strip().capitalize() for c in df_excel.columns]
                st.session_state['dados_live'] = df_excel
            except Exception as e: st.error(f"Erro no Excel: {e}")
        
        st.caption("Edite os dados abaixo e o resultado atualizará automaticamente:")
        st.session_state['dados_live'] = st.data_editor(
            st.session_state['dados_live'], 
            num_rows="dynamic", 
            use_container_width=True, 
            height=200,
            key="editor_lancamento"
        )

    if not st.session_state['dados_live'].empty:
        st.divider()
        if not df_fin.empty and rodada in df_fin["Rodada"].values:
            st.warning(f"⚠️ Rodada {rodada} já existe. Ao confirmar, será SUBSTITUÍDA.")
            
        devedores, imunes, salvos, total, pagantes = calcular_logica(st.session_state['dados_live'], df_fin, rodada)
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Participantes", total)
        k2.metric("Pagantes (25%)", pagantes)
        k3.metric("Imunes (>10x)", len(imunes))
        
        st.write("##### 📉 Quem deve pagar:")
        df_show = pd.DataFrame(devedores)
        if not df_show.empty:
            df_show.index += 1
            st.dataframe(df_show[["Time", "Pontos", "Valor"]], use_container_width=True)
        else:
            st.success("Ninguém paga nesta rodada!")

        if st.button("✅ Confirmar e Salvar Rodada"):
            df_limpo = df_fin[df_fin["Rodada"] != rodada]
            todos_registros = devedores + imunes + salvos
            df_final = pd.concat([df_limpo, pd.DataFrame(todos_registros)], ignore_index=True)
            salvar_dados(df_final)
            
            mostrar_disquete()
            st.toast("Rodada salva!")
            
            import time
            time.sleep(1.5)
            st.rerun()

# --- TAB 2: RESUMO GERAL ---
with tab2:
    st.header("Resumo Geral (Ordem Alfabética)")
    
    if not df_fin.empty:
        todos_times = df_fin["Time"].unique()
        df_view = df_fin.copy()
        df_view.loc[df_view["Valor"] == 0, "Pago"] = None
        
        matrix = df_view.pivot_table(index="Time", columns="Rodada", values="Pago", aggfunc="last")
        dividas_reais = df_fin[df_fin["Valor"] > 0]
        contagem = dividas_reais["Time"].value_counts().rename("Vezes")
        
        df_display = pd.DataFrame(index=todos_times)
        df_display = df_display.join(contagem).fillna(0).astype(int)
        df_display = df_display.join(matrix)
        
        df_display.insert(0, "Status", df_display["Vezes"].apply(
            lambda x: "⚠️ >10" if x >= LIMITE_MAX_PAGAMENTOS else "Ativo"
        ))
        
        rodadas_cols = []
        for i in range(1, 20):
            if i not in df_display.columns: df_display[i] = None
            rodadas_cols.append(i)
        
        df_display.index.name = "Time"
        df_display = df_display.reset_index()
        df_display = df_display.sort_values(by="Time", ascending=True)

        cfg = {
            "Time": st.column_config.TextColumn("Time", width="medium", disabled=True),
            "Status": st.column_config.TextColumn("Status", width="small", disabled=True),
            "Vezes": st.column_config.NumberColumn("#", width="small", disabled=True),
        }
        for i in range(1, 20):
            cfg[str(i)] = st.column_config.CheckboxColumn(f"{i}", width="small")
            
        st.caption("Legenda: **Vazio** = Salvo | **☐** = Deve | **☑** = Pago")
        
        df_editado = st.data_editor(
            df_display, 
            column_config=cfg,
            height=600, 
            use_container_width=True,
            hide_index=True 
        )

        try:
            if "Time" not in df_editado.columns:
                df_editado = df_editado.reset_index()
            
            cols_nums = [c for c in df_editado.columns if str(c).isdigit()]
            
            df_melt = df_editado.melt(
                id_vars=["Time"], 
                value_vars=cols_nums,
                var_name="Rodada", 
                value_name="Novo_Status"
            )
            df_melt = df_melt.dropna(subset=["Novo_Status"])
            
            if not df_melt.empty:
                mudou = False
                for _, row in df_melt.iterrows():
                    mask = (df_fin["Time"] == row["Time"]) & \
                           (df_fin["Rodada"] == int(row["Rodada"])) & \
                           (df_fin["Valor"] > 0)
                    
                    if mask.any():
                        idx = df_fin[mask].index[0]
                        if bool(df_fin.at[idx, "Pago"]) != bool(row["Novo_Status"]):
                            df_fin.at[idx, "Pago"] = bool(row["Novo_Status"])
                            mudou = True
                
                if mudou:
                    salvar_dados(df_fin)
                    mostrar_disquete()
                    import time
                    time.sleep(1)
                    st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")

    else:
        st.info("Nenhum dado encontrado. Faça o lançamento da Rodada 1.")

# --- TAB 3: CONTROLE DE PENDÊNCIAS ---
with tab3:
    if not df_fin.empty:
        total_pago = df_fin[(df_fin["Valor"] > 0) & (df_fin["Pago"] == True)]["Valor"].sum()
        total_aberto = df_fin[(df_fin["Valor"] > 0) & (df_fin["Pago"] == False)]["Valor"].sum()
        
        k1, k2, k3 = st.columns(3)
        k1.metric("💰 Arrecadado", f"R$ {total_pago:.2f}")
        k2.metric("🔴 A Receber", f"R$ {total_aberto:.2f}", delta=-total_aberto)
        k3.metric("Última Rodada", df_fin["Rodada"].max())
        
        st.divider()
        
        resumo = df_fin[df_fin["Valor"] > 0].groupby("Time").agg(
            Pendentes=("Pago", lambda x: (~x).sum()),
            Valor_Aberto=("Valor", lambda x: x[~df_fin.loc[x.index, "Pago"]].sum())
        )
        
        devedores_reais = resumo[resumo["Valor_Aberto"] > 0].sort_values("Valor_Aberto", ascending=False)
        
        if not devedores_reais.empty:
            st.subheader("🚨 Ranking de Devedores")
            st.dataframe(
                devedores_reais.style.format({"Valor_Aberto": "R$ {:.2f}"})
                               .background_gradient(cmap="Reds"),
                use_container_width=True
            )
        else:
            st.success("Todos em dia! 🏆")
    else:
        st.info("Sem dados.")