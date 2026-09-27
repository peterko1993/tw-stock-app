import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import json
import os
import time

st.set_page_config(page_title="短線成長股決策助手", page_icon="📈", layout="wide")

WATCHLIST_FILE = "watchlist.json"
REPORT_FILE = "radar_report.json"

DEFAULT_STOCKS = {
    "台積電 (2330)": "2330.TW",
    "聯發科 (2454)": "2454.TW",
    "欣興 (3037)": "3037.TW",
    "奇鋐 (3017)": "3017.TW",
    "雙鴻 (3324)": "3324.TWO",
    "台燿 (6274)": "6274.TWO"
}

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return DEFAULT_STOCKS.copy()
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_STOCKS.copy()

def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_radar_report():
    if not os.path.exists(REPORT_FILE):
        return None
    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# ================= 側邊欄：參數設定與名單管理 =================
with st.sidebar:
    st.header("🎛️ 策略參數動態微調")
    with st.expander("⚙️ 調整進出場判定數值", expanded=True):
        buffer_pct = st.slider("均線回測容許緩衝 (%)", 0.5, 3.0, 1.2, 0.1)
        k_body_limit = st.slider("K棒實體最大振幅 (%)", 1.0, 5.0, 2.5, 0.5)
        vol_mode = st.radio("成交量萎縮標準", ["嚴格（低於 5MV 且 20MV）", "標準（低於 5MV 或 20MV）"], index=0)
        stop_loss_pct = st.slider("硬停損比例 (-%)", 2.0, 8.0, 4.0, 0.5)
        take_profit_pct = st.slider("第一階段停利目標 (+%)", 5.0, 15.0, 8.0, 0.5)

    st.divider()
    st.header("📋 自選名單管理")
    with st.expander("➕ 新增自選股票", expanded=False):
        new_name = st.text_input("股票名稱", placeholder="例如：金像電")
        new_code = st.text_input("4 碼代號", placeholder="例如：2368")
        new_market = st.selectbox("市場類別", ["上市 (.TW)", "上櫃 (.TWO)"], index=0)
        if st.button("確認加入清單", type="primary", use_container_width=True):
            clean_code = new_code.strip()
            clean_name = new_name.strip()
            if clean_code and clean_name:
                suffix = ".TW" if "上市" in new_market else ".TWO"
                label = f"{clean_name} ({clean_code})"
                st.session_state.watchlist[label] = f"{clean_code}{suffix}"
                save_watchlist(st.session_state.watchlist)
                st.success(f"已新增：{label}")
                st.rerun()

    with st.expander("🗑️ 刪除自選股票", expanded=False):
        if st.session_state.watchlist:
            del_target = st.selectbox("選擇要移除的標的", options=list(st.session_state.watchlist.keys()))
            if st.button("確認刪除", use_container_width=True):
                del st.session_state.watchlist[del_target]
                save_watchlist(st.session_state.watchlist)
                st.success(f"已移除：{del_target}")
                st.rerun()

st.title("📈 短線成長股・量縮深蹲指示器")
st.caption(f"即時防守設定：停損 -{stop_loss_pct}% ｜ 停利 +{take_profit_pct}% ｜ K棒實體上限 {k_body_limit}%")

# 主頁面四大功能分頁
tab_radar, tab_batch, tab_single, tab_docs = st.tabs([
    "📡 今日雷達獵股戰報",
    "🚀 自選名單批次體檢", 
    "🔍 個股深入技術體檢", 
    "📖 策略手冊與 SOP 指南"
])

