import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# 頁面配置
st.set_page_config(page_title="短線成長股決策助手", page_icon="📈", layout="centered")

st.title("📈 短線成長股・量縮深蹲指示器")
st.caption("台股盤後專用｜均線多頭・回測支撐・成交量窒息診斷")

# 輸入區塊
col_input1, col_input2 = st.columns([2, 1])
with col_input1:
    ticker_num = st.text_input("輸入台股代號（如：2330、2454、3037）", value="2330")
with col_input2:
    market_type = st.selectbox("市場類別", ["上市 (.TW)", "上櫃 (.TWO)"], index=0)

suffix = ".TW" if "上市" in market_type else ".TWO"
full_ticker = f"{ticker_num.strip()}{suffix}"

target_ma_choice = st.radio("回測防守目標線", ["10MA", "20MA (月線)"], horizontal=True)

if st.button("🔍 開始技術體檢", type="primary", use_container_width=True):
    with st.spinner(f"正在分析 {full_ticker} 近半年日 K 線與成交量..."):
        try:
            df = yf.download(full_ticker, period="6mo", interval="1d", progress=False)
            
            if df.empty or len(df) < 30:
                st.error("⚠️ 找不到該股票資料，請檢查代號是否正確，或切換「上市/上櫃」重試。")
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
                prev = df.iloc[-2]
                
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
                
                # 策略規則檢查
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * 1.012) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
                cond_k = abs(close - open_p) / open_p <= 0.03
                
                is_ready = cond_trend and cond_support and cond_vol and cond_k
                
                # 數據摘要
                st.write("---")
                c1, c2, c3 = st.columns(3)
                c1.metric("最新收盤價", f"${close:,.1f}")
                c2.metric("目標防守線", f"${target_ma:,.1f}")
                c3.metric("當日成交量", f"{int(vol):,d}")
                
                # 決策結果
                if is_ready:
                    sl_price = target_ma * 0.96
                    tp_price = close * 1.08
                    st.success("🎯 **【符合進場訊號】：量縮深蹲成型！**")
                    st.markdown(f"""
                    * **建議進場區間**：`\({target_ma:,.1f} ～\){close:,.1f}`
                    * **硬停損價 (-4%)**：`${sl_price:,.1f}`（收盤跌破立刻離場）
                    * **第一階段停利 (+8%)**：`${tp_price:,.1f}`（達標出脫 50%）
                    """)
                else:
                    st.info("⏸ **【暫無訊號】：目前維持觀望**")
                    st.markdown(f"""
                    * 均線多頭排列：{'✅ 符合' if cond_trend else '❌ 未成多頭'}
                    * 回測 {target_ma_choice} 支撐：{'✅ 有踩到且收上' if cond_support else '❌ 未達或已跌破'}
                    * 成交量窒息量縮：{'✅ 萎縮' if cond_vol else '❌ 尚未量縮'}
                    * K 線小實體非長黑：{'✅ 健康' if cond_k else '❌ 波動過大'}
                    """)
                
                # 互動 K 線圖
                st.subheader("📊 近期走勢與均線")
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
