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
import importlib

st.set_page_config(page_title="短線成長股決策助手 V2.5", page_icon="📈", layout="wide")

WATCHLIST_FILE = "watchlist.json"
REPORT_FILE = "radar_report.json"
POSITIONS_FILE = "positions.json"
HISTORY_FILE = "trade_history.csv"
PENDING_FILE = "pending_orders.json"

FEE_RATE = 0.001425 * 0.5
TAX_RATE = 0.003

DEFAULT_STOCKS = {
    "台積電 (2330)": "2330.TW", "聯發科 (2454)": "2454.TW",
    "欣興 (3037)": "3037.TW", "奇鋐 (3017)": "3017.TW",
    "雙鴻 (3324)": "3324.TWO", "台燿 (6274)": "6274.TWO",
    "智邦 (2345)": "2345.TW", "金像電 (2368)": "2368.TW",
    "致伸 (4915)": "4915.TW", "系統電 (5309)": "5309.TWO"
}

TW_INDUSTRY_MAP = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學生技", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "13": "電子工業", "14": "建材營造", "15": "航運業", "16": "觀光餐旅",
    "17": "金融保險業", "18": "貿易百貨業", "19": "綜合", "20": "其他業",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業",
    "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業",
    "33": "農業科技業", "34": "電子商務業", "35": "綠能環保", "36": "數位雲端",
    "37": "運動休閒", "38": "居家生活"
}

def translate_industry(ind_raw):
    raw_str = str(ind_raw).strip()
    if raw_str in TW_INDUSTRY_MAP:
        return TW_INDUSTRY_MAP[raw_str]
    for code, name in TW_INDUSTRY_MAP.items():
        if code in raw_str:
            return name
    return raw_str if raw_str and raw_str not in ["None", "nan", ""] else "電子科技"