# ================= TAB 0: 每日雷達戰報 (核心新功能) =================
with tab_radar:
    st.subheader("📡 全自動獵股雷達・今日盤後戰報")
    report = load_radar_report()
    
    if report is None:
        st.info("💡 目前尚未有雷達報告。請至 GitHub Actions 手動點擊一次「Daily Auto Stock Radar」或等待每日 16:30 自動產出！")
    else:
        # 頂部戰報統計卡
        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("最後掃描時間", report.get("update_time", "未知"))
        col_r2.metric("基本面/籌碼過濾留存", f"{report.get('total_funnel', 0)} 檔")
        col_r3.metric("🎯 符合深蹲買點", f"{report.get('total_squat', 0)} 檔")

        stocks = report.get("stocks", [])
        squat_stocks = [s for s in stocks if s.get("is_squat")]
        watching_stocks = [s for s in stocks if not s.get("is_squat")]

        st.write("---")
        if squat_stocks:
            st.success(f"🎯 **【今日焦點】：共發現 {len(squat_stocks)} 檔精準符合「量縮深蹲」進場門檻！**")
            
            for s in squat_stocks:
                with st.container():
                    c_s1, c_s2, c_s3, c_s4 = st.columns([2, 2, 2, 2])
                    c_s1.markdown(f"### **{s['name']} ({s['code']})**")
                    c_s1.caption(f"最新收盤：**${s['close']}** ｜ 踩中 **{s['support']}**")
                    
                    c_s2.write(f"• **投信買超**：`+{s['trust_buy']}` 張")
                    c_s2.write(f"• **單月營收 YoY**：`+{s['rev_yoy']}%`")
                    
                    c_s3.write(f"• **建議掛單**：`\({s['buy_min']} ~\){s['buy_max']}`")
                    c_s3.write(f"• **硬停損價 (-4%)**：`${s['stop_loss']}`")
                    
                    label_key = f"{s['name']} ({s['code']})"
                    if label_key not in st.session_state.watchlist:
                        if c_s4.button(f"📥 加到自選名單", key=f"add_{s['code']}"):
                            st.session_state.watchlist[label_key] = s['ticker']
                            save_watchlist(st.session_state.watchlist)
                            st.success(f"已加入 {label_key}")
                            st.rerun()
                    else:
                        c_s4.write("✅ 已在自選觀察清單中")
                st.divider()
        else:
            st.warning(" 今日經 3-1-2 漏斗過濾後的強勢股，尚未剛好踩在均線深蹲點，建議維持觀望。")

        if watching_stocks:
            with st.expander(f"👀 檢視籌碼與基本面強勢池（尚在拉回或整理中，共 {len(watching_stocks)} 檔）", expanded=False):
                df_watch = pd.DataFrame(watching_stocks)[['name', 'code', 'close', 'trust_buy', 'cap', 'rev_yoy']]
                df_watch.columns = ['股票名稱', '代號', '收盤價', '投信買超(張)', '股本(億)', '營收YoY(%)']
                st.dataframe(df_watch, use_container_width=True, hide_index=True)

# ================= TAB 1: 一鍵批次全掃描 =================
with tab_batch:
    st.subheader("📋 自選股深蹲訊號掃描")
    st.write(f"目前名單待檢驗數量：**{len(st.session_state.watchlist)}** 檔")
    
    if st.button("⚡ 開始掃描自選名單全部標的", type="primary", use_container_width=True):
        progress_text = st.empty()
        progress_bar = st.progress(0)
        triggered_list, waiting_list = [], []
        items = list(st.session_state.watchlist.items())
        total_items = len(items)
        
        for idx, (label, ticker) in enumerate(items):
            progress_text.text(f"正在分析第 {idx + 1}/{total_items} 檔：{label} ...")
            try:
                df = yf.download(ticker, period="6mo", interval="1d", progress=False)
                if df.empty or len(df) < 30: continue
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df['VOL_MA5'] = df['Volume'].rolling(5).mean()
                df['VOL_MA20'] = df['Volume'].rolling(20).mean()

                latest = df.iloc[-1]
                close = float(latest['Close'])
                vol = float(latest['Volume'])
                low = float(latest['Low'])
                open_p = float(latest['Open'])
                ma5 = float(latest['MA5'])
                ma10 = float(latest['MA10'])
                ma20 = float(latest['MA20'])
                vol_ma5 = float(latest['VOL_MA5'])
                vol_ma20 = float(latest['VOL_MA20'])

                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                buf = 1 + (buffer_pct / 100)
                touch_10 = (low <= ma10 * buf) and (close >= ma10 * 0.99)
                touch_20 = (low <= ma20 * buf) and (close >= ma20 * 0.99)
                cond_support = touch_10 or touch_20
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit

                target_ma = ma10 if touch_10 else ma20
                support_name = "10MA" if touch_10 else ("20MA" if touch_20 else "未回踩")

                if cond_trend and cond_support and cond_vol and cond_k:
                    triggered_list.append({
                        "股票標的": label,
                        "最新收盤": f"${close:,.1f}",
                        "回踩均線": support_name,
                        "建議掛單區間": f"\({target_ma:,.1f} ~\){close:,.1f}",
                        f"硬停損 (-{stop_loss_pct}%)": f"${target_ma * (1 - stop_loss_pct/100):,.1f}",
                        f"目標價 (+{take_profit_pct}%)": f"${close * (1 + take_profit_pct/100):,.1f}",
                        "當日量": f"{int(vol):,d}"
                    })
                else:
                    reasons = []
                    if not cond_trend: reasons.append("均線非多頭")
                    if not cond_support: reasons.append("未回踩")
                    if not cond_vol: reasons.append("未量縮")
                    if not cond_k: reasons.append("實體黑棒過大")
                    waiting_list.append({"股票標的": label, "最新收盤": f"${close:,.1f}", "未符合原因": "、".join(reasons)})
            except Exception: pass
            progress_bar.progress((idx + 1) / total_items)

        progress_text.empty()
        progress_bar.empty()

        if triggered_list:
            st.success(f"🎯 **自選股中今日共 {len(triggered_list)} 檔符合深蹲條件！**")
            st.dataframe(pd.DataFrame(triggered_list), use_container_width=True, hide_index=True)
        else:
            st.warning("自選股中今日無符合標的。")

