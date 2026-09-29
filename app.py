import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import base64
import requests
import datetime

st.set_page_config(page_title="短線成長股決策助手 V2.0", page_icon="📈", layout="wide")

WATCHLIST_FILE = "watchlist.json"
REPORT_FILE = "radar_report.json"
POSITIONS_FILE = "positions.json"
HISTORY_FILE = "trade_history.csv"

# 預設自選標的池（涵蓋 20~150 億旗艦股）
DEFAULT_STOCKS = {
    "台積電 (2330)": "2330.TW", "聯發科 (2454)": "2454.TW",
    "欣興 (3037)": "3037.TW", "奇鋐 (3017)": "3017.TW",
    "雙鴻 (3324)": "3324.TWO", "台燿 (6274)": "6274.TWO",
    "智邦 (2345)": "2345.TW", "金像電 (2368)": "2368.TW",
    "致伸 (4915)": "4915.TW"
}

def load_json(filepath, default):
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    has_secrets = False
    try:
        if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
            has_secrets = True
    except Exception:
        has_secrets = False

    if has_secrets:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]
            url = f"https://api.github.com/repos/{repo}/contents/{filepath}"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json"
            }
            get_res = requests.get(url, headers=headers)
            sha = get_res.json().get("sha") if get_res.status_code == 200 else None
            
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            content_b64 = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
            
            payload = {
                "message": f"🤖 [Streamlit] 使用者反向更新 {filepath}",
                "content": content_b64
            }
            if sha:
                payload["sha"] = sha
                
            put_res = requests.put(url, headers=headers, json=payload)
            if put_res.status_code in [200, 201]:
                print(f"✅ 成功反向更新 {filepath} 至 GitHub！")
        except Exception as e:
            print(f"⚠️ 反向更新例外異常: {e}")

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
        use_right_side = st.toggle("啟用右側過高確認", value=True)
        be_threshold = st.slider("動態保本啟動點 (+%)", 2.5, 6.0, 4.0, 0.5)
        stop_loss_pct = st.slider("硬停損比例 (-%)", 2.0, 8.0, 4.0, 0.5)
        take_profit_pct = st.slider("階段一停利目標 (+%)", 5.0, 15.0, 8.0, 0.5)

    with st.expander("⚙️ 技術面閥值設定", expanded=False):
        buffer_pct = st.slider("均線回測緩衝 (%)", 0.5, 3.0, 1.8, 0.1)
        k_body_limit = st.slider("K棒實體振幅上限 (%)", 1.0, 5.0, 3.5, 0.5)
        vol_mode = st.radio("成交量萎縮標準", ["嚴格（低於 5MV 且 20MV）", "標準（低於 5MV 或 20MV）"], index=0)

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

    with st.expander("🗑️ 刪除自選股票", expanded=False):
        if st.session_state.watchlist:
            del_target = st.selectbox("選擇要移除的標的", options=list(st.session_state.watchlist.keys()))
            if st.button("確認刪除", use_container_width=True):
                del st.session_state.watchlist[del_target]
                save_json(WATCHLIST_FILE, st.session_state.watchlist)
                st.success(f"已移除：{del_target}")
                st.rerun()

    if st.button("🔄 恢復初始預設名單", use_container_width=True):
        st.session_state.watchlist = DEFAULT_STOCKS.copy()
        save_json(WATCHLIST_FILE, st.session_state.watchlist)
        st.success("已還原預設自選清單！")
        st.rerun()

# 頂部大盤環境狀態
st.title("📈 短線成長股・量縮深蹲指示器 V2.0")
is_bull, twii_c, twii_ma = get_twii_market_status()
if is_bull:
    st.success(f"🟢 **大盤多頭健康**（加權指數：{twii_c:,.0f} 點 守於月線 {twii_ma:,.0f} 點之上）")
