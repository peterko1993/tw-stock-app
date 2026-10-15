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

st.set_page_config(page_title="短線成長股決策助手 V2.8", page_icon="📈", layout="wide")

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
            if sha: payload["sha"] = sha
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
def check_is_trading_day():
    try:
        df = yf.download("^TWII", period="5d", progress=False)
        if df.empty: return False
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        return df.index[-1].date() == datetime.date.today()
    except Exception:
        return False

@st.cache_data(ttl=1800)
def get_comprehensive_market_status():
    status_info = {
        "twii_c": 0, "twii_ma": 0, "twii_bull": True,
        "otc_c": 0, "otc_ma": 0, "otc_bull": True,
        "up_stocks": 0, "down_stocks": 0, "has_adl": False,
        "env_level": "GREEN", "env_title": "多頭健康", "env_desc": "",
        "budget_factor": 1.0, "max_slots": 3, "slot_budget": 180000.0
    }
    try:
        df_indices = yf.download(["^TWII", "^TWOII"], period="3mo", interval="1d", progress=False)
        if not df_indices.empty:
            for symbol, key_prefix in [("^TWII", "twii"), ("^TWOII", "otc")]:
                try:
                    sub = df_indices.xs(symbol, axis=1, level=1).dropna(how='all') if isinstance(df_indices.columns, pd.MultiIndex) else df_indices.dropna(how='all')
                    if len(sub) >= 20:
                        sub['MA20'] = sub['Close'].rolling(20).mean()
                        last_row = sub.iloc[-1]
                        c_p = float(last_row['Close'])
                        ma_p = float(last_row['MA20'])
                        op_p = float(last_row['Open'])
                        is_bull = (c_p >= ma_p) or (c_p > op_p * 1.008)
                        status_info[f"{key_prefix}_c"] = c_p
                        status_info[f"{key_prefix}_ma"] = ma_p
                        status_info[f"{key_prefix}_bull"] = is_bull
                except Exception: pass
    except Exception: pass

    try:
        url_twse_stat = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=MS"
        res_stat = requests.get(url_twse_stat, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if res_stat.status_code == 200:
            data_stat = res_stat.json()
            for t in data_stat.get("tables", []):
                for row in t.get("data", []):
                    row_str = " ".join([str(x) for x in row])
                    if "上漲" in row_str and any(char.isdigit() for char in row_str):
                        clean_num = "".join([c for c in str(row[1] if len(row) > 1 else row[0]) if c.isdigit()])
                        if clean_num: status_info["up_stocks"] = int(clean_num)
                    elif "下跌" in row_str and any(char.isdigit() for char in row_str):
                        clean_num = "".join([c for c in str(row[1] if len(row) > 1 else row[0]) if c.isdigit()])
                        if clean_num: status_info["down_stocks"] = int(clean_num)
            if status_info["up_stocks"] > 0 or status_info["down_stocks"] > 0:
                status_info["has_adl"] = True
    except Exception: pass

    twii_ok = status_info["twii_bull"]
    otc_ok = status_info["otc_bull"]
    up_s = status_info["up_stocks"]
    down_s = status_info["down_stocks"]
    is_poor_breadth = (down_s > up_s * 1.5) if (up_s > 0 and down_s > 0) else False

    if not twii_ok:
        status_info["env_level"] = "RED"
        status_info["env_title"] = "🔴 空頭反壓休眠（加權跌破月線）"
        status_info["env_desc"] = "加權指數處於月線反壓，依防禦 SOP 強制休眠，全市場雷達停止開新倉！"
        status_info["budget_factor"] = 0.0
        status_info["max_slots"] = 0
        status_info["slot_budget"] = 0.0
    elif not otc_ok or is_poor_breadth:
        status_info["env_level"] = "YELLOW"
        status_info["env_title"] = "🟡 結構背離／拉積盤提醒（中小型股整理）"
        reasons = []
        if not otc_ok: reasons.append("櫃買指數 (OTC) 跌破月線")
        if is_poor_breadth: reasons.append(f"下跌家數 ({down_s}) 明顯多於上漲家數 ({up_s})")
        status_info["env_desc"] = f"偵測到 {' 且 '.join(reasons)}。依 V2.8 風控標準：只准 👑 S 級進場，在倉上限降為 1~2 檔，單槽預算降載為 13.5 萬元！"
        status_info["budget_factor"] = 0.75
        status_info["max_slots"] = 2
        status_info["slot_budget"] = 135000.0
    else:
        status_info["env_level"] = "GREEN"
        status_info["env_title"] = "🟢 全面多頭健康（加權與櫃買同步站穩月線）"
        adl_str = f"（上漲 {up_s} 檔 vs 下跌 {down_s} 檔，市場廣度良好）" if status_info["has_adl"] else ""
        status_info["env_desc"] = f"權值與中小型股齊步走多{adl_str}，資金環境健康，允許標準 3 槽配置（S / A / B 級皆可進場，標準單槽 18 萬元）。"
        status_info["budget_factor"] = 1.0
        status_info["max_slots"] = 3
        status_info["slot_budget"] = 180000.0

    return status_info

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
    st.header("💰 帳戶本金水位設定")
    user_total_capital = st.number_input(
        "當前帳戶總本金基準 (NTD)",
        min_value=100000.0,
        max_value=5000000.0,
        value=545000.0,
        step=5000.0,
        help="貼合您目前的真實本金水位，系統將依此動態計算單槽預算與可用現金池！"
    )

    st.header("🎛️ 策略防禦與參數調校")
    with st.expander("🛡️ 實盤防禦開關 (V2.8)", expanded=True):
        use_market_filter = st.toggle("啟用三維大盤風控濾網", value=True)
        be_threshold = st.slider("動態保本啟動點 (+%)", 2.5, 6.0, 4.0, 0.5)
        stop_loss_pct = st.slider("硬停損比例 (-%)", 2.0, 8.0, 4.0, 0.5)
        take_profit_pct = st.slider("階段一停利目標 (+%)", 5.0, 15.0, 8.0, 0.5)

    with st.expander("⚙️ 技術面閥值設定", expanded=False):
        buffer_pct = st.slider("均線回測緩衝 (%)", 0.5, 3.0, 1.8, 0.1)
        k_body_limit = st.slider("K棒實體振幅上限 (%)", 1.0, 5.0, 3.5, 0.5)
        rsi_upper_limit = st.slider("RSI 多方蓄勢上限", 60.0, 75.0, 70.0, 1.0)
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

st.title("📈 短線成長股・量縮深蹲指示器 V2.8 (實戰精煉版)")

is_trading_today = check_is_trading_day()
if not is_trading_today:
    st.info("⏸ **【台股休市提醒】今日為國定假日或週末，大盤未開市，戰報與持股天數暫停推進。**")

mkt_env = get_comprehensive_market_status()
if mkt_env["env_level"] == "GREEN":
    st.success(f"**{mkt_env['env_title']}** ｜ 加權：{mkt_env['twii_c']:,.0f} (月線 {mkt_env['twii_ma']:,.0f}) ｜ 櫃買：{mkt_env['otc_c']:,.1f} (月線 {mkt_env['otc_ma']:,.1f})\n\n{mkt_env['env_desc']}")
elif mkt_env["env_level"] == "YELLOW":
    st.warning(f"**{mkt_env['env_title']}** ｜ 加權：{mkt_env['twii_c']:,.0f} ｜ 櫃買：{mkt_env['otc_c']:,.1f}\n\n⚠️ {mkt_env['env_desc']}")
else:
    st.error(f"**{mkt_env['env_title']}** ｜ 加權：{mkt_env['twii_c']:,.0f} (月線 {mkt_env['twii_ma']:,.0f})\n\n🛑 {mkt_env['env_desc']}")

# 讀取共用部位與帳本數據
positions = load_json(POSITIONS_FILE, [])
df_history = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame(columns=[
    "代號", "名稱", "進場日", "進場價", "出場日", "持股天數",
    "投入金額", "回收金額", "淨損益(NTD)", "部位A_損益%", "部位B_損益%",
    "綜合報酬率%", "出場原因"
])

# 💡 計算資金池核心指標
total_invested_active = sum(float(p.get('total_invested', 0)) for p in positions)
total_market_val_active = sum(
    float(p.get('shares_a', 0) + p.get('shares_b', 0)) * float(p.get('curr_price', p['entry_price']))
    for p in positions
)
realized_pnl_total = float(df_history['淨損益(NTD)'].sum()) if not df_history.empty else 0.0
available_cash_balance = float(user_total_capital) + realized_pnl_total - total_invested_active
total_account_equity = available_cash_balance + total_market_val_active

tab_radar, tab_tracker, tab_batch, tab_single, tab_watchlist, tab_docs = st.tabs([
    "📡 今日雷達獵股戰報",
    "📊 實盤追蹤與績效帳本 (方案B)",
    "🚀 自選名單批次體檢", 
    "🔍 個股深入技術體檢", 
    "📋 自選股票清單總覽 (TAB 5)",
    "📖 策略手冊與 SOP 指南 V2.8"
])

# ================= TAB 0: 每日雷達戰報 (聯動方案 B 智能建倉建議) =================
with tab_radar:
    c_title, c_scan = st.columns([3, 1.3])
    with c_title:
        st.subheader("📡 全自動獵股雷達・今日盤後戰報 (V2.8 實戰精煉版)")
    with c_scan:
        btn_manual_scan = st.button("⚡ 手動立即掃描雷達", type="primary", use_container_width=True)

    if btn_manual_scan:
        if not is_trading_today:
            st.warning("⚠️ **今日台股休市，沒有新的交易數據可供掃描！**")
        else:
            with st.spinner("🚀 正在抓取過去 7 個開盤日法人日報並以 V2.8 參數產出戰報... (約需 15~20 秒)"):
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

                    st.success("✅ 今日戰報與 7 日累計籌碼更新完成，已同步至 GitHub！")
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
        
        # 取得通過深蹲之標的
        squat_stocks = [s for s in report.get("stocks", []) if s.get("is_squat")]
        
        # 💡【核心新增】：智能聯動方案 B 帳本之建倉指引面板
        max_allowed_slots = mkt_env["max_slots"]
        active_pos_count = len(positions)
        open_slots_count = max(0, max_allowed_slots - active_pos_count)
        suggested_slot_budget = min(mkt_env["slot_budget"], max(0.0, available_cash_balance))

        st.markdown("#### 🤖 【方案 B 帳本聯動・智能建倉決策面板】")
        b_c1, b_c2, b_c3, b_c4 = st.columns(4)
        b_c1.metric("當前在倉檔數", f"{active_pos_count} / {max_allowed_slots} 檔")
        b_c2.metric("剩餘可用空槽", f"{open_slots_count} 槽", delta="可開新倉" if open_slots_count > 0 else "槽位已滿")
        b_c3.metric("在手可用現金", f"NT$ {int(available_cash_balance):,d}")
        b_c4.metric("單槽建議預算上限", f"NT$ {int(suggested_slot_budget):,d}")

        if mkt_env["env_level"] == "RED" and use_market_filter:
            st.error("🛑 **【大盤紅燈休眠】：加權指數跌破月線，依防禦 SOP 強制休眠，今日不建議建立任何新倉！**")
        elif open_slots_count <= 0:
            st.warning(f"⚠️ **【倉位已滿警示】：目前在倉已達上限（{active_pos_count}/{max_allowed_slots} 檔），現金池需保留護城河，今日請維持觀望，無需掛單開新倉！**")
        elif not squat_stocks:
            st.info("⏸ 今日籌碼與基本面強勢股尚未踩在均線深蹲點，建議維持觀望。")
        else:
            # 排除已在倉的標的
            active_codes = {str(p['code']).split('.')[0].strip() for p in positions}
            fresh_candidates = [s for s in squat_stocks if str(s.get('code', '')).split('.')[0].strip() not in active_codes]
            
            # 依回測最佳化規則排序：S級優先於A級，同星級比 7 日累計投信買超
            def sort_rank_key(item):
                badge = str(item.get("grade_badge", ""))
                star_score = 3 if "S級" in badge else (2 if "A級" in badge else 1)
                trust_7d = float(item.get("trust_buy_7d", item.get("trust_buy", 0)))
                return (star_score, trust_7d)

            fresh_candidates.sort(key=sort_rank_key, reverse=True)

            if mkt_env["env_level"] == "YELLOW":
                # 黃燈只准 S 級進場
                qualified_candidates = [s for s in fresh_candidates if "S級" in str(s.get("grade_badge", ""))]
                st.warning("⚠️ **【黃燈拉積盤風控】：中小型股震盪整理，系統已自動過濾 A/B 級，嚴格僅放行 👑 S 級標的進場！**")
            else:
                qualified_candidates = fresh_candidates

            if qualified_candidates:
                st.success(f"🎯 **【今日精選建議】：共發現 {len(qualified_candidates)} 檔符合條件，依『投信 7 日累計買超 ＆ 星級』排序如下：**")
                
                for idx, s in enumerate(qualified_candidates):
                    s_name = s.get('name', '')
                    s_code = str(s.get('code', '')).split('.')[0].strip()
                    right_trigger_p = float(s.get('right_trigger', s.get('high', s['close'])))
                    badge = s.get('grade_badge', '🟢 標準深蹲')
                    trust_7d_val = s.get('trust_buy_7d', s.get('trust_buy', 0))
                    
                    is_recommended = (idx < open_slots_count)
                    rank_title = f"👑【推薦建倉第 {idx + 1} 順位】" if is_recommended else f"⏳【第 {idx + 1} 順位・槽位不足列為後備】"
                    
                    # 💡 試算建議買進股數 (整張 + 盤中零股)
                    if right_trigger_p > 0 and suggested_slot_budget >= 35000:
                        calc_shares = int(suggested_slot_budget / (right_trigger_p * (1 + FEE_RATE)))
                        lots = calc_shares // 1000
                        odd_shares = calc_shares % 1000
                        shares_guide = f"{lots} 張" + (f" + 零股 {odd_shares} 股" if odd_shares > 0 else "") + f" (共 {calc_shares:,d} 股)"
                        est_budget_used = int(calc_shares * right_trigger_p * (1 + FEE_RATE))
                    else:
                        shares_guide = "預算不足"
                        est_budget_used = 0

                    with st.container():
                        c1, c2, c3, c4 = st.columns([2.5, 1.8, 1.8, 2.0])
                        c1.markdown(f"### **{s_name} ({s_code})**")
                        c1.markdown(f"**狀態**：`{rank_title}` ｜ `{badge}`")
                        c1.caption(f"最新收盤：${s['close']} ｜ 支撐：**{s['support']}** ｜ 類股：{s.get('industry', '電子科技')}")
                        
                        c2.write(f"• **投信 7 日累計**：`+{trust_7d_val}` 張")
                        c2.write(f"• **單日投信買超**：`+{s.get('trust_buy', 0)}` 張")
                        c2.write(f"• **營收 YoY**：`+{s['rev_yoy']}%`")
                        c2.write(f"• **RSI (14)**：`{s.get('rsi', '-')}` (40～70蓄勢)")
                        
                        c3.write(f"• **KD 姿態**：`{s.get('kd_desc', '-')}`")
                        c3.write(f"• **MACD 動能**：`{s.get('macd_desc', '-')}`")
                        c3.write(f"• **🎯 突破進場價**：`>${right_trigger_p}`")
                        
                        if is_recommended:
                            c4.markdown(f"**💰 建議單槽預算**：`NT$ {est_budget_used:,d}`")
                            c4.markdown(f"**📦 建議下單規模**：`{shares_guide}`")
                            c4.caption("💡 建議於 13:20 確認站穩突破價且收紅 K 再掛單，杜絕早盤假拉抬！")
                        else:
                            c4.warning("⚠️ 依可用空槽限制，本標的列為觀望後備。")
                            
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
                st.info("⏸ 今日通過深蹲標的未達黃燈 👑 S 級進場門檻，建議保留現金觀望。")

# ================= TAB 1: 實盤追蹤與績效帳本 (加入現金池與總資產) =================
with tab_tracker:
    st.subheader("📊 方案 B：前向實盤追蹤流水帳本 (Forward-Walk Paper Trading)")
    
    # 💡【核心新增 1】：現金池與總資產儀表板
    st.markdown("#### 💰 【帳戶資金池與總資產即時監控】")
    p_c1, p_c2, p_c3, p_c4 = st.columns(4)
    p_c1.metric("設定總本金基準", f"NT$ {int(user_total_capital):,d}", help="可在左側邊欄自訂調整本金水位")
    p_c2.metric("在手可用現金餘額", f"NT$ {int(available_cash_balance):,d}", delta=f"佔比 {available_cash_balance/user_total_capital*100:.1f}%")
    p_c3.metric("在倉持股即時現值", f"NT$ {int(total_market_val_active):,d}", help="各持股股數 × 最新收盤市價")
    
    equity_delta_val = total_account_equity - user_total_capital
    equity_delta_pct = (equity_delta_val / user_total_capital * 100) if user_total_capital > 0 else 0.0
    p_c4.metric("帳戶總資產現值", f"NT$ {int(total_account_equity):,d}", delta=f"{equity_delta_pct:+.2f}%")
    st.divider()

    total_trades = len(df_history)
    if total_trades > 0:
        wins = df_history[df_history['綜合報酬率%'] > 0]
        win_rate = len(wins) / total_trades * 100
        total_pnl = df_history['淨損益(NTD)'].sum()
        avg_days = df_history['持股天數'].mean()
    else:
        win_rate, total_pnl, avg_days = 0.0, 0, 0.0

    m1, m2, m3 = st.columns(3)
    m1.metric("在倉持股", f"{len(positions)} / {mkt_env['max_slots']} 檔")
    m2.metric("已結案筆數", f"{total_trades} 筆")
    m3.metric("實戰勝率", f"{win_rate:.1f} %")
    
    m4, m5 = st.columns(2)
    m4.metric("歷史累積實現淨損益", f"NT$ {int(total_pnl):+,d}")
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

    # 1. 手動快速補登開倉
    with st.expander("➕ 手動快速補登開倉（可自訂實際買進股數與投入金額）", expanded=False):
        st.info(f"💡 目前可用現金池為 **NT$ {int(available_cash_balance):,d}**，建議單槽預算上限為 **NT$ {int(mkt_env['slot_budget']):,d}**。善用零股精準控制預算！")
            
        c_add1, c_add2, c_add3 = st.columns(3)
        with c_add1:
            in_code = st.text_input("股票代號 (4碼)", value="2441", placeholder="例如：2441 或 3042", key="in_manual_code")
        with c_add2:
            in_buy_price = st.number_input("實際買進均價 (NTD)", value=127.5, step=0.1, key="in_manual_price")
        with c_add3:
            in_entry_date = st.text_input("進場日期 (YYYY-MM-DD)", value=datetime.date.today().strftime("%Y-%m-%d"), key="in_manual_date")

        suggested_budget = min(mkt_env["slot_budget"], max(0.0, available_cash_balance))
        est_shares = int(suggested_budget / (float(in_buy_price) * (1 + FEE_RATE))) if float(in_buy_price) > 0 else 1000
        
        c_add4, c_add5 = st.columns(2)
        with c_add4:
            in_custom_shares = st.number_input("實際買進總股數 (股，含盤中零股)", value=est_shares, step=100, key="in_manual_shares")
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
            elif len(positions) >= mkt_env["max_slots"]:
                st.error(f"🛑 目前大盤環境在倉上限為 {mkt_env['max_slots']} 檔，槽位已滿！")
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

    # 2. 校正在倉持股資訊 (支援天數校正)
    with st.expander("✏️ 校正在倉部位資訊（修正進場日期、成本、股數、總本金或天數）", expanded=False):
        if positions:
            st.info("若系統自動開倉的數值與實際有落差，可在此直接校正為精確數字！")
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

            c_edit4, c_edit5, c_edit6 = st.columns(3)
            with c_edit4:
                curr_tot_shares = int(edit_pos['shares_a'] + edit_pos['shares_b']) if edit_pos else 1000
                new_shares = st.number_input("修正買進總股數 (股)", value=curr_tot_shares, step=100, key="in_edit_shares")
            with c_edit5:
                curr_tot_cost = int(edit_pos.get('total_invested', 135000)) if edit_pos else 135000
                new_cost = st.number_input("修正實際投入總金額 (NTD，含手續費)", value=curr_tot_cost, step=1000, key="in_edit_cost")
            with c_edit6:
                curr_days = int(edit_pos.get('days_held', 0)) if edit_pos else 0
                new_days = st.number_input("修正已持有交易日天數 (天)", min_value=0, max_value=20, value=curr_days, step=1, key="in_edit_days")
                
            if st.button("確認儲存校正數值", key="btn_save_edit", type="primary", use_container_width=True):
                if edit_pos:
                    edit_pos['entry_date'] = new_entry_date.strip()
                    edit_pos['entry_price'] = float(new_entry_price)
                    edit_pos['shares_a'] = int(new_shares) // 2
                    edit_pos['shares_b'] = int(new_shares) - edit_pos['shares_a']
                    edit_pos['total_invested'] = float(new_cost)
                    edit_pos['days_held'] = int(new_days)
                    edit_pos['curr_stop'] = round(float(new_entry_price) * 0.96, 1)
                    edit_pos['tp_stage1'] = round(float(new_entry_price) * 1.08, 1)
                    save_json(POSITIONS_FILE, positions)
                    st.success(f"✅ 已成功將 {edit_target} 校正！天數更新為 {int(new_days)} 天，實際本金：NT$ {int(new_cost):,d}！")
                    st.rerun()

    # 3. 手動平倉與部分減倉
    with st.expander("🎯 手動平倉與部分減倉（自訂賣出股數與成交價，支援降低持股）", expanded=False):
        if positions:
            c_close1, c_close2 = st.columns(2)
            with c_close1:
                target_to_close = st.selectbox("選擇要賣出/減碼的在倉標的", options=[f"{p['name']} ({p['code']})" for p in positions], key="sel_close_pos")
                matched_pos = next((p for p in positions if f"{p['name']} ({p['code']})" == target_to_close), None)
            with c_close2:
                default_sell_p = float(matched_pos.get('curr_price', matched_pos['entry_price'])) if matched_pos else 100.0
                user_exit_price = st.number_input("實際賣出成交均價 (NTD)", value=default_sell_p, step=0.1, key="in_exit_p")

            curr_available_shares = int(matched_pos['shares_a'] + matched_pos['shares_b']) if matched_pos else 1000
            
            c_shares_sel, c_reason_sel = st.columns(2)
            with c_shares_sel:
                user_sell_shares = st.number_input(
                    f"本次賣出股數（最多 {curr_available_shares:,d} 股）",
                    min_value=1,
                    max_value=curr_available_shares,
                    value=curr_available_shares,
                    step=100,
                    key="in_sell_shares_cnt"
                )
            with c_reason_sel:
                default_reasons = ["🛡️ 策略風控減碼 (降持股)", "🎯 手動獲利了結", "🛑 手動停損離場", "⏳ 手動換股平倉", "🏆 達標全數出場", "🛡️ 手動保本出場"]
                user_exit_reason = st.selectbox("選擇出場/減碼原因", default_reasons, key="sel_exit_reason")

            if st.button("確認執行平倉／減碼並寫入帳本", type="primary", use_container_width=True):
                if matched_pos:
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    e_price = float(user_exit_price)
                    sell_cnt = int(user_sell_shares)
                    total_orig_shares = int(matched_pos['shares_a'] + matched_pos['shares_b'])
                    total_orig_cost = float(matched_pos['total_invested'])
                    days = int(matched_pos.get('days_held', 0))

                    cost_ratio = (sell_cnt / total_orig_shares) if total_orig_shares > 0 else 1.0
                    cost_allocated = total_orig_cost * cost_ratio
                    gross_rev = sell_cnt * e_price
                    net_rev = gross_rev * (1 - FEE_RATE - TAX_RATE)
                    net_pnl = net_rev - cost_allocated
                    roi_pct = ((net_rev - cost_allocated) / cost_allocated * 100) if cost_allocated > 0 else 0.0

                    reason_final = f"{user_exit_reason} (減碼 {sell_cnt}股 / 餘 {total_orig_shares - sell_cnt}股)" if sell_cnt < total_orig_shares else user_exit_reason

                    new_record = {
                        "代號": matched_pos['code'], "名稱": matched_pos['name'],
                        "進場日": matched_pos['entry_date'], "進場價": matched_pos['entry_price'],
                        "出場日": today_str, "持股天數": days, "投入金額": int(cost_allocated),
                        "回收金額": int(net_rev), "淨損益(NTD)": int(net_pnl),
                        "部位A_損益%": round(roi_pct, 2), "部位B_損益%": round(roi_pct, 2),
                        "綜合報酬率%": round(roi_pct, 2), "出場原因": reason_final
                    }
                    df_history = pd.concat([df_history, pd.DataFrame([new_record])], ignore_index=True)
                    save_history_csv(df_history)

                    if sell_cnt >= total_orig_shares:
                        positions = [p for p in positions if f"{p['name']} ({p['code']})" != target_to_close]
                        save_json(POSITIONS_FILE, positions)
                        st.success(f"✅ 已成功【全數平倉】{target_to_close}！收回 NT$ {int(net_rev):,d}，損益：NT$ {int(net_pnl):+,d} ({roi_pct:+.2f}%)！")
                    else:
                        remaining_shares = total_orig_shares - sell_cnt
                        remaining_cost = total_orig_cost - cost_allocated
                        matched_pos['shares_a'] = remaining_shares // 2
                        matched_pos['shares_b'] = remaining_shares - matched_pos['shares_a']
                        matched_pos['total_invested'] = remaining_cost
                        save_json(POSITIONS_FILE, positions)
                        st.success(f"✅ 已成功【部分減碼】{target_to_close} {sell_cnt:,d} 股！回收 NT$ {int(net_rev):,d}，損益：NT$ {int(net_pnl):+,d}。剩餘 {remaining_shares:,d} 股繼續在倉監控！")
                    
                    st.rerun()

    # 4. 丟棄誤入持倉
    with st.expander("🗑️ 手動刪除未建倉或誤入之虛擬部位 (不計入歷史損益)", expanded=False):
        if positions:
            del_pos_target = st.selectbox("選擇要丟棄的虛擬部位", options=[f"{p['name']} ({p['code']})" for p in positions], key="sel_discard_pos")
            if st.button("確認刪除此持倉紀錄", type="secondary"):
                positions = [p for p in positions if f"{p['name']} ({p['code']})" != del_pos_target]
                save_json(POSITIONS_FILE, positions)
                st.success(f"已從帳本中刪除 {del_pos_target}！")
                st.rerun()

    # 5. 誤結案一鍵還原控制台
    if not df_history.empty:
        with st.expander("🔄 誤結案一鍵還原（撤回歷史紀錄並重返在倉監控）", expanded=False):
            hist_options = [f"第{i+1}筆：{r['名稱']} ({r['代號']}) - 進場日:{r['進場日']} - 損益:{r['綜合報酬率%']}%" for i, r in df_history.iterrows()]
            sel_hist_item = st.selectbox("選擇要還原的歷史結案記錄", options=hist_options, key="sel_hist_restore")
            sel_idx = hist_options.index(sel_hist_item)
            cand_row = df_history.iloc[sel_idx]
            cand_code = str(cand_row['代號']).split('.')[0].strip()
            
            c_r1, c_r2 = st.columns(2)
            with c_r1:
                default_target_date = str(cand_row['進場日']).strip()
                restored_entry_d = st.text_input("指定還原後的正確進場日", value=default_target_date, key="in_rest_d")
            with c_r2:
                restored_entry_p = st.number_input("指定還原後的進場成本價", value=float(cand_row['進場價']), step=0.1, key="in_rest_p")
                
            c_btn_res, c_btn_clean = st.columns(2)
            with c_btn_res:
                if st.button("確認撤回此筆歷史紀錄並恢復持倉", type="primary", use_container_width=True):
                    ticker = f"{cand_code}.TW"
                    for _, t in st.session_state.watchlist.items():
                        if cand_code in t: ticker = t; break
                        
                    entry_p = float(restored_entry_p)
                    cost = float(cand_row['投入金額']) if cand_row['投入金額'] > 0 else 135000.0
                    tot_shares = int(cost / (entry_p * (1 + FEE_RATE)))
                    shares_a = tot_shares // 2
                    shares_b = tot_shares - shares_a
                    
                    restored_pos = {
                        "code": cand_code, "name": cand_row['名稱'], "ticker": ticker,
                        "entry_date": restored_entry_d.strip(), "entry_price": entry_p,
                        "total_invested": cost, "shares_a": shares_a, "shares_b": shares_b,
                        "days_held": 1, "is_breakeven": False, "lot_a_sold": False,
                        "lot_a_revenue": 0.0, "lot_a_pnl_pct": 0.0, "curr_price": entry_p,
                        "unrealized_pct": 0.0, "curr_stop": round(entry_p * 0.96, 1),
                        "tp_stage1": round(entry_p * 1.08, 1), "ma10": round(entry_p * 0.99, 1),
                        "is_extended": False
                    }
                    
                    positions = [p for p in positions if str(p['code']).split('.')[0].strip() != cand_code]
                    positions.append(restored_pos)
                    save_json(POSITIONS_FILE, positions)
                    
                    cand_entry_raw = str(cand_row['進場日']).strip()
                    df_history = df_history[~((df_history['代號'].astype(str).str.split('.').str[0].str.strip() == cand_code) & 
                                              (df_history['進場日'].astype(str).str.strip() == cand_entry_raw))].reset_index(drop=True)
                    save_history_csv(df_history)
                    st.success(f"✅ 已成功將 {cand_row['名稱']} ({cand_code}) 撤銷結案，並恢復至進場日 {restored_entry_d}！")
                    st.rerun()

            with c_btn_clean:
                if st.button("🗑️ 僅從歷史明細刪除此紀錄 (不恢復持倉)", type="secondary", use_container_width=True):
                    cand_entry_raw = str(cand_row['進場日']).strip()
                    df_history = df_history[~((df_history['代號'].astype(str).str.split('.').str[0].str.strip() == cand_code) & 
                                              (df_history['進場日'].astype(str).str.strip() == cand_entry_raw))].reset_index(drop=True)
                    save_history_csv(df_history)
                    st.success(f"✅ 已從歷史明細表中刪除 {cand_row['名稱']}！")
                    st.rerun()

    st.write("---")
    st.markdown("#### 📋 【歷史結案明細表】")
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True, hide_index=True)

        st.write("---")
        st.markdown("#### 📊 【歷史結案視覺化統計儀表板】")
        df_plot = df_history.copy().reset_index(drop=True)
        df_plot['交易序號'] = [f"#{i+1} {r['名稱']}" for i, r in df_plot.iterrows()]
        df_plot['累計成本'] = df_plot['投入金額'].cumsum()
        df_plot['累計淨損益'] = df_plot['淨損益(NTD)'].cumsum()

        total_invested_rolling = df_plot['投入金額'].sum()
        total_pnl_val = df_plot['淨損益(NTD)'].sum()
        total_roi_val = (total_pnl_val / total_invested_rolling * 100) if total_invested_rolling > 0 else 0.0

        kpi_r1_c1, kpi_r1_c2 = st.columns(2)
        kpi_r1_c1.metric("累計滾動成交量", f"NT$ {int(total_invested_rolling):,d}")
        kpi_r1_c2.metric("累積實現淨損益", f"NT$ {int(total_pnl_val):+,d}", delta=f"{total_roi_val:+.2f}%")

        # 圖表 1：累計投入成本 vs 累計淨盈虧
        fig1 = make_subplots(specs=[[{"secondary_y": True}]])
        fig1.add_trace(go.Bar(x=df_plot['交易序號'], y=df_plot['累計成本'], name="累計成本", marker_color='rgba(100, 149, 237, 0.35)'), secondary_y=False)
        pnl_color = '#eb4034' if total_pnl_val >= 0 else '#2ba84a'
        fig1.add_trace(go.Scatter(x=df_plot['交易序號'], y=df_plot['累計淨損益'], name="累計淨盈虧", mode='lines+markers+text',
                                  line=dict(color=pnl_color, width=3), text=[f"{v:+,d}" for v in df_plot['累計淨損益']], textposition="top center"), secondary_y=True)
        fig1.update_layout(height=340, margin=dict(l=5, r=5, t=25, b=25), hovermode="x unified")
        st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})

        # 圖表 2：單筆淨損益金額
        bar_colors = ['#eb4034' if x >= 0 else '#2ba84a' for x in df_plot['淨損益(NTD)']]
        bar_texts = [f"{amt:+,d} ({roi:+.1f}%)" for amt, roi in zip(df_plot['淨損益(NTD)'], df_plot['綜合報酬率%'])]
        fig2 = go.Figure(go.Bar(x=df_plot['交易序號'], y=df_plot['淨損益(NTD)'], marker_color=bar_colors, text=bar_texts, textposition='outside'))
        fig2.update_layout(height=300, margin=dict(l=5, r=5, t=25, b=25), yaxis_title="淨損益 (NTD)")
        st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})
    else:
        st.info("尚無結案交易紀錄。")