# ================= TAB 2: 單一個股詳細技術體檢 =================
with tab_single:
    st.subheader("🔍 個股深入技術診斷與 K 線走勢")
    options_list = list(st.session_state.watchlist.keys()) + ["✏️ 臨時手動輸入其他代號"]
    selected_option = st.selectbox("選擇診斷標的：", options=options_list, index=0)
    
    if selected_option == "✏️ 臨時手動輸入其他代號":
        c1, c2 = st.columns([2, 1])
        with c1: custom_code = st.text_input("輸入 4 位數代號", value="2308")
        with c2: market_suffix = st.selectbox("市場別", [".TW (上市)", ".TWO (上櫃)"], index=0)
        full_ticker = f"{custom_code.strip()}{'.TW' if '上市' in market_suffix else '.TWO'}"
        display_title = f"自訂標的 ({full_ticker})"
    else:
        full_ticker = st.session_state.watchlist[selected_option]
        display_title = selected_option

    target_ma_choice = st.radio("指定防守均線基準", ["10MA", "20MA (月線)"], horizontal=True)

    if st.button("開始診斷該股", type="secondary", use_container_width=True):
        with st.spinner(f"正在分析 {display_title}..."):
            df = yf.download(full_ticker, period="6mo", interval="1d", progress=False)
            if df.empty or len(df) < 30:
                st.error("⚠️ 找不到行情資料。")
            else:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                
                c_out1, c_out2 = st.columns(2)
                c_out1.metric("最新收盤價", f"${df['Close'].iloc[-1]:,.1f}")
                c_out2.metric(f"防守 {target_ma_choice}", f"${(df['MA10'] if '10' in target_ma_choice else df['MA20']).iloc[-1]:,.1f}")

                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df.index[-60:], open=df['Open'][-60:], high=df['High'][-60:],
                                             low=df['Low'][-60:], close=df['Close'][-60:], name="K線"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA5'][-60:], line=dict(color='orange', width=1), name="5MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA10'][-60:], line=dict(color='blue', width=1.5), name="10MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA20'][-60:], line=dict(color='purple', width=2), name="20MA"))
                fig.update_layout(xaxis_rangeslider_visible=False, height=420, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

# ================= TAB 3: 策略手冊與 SOP 指南 =================
with tab_docs:
    st.subheader("📖 短線成長股・量縮深蹲 (Squat & Rebound) 作戰手冊")
    st.markdown("""
### 一、 核心策略哲學
本策略專為**「不盯盤、盤後離線決策」**設計。核心在於捕捉法人買盤推升後，浮額洗淨、賣壓竭盡的「均線支撐深蹲點」，兼顧高勝算與極小虧損風險。
""")
    st.markdown("""
### 二、 股票池與前置選股條件
    1. 股本規模：20 億 ～ 60 億元台幣（排除不易推動的權值股與流動性差的小型股）。
    2. 營收動能：單月營收年增率（YoY）大於 20%，且具備連月成長態勢。
    3. 籌碼鎖定：投信連續買超 3 天以上，或近 5 日投信買超佔比大於 8%。
    """)
    st.markdown("""
### 三、 成交量量縮黃金標準（Volume Dry-Up）
    相較前波發動量：回測當日成交量小於等於前波長紅突破量的 30% ～ 40%。
    相較均量線（窒息量）：當日成交量同時低於 5 日均量（5MV） 與 20 日均量（20MV）。
💡 量化意涵：量縮代表「主力大戶未倒貨、盤面浮額已乾涸」，稍有微量買盤即可再次推升。
    """)

doc_comparison = pd.DataFrame([
    {"觀察維度": "K 線實體", "主力洗盤深蹲 (可進場)": "小陰線、小陽線或十字星 (振幅 <= 2.5%)", "主力出貨真崩跌 (禁進場)": "大實體中長黑棒 (單日跌幅 > 4%)"},
    {"觀察維度": "成交量變化", "主力洗盤深蹲 (可進場)": "量急縮 (低於 5MV/20MV 均量線)", "主力出貨真崩跌 (禁進場)": "帶量下殺或爆量收長黑"},
    {"觀察維度": "下影線特徵", "主力洗盤深蹲 (可進場)": "回踩均線後收斂，帶有承接下影線", "主力出貨真崩跌 (禁進場)": "開高走低光頭光腳、收在最低點"},
    {"觀察維度": "均線姿態", "主力洗盤深蹲 (可進場)": "10MA / 20MA 角度陡峭向上", "主力出貨真崩跌 (禁進場)": "均線走平或下彎形成上蓋反壓"}
])
st.table(doc_comparison)

st.markdown("""五、 嚴格出場紀律 SOP
🛑 硬停損線：跌破進場成本價或防守均線之 -4.0%，次日開盤無條件市價砍單。

⏳ 時間停損：進場後 4 個交易日內 未創波段新高或脫離成本區，平手或微損換股。

🎯 第一階段停利：獲利達 +8% ～ +10% 時，掛單賣出 50% 部位 鎖住勝果。

🏄 第二階段移動停利：剩餘 50% 部位以 收盤跌破 10MA 作為波段落袋點。""")