def load_json(filepath, default):
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def push_file_to_github(filepath, content_bytes):
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
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
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
            payload = {
                "message": f"🤖 [Streamlit] 使用者反向更新 {filepath}",
                "content": content_b64
            }
            if sha:
                payload["sha"] = sha
            requests.put(url, headers=headers, json=payload)
        except Exception as e:
            print(f"⚠️ 反向更新 {filepath} 異常: {e}")

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    push_file_to_github(filepath, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

def save_history_csv(df):
    df.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    with open(HISTORY_FILE, "rb") as f:
        push_file_to_github(HISTORY_FILE, f.read())

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

@st.cache_data(ttl=86400)
def get_all_taiwan_stocks():
    stocks = {
        "5309": {"code": "5309", "name": "系統電", "market": ".TWO", "market_name": "上櫃", "industry": "電腦及週邊設備業", "cap": 19.5},
        "3324": {"code": "3324", "name": "雙鴻", "market": ".TWO", "market_name": "上櫃", "industry": "電腦及週邊設備業", "cap": 8.8},
        "6274": {"code": "6274", "name": "台燿", "market": ".TWO", "market_name": "上櫃", "industry": "電子零組件業", "cap": 27.2},
        "8069": {"code": "8069", "name": "元太", "market": ".TWO", "market_name": "上櫃", "industry": "光電業", "cap": 114.5},
        "2330": {"code": "2330", "name": "台積電", "market": ".TW", "market_name": "上市", "industry": "半導體業", "cap": 2593.2},
        "2454": {"code": "2454", "name": "聯發科", "market": ".TW", "market_name": "上市", "industry": "半導體業", "cap": 160.2},
        "3037": {"code": "3037", "name": "欣興", "market": ".TW", "market_name": "上市", "industry": "電子零組件業", "cap": 153.0},
        "3017": {"code": "3017", "name": "奇鋐", "market": ".TW", "market_name": "上市", "industry": "電腦及週邊設備業", "cap": 38.8},
        "2345": {"code": "2345", "name": "智邦", "market": ".TW", "market_name": "上市", "industry": "通信網路業", "cap": 56.4},
        "2368": {"code": "2368", "name": "金像電", "market": ".TW", "market_name": "上市", "industry": "電子零組件業", "cap": 49.3},
        "4915": {"code": "4915", "name": "致伸", "market": ".TW", "market_name": "上市", "industry": "電子零組件業", "cap": 45.6}
    }
    try:
        url_l = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        res_l = requests.get(url_l, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if res_l.status_code == 200:
            for item in res_l.json():
                c = item.get("公司代號", "").strip()
                n = item.get("公司簡稱", "").strip() or item.get("公司名稱", "").strip()
                ind_raw = item.get("產業別", "")
                cap_s = float(item.get("實收資本額", 0)) / 100_000_000
                if c and n:
                    stocks[c] = {"code": c, "name": n, "market": ".TW", "market_name": "上市", "industry": translate_industry(ind_raw), "cap": round(cap_s, 1)}
    except Exception: pass

    try:
        url_o = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
        res_o = requests.get(url_o, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if res_o.status_code == 200:
            for item in res_o.json():
                c = str(item.get("SecuritiesCompanyCode", "")).strip() or str(item.get("公司代號", "")).strip()
                n = str(item.get("CompanyBriefName", "")).strip() or str(item.get("公司簡稱", "")).strip()
                ind_raw = str(item.get("SectorName", "")).strip() or str(item.get("產業別", "")).strip()
                cap_raw = float(item.get("PaidInCapital", 0) or item.get("實收資本額", 0))
                cap_s = cap_raw / 100_000_000
                if c and n:
                    stocks[c] = {"code": c, "name": n, "market": ".TWO", "market_name": "上櫃", "industry": translate_industry(ind_raw), "cap": round(cap_s, 1)}
    except Exception: pass
    return stocks

def resolve_taiwan_stock(query):
    q = query.strip()
    if not q: return None, "請輸入欲搜尋的股票名稱或代號！"
    universe = get_all_taiwan_stocks()
    if q in universe: return universe[q], None
    for c, s in universe.items():
        if s['name'] == q: return s, None
    candidates = [s for s in universe.values() if (q in s['name']) or (q == s['code'])]
    if len(candidates) == 1: return candidates[0], None
    elif len(candidates) > 1:
        cand_str = "、".join([f"{c['name']} ({c['code']})" for c in candidates[:4]])
        return None, f"找到多檔符合標的：{cand_str}，請輸入更精確的名稱或代號！"
    if q.isdigit() or (len(q) >= 4 and q[:4].isdigit()):
        for sfx, m_name in [(".TW", "上市"), (".TWO", "上櫃")]:
            try:
                t = yf.Ticker(f"{q}{sfx}")
                h = t.history(period="5d")
                if not h.empty:
                    s_name = t.info.get("shortName") or q
                    shares = t.fast_info.get("shares") or 0
                    calc_cap = round((shares * 10) / 100_000_000, 1) if shares else 0.0
                    return {"code": q, "name": s_name, "market": sfx, "market_name": m_name, "industry": "電子科技", "cap": calc_cap}, None
            except Exception: pass
    return None, f"查無台股標的「{q}」，請確認名稱是否正確！"

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
    with st.expander("➕ 新增自選股票 (智慧辨識)", expanded=False):
        sb_query = st.text_input("輸入名稱或代號", placeholder="例如：系統電 或 5309", key="sb_smart_in")
        if st.button("確認加入清單", type="primary", use_container_width=True, key="sb_btn_add"):
            stock_info, err = resolve_taiwan_stock(sb_query)
            if stock_info:
                label = f"{stock_info['name']} ({stock_info['code']})"
                st.session_state.watchlist[label] = f"{stock_info['code']}{stock_info['market']}"
                save_json(WATCHLIST_FILE, st.session_state.watchlist)
                st.success(f"✅ 成功加入：{label} ({stock_info['market_name']})")
                st.rerun()
            else:
                st.error(err)

    with st.expander("🗑️ 刪除自選股票", expanded=False):
        if st.session_state.watchlist:
            del_target = st.selectbox("選擇要移除的標的", options=list(st.session_state.watchlist.keys()), key="sb_del_target")
            if st.button("確認刪除", use_container_width=True, key="sb_btn_del"):
                del st.session_state.watchlist[del_target]
                save_json(WATCHLIST_FILE, st.session_state.watchlist)
                st.success(f"已移除：{del_target}")
                st.rerun()

    if st.button("🔄 恢復初始預設名單", use_container_width=True):
        st.session_state.watchlist = DEFAULT_STOCKS.copy()
        save_json(WATCHLIST_FILE, st.session_state.watchlist)
        st.success("已還原預設自選清單！")
        st.rerun()

st.title("📈 短線成長股・量縮深蹲指示器 V2.5 (三指標共振升級版)")
is_bull, twii_c, twii_ma = get_twii_market_status()
if is_bull:
    st.success(f"🟢 **大盤多頭健康**（加權指數：{twii_c:,.0f} 點 守於月線 {twii_ma:,.0f} 點之上）")
else:
    st.warning(f"🟡 **大盤月線反壓中**（加權指數：{twii_c:,.0f} 點 低於月線 {twii_ma:,.0f} 點），建議空手或將部位打折！")

tab_radar, tab_tracker, tab_batch, tab_single, tab_watchlist, tab_docs = st.tabs([
    "📡 今日雷達獵股戰報",
    "📊 實盤追蹤與績效帳本 (方案B)",
    "🚀 自選名單批次體檢", 
    "🔍 個股深入技術體檢", 
    "📋 自選股票清單總覽 (TAB 5)",
    "📖 策略手冊與 SOP 指南 V2.5"
])

# ================= TAB 0: 每日雷達戰報 =================
with tab_radar:
    c_title, c_scan = st.columns([3, 1.3])
    with c_title:
        st.subheader("📡 全自動獵股雷達・今日盤後戰報")
    with c_scan:
        btn_manual_scan = st.button("⚡ 手動立即掃描雷達", type="primary", use_container_width=True)

    if btn_manual_scan:
        with st.spinner("🚀 正在檢驗昨日突破建倉，並連線證交所產出今日雷達戰報... (約需 15~20 秒)"):
            try:
                import tracker
                import screener
                importlib.reload(tracker)
                importlib.reload(screener)

                tracker.run_tracker()
                screener.run_screener()

                new_rep = load_json(REPORT_FILE, {})
                if new_rep: save_json(REPORT_FILE, new_rep)

                new_pos = load_json(POSITIONS_FILE, [])
                if new_pos: save_json(POSITIONS_FILE, new_pos)

                if os.path.exists(HISTORY_FILE):
                    with open(HISTORY_FILE, "rb") as f:
                        push_file_to_github(HISTORY_FILE, f.read())

                st.success("✅ 昨日突破建倉結算與今日雷達掃描已完成，已同步至 GitHub！")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 手動掃描異常: {e}")

    st.write("---")
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
            st.success(f"🎯 **【今日焦點】：共發現 {len(squat_stocks)} 檔精準符合「量縮深蹲 ＋ RSI蓄勢」進場門檻！**")
            for s in squat_stocks:
                s_name = s.get('name', '')
                s_code = str(s.get('code', '')).split('.')[0].strip()
                right_trigger_p = s.get('right_trigger', s.get('high', s['close']))
                badge = s.get('grade_badge', '🟢 標準深蹲')
                
                with st.container():
                    c1, c2, c3, c4 = st.columns([2.3, 1.8, 1.9, 2.0])
                    c1.markdown(f"### **{s_name} ({s_code})**")
                    c1.markdown(f"**評級**：`{badge}`")
                    c1.caption(f"最新收盤：${s['close']} ｜ 支撐：**{s['support']}** ｜ 類股：{s.get('industry', '電子科技')}")
                    
                    c2.write(f"• **投信買超**：`+{s['trust_buy']}` 張")
                    c2.write(f"• **營收 YoY**：`+{s['rev_yoy']}%`")
                    c2.write(f"• **RSI (14)**：`{s.get('rsi', '-')}` (40~65蓄勢)")
                    
                    c3.write(f"• **KD 姿態**：`{s.get('kd_desc', '-')}`")
                    c3.write(f"• **MACD 動能**：`{s.get('macd_desc', '-')}`")
                    c3.write(f"• **🎯 明日確認進場**：`突破 ${right_trigger_p}`")
                    
                    label_key = f"{s_name} ({s_code})"
                    if label_key not in st.session_state.watchlist:
                        if c4.button(f"📥 加到自選名單", key=f"radar_add_{s_code}"):
                            st.session_state.watchlist[label_key] = s['ticker']
                            save_json(WATCHLIST_FILE, st.session_state.watchlist)
                            st.success(f"已將 {label_key} 加入觀察清單！")
                            st.rerun()
                    else:
                        c4.write("✅ 已在自選觀察清單中")
                        
                    yahoo_url = f"https://tw.stock.yahoo.com/quote/{s_code}/news"
                    google_url = f"https://www.google.com/search?q={s_name}+{s_code}+股票&tbm=nws&tbs=qdr:m"
                    cnyes_url = f"https://invest.cnyes.com/twstock/TWS/{s_code}/news"

                    with st.expander(f"📰 查看 {s_name} 近半個月新聞與產業速查", expanded=False):
                        n1, n2, n3 = st.columns(3)
                        n1.markdown(f"[📰 Yahoo 奇摩個股新聞]({yahoo_url})")
                        n2.markdown(f"[🔍 Google 財經近半月新聞]({google_url})")
                        n3.markdown(f"[📊 鉅亨網法人與重大訊息]({cnyes_url})")
                st.divider()
        else:
            st.info("⏸ 今日籌碼與基本面強勢股尚未剛好踩在均線深蹲點，建議維持觀望。")

# ================= TAB 1: 實盤追蹤與績效帳本 (支援自訂實際本金與股數) =================
with tab_tracker:
    st.subheader("📊 方案 B：前向實盤追蹤流水帳本 (Forward-Walk Paper Trading)")
    
    positions = load_json(POSITIONS_FILE, [])
    df_history = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame(columns=[
        "代號", "名稱", "進場日", "進場價", "出場日", "持股天數",
        "投入金額", "回收金額", "淨損益(NTD)", "部位A_損益%", "部位B_損益%",
        "綜合報酬率%", "出場原因"
    ])

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
    m5.metric("平均持股交易日", f"{avg_days:.1f} 天")
    st.divider()

    st.markdown("#### 🏦 【當前持倉部位即時監控・實戰下單指標】")
    if positions:
        pos_display = []
        for p in positions:
            entry_p = float(p['entry_price'])
            curr_p = float(p.get('curr_price', entry_p))
            unreal_pct = float(p.get('unrealized_pct', 0.0))
            days = p.get('days_held', 0)
            is_ext = p.get('is_extended', False)
            limit_days = 7 if is_ext else 4
            
            day_str = f"{days}/{limit_days}天 🔄已展延" if is_ext else f"{days}/{limit_days}天"
            
            if p.get('is_breakeven') and days >= 1:
                stop_display = f"🛡️ ${entry_p * 1.002:.1f} (保本線)"
            else:
                stop_display = f"🛑 ${entry_p * 0.96:.1f} (-4%)"
                
            if p.get('lot_a_sold'):
                tp1_display = "✅ 半倉已停利"
            else:
                tp1_display = f"🎯 ${entry_p * 1.08:.1f} (+8%)"
                
            ma10_val = p.get('ma10')
            ma10_display = f"🏄 ${ma10_val:.1f}" if ma10_val else "計算中"

            tot_shares = p.get('shares_a', 0) + p.get('shares_b', 0)
            tot_cost = int(p.get('total_invested', 0))

            pos_display.append({
                "標的": f"{p['name']} ({p['code']})",
                "進場日": p['entry_date'],
                "持有交易日進度": day_str,
                "進場成本": f"${entry_p:.1f}",
                "持有總股數": f"{tot_shares:,d} 股",
                "投入總本金": f"NT$ {tot_cost:,d}",
                "現價 (浮盈%)": f"${curr_p:.1f} ({unreal_pct:+.2f}%)",
                "🛑 當前防守停損": stop_display,
                "🎯 階段一停利": tp1_display,
                "🏄 移動停利 (10MA)": ma10_display,
                "持倉狀態": "半倉續抱守10MA" if p.get('lot_a_sold') else ("保本防護中" if p.get('is_breakeven') else "持倉中")
            })
        st.dataframe(pd.DataFrame(pos_display), use_container_width=True, hide_index=True)
    else:
        st.info("目前無在倉持股，現金池 100% 待命。")

    # 💡 核心功能 A：手動快速補登開倉（支援自訂股數與實際扣款成本）
    with st.expander("➕ 手動快速補登開倉（可自訂實際買進股數與投入金額）", expanded=True):
        st.info("💡 在此可直接輸入真實券商對帳單的實際買進價格、實際股數與扣款總額，損益計算將 100% 精準吻合！")
        c_add1, c_add2, c_add3 = st.columns(3)
        with c_add1:
            in_code = st.text_input("股票代號 (4碼)", value="2441", placeholder="例如：2441 或 3042", key="in_manual_code")
        with c_add2:
            in_buy_price = st.number_input("實際買進均價 (NTD)", value=127.5, step=0.1, key="in_manual_price")
        with c_add3:
            in_entry_date = st.text_input("進場日期 (YYYY-MM-DD)", value="2026-10-08", key="in_manual_date")

        # 自動依 20 萬估計建議股數與預估金額
        est_shares = int(200000.0 / (float(in_buy_price) * (1 + FEE_RATE))) if float(in_buy_price) > 0 else 1000
        c_add4, c_add5 = st.columns(2)
        with c_add4:
            in_custom_shares = st.number_input("實際買進總股數 (股，可自由調整整張或零股)", value=est_shares, step=100, key="in_manual_shares")
        with c_add5:
            est_cost = int(float(in_custom_shares) * float(in_buy_price) * (1 + FEE_RATE))
            in_custom_cost = st.number_input("實際投入總金額 (NTD，可填對帳單實際扣款)", value=est_cost, step=1000, key="in_manual_cost")

        if st.button("確認將此標的加入方案 B 在倉監控", type="primary", use_container_width=True):
            clean_c = in_code.strip()
            stock_info, _ = resolve_taiwan_stock(clean_c)
            s_name = stock_info['name'] if stock_info else clean_c
            s_ticker = f"{clean_c}{stock_info['market']}" if stock_info else f"{clean_c}.TW"

            if any(str(p['code']).split('.')[0].strip() == clean_c for p in positions):
                st.warning(f"⚠️ 在倉中已有 {clean_c}，無需重複加入！")
            elif len(positions) >= 3:
                st.error("🛑 槽位已滿（上限 3 檔），無法再開新部位！")
            else:
                b_price = float(in_buy_price)
                tot_shares = int(in_custom_shares)
                cost = float(in_custom_cost)
                shares_a = tot_shares // 2
                shares_b = tot_shares - shares_a

                new_pos_entry = {
                    "code": clean_c, "name": s_name, "ticker": s_ticker,
                    "entry_date": in_entry_date.strip(),
                    "entry_price": b_price, "total_invested": cost,
                    "shares_a": shares_a, "shares_b": shares_b,
                    "days_held": 0, "is_breakeven": False, "lot_a_sold": False,
                    "lot_a_revenue": 0.0, "lot_a_pnl_pct": 0.0,
                    "curr_price": b_price, "unrealized_pct": 0.0,
                    "curr_stop": round(b_price * 0.96, 1),
                    "tp_stage1": round(b_price * 1.08, 1),
                    "ma10": round(b_price * 0.99, 1), "is_extended": False
                }
                positions.append(new_pos_entry)
                save_json(POSITIONS_FILE, positions)
                st.success(f"✅ 成功將 {s_name} ({clean_c}) 加入方案 B！股數：{tot_shares:,d} 股，本金：NT$ {int(cost):,d}")
                st.rerun()

    # 💡 核心功能 B：校正在倉持股資訊（可修正股數與投入金額）
    with st.expander("✏️ 校正在倉部位資訊（修正進場日期、成本、股數或總本金）", expanded=False):
        if positions:
            st.info("若系統自動開倉的 20 萬與真實券商扣款金額有落差，可在此直接校正為精確數字！")
            c_edit1, c_edit2, c_edit3 = st.columns(3)
            with c_edit1:
                edit_target = st.selectbox("選擇要校正的在倉股票", options=[f"{p['name']} ({p['code']})" for p in positions], key="sel_edit_pos")
                edit_pos = next((p for p in positions if f"{p['name']} ({p['code']})" == edit_target), None)
            with c_edit2:
                default_ed = edit_pos['entry_date'] if edit_pos else "2026-10-08"
                new_entry_date = st.text_input("修正進場日期 (YYYY-MM-DD)", value=default_ed, key="in_edit_date")
            with c_edit3:
                default_ep = float(edit_pos['entry_price']) if edit_pos else 100.0
                new_entry_price = st.number_input("修正買進均價 (NTD)", value=default_ep, step=0.1, key="in_edit_price")

            c_edit4, c_edit5 = st.columns(2)
            with c_edit4:
                curr_tot_shares = int(edit_pos['shares_a'] + edit_pos['shares_b']) if edit_pos else 1000
                new_shares = st.number_input("修正買進總股數 (股)", value=curr_tot_shares, step=100, key="in_edit_shares")
            with c_edit5:
                curr_tot_cost = int(edit_pos.get('total_invested', 200000)) if edit_pos else 200000
                new_cost = st.number_input("修正實際投入總金額 (NTD，含手續費)", value=curr_tot_cost, step=1000, key="in_edit_cost")
                
            if st.button("確認儲存校正數值", key="btn_save_edit", type="primary", use_container_width=True):
                if edit_pos:
                    edit_pos['entry_date'] = new_entry_date.strip()
                    edit_pos['entry_price'] = float(new_entry_price)
                    edit_pos['shares_a'] = int(new_shares) // 2
                    edit_pos['shares_b'] = int(new_shares) - edit_pos['shares_a']
                    edit_pos['total_invested'] = float(new_cost)
                    edit_pos['curr_stop'] = round(float(new_entry_price) * 0.96, 1)
                    edit_pos['tp_stage1'] = round(float(new_entry_price) * 1.08, 1)
                    save_json(POSITIONS_FILE, positions)
                    st.success(f"✅ 已成功將 {edit_target} 校正！總股數：{int(new_shares):,d} 股，實際本金：NT$ {int(new_cost):,d}！")
                    st.rerun()

    # 手動平倉結案
    with st.expander("🎯 手動平倉結案（自訂出場價記帳至歷史明細）", expanded=False):
        st.info("若你已在券商帳戶實際出清該檔股票，可在此填寫賣出價，系統將自動計算損益並歸檔至歷史結案帳本！")
        if positions:
            c_close1, c_close2, c_close3 = st.columns(3)
            with c_close1:
                target_to_close = st.selectbox("選擇要結案平倉的在倉標的", options=[f"{p['name']} ({p['code']})" for p in positions], key="sel_close_pos")
                matched_pos = next((p for p in positions if f"{p['name']} ({p['code']})" == target_to_close), None)
            with c_close2:
                default_sell_p = float(matched_pos.get('curr_price', matched_pos['entry_price'])) if matched_pos else 100.0
                user_exit_price = st.number_input("實際賣出成交均價 (NTD)", value=default_sell_p, step=0.1, key="in_exit_p")
            with c_close3:
                user_exit_reason = st.selectbox("選擇結案原因", [
                    "🎯 手動獲利了結", "🛑 手動停損離場", "⏳ 手動換股平倉", "🏆 達標全數出場", "🛡️ 手動保本出場"
                ], key="sel_exit_reason")
                
            if st.button("確認結案此筆交易並寫入帳本", type="primary", use_container_width=True):
                if matched_pos:
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    e_price = float(user_exit_price)
                    cost = float(matched_pos['total_invested'])
                    days = int(matched_pos.get('days_held', 0))
                    
                    if matched_pos.get('lot_a_sold'):
                        shares_b = matched_pos['shares_b']
                        rev_b = shares_b * e_price * (1 - FEE_RATE - TAX_RATE)
                        tot_rev = matched_pos['lot_a_revenue'] + rev_b
                        pnl_b_pct = (e_price - matched_pos['entry_price']) / matched_pos['entry_price'] * 100
                        pnl_a_pct = matched_pos['lot_a_pnl_pct']
                    else:
                        tot_shares = matched_pos['shares_a'] + matched_pos['shares_b']
                        tot_rev = tot_shares * e_price * (1 - FEE_RATE - TAX_RATE)
                        pnl_pct = (e_price - matched_pos['entry_price']) / matched_pos['entry_price'] * 100
                        pnl_a_pct = pnl_pct
                        pnl_b_pct = pnl_pct
                        
                    net_pnl = tot_rev - cost
                    tot_roi = (net_pnl / cost) * 100
                    
                    new_record = {
                        "代號": matched_pos['code'], "名稱": matched_pos['name'],
                        "進場日": matched_pos['entry_date'], "進場價": matched_pos['entry_price'],
                        "出場日": today_str, "持股天數": days, "投入金額": int(cost),
                        "回收金額": int(tot_rev), "淨損益(NTD)": int(net_pnl),
                        "部位A_損益%": round(pnl_a_pct, 2), "部位B_損益%": round(pnl_b_pct, 2),
                        "綜合報酬率%": round(tot_roi, 2), "出場原因": user_exit_reason
                    }
                    
                    df_history = pd.concat([df_history, pd.DataFrame([new_record])], ignore_index=True)
                    save_history_csv(df_history)
                    positions = [p for p in positions if f"{p['name']} ({p['code']})" != target_to_close]
                    save_json(POSITIONS_FILE, positions)
                    st.success(f"✅ 已成功平倉 {target_to_close}！損益：NT$ {int(net_pnl):+,d} ({tot_roi:+.2f}%)！")
                    st.rerun()

    # 丟棄誤入持倉
    with st.expander("🗑️ 手動刪除未建倉或誤入之虛擬部位 (不計入歷史損益)", expanded=False):
        if positions:
            del_pos_target = st.selectbox("選擇要丟棄的虛擬部位", options=[f"{p['name']} ({p['code']})" for p in positions], key="sel_discard_pos")
            if st.button("確認刪除此持倉紀錄", type="secondary"):
                positions = [p for p in positions if f"{p['name']} ({p['code']})" != del_pos_target]
                save_json(POSITIONS_FILE, positions)
                st.success(f"已從帳本中刪除 {del_pos_target}！")
                st.rerun()

    st.write("---")
    st.markdown("#### 📋 【歷史結案明細表】")
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True, hide_index=True)
    else:
        st.info("尚無結案交易紀錄，等待排程每日 16:30 自動追蹤結算。")

# ================= TAB 2: 自選名單批次體檢 =================
with tab_batch:
    st.subheader("📋 自選股今日深蹲訊號掃描 (升級三指標共振)")
    st.write(f"目前自選名單中共有 **{len(st.session_state.watchlist)}** 檔標的。")
    
    if st.button("⚡ 開始全自選股技術體檢", type="primary", use_container_width=True):
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

                delta = df['Close'].diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.ewm(com=13, adjust=False).mean()
                avg_loss = loss.ewm(com=13, adjust=False).mean()
                rs = avg_gain / (avg_loss + 1e-9)
                df['RSI14'] = 100 - (100 / (1 + rs))

                low9 = df['Low'].rolling(9).min()
                high9 = df['High'].rolling(9).max()
                rsv = (df['Close'] - low9) / (high9 - low9 + 1e-9) * 100
                k_list, d_list = [50.0], [50.0]
                for r in rsv.fillna(50):
                    new_k = (k_list[-1] * 2 / 3) + (r * 1 / 3)
                    new_d = (d_list[-1] * 2 / 3) + (new_k * 1 / 3)
                    k_list.append(new_k)
                    d_list.append(new_d)
                df['K'] = k_list[1:]
                df['D'] = d_list[1:]

                ema12 = df['Close'].ewm(span=12, adjust=False).mean()
                ema26 = df['Close'].ewm(span=26, adjust=False).mean()
                df['DIF'] = ema12 - ema26
                df['MACD_SIG'] = df['DIF'].ewm(span=9, adjust=False).mean()
                df['OSC'] = df['DIF'] - df['MACD_SIG']

                now_t = datetime.datetime.now().time()
                is_trading_hours = (datetime.time(9, 0) <= now_t <= datetime.time(13, 35))
                if is_trading_hours and len(df) >= 2:
                    latest, prev = df.iloc[-2], df.iloc[-3]
                else:
                    latest, prev = df.iloc[-1], df.iloc[-2]

                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])
                rsi_val = float(latest['RSI14'])
                k_val, d_val = float(latest['K']), float(latest['D'])
                dif_val, osc_val, prev_osc = float(latest['DIF']), float(latest['OSC']), float(prev['OSC'])

                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                buf = 1 + (buffer_pct / 100)
                touch_10 = (low <= ma10 * buf) and (close >= ma10 * 0.99)
                touch_20 = (low <= ma20 * buf) and (close >= ma20 * 0.99)
                cond_support = touch_10 or touch_20
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit
                cond_rsi = (40.0 <= rsi_val <= 65.0)

                target_ma = ma10 if touch_10 else ma20
                support_name = "10MA" if touch_10 else ("20MA" if touch_20 else "未回踩")

                if cond_trend and cond_support and cond_vol and cond_k and cond_rsi:
                    cond_macd_res = (dif_val > 0) and ((osc_val > prev_osc) or (osc_val > 0))
                    cond_kd_res = (30.0 <= k_val <= 65.0) and ((k_val > float(prev['K'])) or (k_val >= d_val))
                    if cond_macd_res and cond_kd_res: badge = "👑 S級"
                    elif cond_macd_res or cond_kd_res: badge = "🎯 A級"
                    else: badge = "🟢 B級"

                    right_trigger = high
                    sl_p = right_trigger * (1 - stop_loss_pct / 100)
                    tp_p = right_trigger * (1 + take_profit_pct / 100)
                    
                    triggered_list.append({
                        "股票標的": label, "動能評級": badge, "最新收盤": f"${close:,.1f}",
                        "RSI (14)": f"{rsi_val:.1f}", "回踩均線": support_name,
                        "🎯 明日確認進場": f"突破 ${right_trigger:,.1f}",
                        f"硬停損 (-{stop_loss_pct}%)": f"${sl_p:,.1f}",
                        f"階段一停利 (+{take_profit_pct}%)": f"${tp_p:,.1f}",
                        "成交量": f"{int(vol):,d}"
                    })
                else:
                    reasons = []
                    if not cond_trend: reasons.append("均線非多頭")
                    if not cond_support: reasons.append("未回踩支撐")
                    if not cond_vol: reasons.append("未達量縮")
                    if not cond_k: reasons.append(f"實體 > {k_body_limit}%")
                    if not cond_rsi: reasons.append(f"RSI={rsi_val:.1f} (不在40~65)")
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
    st.subheader("🔍 個股深入技術診斷與三指標共振分析")
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

                delta = df['Close'].diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.ewm(com=13, adjust=False).mean()
                avg_loss = loss.ewm(com=13, adjust=False).mean()
                rs = avg_gain / (avg_loss + 1e-9)
                df['RSI14'] = 100 - (100 / (1 + rs))

                now_t = datetime.datetime.now().time()
                is_trading_hours = (datetime.time(9, 0) <= now_t <= datetime.time(13, 35))
                if is_trading_hours and len(df) >= 2: latest = df.iloc[-2]
                else: latest = df.iloc[-1]

                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])
                rsi_val = float(latest['RSI14'])

                target_ma = ma10 if "10MA" in target_ma_choice else ma20
                buf = 1 + (buffer_pct / 100)
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * buf) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit
                cond_rsi = (40.0 <= rsi_val <= 65.0)
                is_ready = cond_trend and cond_support and cond_vol and cond_k and cond_rsi

                c_out1, c_out2, c_out3, c_out4 = st.columns(4)
                c_out1.metric("診斷收盤基準", f"${close:,.1f}")
                c_out2.metric(f"防守 {target_ma_choice}", f"${target_ma:,.1f}")
                c_out3.metric("RSI (14)", f"{rsi_val:.1f}")
                c_out4.metric("成交量", f"{int(vol):,d}")

                if is_ready:
                    sl_p = high * (1 - stop_loss_pct / 100)
                    tp_p = high * (1 + take_profit_pct / 100)
                    st.success(f"🎯 **【{display_title} 觸發訊號】：符合量縮深蹲 ＋ RSI 蓄勢門檻！**")
                    st.markdown(f"""
                    * 🎯 **明日右側確認進場價**：`盤中突破今日高點 ${high:,.1f} 才可掛單`
                    * 🛑 **硬停損價 (-{stop_loss_pct}%)**：`${sl_p:,.1f}`
                    * 🏆 **階段一停利 (+{take_profit_pct}%)**：`${tp_p:,.1f}`（出脫 50%）
                    """)
                else:
                    st.info(f"⏸ **【{display_title} 維持觀望】：尚未滿足全部深蹲條件**")

                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df.index[-60:], open=df['Open'][-60:], high=df['High'][-60:],
                                             low=df['Low'][-60:], close=df['Close'][-60:], name="K線"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA5'][-60:], line=dict(color='orange', width=1), name="5MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA10'][-60:], line=dict(color='blue', width=1.5), name="10MA"))
                fig.add_trace(go.Scatter(x=df.index[-60:], y=df['MA20'][-60:], line=dict(color='purple', width=2), name="20MA"))
                fig.update_layout(xaxis_rangeslider_visible=False, height=420, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

# ================= TAB 5: 自選股票清單總覽 =================
with tab_watchlist:
    st.subheader("📋 自選股票清單總覽儀表板 (Watchlist Overview)")
    
    with st.expander("⚙️ 快速管理自選名單 (在此新增 / 剔除標的)", expanded=False):
        c_add, c_del = st.columns(2)
        with c_add:
            st.markdown("##### ➕ 新增標的至自選清單 (智慧二合一)")
            t5_smart_query = st.text_input("輸入股票名稱 或 4 碼代號", placeholder="例如：系統電 或 5309 或 鴻海", key="t5_smart_query")
            if st.button("確認加入自選名單", key="t5_btn_add", type="primary", use_container_width=True):
                stock_info, err = resolve_taiwan_stock(t5_smart_query)
                if stock_info:
                    lbl = f"{stock_info['name']} ({stock_info['code']})"
                    st.session_state.watchlist[lbl] = f"{stock_info['code']}{stock_info['market']}"
                    save_json(WATCHLIST_FILE, st.session_state.watchlist)
                    st.success(f"✅ 成功找到並加入：{lbl} ({stock_info['market_name']})！")
                    st.rerun()
                else:
                    st.error(err)

        with c_del:
            st.markdown("##### 🗑️ 從自選清單剔除標的")
            if st.session_state.watchlist:
                t5_del_target = st.selectbox("選擇要剔除的股票", options=list(st.session_state.watchlist.keys()), key="t5_in_del")
                if st.button("確認從清單剔除", key="t5_btn_del", use_container_width=True):
                    del st.session_state.watchlist[t5_del_target]
                    save_json(WATCHLIST_FILE, st.session_state.watchlist)
                    st.success(f"已成功移除：{t5_del_target}！")
                    st.rerun()
            else:
                st.info("目前自選清單中無任何標的。")

    profiles = get_all_taiwan_stocks()
    watchlist_items = list(st.session_state.watchlist.items())
    
    if not watchlist_items:
        st.info("目前自選清單為空，可點擊上方「快速管理自選名單」或由雷達戰報加入股票。")
    else:
        with st.spinner("正在取得自選股即時產業、規模、均線與動能指標..."):
            tickers = [t for _, t in watchlist_items]
            try:
                df_all = yf.download(tickers, period="4mo", interval="1d", progress=False)
            except Exception:
                df_all = pd.DataFrame()

            overview_rows = []
            bull_count = 0
            
            for label, ticker in watchlist_items:
                code = ticker.split(".")[0].strip()
                name = label.split(" (")[0].strip()
                
                p_info = profiles.get(code, {})
                ind_text = translate_industry(p_info.get("industry", "電子科技"))
                cap_val = float(p_info.get("cap", 0.0))
                
                if cap_val <= 0.0:
                    try:
                        t_obj = yf.Ticker(ticker)
                        shares_out = t_obj.fast_info.get("shares") or 0
                        if shares_out:
                            cap_val = round((shares_out * 10) / 100_000_000, 1)
                    except Exception: pass

                if cap_val <= 0: cap_bracket_label = "未提供"
                elif cap_val < 20.0: cap_bracket_label = f"{cap_val:.1f}億 (小型爆發股)"
                elif cap_val <= 60.0: cap_bracket_label = f"{cap_val:.1f}億 (中型成長股)"
                elif cap_val <= 150.0: cap_bracket_label = f"{cap_val:.1f}億 (旗艦領頭羊)"
                else: cap_bracket_label = f"{cap_val:.1f}億 (大型權值股)"

                sub_df = None
                try:
                    if not df_all.empty:
                        if isinstance(df_all.columns, pd.MultiIndex):
                            sub_df = df_all.xs(ticker, axis=1, level=1).dropna(how='all')
                        else:
                            sub_df = df_all.dropna(how='all')
                except Exception:
                    sub_df = None

                if sub_df is not None and len(sub_df) >= 20:
                    c_today = float(sub_df['Close'].iloc[-1])
                    c_prev = float(sub_df['Close'].iloc[-2])
                    change_pct = ((c_today - c_prev) / c_prev) * 100
                    
                    ma20 = float(sub_df['Close'].rolling(20).mean().iloc[-1])
                    ma10 = float(sub_df['Close'].rolling(10).mean().iloc[-1])
                    ma5 = float(sub_df['Close'].rolling(5).mean().iloc[-1]) if len(sub_df) >= 5 else ma10
                    vol = float(sub_df['Volume'].iloc[-1])
                    vol_ma5 = float(sub_df['Volume'].rolling(5).mean().iloc[-1])
                    
                    dist_ma20 = ((c_today - ma20) / ma20) * 100
                    if c_today >= ma20:
                        mkt_pos = f"🟢 站上 (+{dist_ma20:.1f}%)"
                        bull_count += 1
                    else:
                        mkt_pos = f"🔴 跌破 ({dist_ma20:.1f}%)"
                        
                    vol_ratio = vol / vol_ma5 if vol_ma5 > 0 else 1.0
                    if vol_ratio <= 0.7: vol_tag = f"🧊 量縮 ({vol_ratio:.2f}x)"
                    elif vol_ratio >= 1.5: vol_tag = f"🔥 出量 ({vol_ratio:.2f}x)"
                    else: vol_tag = f"⚪ 常態 ({vol_ratio:.2f}x)"

                    delta = sub_df['Close'].diff()
                    gain = delta.clip(lower=0)
                    loss = -delta.clip(upper=0)
                    avg_gain = gain.ewm(com=13, adjust=False).mean()
                    avg_loss = loss.ewm(com=13, adjust=False).mean()
                    rs = avg_gain / (avg_loss + 1e-9)
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_val = float(rsi_series.iloc[-1])

                    low9 = sub_df['Low'].rolling(9).min()
                    high9 = sub_df['High'].rolling(9).max()
                    rsv = (sub_df['Close'] - low9) / (high9 - low9 + 1e-9) * 100
                    k_list, d_list = [50.0], [50.0]
                    for r in rsv.fillna(50):
                        new_k = (k_list[-1] * 2 / 3) + (r * 1 / 3)
                        new_d = (d_list[-1] * 2 / 3) + (new_k * 1 / 3)
                        k_list.append(new_k)
                        d_list.append(new_d)
                    k_val = float(k_list[-1])
                    d_val = float(d_list[-1])
                    prev_k = float(k_list[-2]) if len(k_list) >= 2 else k_val

                    ema12 = sub_df['Close'].ewm(span=12, adjust=False).mean()
                    ema26 = sub_df['Close'].ewm(span=26, adjust=False).mean()
                    dif_series = ema12 - ema26
                    macd_sig = dif_series.ewm(span=9, adjust=False).mean()
                    osc_series = dif_series - macd_sig
                    dif_val = float(dif_series.iloc[-1])
                    osc_val = float(osc_series.iloc[-1])
                    prev_osc = float(osc_series.iloc[-2]) if len(osc_series) >= 2 else osc_val

                    open_p = float(sub_df['Open'].iloc[-1])
                    low = float(sub_df['Low'].iloc[-1])
                    prev_ma20 = float(sub_df['Close'].rolling(20).mean().iloc[-4]) if len(sub_df) >= 24 else ma20

                    cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 >= prev_ma20)
                    touch_10 = (low <= ma10 * 1.018 and c_today >= ma10 * 0.99)
                    touch_20 = (low <= ma20 * 1.018 and c_today >= ma20 * 0.99)
                    cond_support = touch_10 or touch_20
                    cond_vol = (vol < vol_ma5)
                    cond_k = (abs(c_today - open_p) / open_p <= 0.035)
                    cond_rsi_hard = (40.0 <= rsi_val <= 65.0)

                    is_squat = cond_trend and cond_support and cond_vol and cond_k and cond_rsi_hard

                    if is_squat: squat_tag = "🎯 均線量縮深蹲"
                    elif touch_10 or touch_20 or (abs(c_today - ma10) / ma10 <= 0.025): squat_tag = "⏳ 回測均線中"
                    elif c_today > ma10: squat_tag = "🚀 均線上強勢"
                    else: squat_tag = "🔻 均線反壓整理"

                    cond_macd_res = (dif_val > 0) and ((osc_val > prev_osc) or (osc_val > 0))
                    cond_kd_res = (30.0 <= k_val <= 65.0) and ((k_val > prev_k) or (k_val >= d_val))

                    if is_squat:
                        if cond_macd_res and cond_kd_res: signal_quality = "👑 頂級共振 (S級)"
                        elif cond_macd_res or cond_kd_res: signal_quality = "🎯 強勢動能 (A級)"
                        else: signal_quality = "🟢 標準深蹲 (B級)"
                    elif c_today >= ma20 and cond_trend:
                        if cond_macd_res and cond_kd_res: signal_quality = "⚡ 多頭共振 (待深蹲)"
                        else: signal_quality = "⚪ 多頭蓄勢 (待深蹲)"
                    elif c_today >= ma20: signal_quality = "⚪ 區間整理"
                    else: signal_quality = "🔻 弱勢整理"

                else:
                    c_today, change_pct = 0.0, 0.0
                    mkt_pos, vol_tag, squat_tag, signal_quality = "無資料", "無資料", "無資料", "無資料"

                overview_rows.append({
                    "標的代號": label,
                    "動能共振評級": signal_quality,
                    "深蹲就緒度": squat_tag,
                    "最新收盤價": f"${c_today:,.1f}" if c_today > 0 else "無資料",
                    "今日漲跌%": f"{change_pct:+.2f}%" if c_today > 0 else "-",
                    "產業類別": ind_text,
                    "股本規模區間": cap_bracket_label,
                    "20MA月線位階": mkt_pos,
                    "量能萎縮比 (vs 5MV)": vol_tag,
                    "code": code,
                    "name": name
                })

        c_ov1, c_ov2, c_ov3, c_ov4 = st.columns(4)
        c_ov1.metric("自選監控總數", f"{len(overview_rows)} 檔")
        bull_pct = (bull_count / len(overview_rows) * 100) if overview_rows else 0
        c_ov2.metric("多頭站穩月線比例", f"{bull_pct:.0f} %")
        squat_ready_count = len([r for r in overview_rows if "🎯" in r["深蹲就緒度"]])
        c_ov3.metric("🎯 處於量縮深蹲點", f"{squat_ready_count} 檔")
        s_a_count = len([r for r in overview_rows if ("S級" in r["動能共振評級"]) or ("A級" in r["動能共振評級"]) or ("多頭共振" in r["動能共振評級"])])
        c_ov4.metric("👑 高動能共振標的", f"{s_a_count} 檔")

        st.write("---")
        df_display = pd.DataFrame(overview_rows).drop(columns=['code', 'name'])
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        st.write("---")
        st.markdown("#### 📰 【自選股近半個月即時新聞與研究傳送門】")
        sel_stock = st.selectbox("選擇要查閱近半個月新聞的標的：", options=[r["標的代號"] for r in overview_rows])
        chosen_info = next((r for r in overview_rows if r["標的代號"] == sel_stock), None)
        
        if chosen_info:
            clean_c = str(chosen_info['code']).split('.')[0].strip()
            c_name = chosen_info['name']
            
            nc1, nc2, nc3 = st.columns(3)
            nc1.markdown(f"**[📰 Yahoo 奇摩股市新聞 ({c_name})]**(https://tw.stock.yahoo.com/quote/{clean_c}/news)")
            nc1.caption("包含法說會、重大訊息、營收動態")
            
            nc2.markdown(f"**[🔍 Google 財經近半月新聞彙整]**(https://www.google.com/search?q={c_name}+{clean_c}+股票&tbm=nws&tbs=qdr:m)")
            nc2.caption("自動過濾近兩週至一個月相關報導")
            
            nc3.markdown(f"**[📊 鉅亨網法人動態與營收走勢]**(https://invest.cnyes.com/twstock/TWS/{clean_c}/news)")
            nc3.caption("三大法人買賣超與業績解析")

