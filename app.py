import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import json
import os
import time

# 頁面配置
st.set_page_config(page_title="短線成長股決策助手", page_icon="📈", layout="wide")

WATCHLIST_FILE = "watchlist.json"

DEFAULT_STOCKS = {
    "台積電 (2330)": "2330.TW",
    "聯發科 (2454)": "2454.TW",
    "欣興 (3037)": "3037.TW",
    "奇鋐 (3017)": "3017.TW",
    "雙鴻 (3324)": "3324.TWO",
    "台燿 (6274)": "6274.TWO",
    "保瑞 (6472)": "6472.TWO",
    "世芯-KY (3661)": "3661.TW"
}

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        save_watchlist(DEFAULT_STOCKS)
        return DEFAULT_STOCKS.copy()
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_STOCKS.copy()

def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# ================= 側邊欄：參數設定與名單管理 =================
with st.sidebar:
    st.header("🎛️ 策略參數動態微調")
    with st.expander("⚙️ 調整進出場判定數值", expanded=True):
        buffer_pct = st.slider("均線回測容許緩衝 (%)", 0.5, 3.0, 1.2, 0.1, help="價格下探至均線的容許誤差範圍")
        k_body_limit = st.slider("K棒實體最大振幅 (%)", 1.0, 5.0, 2.5, 0.5, help="過濾大實體黑棒，只留小碎步洗盤")
        vol_mode = st.radio("成交量萎縮標準", ["嚴格（低於 5MV 且 20MV）", "標準（低於 5MV 或 20MV）"], index=0)
        stop_loss_pct = st.slider("硬停損比例 (-%)", 2.0, 8.0, 4.0, 0.5)
        take_profit_pct = st.slider("第一階段停利目標 (+%)", 5.0, 15.0, 8.0, 0.5)

    st.divider()
    st.header("📋 觀察清單管理")
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
            else:
                st.warning("請填寫完整的名稱與代號！")

    with st.expander("🗑️ 刪除自選股票", expanded=False):
        if st.session_state.watchlist:
            del_target = st.selectbox("選擇要移除的標的", options=list(st.session_state.watchlist.keys()))
            if st.button("確認刪除", use_container_width=True):
                del st.session_state.watchlist[del_target]
                save_watchlist(st.session_state.watchlist)
                st.success(f"已移除：{del_target}")
                st.rerun()
        else:
            st.info("目前清單為空。")

    if st.button("🔄 恢復初始預設名單", use_container_width=True):
        st.session_state.watchlist = DEFAULT_STOCKS.copy()
        save_watchlist(st.session_state.watchlist)
        st.success("已重設回預設名單！")
        st.rerun()

st.title("📈 短線成長股・量縮深蹲指示器")
st.caption(f"動態設定中：停損 -{stop_loss_pct}% ｜ 停利 +{take_profit_pct}% ｜ K棒上限 {k_body_limit}%")

# 主頁面三大功能分頁
tab_batch, tab_single, tab_docs = st.tabs([
    "🚀 一鍵全清單自動掃描", 
    "🔍 個股深入技術體檢", 
    "📖 策略手冊與 SOP 指南"
])

# ================= TAB 1: 一鍵批次全掃描 =================
with tab_batch:
    st.subheader("📋 自選股今日深蹲訊號掃描")
    st.write(f"目前清單待檢驗數量：**{len(st.session_state.watchlist)}** 檔")
    
    scan_btn = st.button("⚡ 開始套用自訂參數掃描全部自選股", type="primary", use_container_width=True)
    
    if scan_btn:
        progress_text = st.empty()
        progress_bar = st.progress(0)
        
        triggered_list = []
        waiting_list = []
        
        items = list(st.session_state.watchlist.items())
        total_items = len(items)
        
        for idx, (label, ticker) in enumerate(items):
            progress_text.text(f"正在分析第 {idx + 1}/{total_items} 檔：{label} ...")
            try:
                df = yf.download(ticker, period="6mo", interval="1d", progress=False)
                if df.empty or len(df) < 30:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

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

                # 動態條件判定
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                
                buf = 1 + (buffer_pct / 100)
                touch_10 = (low <= ma10 * buf) and (close >= ma10 * 0.99)
                touch_20 = (low <= ma20 * buf) and (close >= ma20 * 0.99)
                cond_support = touch_10 or touch_20
                
                if "嚴格" in vol_mode:
                    cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
                else:
                    cond_vol = (vol < vol_ma5) or (vol < vol_ma20)
                    
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit

                support_name = "10MA" if touch_10 else ("20MA" if touch_20 else "未回踩")
                target_ma = ma10 if touch_10 else ma20

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
                    if not cond_support: reasons.append(f"未達 {buffer_pct}% 緩衝回踩")
                    if not cond_vol: reasons.append("成交量未達萎縮")
                    if not cond_k: reasons.append(f"K棒實體 > {k_body_limit}%")
                    
                    waiting_list.append({
                        "股票標的": label,
                        "最新收盤": f"${close:,.1f}",
                        "10MA": f"${ma10:,.1f}",
                        "20MA": f"${ma20:,.1f}",
                        "未符合原因": "、".join(reasons)
                    })

            except Exception:
                pass
            
            progress_bar.progress((idx + 1) / total_items)

        progress_text.text(" 掃描完成！")
        time.sleep(0.5)
        progress_text.empty()
        progress_bar.empty()

        if triggered_list:
            st.success(f"🎯 **今日共發現 {len(triggered_list)} 檔符合「量縮深蹲」進場門檻！**")
            st.dataframe(pd.DataFrame(triggered_list), use_container_width=True, hide_index=True)
        else:
            st.warning(" 今日自選股中無標的符合設定之條件，建議維持空手觀望。")

        if waiting_list:
            with st.expander("👀 查看其餘觀察中股票狀態（未符合原因清單）", expanded=True):
                st.dataframe(pd.DataFrame(waiting_list), use_container_width=True, hide_index=True)