else:
    st.warning(f"🟡 **大盤月線反壓中**（加權指數：{twii_c:,.0f} 點 低於月線 {twii_ma:,.0f} 點），建議空手或將部位打折！")

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
        st.write("---")
        
        if not is_bull and use_market_filter:
            st.error("🛑 **【風控攔截】：今日大盤跌破月線，依防禦 SOP 建議全市場雷達強制休眠，暫不建新倉！**")
        elif squat_stocks:
            st.success(f"🎯 **【今日焦點】：共發現 {len(squat_stocks)} 檔精準符合「量縮深蹲」進場門檻！**")
            for s in squat_stocks:
                with st.container():
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                    c1.markdown(f"### **{s['name']} ({s['code']})**")
                    c1.caption(f"最新收盤：${s['close']} ｜ 支撐：{s['support']} ｜ 股本：{s['cap']}億")
                    c2.write(f"• 投信買超：`+{s['trust_buy']}` 張 ｜ 營收 YoY：`+{s['rev_yoy']}%`")
                    c3.write(f"• 建議掛單區間：`\({s['buy_min']} ~\){s['buy_max']}` ｜ 停損：`${s['stop_loss']}`")
                    
                    label_key = f"{s['name']} ({s['code']})"
                    if label_key not in st.session_state.watchlist:
                        if c4.button(f"📥 加到自選名單", key=f"radar_add_{s['code']}"):
                            st.session_state.watchlist[label_key] = s['ticker']
                            save_json(WATCHLIST_FILE, st.session_state.watchlist)
                            st.success(f"已將 {label_key} 加入觀察清單！")
                            st.rerun()
                    else:
                        c4.write("✅ 已在自選觀察清單中")
                st.divider()
        else:
            st.info("⏸ 今日籌碼與基本面強勢股尚未剛好踩在均線深蹲點，建議維持觀望。")