# ================= TAB 4: 策略手冊與 SOP 指南 (V2.5 完整作戰手冊) =================
with tab_docs:
    st.subheader("📖 短線成長股・量縮深蹲 (Squat & Rebound) 全流程作戰手冊 V2.5")
    st.info("💡 本系統專為「不盯盤、每日 16:30 離線決策、次日開盤智慧單自動執行」設計，經量化回測完整實證。")

    with st.expander("🔍 一、 盤後全自動獵股漏斗 SOP（3 → 1 → 2 順序過濾）", expanded=True):
        st.write("• **步驟 3【籌碼鎖定度與階梯門檻】**：最新日投信買超 >= 50 張；若股本在 60 億～150 億，門檻提高至 >= 250 張。")
        st.write("• **步驟 1【放寬股本規模 (20億～150億)】**：鎖定 20～60 億中型成長股與 60～150 億旗艦領頭羊（如欣興、技嘉），排除 > 150 億權值牛皮股。")
        st.write("• **步驟 2【業績加速動能】**：最新公告單月營收年增率 YoY > 20%，具實質基本面保護。")

    with st.expander("🧘 二、 盤後「量縮深蹲 (Squat)」技術面檢驗 SOP (升級 V2.5)", expanded=True):
        st.write("• **條件 1【均線多頭排列】**：收盤價位於多頭排列（5MA > 10MA > 20MA），且 20 日均線（月線）斜率向上。")
        st.write("• **條件 2【均線精確回踩】**：最低價回測 10MA 或 20MA 緩衝區（Low <= MA * 1.018），收盤未跌破（Close >= MA * 0.99）。")
        st.write("• **條件 3【極致成交窒息量】**：當日成交量同時低於 5 日均量（5MV）與 20 日均量（20MV），代表浮額洗淨。")
        st.write("• **條件 4【K 棒實體收斂】**：當日 K 棒實體振幅 <= 3.5%，禁止長黑摜壓實體。")
        st.write("• **條件 5【RSI 多方蓄勢中軸 (回測驗證最佳單因子)】**：14 日 RSI 必須介於 40 ～ 65 之間。實測總報酬提升至 +23.13%、勝率提升近 5%、MDD 壓低至 -5.53%，徹底剃除弱勢破底股。")

    with st.expander("🌟 三、 獵股品質「動能共振星級評級 (Signal Quality)」", expanded=True):
        st.write("• **👑 頂級三指標共振 (S 級)**：符合深蹲 + RSI(14) 守穩 40～65 + MACD(零軸上綠縮/翻紅) + KD(30～65區間打勾金叉)。多方動能最強，列為第一優先下單目標！")
        st.write("• **🎯 強勢動能深蹲 (A 級)**：符合核心深蹲 + RSI 守穩 + MACD 或 KD 其一亮燈。")
        st.write("• **🟢 標準量縮深蹲 (B 級)**：符合核心深蹲 + RSI 守穩，籌碼沉澱完畢。")

    with st.expander("🏹 四、 盤中「右側確認」掛單進場 SOP", expanded=True):
        st.write("• **大盤多頭濾網】**：加權指數收盤必須站穩 20MA（月線）之上。若大盤處於月線反壓，全市場雷達強制休眠。")
        st.write("• **次日右側過高確認】**：訊號成立次日，盤中最高價突破深蹲日最高點才准掛單進場；未突破則一律放棄建倉。")

    with st.expander("🛑 五、 嚴格五大出場紀律 SOP（含智慧展延防護）", expanded=True):
        st.write("• **🛑 防線 1【硬停損線 (-4.0%)】**：跌破成本價之 -4.0%，無條件市價全數砍單。")
        st.write("• **⏳ 防線 2【時間停損 (4個交易日 / 最多展延至7天)】**：持有滿 4 個實際交易日漲幅未達 +3% 則平手換股。**若持有期間再次符合雷達深蹲且帳面維持成本之上，自動展延 1 次至滿 7 個交易日**。")
        st.write("• **🛡️ 防線 3【動態保本機制 (+4.0%)】**：盤中浮盈達 +4.0% 時，次日起停損防線調升至成本價 (+0.2%)，消滅賺變賠。")
        st.write("• **🎯 防線 4【第一階段停利 (+8.0%)】**：觸及成本價 +8.0% 時，掛單賣出部位 A（50% 股數）鎖住勝果。")
        st.write("• **🏄 防線 5【第二階段波段落袋 (破 10MA)】**：剩餘部位 B 只要收盤跌破 10MA，次個交易日開盤市價出清。")
        st.write("• **❄️ 防線 6【停損冷卻機制】**：若觸發硬停損，7～10 個交易日內禁止重複買進同一檔股票。")

    with st.expander("💼 六、 60 萬元資金與部位管理模型 SOP", expanded=True):
        st.write("• **三槽位配置**：總資金 60 萬元切分為 3 槽位，每槽上限 20 萬元。單筆極限虧損鎖死在總資金之 1.33%。")
        st.write("• **回撤熔斷機制**：歷程回撤超 -10% 時，槽位下單預算降為 14 萬元（7 折），防禦至淨值回升至 95% 以上。")
