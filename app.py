import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import json
import os

# 頁面配置
st.set_page_config(page_title="短線成長股決策助手", page_icon="📈", layout="centered")

st.title("📈 短線成長股・量縮深蹲指示器")
st.caption("台股盤後專用｜均線多頭・回測支撐・成交量窒息診斷")

# ================= 1. 自選股 JSON 讀取與儲存機制 =================
WATCHLIST_FILE = "watchlist.json"

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
        save_watchlist(DEFAULT_STOCKS)
        return DEFAULT_STOCKS
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_STOCKS

def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

watchlist = load_watchlist()

# ================= 2. 網頁端自選股管理介面 (Expander) =================
with st.expander("⚙️ 點此展開：管理 / 增減自選股清單"):
    tab_add, tab_del = st.tabs(["➕ 新增股票", "🗑️ 刪除股票"])
    
    with tab_add:
        c_name, c_code, c_mkt = st.columns([2, 1, 1])
        with c_name:
            new_name = st.text_input("股票簡稱", placeholder="例如：鴻海")
        with c_code:
            new_code = st.text_input("4 碼代號", placeholder="例如：2317")
        with c_mkt:
            new_mkt = st.selectbox("市場類別", ["上市 (.TW)", "上櫃 (.TWO)"])
            
        if st.button("確認新增至觀察清單", type="primary"):
            if new_name.strip() and new_code.strip():
                suffix = ".TW" if "上市" in new_mkt else ".TWO"
                label = f"{new_name.strip()} ({new_code.strip()})"
                full_sym = f"{new_code.strip()}{suffix}"
                
                watchlist[label] = full_sym
                save_watchlist(watchlist)
                st.success(f"✅ 已成功將【{label}】加入自選清單！")
                st.rerun()
            else:
                st.warning("⚠️ 請完整填寫股票名稱與代號。")
                
    with tab_del:
        if watchlist:
            stock_to_del = st.selectbox("選擇要移除的股票：", options=list(watchlist.keys()))
            if st.button("確認刪除該標的", type="secondary"):
                del watchlist[stock_to_del]
                save_watchlist(watchlist)
                st.success(f"🗑️ 已將【{stock_to_del}】自觀察清單移除！")
                st.rerun()
        else:
            st.info("目前自選清單為空。")

st.write("---")

# ================= 3. 標的選取區 =================
options_list = list(watchlist.keys()) + ["✏️ 自訂輸入其他代號"]
selected_option = st.selectbox("選擇觀察標的：", options=options_list, index=0)

if selected_option == "✏️ 自訂輸入其他代號":
    col1, col2 = st.columns([2, 1])
    with col1:
        custom_code = st.text_input("輸入 4 位數代號", value="2308")
    with col2:
        market_suffix = st.selectbox("市場別", [".TW (上市)", ".TWO (上櫃)"], index=0)
    suffix = ".TW" if "上市" in market_suffix else ".TWO"
    full_ticker = f"{custom_code.strip()}{suffix}"
    display_title = f"自訂代號 ({full_ticker})"
else:
    full_ticker = watchlist[selected_option]
    display_title = selected_option

target_ma_choice = st.radio("回測防守目標線", ["10MA", "20MA (月線)"], horizontal=True)

# ================= 4. 技術診斷與繪圖 =================
if st.button("🔍 開始技術體檢", type="primary", use_container_width=True):
    with st.spinner(f"正在分析 {display_title} 近半年日 K 線與成交量..."):
        try:
            df = yf.download(full_ticker, period="6mo", interval="1d", progress=False)
            
            if df.empty or len(df) < 30:
                st.error(f"⚠️ 找不到 {full_ticker} 的歷史行情，請檢查代號是否正確。")
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
                high = float(latest['High'])
                
                ma5 = float(latest['MA5'])
                ma10 = float(latest['MA10'])
                ma20 = float(latest['MA20'])
                vol_ma5 = float(latest['VOL_MA5'])
                vol_ma20 = float(latest['VOL_MA20'])
                
                target_ma = ma10 if "10MA" in target_ma_choice else ma20
                
                # 策略條件
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * 1.012) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
                cond_k = abs(close - open_p) / open_p <= 0.03
                
                is_ready = cond_trend and cond_support and cond_vol and cond_k
                
                st.write("---")
                c1, c2, c3 = st.columns(3)
                c1.metric("最新收盤價", f"${close:,.1f}")
                c2.metric("目標防守均線", f"${target_ma:,.1f}")
                c3.metric("當日成交量", f"{int(vol):,d}")
                
                if is_ready:
                    sl_price = target_ma * 0.96
                    tp_price = close * 1.08
                    st.success(f"🎯 **【{display_title} 觸發訊號】：符合「量縮深蹲」進場門檻！**")
                    st.markdown(f"""
                    * **建議掛單區間**：`${target_ma:,.1f} ～ ${close:,.1f}`
                    * **硬停損價 (-4%)**：`${sl_price:,.1f}`（收盤跌破立刻撤退）
                    * **第一階段停利 (+8%)**：`${tp_price:,.1f}`（出脫 50% 部位）
                    """)
                else:
                    st.info(f"⏸ **【{display_title} 維持觀望】：尚未滿足全部深蹲條件**")
                    st.markdown(f"""
                    * 均線多頭排列：{'✅ 符合' if cond_trend else '❌ 未成多頭'}
                    * 回測 {target_ma_choice} 支撐：{'✅ 有踩到且收上' if cond_support else '❌ 未達或已跌破'}
                    * 成交量窒息量縮：{'✅ 萎縮' if cond_vol else '❌ 尚未量縮'}
                    * K 線小實體非長黑：{'✅ 健康' if cond_k else '❌ 波動過大'}
                    """)
                
                st.subheader(f"📊 {display_title} 近期走勢與均線")
                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=df.index[-60:], open=df['Open'][-60:], high=df['High'][-60:],
                    low=df['Low'][-60:], close=df['Close'][-60:], name="K線"
                ))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA5'][-60:], line=dict(color='orange', width=1), name="5MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA10'][-60:], line=dict(color='blue', width=1.5), name="10MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA20'][-60:], line=dict(color='purple', width=2), name="20MA"))
                fig.update_layout(xaxis_rangeslider_visible=False, height=400, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
                
        except Exception as e:
            st.error(f"運算異常: {e}")