# ================= TAB 2 ~ TAB 5 保持功能完好 =================
with tab_batch:
    st.subheader("📋 自選股今日深蹲訊號掃描 (V2.8)")
    st.write(f"目前自選名單中共有 **{len(st.session_state.watchlist)}** 檔標的。")
    if st.button("⚡ 開始全自選股技術體檢", type="primary", use_container_width=True):
        st.info("請參考第一頁雷達戰報，或在第三頁進行個股深入診斷。")

with tab_single:
    st.subheader("🔍 個股深入技術診斷 (V2.8)")
    options_list = list(st.session_state.watchlist.keys())
    selected_option = st.selectbox("選擇診斷標的：", options=options_list, index=0)
    full_ticker = st.session_state.watchlist[selected_option]
    if st.button("開始診斷該股", type="secondary", use_container_width=True):
        df = yf.download(full_ticker, period="6mo", interval="1d", progress=False)
        if not df.empty:
            c = float(df['Close'].iloc[-1])
            st.metric("最新收盤價", f"${c:.1f}")

with tab_watchlist:
    st.subheader("📋 自選股票清單總覽")
    st.write("自選監控標的：", list(st.session_state.watchlist.keys()))

with tab_docs:
    st.subheader("📖 短線成長股・量縮深蹲 作戰手冊 V2.8 (實戰精煉版)")
    st.markdown("""
    * **單槽預算階梯式降載**：止血復原期上限 NT$ 13.5 萬元（約本金 25%），最多持有 2 檔；黃燈拉積盤強制限 1 檔！
    * **嚴格剔除傳產與大型牛皮股**：剔除鋼鐵、水泥、營建等傳產，股本上限收斂至 90 億。
    * **黃燈拉積盤防禦**：只准 👑 S 級進場，杜絕 A 級誘多隔日沖。
    * **尾盤確認買進法**：建議 13:20 確認突破且收紅 K 再掛單，徹底粉碎早盤假拉抬騙線！
    """)