# ================= TAB 2: 單一個股詳細技術體檢 =================
with tab_single:
    st.subheader("🔍 個股深入技術診斷與 K 線走勢")
    options_list = list(st.session_state.watchlist.keys()) + ["✏️ 臨時手動輸入其他代號"]
    selected_option = st.selectbox("選擇診斷標的：", options=options_list, index=0)
    
    if selected_option == "✏️ 臨時手動輸入其他代號":
        c1, c2 = st.columns([2, 1])
        with c1: custom_code = st.text_input("輸入 4 位數代號", value="2308")
        with c2: market_suffix = st.selectbox("市場別", [".TW (上市)", ".TWO (上櫃)"], index=0)
        suffix = ".TW" if "上市" in market_suffix else ".TWO"
        full_ticker = f"{custom_code.strip()}{suffix}"
        display_title = f"自訂標的 ({full_ticker})"
    else:
        full_ticker = st.session_state.watchlist[selected_option]
        display_title = selected_option

    target_ma_choice = st.radio("指定防守均線基準", ["10MA", "20MA (月線)"], horizontal=True)

    if st.button("開始診斷該股", type="secondary", use_container_width=True):
        with st.spinner(f"正在分析 {display_title}..."):
            df = yf.download(full_ticker, period="6mo", interval="1d", progress=False)
            if df.empty or len(df) < 30:
                st.error(f"⚠️ 找不到 {full_ticker} 的歷史行情。")
            else:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

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

                target_ma = ma10 if "10MA" in target_ma_choice else ma20
                buf = 1 + (buffer_pct / 100)
                
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * buf) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit
                is_ready = cond_trend and cond_support and cond_vol and cond_k

                c_out1, c_out2, c_out3 = st.columns(3)
                c_out1.metric("最新收盤價", f"${close:,.1f}")
                c_out2.metric(f"防守 {target_ma_choice}", f"${target_ma:,.1f}")
                c_out3.metric("當日成交量", f"{int(vol):,d}")

                if is_ready:
                    sl_price = target_ma * (1 - stop_loss_pct / 100)
                    tp_price = close * (1 + take_profit_pct / 100)
                    st.success(f"🎯 **【{display_title} 觸發訊號】：符合深蹲進場門檻！**")
                    st.write(f"• **建議掛單區間**：`\({target_ma:,.1f} ~\){close:,.1f}`")
                    st.write(f"• **硬停損價 (-{stop_loss_pct}%)**：`${sl_price:,.1f}`")
                    st.write(f"• **第一階段停利 (+{take_profit_pct}%)**：`${tp_price:,.1f}`（出脫 50% 部位）")
                else:
                    st.info(f"⏸ **【{display_title} 維持觀望】：尚未滿足全部條件**")
                    st.markdown(f"""
                    * 均線多頭排列：{'✅ 符合' if cond_trend else '❌ 未成多頭'}
                    * 回踩 {target_ma_choice}（緩衝 {buffer_pct}%）：{'✅ 有踩到且收上' if cond_support else '❌ 未達或已跌破'}
                    * 成交量窒息量縮：{'✅ 符合萎縮' if cond_vol else '❌ 尚未量縮'}
                    * K 棒實體振幅 \(\le\) {k_body_limit}%：{'✅ 健康小實體' if cond_k else '❌ 波動過大或長黑'}
                    """)

                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=df.index[-60:], open=df['Open'][-60:], high=df['High'][-60:],
                    low=df['Low'][-60:], close=df['Close'][-60:], name="K線"
                ))
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