# ================= TAB 1: 實盤追蹤與績效帳本 =================
with tab_tracker:
    st.subheader("📊 方案 B：前向實盤追蹤流水帳本 (Forward-Walk Paper Trading)")
    
    positions = load_json(POSITIONS_FILE, [])
    df_history = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame()

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

    st.markdown("#### 🏦 【當前持倉部位即時監控・實戰下單指標】")
    if positions:
        pos_display = []
        for p in positions:
            entry_p = float(p['entry_price'])
            curr_p = float(p.get('curr_price', entry_p))
            unreal_pct = float(p.get('unrealized_pct', 0.0))
            days = p.get('days_held', 0)
            
            if p.get('is_breakeven') and days > 1:
                stop_display = f"🛡️ ${entry_p * 1.002:.1f} (保本線)"
            else:
                stop_display = f"🛑 ${entry_p * 0.96:.1f} (-4%)"
                
            if p.get('lot_a_sold'):
                tp1_display = "✅ 半倉已停利"
            else:
                tp1_display = f"🎯 ${entry_p * 1.08:.1f} (+8%)"
                
            ma10_val = p.get('ma10')
            ma10_display = f"🏄 ${ma10_val:.1f}" if ma10_val else "計算中"

            pos_display.append({
                "標的": f"{p['name']} ({p['code']})",
                "進場日 (天數)": f"{p['entry_date']} ({days}天)",
                "進場成本": f"${entry_p:.1f}",
                "現價 (浮盈%)": f"${curr_p:.1f} ({unreal_pct:+.2f}%)",
                "🛑 當前防守停損": stop_display,
                "🎯 階段一停利": tp1_display,
                "🏄 移動停利 (10MA)": ma10_display,
                "持倉狀態": "半倉續抱守10MA" if p.get('lot_a_sold') else ("保本防護中" if p.get('is_breakeven') else "持倉中")
            })
        st.dataframe(pd.DataFrame(pos_display), use_container_width=True, hide_index=True)
        
        with st.expander("🗑️ 手動刪除未建倉或誤入之虛擬部位", expanded=False):
            st.warning("若你在真實帳戶中並未買進該檔股票，可在此將其從虛擬帳本中剔除，以釋放槽位空間。")
            del_pos_target = st.selectbox("選擇要刪除的在倉部位", options=[f"{p['name']} ({p['code']})" for p in positions])
            if st.button("確認刪除此持倉紀錄", type="primary"):
                positions = [p for p in positions if f"{p['name']} ({p['code']})" != del_pos_target]
                save_json(POSITIONS_FILE, positions)
                st.success(f"已從帳本中刪除 {del_pos_target}！")
                st.rerun()
    else:
        st.info("目前無在倉持股，現金池 100% 待命。")

    st.write("---")
    st.markdown("#### 📋 【歷史結案明細表】")
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True, hide_index=True)
        st.markdown("#### 📈 【實盤績效視覺化儀表板】")
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("累積淨利潤走勢 (TWD)", "SOP 出場原因結構佔比", "每筆交易損益率與持股日數", "階段一 vs. 階段二損益對照"),
            specs=[[{"type": "xy"}, {"type": "domain"}], [{"type": "xy"}, {"type": "xy"}]]
        )

        cum_pnl = df_history['淨損益(NTD)'].cumsum()
        fig.add_trace(go.Scatter(y=cum_pnl, mode='lines+markers', line=dict(color='#2ca02c', width=2.5), name="累積利潤"), row=1, col=1)

        pie_data = df_history['出場原因'].value_counts()
        fig.add_trace(go.Pie(labels=pie_data.index, values=pie_data.values, hole=0.4), row=1, col=2)

        colors = ['#2ca02c' if x > 0 else '#d62728' for x in df_history['綜合報酬率%']]
        fig.add_trace(go.Bar(
            y=df_history['綜合報酬率%'], marker_color=colors,
            text=[f"{p:+.1f}% ({d}天)" for p, d in zip(df_history['綜合報酬率%'], df_history['持股天數'])],
            textposition='auto', name="綜合損益%"
        ), row=2, col=1)

        fig.add_trace(go.Bar(name='部位A (半倉+8%)', y=df_history['部位A_損益%'], marker_color='#1f77b4'), row=2, col=2)
        fig.add_trace(go.Bar(name='部位B (波段10MA)', y=df_history['部位B_損益%'], marker_color='#ff7f0e'), row=2, col=2)

        fig.update_layout(height=650, showlegend=False, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("尚無結案交易紀錄，等待排程每日 16:30 自動追蹤結算。")

# ================= TAB 2: 自選名單批次體檢 =================
with tab_batch:
    st.subheader("📋 自選股今日深蹲訊號掃描")
    st.write(f"目前自選名單中共有 **{len(st.session_state.watchlist)}** 檔標的。")
    
    if st.button("⚡ 開始全自選股技術體檢", type="primary", use_container_width=True):
        if not is_bull and use_market_filter:
            st.warning("⚠️ 提醒：目前大盤偏弱，即使自選股出現訊號，也請控制部位（建議至多單筆 10~12 萬）。")
            
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

                now_t = datetime.datetime.now().time()
                is_trading_hours = (datetime.time(9, 0) <= now_t <= datetime.time(13, 35))
                if is_trading_hours and len(df) >= 2:
                    latest = df.iloc[-2]
                else:
                    latest = df.iloc[-1]

                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])

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
                    right_trigger = high
                    sl_p = right_trigger * (1 - stop_loss_pct / 100)
                    be_p = right_trigger * (1 + be_threshold / 100)
                    tp_p = right_trigger * (1 + take_profit_pct / 100)
                    
                    triggered_list.append({
                        "股票標的": label,
                        "最新收盤": f"${close:,.1f}",
                        "回踩均線": support_name,
                        "🎯 明日確認進場價": f"突破 ${right_trigger:,.1f}",
                        f"硬停損 (-{stop_loss_pct}%)": f"${sl_p:,.1f}",
                        f"動態保本啟動 (+{be_threshold}%)": f"${be_p:,.1f}",
                        f"階段一停利 (+{take_profit_pct}%)": f"${tp_p:,.1f}",
                        "成交量": f"{int(vol):,d}"
                    })
                else:
                    reasons = []
                    if not cond_trend: reasons.append("均線非多頭")
                    if not cond_support: reasons.append("未回踩支撐")
                    if not cond_vol: reasons.append("未達量縮")
                    if not cond_k: reasons.append(f"實體 > {k_body_limit}%")
                    waiting_list.append({"股票標的": label, "最新收盤": f"${close:,.1f}", "未符合原因": "、".join(reasons)})
            except Exception: pass
            progress_bar.progress((idx + 1) / total_items)

        progress_text.empty()
        progress_bar.empty()

        if triggered_list:
            st.success(f"🎯 **自選股中今日共發現 {len(triggered_list)} 檔符合深蹲條件！**")
            st.dataframe(pd.DataFrame(triggered_list), use_container_width=True, hide_index=True)
        else:
            st.warning(" 今日自選股中無標的符合深蹲條件。")

        if waiting_list:
            with st.expander("👀 檢視其餘觀察中股票狀態", expanded=False):
                st.dataframe(pd.DataFrame(waiting_list), use_container_width=True, hide_index=True)

