import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# 頁面配置
st.set_page_config(page_title="短線成長股決策助手", page_icon="📈", layout="centered")

st.title("📈 短線成長股・量縮深蹲指示器")
st.caption("台股盤後專用｜均線多頭・回測支撐・成交量窒息診斷")

# ================= 1. 預設自選成長股清單 =================
# 你可以自由修改中文名稱、代號，上市請加 .TW，上櫃請加 .TWO
DEFAULT_WATCHLIST = {
    "台積電 (2330)": "2330.TW",
    "聯發科 (2454)": "2454.TW",
    "欣興 (3037)": "3037.TW",
    "奇鋐 (3017)": "3017.TW",
    "雙鴻 (3324)": "3324.TWO",
    "台燿 (6274)": "6274.TWO",
    "世芯-KY (3661)": "3661.TW",
    "智邦 (2345)": "2345.TW",
    "✏️ 自訂輸入其他代號": "CUSTOM"
}

# ================= 2. 側邊或主畫面選擇區 =================
selected_option = st.selectbox(
    "選擇自選觀察股（或切換手動輸入）：",
    options=list(DEFAULT_WATCHLIST.keys()),
    index=0
)

# 依選擇決定要抓取的代號
if selected_option == "✏️ 自訂輸入其他代號":
    col1, col2 = st.columns([2, 1])
    with col1:
        custom_code = st.text_input("輸入 4 位數股票代號", value="2308")
    with col2:
        market_suffix = st.selectbox("市場別", [".TW (上市)", ".TWO (上櫃)"], index=0)
    suffix = ".TW" if "上市" in market_suffix else ".TWO"
    full_ticker = f"{custom_code.strip()}{suffix}"
    display_title = f"自訂代號 ({full_ticker})"
else:
    full_ticker = DEFAULT_WATCHLIST[selected_option]
    display_title = selected_option

target_ma_choice = st.radio("回測防守目標線", ["10MA", "20MA (月線)"], horizontal=True)

# ================= 3. 診斷與圖表運算 =================
if st.button("🔍 開始技術體檢", type="primary", use_container_width=True):
    with st.spinner(f"正在分析 {display_title} 近半年日 K 線與成交量..."):
        try:
            df = yf.download(full_ticker, period="6mo", interval="1d", progress=False)
            
            if df.empty or len(df) < 30:
                st.error(f"⚠️ 找不到 {full_ticker} 的歷史行情，請檢查代號是否正確。")
            else:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                    
                # 計算技術均線與均量
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
                
                # 四大條件檢驗
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * 1.012) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
                cond_k = abs(close - open_p) / open_p <= 0.03
                
                is_ready = cond_trend and cond_support and cond_vol and cond_k
                
                # 輸出數據摘要卡
                st.write("---")
                c1, c2, c3 = st.columns(3)
                c1.metric("最新收盤價", f"${close:,.1f}")
                c2.metric("目標防守均線", f"${target_ma:,.1f}")
                c3.metric("當日成交量", f"{int(vol):,d}")
                
                # 決策判斷提示
                if is_ready:
                    sl_price = target_ma * 0.96
                    tp_price = close * 1.08
                    st.success(f"🎯 **【{display_title} 觸發訊號】：符合「量縮深蹲」進場門檻！**")
                    st.markdown(f"""
                    * **建議掛單區間**：`\({target_ma:,.1f} ～\){close:,.1f}`
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
                
                # 互動 K 線圖表
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
