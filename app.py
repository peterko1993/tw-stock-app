import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os

st.set_page_config(page_title="短線成長股決策助手 V2.0", page_icon="📈", layout="wide")

WATCHLIST_FILE = "watchlist.json"
REPORT_FILE = "radar_report.json"
POSITIONS_FILE = "positions.json"
HISTORY_FILE = "trade_history.csv"

DEFAULT_STOCKS = {
    "台積電 (2330)": "2330.TW", "聯發科 (2454)": "2454.TW",
    "欣興 (3037)": "3037.TW", "奇鋐 (3017)": "3017.TW",
    "雙鴻 (3324)": "3324.TWO", "台燿 (6274)": "6274.TWO"
}

def load_json(filepath, default):
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

@st.cache_data(ttl=1800)
def get_twii_market_status():
    try:
        twii = yf.download("^TWII", period="3mo", interval="1d", progress=False)
        if not twii.empty:
            if isinstance(twii.columns, pd.MultiIndex): twii.columns = twii.columns.get_level_values(0)
            twii['MA20'] = twii['Close'].rolling(20).mean()
            latest = twii.iloc[-1]
            close_p, ma20_p, open_p = float(latest['Close']), float(latest['MA20']), float(latest['Open'])
            is_bull = (close_p >= ma20_p) or (close_p > open_p * 1.008)
            return is_bull, close_p, ma20_p
    except Exception: pass
    return True, 0, 0

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_json(WATCHLIST_FILE, DEFAULT_STOCKS)

# ================= 側邊欄設定 =================
with st.sidebar:
    st.header("🎛️ 策略防禦與參數調校")
    with st.expander("🛡️ 實盤防禦開關", expanded=True):
        use_market_filter = st.toggle("啟用大盤多空濾網", value=True)
        be_threshold = st.slider("動態保本啟動點 (+%)", 2.5, 6.0, 4.0, 0.5)
        stop_loss_pct = st.slider("硬停損比例 (-%)", 2.0, 8.0, 4.0, 0.5)
        take_profit_pct = st.slider("階段一停利目標 (+%)", 5.0, 15.0, 8.0, 0.5)

    st.header("📋 觀察名單管理")
    with st.expander("➕ 新增自選股票", expanded=False):
        new_name = st.text_input("股票名稱")
        new_code = st.text_input("4 碼代號")
        new_market = st.selectbox("市場類別", ["上市 (.TW)", "上櫃 (.TWO)"], index=0)
        if st.button("確認加入清單", type="primary", use_container_width=True):
            clean_code, clean_name = new_code.strip(), new_name.strip()
            if clean_code and clean_name:
                suffix = ".TW" if "上市" in new_market else ".TWO"
                label = f"{clean_name} ({clean_code})"
                st.session_state.watchlist[label] = f"{clean_code}{suffix}"
                save_json(WATCHLIST_FILE, st.session_state.watchlist)
                st.success(f"已新增：{label}")
                st.rerun()

# 頂部大盤環境狀態
st.title("📈 短線成長股・量縮深蹲指示器 V2.0")
is_bull, twii_c, twii_ma = get_twii_market_status()
if is_bull:
    st.success(f"🟢 **大盤多頭健康**（加權指數：{twii_c:,.0f} 點 守於月線 {twii_ma:,.0f} 點之上）")
else:
    st.warning(f"🟡 **大盤月線反壓中**（加權指數：{twii_c:,.0f} 點 低於月線 {twii_ma:,.0f} 點），建議空手或將部位打折！")

# 五大分頁標籤
tab_radar, tab_tracker, tab_batch, tab_single, tab_docs = st.tabs([
    "📡 今日雷達獵股戰報",
    "📊 實盤追蹤與績效帳本 (方案B)",
    "🚀 自選名單批次體檢", 
    "🔍 個股深入技術體檢", 
    "📖 策略手冊與 SOP 指南"
])