# ================= TAB 3: 個股深入技術體檢 =================
with tab_single:
    st.subheader("🔍 個股深入技術診斷與 SOP 價位計算")
    options_list = list(st.session_state.watchlist.keys()) + ["✏️ 臨時手動輸入其他代號"]
    selected_option = st.selectbox("選擇診斷標的：", options=options_list, index=0)
    
    if selected_option == "✏️ 臨時手動輸入其他代號":
        c1, c2 = st.columns([2, 1])
        with c1: custom_code = st.text_input("輸入 4 位數代號", value="2368")
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
                df['VOL_MA5'] = df['Volume'].rolling(5).mean()
                df['VOL_MA20'] = df['Volume'].rolling(20).mean()

                now_t = datetime.datetime.now().time()
                is_trading_hours = (datetime.time(9, 0) <= now_t <= datetime.time(13, 35))
                if is_trading_hours and len(df) >= 2:
                    latest = df.iloc[-2]
                else:
                    latest = df.iloc[-1]

                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])

                target_ma = ma10 if "10MA" in target_ma_choice else ma20
                buf = 1 + (buffer_pct / 100)
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * buf) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit
                is_ready = cond_trend and cond_support and cond_vol and cond_k

                c_out1, c_out2, c_out3 = st.columns(3)
                c_out1.metric("診斷收盤基準", f"${close:,.1f}")
                c_out2.metric(f"防守 {target_ma_choice}", f"${target_ma:,.1f}")
                c_out3.metric("成交量", f"{int(vol):,d}")

                if is_ready:
                    sl_p = high * (1 - stop_loss_pct / 100)
                    be_p = high * (1 + be_threshold / 100)
                    tp_p = high * (1 + take_profit_pct / 100)
                    st.success(f"🎯 **【{display_title} 觸發訊號】：符合深蹲進場門檻！**")
                    st.markdown(f"""
                    * 🎯 **明日右側確認進場價**：`盤中突破今日高點 ${high:,.1f} 才可掛單`
                    * 🛑 **硬停損價 (-{stop_loss_pct}%)**：`${sl_p:,.1f}`
                    * 🛡️ **動態保本啟動點 (+{be_threshold}%)**：`達 ${be_p:,.1f} 後，停損拉至成本`
                    * 🏆 **階段一停利 (+{take_profit_pct}%)**：`${tp_p:,.1f}`（出脫 50%）
                    """)
                else:
                    st.info(f"⏸ **【{display_title} 維持觀望】：尚未滿足全部條件**")

                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df.index[-60:], open=df['Open'][-60:], high=df['High'][-60:],
                                             low=df['Low'][-60:], close=df['Close'][-60:], name="K線"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA5'][-60:], line=dict(color='orange', width=1), name="5MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA10'][-60:], line=dict(color='blue', width=1.5), name="10MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA20'][-60:], line=dict(color='purple', width=2), name="20MA"))
                fig.update_layout(xaxis_rangeslider_visible=False, height=420, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

# ================= TAB 4: 策略手冊與 SOP 指南 (原生卡片架構，絕不溢出) =================
with tab_docs:
    st.subheader("📖 短線成長股・量縮深蹲 (Squat & Rebound) 全流程作戰手冊 V2.0")
    st.info("💡 本系統專為「不盯盤、每日 16:30 離線決策、次日開盤智慧單自動執行」設計，具備標準作業程序（SOP）。")

    with st.expander("🔍 一、 盤後全自動獵股漏斗 SOP（3 → 1 → 2 順序過濾）", expanded=True):
        st.write("• **步驟 3【籌碼鎖定度與階梯門檻】**：最新日投信買超 >= 50 張；若股本在 60 億~150 億，門檻提高至 >= 250 張。")
        st.write("• **步驟 1【放寬股本規模 (20億 ~ 150億)】**：鎖定 20~60 億中型成長股與 60~150 億旗艦領頭羊（如欣興、技嘉），排除 > 150 億權值牛皮股。")
        st.write("• **步驟 2【業績加速動能】**：最新公告單月營收年增率 YoY > 20%，具實質基本面保護。")

    with st.expander("🧘 二、 盤後「量縮深蹲 (Squat)」技術面檢驗 SOP", expanded=True):
        st.write("• **條件 1【均線多頭排列】**：收盤價位於多頭排列（5MA > 10MA > 20MA），且 20 日均線（月線）斜率向上。")
        st.write("• **條件 2【均線精確回踩】**：最低價回測 10MA 或 20MA 緩衝區（Low <= MA * 1.018），收盤未跌破（Close >= MA * 0.99）。")
        st.write("• **條件 3【極致成交窒息量】**：當日成交量同時低於 5 日均量（5MV）與 20 日均量（20MV），代表浮額洗淨。")
        st.write("• **條件 4【K 棒實體收斂】**：當日 K 棒實體振幅 <= 3.5%，禁止長黑實體。")

    with st.expander("🏹 三、 盤中「右側確認」掛單進場 SOP", expanded=True):
        st.write("• **大盤多頭濾網**：加權指數收盤必須站穩 20MA（月線）之上。若大盤處於月線反壓，全市場雷達強制休眠。")
        st.write("• **次日右側過高確認**：訊號成立次日，盤中最高價突破深蹲日最高點才准掛單進場；未突破則一律放棄建倉。")

    with st.expander("🛑 四、 嚴格五大出場紀律 SOP", expanded=True):
        st.write("• **🛑 防線 1【硬停損線 (-4.0%)】**：跌破成本價之 -4.0%，無條件市價全數砍單。")
        st.write("• **⏳ 防線 2【時間停損 (4天)】**：持有滿 4 天漲幅未達 +3%，第 5 天開盤平手換股。")
        st.write("• **🛡️ 防線 3【動態保本機制 (+4.0%)】**：盤中浮盈達 +4.0% 時，次日起停損防線調升至成本價 (+0.2%)，消滅賺變賠。")
        st.write("• **🎯 防線 4【第一階段停利 (+8.0%)】**：觸及成本價 +8.0% 時，掛單賣出部位 A（50% 股數）鎖住勝果。")
        st.write("• **🏄 防線 5【第二階段波段落袋 (破 10MA)】**：剩餘部位 B 只要收盤跌破 10MA，次日開盤市價出清。")
        st.write("• **❄️ 防線 6【停損冷卻機制】**：若觸發硬停損，7～10 個交易日內禁止重複買進同一檔股票。")

    with st.expander("💼 五、 60 萬元資金與部位管理模型 SOP", expanded=True):
        st.write("• **三槽位配置**：總資金 60 萬元切分為 3 槽位，每槽上限 20 萬元。單筆極限虧損鎖死在總資金之 1.33%。")
        st.write("• **回撤熔斷機制**：歷程回撤超 -10% 時，槽位下單預算降為 14 萬元（7 折），防禦至淨值回升至 95% 以上。")