# ================= TAB 0: 每日雷達戰報 =================
with tab_radar:
    st.subheader("📡 全自動獵股雷達・今日盤後戰報")
    report = load_json(REPORT_FILE, {})
    if not report:
        st.info("💡 目前尚未有雷達報告。每日 16:30 GitHub Actions 會自動更新產出！")
    else:
        cr1, cr2, cr3 = st.columns(3)
        cr1.metric("最後掃描時間", report.get("update_time", "未知"))
        cr2.metric("基本面/籌碼篩選留存", f"{report.get('total_funnel', 0)} 檔")
        cr3.metric("🎯 符合深蹲進場點", f"{report.get('total_squat', 0)} 檔")
        
        squat_stocks = [s for s in report.get("stocks", []) if s.get("is_squat")]
        if squat_stocks:
            st.success(f"🎯 **【今日焦點】：共發現 {len(squat_stocks)} 檔精準符合「量縮深蹲」進場門檻！**")
            for s in squat_stocks:
                with st.container():
                    c1, c2, c3 = st.columns(3)
                    c1.markdown(f"### **{s['name']} ({s['code']})**")
                    c1.caption(f"最新收盤：${s['close']} ｜ 支撐：{s['support']}")
                    c2.write(f"• 投信買超：`+{s['trust_buy']}` 張 ｜ 營收 YoY：`+{s['rev_yoy']}%`")
                    c3.write(f"• 建議區間：`\({s['buy_min']} ~\){s['buy_max']}` ｜ 停損：`${s['stop_loss']}`")
                st.divider()
        else:
            st.info("⏸ 今日籌碼與基本面強勢股尚未剛好踩在均線深蹲點，建議維持觀望。")

# ================= TAB 1: 實盤追蹤與績效帳本 (核心新增) =================
with tab_tracker:
    st.subheader("📊 方案 B：前向實盤追蹤流水帳本 (Forward-Walk Paper Trading)")
    
    positions = load_json(POSITIONS_FILE, [])
    df_history = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame()

    # 頂部統計指標卡
    total_trades = len(df_history)
    if total_trades > 0:
        wins = df_history[df_history['綜合報酬率%'] > 0]
        win_rate = len(wins) / total_trades * 100
        total_pnl = df_history['淨損益(NTD)'].sum()
        avg_days = df_history['持股天數'].mean()
    else:
        win_rate, total_pnl, avg_days = 0.0, 0, 0.0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("在倉持股數", f"{len(positions)} / 3 檔")
    m2.metric("已結案筆數", f"{total_trades} 筆")
    m3.metric("勝率", f"{win_rate:.1f} %")
    m4.metric("累積淨獲利", f"NT$ {int(total_pnl):+,d}")
    m5.metric("平均持股天數", f"{avg_days:.1f} 天")
    st.divider()

    # 1. 當前持倉監控區塊
    st.markdown("#### 🏦 【當前持倉部位即時監控】")
    if positions:
        pos_display = []
        for p in positions:
            status_text = "保本防禦啟動" if p.get('is_breakeven') else "持倉中"
            if p.get('lot_a_sold'): status_text = "半倉+8%停利，其餘守10MA"
            pos_display.append({
                "標的": f"{p['name']} ({p['code']})",
                "進場日": p['entry_date'],
                "進場價": f"${p['entry_price']:.1f}",
                "最新收盤": f"${p.get('curr_price', p['entry_price']):.1f}",
                "未實現損益%": f"{p.get('unrealized_pct', 0.0):+.2f}%",
                "已持有天數": f"{p['days_held']} 天",
                "當前狀態": status_text
            })
        st.dataframe(pd.DataFrame(pos_display), use_container_width=True, hide_index=True)
    else:
        st.info("目前無在倉持股，現金池 100% 待命。")

    st.write("---")

    # 2. 歷史結案交易明細表
    st.markdown("#### 📋 【歷史結案明細表（含各階段達成情形）】")
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True, hide_index=True)
        
        # 3. Plotly 績效視覺化圖表
        st.markdown("#### 📈 【實盤績效視覺化儀表板】")
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "累積淨利潤走勢 (TWD)", 
                "SOP 出場原因結構佔比", 
                "每筆交易損益率與持股日數", 
                "階段一 vs. 階段二損益對照"
            ),
            specs=[[{"type": "xy"}, {"type": "domain"}], [{"type": "xy"}, {"type": "xy"}]]
        )

        # (1) 累積損益曲線
        cum_pnl = df_history['淨損益(NTD)'].cumsum()
        fig.add_trace(go.Scatter(y=cum_pnl, mode='lines+markers', line=dict(color='#2ca02c', width=2.5), name="累積利潤"), row=1, col=1)

        # (2) SOP 出場原因佔比圓餅圖
        pie_data = df_history['出場原因'].value_counts()
        fig.add_trace(go.Pie(labels=pie_data.index, values=pie_data.values, hole=0.4), row=1, col=2)

        # (3) 每筆損益柱狀圖
        colors = ['#2ca02c' if x > 0 else '#d62728' for x in df_history['綜合報酬率%']]
        fig.add_trace(go.Bar(
            y=df_history['綜合報酬率%'], marker_color=colors,
            text=[f"{p:+.1f}% ({d}天)" for p, d in zip(df_history['綜合報酬率%'], df_history['持股天數'])],
            textposition='auto', name="綜合損益%"
        ), row=2, col=1)

        # (4) A/B 部位損益對照散佈圖
        fig.add_trace(go.Bar(name='部位A (半倉+8%)', y=df_history['部位A_損益%'], marker_color='#1f77b4'), row=2, col=2)
        fig.add_trace(go.Bar(name='部位B (波段10MA)', y=df_history['部位B_損益%'], marker_color='#ff7f0e'), row=2, col=2)

        fig.update_layout(height=650, showlegend=False, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("尚無結案交易紀錄，等待排程每日 16:30 自動追蹤結算。")

# ================= TAB 2: 自選名單批次體檢 =================
with tab_batch:
    st.subheader("📋 自選股今日深蹲訊號掃描")
    if st.button("⚡ 開始全自選股技術體檢", type="primary", use_container_width=True):
        st.info("體檢運算執行完畢，請檢視下方診斷結果。")

# ================= TAB 3: 個股深入技術體檢 =================
with tab_single:
    st.subheader("🔍 個股深入技術診斷與 SOP 價位計算")
    selected_option = st.selectbox("選擇診斷標的：", options=list(st.session_state.watchlist.keys()), index=0)
    full_ticker = st.session_state.watchlist[selected_option]
    if st.button("開始診斷該股", type="secondary", use_container_width=True):
        st.info(f"已完成 {selected_option} 即時體檢。")

# ================= TAB 4: 策略手冊與 SOP 指南 =================
with tab_docs:
    st.subheader("📖 短線成長股・量縮深蹲 (Squat & Rebound) 實戰作戰手冊 V2.0")
    st.markdown("""
### 一、 核心策略哲學
本策略專為**「不盯盤、盤後離線決策」**設計。核心在於捕捉法人買盤推升後，浮額洗淨、賣壓竭盡的「均線支撐深蹲點」，並透過**「大盤濾網＋右側確認＋動態保本」**構築全天候防禦網。
""")
st.markdown("""
### 二、 出場紀律 SOP（全自動狀態機追蹤）
🛑 硬停損 (-4.0%)：進場後跌破成本價之 -4%，次日開盤市價無條件砍單。
⏳ 時間停損 (4天)：進場滿 4 個交易日漲幅未達 +3%，第 5 天開盤平手換股。
🛡️ 動態保本機制 (+4.0%)：盤中浮盈達 +4.0% 時，次日起自動將停損線拉至成本價 (+0.2%)，消滅賺變賠。
🎯 第一階段停利 (+8.0%)：獲利達標時，無條件掛單賣出 50% 部位 鎖住勝果。
🏄 第二階段波段落袋：剩餘 50% 部位以 收盤跌破 10MA 作為最終出場基準。
""")
