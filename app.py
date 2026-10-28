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

# 台灣標準時間 (UTC+8)
TW_TZ = datetime.timezone(datetime.timedelta(hours=8))

# 2026 年台股官方國定休市日清單 (週一至週五之休市日)
TWSE_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-02-27",
    "2026-04-03", "2026-04-06",
    "2026-05-01",
    "2026-06-19",
    "2026-09-25",
    "2026-10-09", "2026-10-26",
    "2026-12-25"
}

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

# ================= 精準檢查今日台股開休市狀態 =================
@st.cache_data(ttl=600)
def get_market_schedule_status():
    now_tw = datetime.datetime.now(TW_TZ)
    today_tw = now_tw.date()
    today_str = today_tw.strftime("%Y-%m-%d")
    curr_time = now_tw.time()

    if today_tw.weekday() >= 5:
        return False, f"⏸ **【台股休市提醒】今日 ({today_str}) 為週末例假休市，戰報與持股天數暫停推進。**"

    if today_str in TWSE_HOLIDAYS_2026:
        return False, f"⏸ **【台股休市提醒】今日 ({today_str}) 為台股國定假日休市，戰報與持股天數暫停推進。**"

    if curr_time < datetime.time(9, 0):
        return True, f"🕒 **【今日 ({today_str}) 正常開盤・盤前準備中】目前時間 {now_tw.strftime('%H:%M')} 尚未開盤（09:00 開市），下方顯示前一交易日收盤數據。**"
    elif curr_time <= datetime.time(13, 35):
        return True, f"🟢 **【今日 ({today_str}) 正常開盤・盤中交易進行中】建議於 13:20 尾盤確認突破收紅再執行進場，盤後 16:30 再掃描最新法人籌碼。**"
    else:
        return True, f"✅ **【今日 ({today_str}) 正常開盤・已收盤】16:30 證交所法人買賣超公布後，即可執行今日雷達戰報掃描。**"

# ================= 三維大盤環境風控 (證交所官方 API 權威校正版) =================
@st.cache_data(ttl=600)
def get_comprehensive_market_status():
    status_info = {
        "twii_c": 0.0, "twii_ma": 0.0, "twii_bull": True, "twii_date": "",
        "otc_c": 0.0, "otc_ma": 0.0, "otc_bull": True,
        "up_stocks": 0, "down_stocks": 0, "has_adl": False,
        "env_level": "GREEN",
        "env_title": "多頭健康",
        "env_desc": "",
        "budget_factor": 1.0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    now_tw = datetime.datetime.now(TW_TZ)

    # ------------------------------------------------------------------
    # 1. 加權指數 (^TWII)：結合 Yahoo 歷史日 K + 台灣證交所官方 FMTQIK 強制校正
    # ------------------------------------------------------------------
    df_twii = pd.DataFrame()
    try:
        t_twii = yf.Ticker("^TWII")
        h_twii = t_twii.history(period="3mo", interval="1d")
        if not h_twii.empty:
            if h_twii.index.tz is not None:
                h_twii.index = h_twii.index.tz_localize(None)
            h_twii.index = pd.to_datetime(h_twii.index).normalize()
            df_twii = h_twii[['Open', 'High', 'Low', 'Close']].dropna(subset=['Close']).copy()
            df_twii = df_twii[~df_twii.index.duplicated(keep='last')]
    except Exception:
        pass

    # 從台灣證交所官方 FMTQIK 抓取上個月與本月的「發行量加權股價指數」每日真實收盤價，解決 Yahoo 漏日或舊價問題
    prev_month_dt = (now_tw.replace(day=1) - datetime.timedelta(days=5))
    for query_dt in [prev_month_dt, now_tw]:
        d_str = query_dt.strftime("%Y%m%d")
        try:
            url_fmt = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={d_str}&response=json"
            res_fmt = requests.get(url_fmt, headers=headers, timeout=5)
            if res_fmt.status_code == 200:
                j_fmt = res_fmt.json()
                if j_fmt.get("stat") == "OK" and j_fmt.get("data"):
                    for row in j_fmt["data"]:
                        # row[0] 為民國日期 "115/10/28"，row[4] 為「發行量加權股價指數」收盤點數
                        parts = str(row[0]).strip().split("/")
                        if len(parts) == 3:
                            dt_idx = pd.Timestamp(year=int(parts[0]) + 1911, month=int(parts[1]), day=int(parts[2]))
                            c_val = float(str(row[4]).replace(",", "").strip())
                            if c_val > 1000:
                                if not df_twii.empty and dt_idx in df_twii.index:
                                    df_twii.loc[dt_idx, "Close"] = c_val
                                else:
                                    df_twii.loc[dt_idx, ["Open", "High", "Low", "Close"]] = [c_val, c_val, c_val, c_val]
        except Exception:
            pass

    # 備援：同時檢查證交所 OpenAPI FMTQIK
    try:
        res_open_fmt = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK", headers=headers, timeout=4)
        if res_open_fmt.status_code == 200:
            for item in res_open_fmt.json():
                d_raw = str(item.get("Date", "")).strip()
                taiex_raw = str(item.get("TAIEX", "") or item.get("發行量加權股價指數", "")).replace(",", "").strip()
                if len(d_raw) == 7 and d_raw.isdigit() and taiex_raw:
                    yr = int(d_raw[:3]) + 1911
                    mo = int(d_raw[3:5])
                    da = int(d_raw[5:7])
                    dt_idx = pd.Timestamp(year=yr, month=mo, day=da)
                    c_val = float(taiex_raw)
                    if c_val > 1000:
                        if not df_twii.empty and dt_idx in df_twii.index:
                            df_twii.loc[dt_idx, "Close"] = c_val
                        else:
                            df_twii.loc[dt_idx, ["Open", "High", "Low", "Close"]] = [c_val, c_val, c_val, c_val]
    except Exception:
        pass

    # 2. 抓取證交所 MI_INDEX 最新盤後統計 (同時取得最新加權收盤價 & 上市漲跌家數)
    try:
        url_twse_stat = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=MS"
        res_stat = requests.get(url_twse_stat, headers=headers, timeout=4)
        if res_stat.status_code == 200:
            data_stat = res_stat.json()
            stat_date_str = str(data_stat.get("date", "")).strip()
            stat_dt = None
            if len(stat_date_str) == 8 and stat_date_str.isdigit():
                stat_dt = pd.Timestamp(year=int(stat_date_str[:4]), month=int(stat_date_str[4:6]), day=int(stat_date_str[6:8]))

            for t in data_stat.get("tables", []):
                t_title = str(t.get("title", ""))
                # (A) 擷取「發行量加權股價指數」最新收盤價
                for row in t.get("data", []):
                    if len(row) >= 2 and "發行量加權股價指數" in str(row[0]):
                        idx_str = str(row[1]).replace(",", "").strip()
                        try:
                            idx_val = float(idx_str)
                            if idx_val > 1000 and stat_dt is not None:
                                if not df_twii.empty and stat_dt in df_twii.index:
                                    df_twii.loc[stat_dt, "Close"] = idx_val
                                else:
                                    df_twii.loc[stat_dt, ["Open", "High", "Low", "Close"]] = [idx_val, idx_val, idx_val, idx_val]
                        except Exception:
                            pass

                # (B) 擷取上市一般股票上漲/下跌家數
                if "漲跌證券數合計" in t_title:
                    for row in t.get("data", []):
                        if len(row) >= 3:
                            label = str(row[0]).strip()
                            stock_cell = str(row[2]).split("(")[0].replace(",", "").strip()
                            if "上漲" in label and stock_cell.isdigit():
                                val = int(stock_cell)
                                if 0 < val < 2500:
                                    status_info["up_stocks"] = val
                            elif "下跌" in label and stock_cell.isdigit():
                                val = int(stock_cell)
                                if 0 < val < 2500:
                                    status_info["down_stocks"] = val
            if status_info["up_stocks"] > 0 and status_info["down_stocks"] > 0:
                status_info["has_adl"] = True
    except Exception:
        pass

    # 計算加權指數最新收盤與 20MA (月線)
    if not df_twii.empty:
        df_twii = df_twii.sort_index()
        df_twii = df_twii[~df_twii.index.duplicated(keep='last')]
        if len(df_twii) >= 20:
            df_twii['MA20'] = df_twii['Close'].rolling(20).mean()
            last_row = df_twii.iloc[-1]
            c_p = float(last_row['Close'])
            ma_p = float(last_row['MA20'])
            op_p = float(last_row['Open'])
            status_info["twii_c"] = c_p
            status_info["twii_ma"] = ma_p
            status_info["twii_bull"] = (c_p >= ma_p) or (c_p > op_p * 1.008)
            status_info["twii_date"] = df_twii.index[-1].strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # 3. 櫃買指數 (^TWOII，若失敗則以 006201.TWO 富櫃50 作為備援)
    # ------------------------------------------------------------------
    for otc_sym in ["^TWOII", "006201.TWO"]:
        if status_info["otc_c"] > 0:
            break
        try:
            h_otc = yf.Ticker(otc_sym).history(period="3mo", interval="1d")
            if not h_otc.empty and len(h_otc) >= 20:
                h_otc = h_otc.dropna(subset=['Close']).copy()
                h_otc['MA20'] = h_otc['Close'].rolling(20).mean()
                last_otc = h_otc.iloc[-1]
                c_otc = float(last_otc['Close'])
                ma_otc = float(last_otc['MA20'])
                op_otc = float(last_otc['Open'])
                if c_otc > 0:
                    status_info["otc_c"] = c_otc
                    status_info["otc_ma"] = ma_otc
                    status_info["otc_bull"] = (c_otc >= ma_otc) or (c_otc > op_otc * 1.008)
        except Exception:
            pass

    twii_ok = status_info["twii_bull"]
    otc_ok = status_info["otc_bull"]
    up_s = status_info["up_stocks"]
    down_s = status_info["down_stocks"]
    is_poor_breadth = (down_s > up_s * 1.5) if status_info["has_adl"] else False

    if not twii_ok:
        status_info["env_level"] = "RED"
        status_info["env_title"] = "🔴 空頭反壓休眠（加權跌破月線）"
        status_info["env_desc"] = "加權指數處於月線反壓，依防禦 SOP 強制休眠，全市場雷達停止開新倉！"
        status_info["budget_factor"] = 0.0
    elif not otc_ok or is_poor_breadth:
        status_info["env_level"] = "YELLOW"
        status_info["env_title"] = "🟡 結構背離／拉積盤警戒（中小型股逆風）"
        reasons = []
        if not otc_ok: reasons.append("櫃買指數跌破月線")
        if is_poor_breadth: reasons.append(f"上市下跌家數 ({down_s}家) 明顯多於上漲家數 ({up_s}家)")
        status_info["env_desc"] = f"偵測到 {' 且 '.join(reasons)}。依 V2.8 實戰精煉規則：嚴格限買 👑 S 級（雙共振）標的、最多持倉 2 槽，單槽降載至 13.5 萬元！"
        status_info["budget_factor"] = 0.75
    else:
        status_info["env_level"] = "GREEN"
        status_info["env_title"] = "🟢 全面多頭健康（加權與櫃買同步站穩月線）"
        adl_str = f"（上市上漲 {up_s} 家 vs 下跌 {down_s} 家，市場廣度良好）" if status_info["has_adl"] else ""
        status_info["env_desc"] = f"權值與中小型股齊步走多{adl_str}，資金環境健康，允許正常槽位配置。"
        status_info["budget_factor"] = 1.0

    return status_info

def get_portfolio_capital_state(base_initial_capital, mkt_env_level):
    positions = load_json(POSITIONS_FILE, [])
    df_history = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame(columns=[
        "代號", "名稱", "進場日", "進場價", "出場日", "持股天數",
        "投入金額", "回收金額", "淨損益(NTD)", "部位A_損益%", "部位B_損益%",
        "綜合報酬率%", "出場原因"
    ])

    realized_pnl = float(df_history['淨損益(NTD)'].sum()) if not df_history.empty else 0.0
    current_net_capital = base_initial_capital + realized_pnl

    locked_capital = 0.0
    unrealized_pnl_total = 0.0
    for p in positions:
        tot_inv = float(p.get('total_invested', 0.0))
        if p.get('lot_a_sold'):
            rem_cost = max(0.0, tot_inv - float(p.get('lot_a_revenue', tot_inv * 0.5)))
            rem_shares = int(p.get('shares_b', 0))
        else:
            rem_cost = tot_inv
            rem_shares = int(p.get('shares_a', 0) + p.get('shares_b', 0))
        locked_capital += rem_cost
        curr_p = float(p.get('curr_price', p.get('entry_price', 0.0)))
        mkt_val = rem_shares * curr_p * (1 - FEE_RATE - TAX_RATE)
        unrealized_pnl_total += (mkt_val - rem_cost)

    available_cash = max(0.0, current_net_capital - locked_capital)
    live_total_equity = current_net_capital + unrealized_pnl_total

    if not df_history.empty:
        eq_curve = base_initial_capital + df_history['淨損益(NTD)'].cumsum()
        peak_eq = max(base_initial_capital, float(eq_curve.max()))
    else:
        peak_eq = base_initial_capital
    current_dd_pct = ((current_net_capital - peak_eq) / peak_eq) * 100

    is_recovery_mode = (current_dd_pct <= -6.0) or (mkt_env_level == "YELLOW")
    if mkt_env_level == "RED":
        max_allowed_slots = 0
        suggested_slot_budget = 0.0
        sizing_mode_label = "🔴 大盤空頭休眠期（暫停開新倉）"
    elif is_recovery_mode:
        max_allowed_slots = 2
        suggested_slot_budget = round((current_net_capital * 0.25) / 5000) * 5000
        sizing_mode_label = f"🛡️ 止血復原／黃燈防禦期（單倉上限 25%：NT$ {int(suggested_slot_budget):,d}｜最多 2 倉）"
    else:
        max_allowed_slots = 3
        suggested_slot_budget = round((current_net_capital / 3.0) / 5000) * 5000
        sizing_mode_label = f"🚀 標準三槽順風期（單倉上限 1/3：NT$ {int(suggested_slot_budget):,d}｜最多 3 倉）"

    remaining_slots = max(0, max_allowed_slots - len(positions))

    return {
        "positions": positions,
        "df_history": df_history,
        "base_initial_capital": base_initial_capital,
        "realized_pnl": realized_pnl,
        "current_net_capital": current_net_capital,
        "locked_capital": locked_capital,
        "available_cash": available_cash,
        "live_total_equity": live_total_equity,
        "current_dd_pct": current_dd_pct,
        "is_recovery_mode": is_recovery_mode,
        "max_allowed_slots": max_allowed_slots,
        "remaining_slots": remaining_slots,
        "suggested_slot_budget": suggested_slot_budget,
        "sizing_mode_label": sizing_mode_label
    }

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
    st.header("🎛️ 策略防禦與資金參數")
    with st.expander("💰 帳戶初始總本金設定", expanded=True):
        base_capital_input = st.number_input("初始投入總本金 (NTD)", value=600000, step=10000)
        st.caption("系統會自動以「初始本金 + 歷史已實現損益」計算您目前的現有實質資金（約 54.7 萬）與可用現金。")

    with st.expander("🛡️ 實盤防禦開關", expanded=True):
        use_market_filter = st.toggle("啟用三維大盤風控濾網", value=True)
        use_right_side = st.toggle("啟用右側過高確認", value=True)
        be_threshold = st.slider("動態保本啟動點 (+%)", 2.5, 6.0, 4.0, 0.5)
        stop_loss_pct = st.slider("硬停損比例 (-%)", 2.0, 8.0, 4.0, 0.5)
        take_profit_pct = st.slider("階段一停利目標 (+%)", 5.0, 15.0, 8.0, 0.5)

    with st.expander("⚙️ 技術面閥值設定 (V2.8)", expanded=False):
        buffer_pct = st.slider("均線回測緩衝 (%)", 0.5, 3.0, 1.8, 0.1)
        k_body_limit = st.slider("K棒實體振幅上限 (%)", 1.0, 5.0, 3.5, 0.5)
        rsi_upper_limit = st.slider("RSI(14) 多方蓄勢上限", 60.0, 75.0, 70.0, 1.0)
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

st.title("📈 短線成長股・量縮深蹲指示器 V2.8 (實戰精煉連動版)")

is_trading_today, schedule_msg = get_market_schedule_status()
st.info(schedule_msg)

mkt_env = get_comprehensive_market_status()
twii_date_tag = f" [基準日: {mkt_env['twii_date']}]" if mkt_env.get("twii_date") else ""
if mkt_env["env_level"] == "GREEN":
    st.success(f"**{mkt_env['env_title']}**{twii_date_tag} ｜ 加權：{mkt_env['twii_c']:,.0f} (月線 {mkt_env['twii_ma']:,.0f}) ｜ 櫃買指標：{mkt_env['otc_c']:,.1f} (月線 {mkt_env['otc_ma']:,.1f})\n\n{mkt_env['env_desc']}")
elif mkt_env["env_level"] == "YELLOW":
    st.warning(f"**{mkt_env['env_title']}**{twii_date_tag} ｜ 加權：{mkt_env['twii_c']:,.0f} (月線 {mkt_env['twii_ma']:,.0f}) ｜ 櫃買指標：{mkt_env['otc_c']:,.1f} (月線 {mkt_env['otc_ma']:,.1f})\n\n⚠️ {mkt_env['env_desc']}")
else:
    st.error(f"**{mkt_env['env_title']}**{twii_date_tag} ｜ 加權：{mkt_env['twii_c']:,.0f} (月線 {mkt_env['twii_ma']:,.0f}) ｜ 櫃買指標：{mkt_env['otc_c']:,.1f} (月線 {mkt_env['otc_ma']:,.1f})\n\n🛑 {mkt_env['env_desc']}")

cap_state = get_portfolio_capital_state(float(base_capital_input), mkt_env["env_level"])

tab_radar, tab_tracker, tab_batch, tab_single, tab_watchlist, tab_docs = st.tabs([
    "📡 今日雷達獵股戰報",
    "📊 實盤追蹤與績效帳本 (方案B)",
    "🚀 自選名單批次體檢", 
    "🔍 個股深入技術體檢", 
    "📋 自選股票清單總覽 (TAB 5)",
    "📖 策略手冊與 SOP 指南 V2.8"
])

# ================= TAB 0: 每日雷達戰報 =================
with tab_radar:
    c_title, c_scan = st.columns([3, 1.3])
    with c_title:
        st.subheader("📡 全自動獵股雷達・今日盤後戰報 (V2.8 連動方案B資金版)")
    with c_scan:
        btn_manual_scan = st.button("⚡ 手動立即掃描雷達", type="primary", use_container_width=True)

    if btn_manual_scan:
        with st.spinner("🚀 正在同步刷新證交所大盤點數、統計近 7 日投信買超，並產出嚴格技術雷達戰報... (約需 15~25 秒)"):
            try:
                # 強制清除大盤與行事曆快取，確保重新抓取證交所最新指數
                st.cache_data.clear()

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

                st.success("✅ 大盤官方指數刷新、近 7 日投信累積買超與 V2.8 嚴格雷達掃描已完成！")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 手動掃描異常: {e}")

    st.markdown("#### 🧭 【方案 B 資金連動・明日建倉額度與順序決策面板】")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("💰 現有實質總本金", f"NT$ {int(cap_state['current_net_capital']):,d}", delta=f"已實現 {int(cap_state['realized_pnl']):+,d} 元")
    rc2.metric("💵 現有可用現金池", f"NT$ {int(cap_state['available_cash']):,d}", delta=f"在倉鎖定 {int(cap_state['locked_capital']):,d} 元", delta_color="off")
    rc3.metric("🏦 可再開倉槽位", f"剩 {cap_state['remaining_slots']} 倉", delta=f"目前在倉 {len(cap_state['positions'])} / 上限 {cap_state['max_allowed_slots']} 倉", delta_color="off")
    rc4.metric("🎯 單一倉位建議上限", f"NT$ {int(cap_state['suggested_slot_budget']):,d}", delta=f"-4%最大風險 NT$ {int(cap_state['suggested_slot_budget']*0.04):,d}", delta_color="off")
    st.caption(f"📌 **當前資金配置模式**：{cap_state['sizing_mode_label']}（建議於 13:20 尾盤確認突破收紅或守穩均線再行建倉，並善用盤中零股控制金額不超標）")

    st.write("---")
    report = load_json(REPORT_FILE, {})
    if not report:
        st.info("💡 目前尚未有雷達報告。每日 16:30 GitHub Actions 會自動更新產出！")
    else:
        cr1, cr2, cr3 = st.columns(3)
        cr1.metric("最後掃描時間", report.get("update_time", "未知"))
        cr2.metric("7日投信籌碼/基本面留存", f"{report.get('total_funnel', 0)} 檔")
        cr3.metric("🎯 符合嚴格深蹲進場點", f"{report.get('total_squat', 0)} 檔")
        
        squat_stocks = [s for s in report.get("stocks", []) if s.get("is_squat")]
        squat_stocks.sort(key=lambda x: (x.get("trust_7d", x.get("trust_buy", 0)), x.get("trust_buy", 0)), reverse=True)

        st.write("---")
        
        if mkt_env["env_level"] == "RED" and use_market_filter:
            st.error("🛑 **【風控攔截】：加權指數跌破月線，依防禦 SOP 建議全市場雷達強制休眠，暫不建新倉！**")
        elif squat_stocks:
            active_codes = {str(p['code']).split('.')[0].strip() for p in cap_state['positions']}
            rem_slots = cap_state['remaining_slots']
            rem_cash = cap_state['available_cash']
            slot_cap = cap_state['suggested_slot_budget']
            seen_industries = {translate_industry(p.get('industry', '')) for p in cap_state['positions'] if p.get('industry')}

            allocation_plan = []
            card_advice_map = {}
            assigned_count = 0

            for idx, s in enumerate(squat_stocks):
                s_code = str(s.get('code', '')).split('.')[0].strip()
                s_name = s.get('name', '')
                s_ind = s.get('industry', '電子科技')
                badge = s.get('grade_badge', '🟢 標準深蹲 (B級)')
                t_7d = int(s.get('trust_7d', s.get('trust_buy', 0)))
                t_1d = int(s.get('trust_1d', s.get('trust_buy', 0)))
                trig_p = float(s.get('right_trigger', s.get('high', s.get('close', 100.0))))

                is_s_grade = "S級" in badge
                is_b_grade = "B級" in badge

                if s_code in active_codes:
                    order_tag = "✅ 已在倉持有"
                    alloc_budget = 0
                    shares_str = "無需加碼"
                    note_str = "已在方案 B 持倉監控中"
                elif mkt_env["env_level"] == "YELLOW" and not is_s_grade:
                    order_tag = f"⏸ 黃燈暫緩 (第{idx+1}名)"
                    alloc_budget = 0
                    shares_str = "0 股 (建議觀望)"
                    note_str = "🟡 黃燈拉積盤嚴格限買 👑 S級，A/B級建議略過防誘多"
                elif mkt_env["env_level"] == "GREEN" and is_b_grade and cap_state['is_recovery_mode']:
                    order_tag = f"⏸ 復原期暫緩 (第{idx+1}名)"
                    alloc_budget = 0
                    shares_str = "0 股 (建議觀望)"
                    note_str = "🛡️ 帳戶止血復原期優先鎖定 S / A 級高動能股"
                elif s_ind in seen_industries:
                    order_tag = f"⚠️ 同族群避險候補 (第{idx+1}名)"
                    alloc_budget = 0
                    shares_str = "0 股 (二擇一)"
                    note_str = f"與前序標的同屬【{s_ind}】，依分散原則不重複重押"
                elif assigned_count >= rem_slots:
                    order_tag = f"⏳ 備取候補 #{assigned_count - rem_slots + 1} (第{idx+1}名)"
                    alloc_budget = 0
                    shares_str = "等前序未突破才遞補"
                    note_str = f"可用槽位已滿 ({cap_state['max_allowed_slots']}倉上限)，僅作盤中遞補"
                elif rem_cash < 35000:
                    order_tag = "⏳ 現金不足暫緩"
                    alloc_budget = 0
                    shares_str = "可用現金低於 3.5 萬"
                    note_str = "請待在倉部位停利/結案回收現金後再建倉"
                else:
                    assigned_count += 1
                    medal = "🥇 第 1 優先建倉" if assigned_count == 1 else (f"🥈 第 {assigned_count} 優先建倉" if assigned_count == 2 else f"🥉 第 {assigned_count} 優先建倉")
                    order_tag = medal
                    alloc_budget = min(slot_cap, rem_cash)
                    est_total_shares = int(alloc_budget / (trig_p * (1 + FEE_RATE))) if trig_p > 0 else 0
                    est_total_shares = (est_total_shares // 10) * 10
                    lots_cnt = est_total_shares // 1000
                    odd_cnt = est_total_shares % 1000
                    est_actual_cost = int(est_total_shares * trig_p * (1 + FEE_RATE))
                    if lots_cnt > 0 and odd_cnt > 0:
                        shares_str = f"{est_total_shares:,d} 股 ({lots_cnt}張 + {odd_cnt}零股)"
                    elif lots_cnt > 0:
                        shares_str = f"{est_total_shares:,d} 股 (整 {lots_cnt} 張)"
                    else:
                        shares_str = f"{odd_cnt} 股 (盤中零股)"
                    rem_cash -= est_actual_cost
                    seen_industries.add(s_ind)
                    note_str = f"預估扣款 NT$ {est_actual_cost:,d}｜-4%停損價 ${trig_p*0.96:.1f} (約虧 {int(est_actual_cost*0.04):,d}元)"
                    alloc_budget = est_actual_cost

                plan_item = {
                    "建倉順位建議": order_tag,
                    "標的": f"{s_name} ({s_code})",
                    "動能評級": badge,
                    "投信7日累積": f"+{t_7d:,d} 張",
                    "投信單日": f"+{t_1d:,d} 張",
                    "產業類別": s_ind,
                    "突破確認價": f"${trig_p:.1f}",
                    "建議投入金額": f"NT$ {int(alloc_budget):,d}" if alloc_budget > 0 else "NT$ 0",
                    "建議買進股數 (整張+零股)": shares_str,
                    "風控與操作說明": note_str
                }
                allocation_plan.append(plan_item)
                card_advice_map[s_code] = plan_item

            st.markdown("##### 📋 【明日建倉順序與資金配置建議總表（依回測『投信 7 日累積買超』由大到小排序）】")
            st.dataframe(pd.DataFrame(allocation_plan), use_container_width=True, hide_index=True)

            if mkt_env["env_level"] == "YELLOW":
                st.warning("⚠️ **【V2.8 黃燈拉積盤嚴格風控】：櫃買跌破月線或下跌家數偏多，系統已自動將 A 級與 B 級標記為「黃燈暫緩」，僅放行 👑 S 級雙共振標的，避免假突破誘多！**")

            st.write("---")
            st.markdown(f"##### 🎯 【今日深蹲候選個股詳細卡片（共 {len(squat_stocks)} 檔）】")
            for s in squat_stocks:
                s_name = s.get('name', '')
                s_code = str(s.get('code', '')).split('.')[0].strip()
                right_trigger_p = s.get('right_trigger', s.get('high', s['close']))
                badge = s.get('grade_badge', '🟢 標準深蹲')
                t_7d = int(s.get('trust_7d', s.get('trust_buy', 0)))
                t_1d = int(s.get('trust_1d', s.get('trust_buy', 0)))
                adv = card_advice_map.get(s_code, {})
                
                with st.container():
                    c1, c2, c3, c4 = st.columns([2.3, 1.9, 2.0, 2.1])
                    c1.markdown(f"### **{s_name} ({s_code})**")
                    c1.markdown(f"**評級**：`{badge}`")
                    c1.caption(f"收盤：${s['close']} ｜ 支撐：**{s['support']}** ｜ 股本：{s.get('cap', '-')}億 ｜ 類股：{s.get('industry', '電子科技')}")
                    
                    c2.write(f"• **🔥 投信 7 日累積**：`+{t_7d:,d}` 張")
                    c2.write(f"• **📊 投信最新單日**：`+{t_1d:,d}` 張")
                    c2.write(f"• **📈 月營收 YoY**：`+{s['rev_yoy']}%`")
                    
                    c3.write(f"• **RSI (5T / 14T)**：`{s.get('rsi5', '-')}` / `{s.get('rsi', '-')}`")
                    c3.write(f"• **KD 姿態**：`{s.get('kd_desc', '-')}`")
                    c3.write(f"• **MACD 動能**：`{s.get('macd_desc', '-')}`")
                    
                    c4.markdown(f"**🧭 建倉建議**：`{adv.get('建倉順位建議', '-')}`")
                    c4.write(f"• **🎯 右側突破價**：`突破 ${right_trigger_p}`")
                    c4.write(f"• **建議股數**：`{adv.get('建議買進股數 (整張+零股)', '-')}`")
                    
                    label_key = f"{s_name} ({s_code})"
                    if label_key not in st.session_state.watchlist:
                        if c4.button(f"📥 加到自選名單", key=f"radar_add_{s_code}"):
                            st.session_state.watchlist[label_key] = s['ticker']
                            save_json(WATCHLIST_FILE, st.session_state.watchlist)
                            st.success(f"已將 {label_key} 加入觀察清單！")
                            st.rerun()
                        
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
            st.info("⏸ 今日 7 日投信籌碼與基本面強勢股尚未同時滿足「量縮深蹲 ＋ 嚴格雙RSI(5T>=40, 14T 45~70)」，建議維持現金觀望。")

# ================= TAB 1: 實盤追蹤與績效帳本 =================
with tab_tracker:
    st.subheader("📊 方案 B：前向實盤追蹤流水帳本 (Forward-Walk Paper Trading)")
    
    positions = cap_state["positions"]
    df_history = cap_state["df_history"]
    total_trades = len(df_history)

    if total_trades > 0:
        wins = df_history[df_history['綜合報酬率%'] > 0]
        win_rate = len(wins) / total_trades * 100
        total_pnl = cap_state["realized_pnl"]
        avg_days = df_history['持股天數'].mean()
    else:
        win_rate, total_pnl, avg_days = 0.0, 0.0, 0.0

    st.markdown("#### 💰 【帳戶資金與現有現金水位即時總覽】")
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("1️⃣ 初始投入本金", f"NT$ {int(cap_state['base_initial_capital']):,d}")
    f2.metric("2️⃣ 現有實質總本金 (含已實現損益)", f"NT$ {int(cap_state['current_net_capital']):,d}", delta=f"{int(total_pnl):+,d} 元 ({cap_state['current_dd_pct']:+.2f}%)")
    f3.metric("3️⃣ 💵 現有可用現金 (可建倉餘額)", f"NT$ {int(cap_state['available_cash']):,d}", delta=f"在倉佔用 NT$ {int(cap_state['locked_capital']):,d}", delta_color="off")
    f4.metric("4️⃣ 單一倉位建議上限", f"NT$ {int(cap_state['suggested_slot_budget']):,d}", delta=f"可再開 {cap_state['remaining_slots']} 倉", delta_color="off")
    st.info(f"💡 **資金控管狀態**：{cap_state['sizing_mode_label']} ｜ 帳戶即時總淨值（含在倉未實現浮盈虧）：**NT$ {int(cap_state['live_total_equity']):,d}**")

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("在倉持股", f"{len(positions)} / {cap_state['max_allowed_slots']} 檔")
    m2.metric("歷史已結案", f"{total_trades} 筆")
    m3.metric("歷史交易勝率", f"{win_rate:.1f} %")
    m4.metric("平均持股天數", f"{avg_days:.1f} 天")
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
        st.info(f"目前無在倉持股，可用現金 NT$ {int(cap_state['available_cash']):,d} (100%) 待命中。")

    # 1. 手動快速補登開倉
    with st.expander("➕ 手動快速補登開倉（自動套用當前建議單倉上限計算股數）", expanded=False):
        default_slot_cap = cap_state['suggested_slot_budget'] if cap_state['suggested_slot_budget'] > 0 else 135000.0
        st.info(f"💡 依您目前現有實質本金 NT$ {int(cap_state['current_net_capital']):,d} 與風控狀態，本筆建議單倉預算上限為 **NT$ {int(default_slot_cap):,d}**（可用現金剩餘 NT$ {int(cap_state['available_cash']):,d}）。")
            
        c_add1, c_add2, c_add3 = st.columns(3)
        with c_add1:
            in_code = st.text_input("股票代號 (4碼)", value="3017", placeholder="例如：3017 或 2368", key="in_manual_code")
        with c_add2:
            in_buy_price = st.number_input("實際買進均價 (NTD)", value=100.0, step=0.1, key="in_manual_price")
        with c_add3:
            in_entry_date = st.text_input("進場日期 (YYYY-MM-DD)", value=datetime.datetime.now(TW_TZ).strftime("%Y-%m-%d"), key="in_manual_date")

        usable_budget = min(default_slot_cap, cap_state['available_cash']) if cap_state['available_cash'] > 0 else default_slot_cap
        est_shares = int(usable_budget / (float(in_buy_price) * (1 + FEE_RATE))) if float(in_buy_price) > 0 else 1000
        est_shares = (est_shares // 10) * 10
        
        c_add4, c_add5 = st.columns(2)
        with c_add4:
            in_custom_shares = st.number_input("實際買進總股數 (股，支援整張+零股)", value=max(10, est_shares), step=100, key="in_manual_shares")
        with c_add5:
            est_cost = int(float(in_custom_shares) * float(in_buy_price) * (1 + FEE_RATE))
            in_custom_cost = st.number_input("實際投入總金額 (NTD，可填對帳單實際扣款)", value=est_cost, step=1000, key="in_manual_cost")

        if in_custom_cost > default_slot_cap * 1.05:
            st.warning(f"⚠️ 提醒：您輸入的投入金額 (NT$ {int(in_custom_cost):,d}) 已超過目前單倉建議上限 (NT$ {int(default_slot_cap):,d})，建議透過盤中零股縮減股數以控制單筆最大停損金額！")

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

    # 2. 校正在倉持股資訊
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
        st.info("💡 支援全數清倉與「部分減倉」！平倉回收的資金將立即回流至「現有可用現金池」。")
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
                default_reasons = [
                    "🛡️ 策略風控減碼 (降持股)",
                    "🎯 手動獲利了結",
                    "🛑 手動停損離場",
                    "⏳ 手動換股平倉",
                    "🏆 達標全數出場",
                    "🛡️ 手動保本出場"
                ]
                user_exit_reason = st.selectbox("選擇出場/減碼原因", default_reasons, key="sel_exit_reason")

            if st.button("確認執行平倉／減碼並寫入帳本", type="primary", use_container_width=True):
                if matched_pos:
                    today_str = datetime.datetime.now(TW_TZ).strftime("%Y-%m-%d")
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
                        st.success(f"✅ 已成功【部分減碼】{target_to_close} {sell_cnt:,d} 股！回收 NT$ {int(net_rev):,d}，損益：NT$ {int(net_pnl):+,d} ({roi_pct:+.2f}%)。")
                    
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
                restored_entry_d = st.text_input("指定還原後的正確進場日", value=str(cand_row['進場日']).strip(), key="in_rest_d")
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
                    st.success(f"✅ 已成功將 {cand_row['名稱']} ({cand_code}) 撤銷結案並恢復持倉！")
                    st.rerun()

            with c_btn_clean:
                if st.button("🗑️ 僅從歷史明細刪除此紀錄 (不恢復持倉)", type="secondary", use_container_width=True):
                    cand_entry_raw = str(cand_row['進場日']).strip()
                    df_history = df_history[~((df_history['代號'].astype(str).str.split('.').str[0].str.strip() == cand_code) & 
                                              (df_history['進場日'].astype(str).str.strip() == cand_entry_raw))].reset_index(drop=True)
                    save_history_csv(df_history)
                    st.success(f"✅ 已從歷史明細表中刪除 {cand_row['名稱']}！")
                    st.rerun()

    # 6. 校正歷史結案紀錄
    if not df_history.empty:
        with st.expander("✏️ 校正歷史結案紀錄（修改實際賣出價格與損益精算）", expanded=False):
            hist_edit_options = [f"第{i+1}筆：{r['名稱']} ({r['代號']}) - 進場日:{r['進場日']} - 目前損益:{r['綜合報酬率%']}%" for i, r in df_history.iterrows()]
            sel_edit_hist_item = st.selectbox("選擇要修正賣出價格的結案交易", options=hist_edit_options, key="sel_edit_hist_target")
            sel_edit_idx = hist_edit_options.index(sel_edit_hist_item)
            target_hist_row = df_history.iloc[sel_edit_idx]

            c_h1, c_h2, c_h3 = st.columns(3)
            with c_h1:
                entry_p_hist = float(target_hist_row['進場價'])
                cost_hist = float(target_hist_row['投入金額'])
                est_shares_hist = int(cost_hist / (entry_p_hist * (1 + FEE_RATE))) if entry_p_hist > 0 else 1000
                st.caption(f"進場價：**${entry_p_hist}** ｜ 投入本金：**NT$ {int(cost_hist):,d}**")
                st.write(f"原始估計股數：`{est_shares_hist:,d}` 股")
            with c_h2:
                curr_exit_p_est = round(float(target_hist_row['回收金額']) / (est_shares_hist * (1 - FEE_RATE - TAX_RATE)), 1) if est_shares_hist > 0 else entry_p_hist
                new_actual_exit_p = st.number_input("券商真實賣出成交均價 (NTD)", value=float(curr_exit_p_est), step=0.1, key="in_actual_exit_p")
            with c_h3:
                new_hist_reason = st.text_input("出場原因說明", value=str(target_hist_row['出場原因']), key="in_actual_exit_reason")

            if st.button("確認儲存校正數值並重新計算歷史帳本", type="primary", use_container_width=True, key="btn_save_hist_edit"):
                new_p = float(new_actual_exit_p)
                new_gross_rev = est_shares_hist * new_p
                new_net_rev = new_gross_rev * (1 - FEE_RATE - TAX_RATE)
                new_net_pnl = new_net_rev - cost_hist
                new_roi = (new_net_pnl / cost_hist * 100) if cost_hist > 0 else 0.0

                df_history.at[sel_edit_idx, '回收金額'] = int(new_net_rev)
                df_history.at[sel_edit_idx, '淨損益(NTD)'] = int(new_net_pnl)
                df_history.at[sel_edit_idx, '部位A_損益%'] = round(new_roi, 2)
                df_history.at[sel_edit_idx, '部位B_損益%'] = round(new_roi, 2)
                df_history.at[sel_edit_idx, '綜合報酬率%'] = round(new_roi, 2)
                df_history.at[sel_edit_idx, '出場原因'] = new_hist_reason.strip()

                save_history_csv(df_history)
                st.success(f"✅ 已成功將 {target_hist_row['名稱']} 的賣出價格校正為 ${new_p:.1f}！")
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
        df_plot['累計回收'] = df_plot['回收金額'].cumsum()
        df_plot['累計淨損益'] = df_plot['淨損益(NTD)'].cumsum()
        df_plot['帳戶實質本金水線'] = cap_state['base_initial_capital'] + df_plot['累計淨損益']

        total_invested_rolling = df_plot['投入金額'].sum()
        total_pnl_val = df_plot['淨損益(NTD)'].sum()
        total_roi_val = (total_pnl_val / total_invested_rolling * 100) if total_invested_rolling > 0 else 0.0
        
        wins_df = df_plot[df_plot['淨損益(NTD)'] > 0]
        losses_df = df_plot[df_plot['淨損益(NTD)'] <= 0]
        avg_win_amt = wins_df['淨損益(NTD)'].mean() if not wins_df.empty else 0
        avg_loss_amt = abs(losses_df['淨損益(NTD)'].mean()) if not losses_df.empty else 1
        profit_factor = (avg_win_amt / avg_loss_amt) if avg_loss_amt > 0 else 0.0

        kpi_r1_c1, kpi_r1_c2, kpi_r1_c3 = st.columns(3)
        kpi_r1_c1.metric("💰 現有實質總本金", f"NT$ {int(cap_state['current_net_capital']):,d}", delta=f"初始 {int(cap_state['base_initial_capital']):,d} 元", delta_color="off")
        kpi_r1_c2.metric("累計滾動成交成本", f"NT$ {int(total_invested_rolling):,d}")
        kpi_r1_c3.metric("累積實現損益", f"NT$ {int(total_pnl_val):+,d}", delta=f"佔滾動成本 {total_roi_val:+.2f}%")

        kpi_r2_c1, kpi_r2_c2 = st.columns(2)
        kpi_r2_c1.metric("實戰賺賠比 (PF)", f"{profit_factor:.2f}")
        kpi_r2_c2.metric("均贏 / 均虧", f"{int(avg_win_amt):,d} / {int(avg_loss_amt):,d}")

        st.write("---")

        st.markdown("##### 📈 1. 帳戶實質總本金水位 vs. 累計實現損益走勢")
        fig1 = make_subplots(specs=[[{"secondary_y": True}]])
        fig1.add_trace(
            go.Bar(
                x=df_plot['交易序號'],
                y=df_plot['帳戶實質本金水線'],
                name="實質總本金水位",
                marker_color='rgba(100, 149, 237, 0.35)',
                text=[f"NT${int(v):,d}" for v in df_plot['帳戶實質本金水線']],
                textposition="inside"
            ),
            secondary_y=False
        )
        pnl_color = '#eb4034' if total_pnl_val >= 0 else '#2ba84a'
        fig1.add_trace(
            go.Scatter(
                x=df_plot['交易序號'],
                y=df_plot['累計淨損益'],
                name="累計淨盈虧",
                mode='lines+markers+text',
                line=dict(color=pnl_color, width=3),
                marker=dict(size=8),
                text=[f"{v:+,d}" for v in df_plot['累計淨損益']],
                textposition="top center"
            ),
            secondary_y=True
        )
        fig1.update_yaxes(title_text="實質總本金 (NTD)", secondary_y=False, showgrid=False)
        fig1.update_yaxes(title_text="累計淨損益 (NTD)", secondary_y=True, showgrid=True)
        fig1.update_layout(height=340, margin=dict(l=5, r=5, t=25, b=25), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified")
        st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})

        st.markdown("##### 📊 2. 每筆交易實質損益與報酬率")
        bar_colors = ['#eb4034' if x >= 0 else '#2ba84a' for x in df_plot['淨損益(NTD)']]
        bar_texts = [f"{amt:+,d} ({roi:+.1f}%)" for amt, roi in zip(df_plot['淨損益(NTD)'], df_plot['綜合報酬率%'])]
        fig2 = go.Figure(go.Bar(x=df_plot['交易序號'], y=df_plot['淨損益(NTD)'], marker_color=bar_colors, text=bar_texts, textposition='outside'))
        fig2.update_layout(height=300, margin=dict(l=5, r=5, t=25, b=25), yaxis_title="淨損益 (NTD)")
        st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

        st.markdown("##### 🍩 3. SOP 出場原因結構佔比")
        reason_counts = df_plot['出場原因'].apply(lambda x: str(x).split(' (')[0]).value_counts()
        fig3 = go.Figure(go.Pie(labels=reason_counts.index, values=reason_counts.values, hole=0.45, textinfo='label+percent'))
        fig3.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", yanchor="bottom", y=-0.2))
        st.plotly_chart(fig3, use_container_width=True, config={'displayModeBar': False})

        st.markdown("##### ⏱️ 4. 持股天數與獲利效率對照")
        fig4 = go.Figure(go.Bar(x=df_plot['交易序號'], y=df_plot['綜合報酬率%'], marker_color=bar_colors, text=[f"{d}天 : {r:+.1f}%" for d, r in zip(df_plot['持股天數'], df_plot['綜合報酬率%'])], textposition='auto'))
        fig4.update_layout(height=280, margin=dict(l=5, r=5, t=25, b=25), yaxis_title="報酬率 (%)")
        st.plotly_chart(fig4, use_container_width=True, config={'displayModeBar': False})

    else:
        st.info("尚無結案交易紀錄，等待排程每日 16:30 自動追蹤結算，或可使用上方「手動平倉結案」自訂出場。")

# ================= TAB 2: 自選名單批次體檢 =================
with tab_batch:
    st.subheader("📋 自選股今日深蹲訊號掃描 (V2.8 嚴格共振版)")
    st.write(f"目前自選名單中共有 **{len(st.session_state.watchlist)}** 檔標的（要求 `RSI(5) >= 40` 且 `45 <= RSI(14) <= {int(rsi_upper_limit)}`）。")
    
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
                df['RSI5'] = 100 - (100 / (1 + (gain.ewm(com=4, adjust=False).mean() / (loss.ewm(com=4, adjust=False).mean() + 1e-9))))
                df['RSI14'] = 100 - (100 / (1 + (gain.ewm(com=13, adjust=False).mean() / (loss.ewm(com=13, adjust=False).mean() + 1e-9))))

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

                now_t = datetime.datetime.now(TW_TZ).time()
                is_trading_hours = (datetime.time(9, 0) <= now_t <= datetime.time(13, 35))
                if is_trading_hours and len(df) >= 2 and df.index[-1].date() == datetime.datetime.now(TW_TZ).date():
                    latest, prev = df.iloc[-2], df.iloc[-3]
                else:
                    latest, prev = df.iloc[-1], df.iloc[-2]

                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])
                rsi5_val, rsi14_val = float(latest['RSI5']), float(latest['RSI14'])
                k_val, d_val, prev_k = float(latest['K']), float(latest['D']), float(prev['K'])
                dif_val, macd_sig_val, osc_val, prev_osc = float(latest['DIF']), float(latest['MACD_SIG']), float(latest['OSC']), float(prev['OSC'])

                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                buf = 1 + (buffer_pct / 100)
                touch_10 = (low <= ma10 * buf) and (close >= ma10 * 0.99)
                touch_20 = (low <= ma20 * buf) and (close >= ma20 * 0.99)
                cond_support = touch_10 or touch_20
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit
                cond_rsi = (rsi5_val >= 40.0) and (45.0 <= rsi14_val <= rsi_upper_limit)

                support_name = "10MA" if touch_10 else ("20MA" if touch_20 else "未回踩")

                if cond_trend and cond_support and cond_vol and cond_k and cond_rsi:
                    cond_macd_res = (dif_val > 0) and (macd_sig_val > 0) and (osc_val > prev_osc)
                    cond_kd_res = (30.0 <= k_val <= 70.0) and (k_val > prev_k) and (k_val >= d_val)
                    if cond_macd_res and cond_kd_res: badge = "👑 S級 (真雙共振)"
                    elif cond_macd_res or cond_kd_res: badge = "🎯 A級 (單共振)"
                    else: badge = "🟢 B級 (純深蹲)"

                    right_trigger = high
                    sl_p = right_trigger * (1 - stop_loss_pct / 100)
                    tp_p = right_trigger * (1 + take_profit_pct / 100)
                    rec_shares = (int(cap_state['suggested_slot_budget'] / (right_trigger * (1 + FEE_RATE))) // 10) * 10 if right_trigger > 0 else 0
                    
                    triggered_list.append({
                        "股票標的": label, "動能評級": badge, "最新收盤": f"${close:,.1f}",
                        "RSI (5T/14T)": f"{rsi5_val:.1f} / {rsi14_val:.1f}", "回踩均線": support_name,
                        "🎯 明日確認進場": f"突破 ${right_trigger:,.1f}",
                        "建議買進股數": f"{rec_shares:,d} 股",
                        f"硬停損 (-{stop_loss_pct}%)": f"${sl_p:,.1f}",
                        f"階段一停利 (+{take_profit_pct}%)": f"${tp_p:,.1f}"
                    })
                else:
                    reasons = []
                    if not cond_trend: reasons.append("均線非多頭")
                    if not cond_support: reasons.append("未回踩支撐")
                    if not cond_vol: reasons.append("未達量縮")
                    if not cond_k: reasons.append(f"實體 > {k_body_limit}%")
                    if not cond_rsi: reasons.append(f"RSI未達標(5T={rsi5_val:.1f}, 14T={rsi14_val:.1f})")
                    waiting_list.append({"股票標的": label, "最新收盤": f"${close:,.1f}", "未符合原因": "、".join(reasons)})
            except Exception: pass
            progress_bar.progress((idx + 1) / total_items)

        progress_text.empty()
        progress_bar.empty()

        if triggered_list:
            st.success(f"🎯 **自選股中今日共發現 {len(triggered_list)} 檔符合嚴格深蹲條件！**")
            st.dataframe(pd.DataFrame(triggered_list), use_container_width=True, hide_index=True)
        else:
            st.warning(" 今日自選股中無標的符合深蹲條件。")

        if waiting_list:
            with st.expander("👀 檢視其餘觀察中股票狀態", expanded=False):
                st.dataframe(pd.DataFrame(waiting_list), use_container_width=True, hide_index=True)

# ================= TAB 3: 個股深入技術體檢 =================
with tab_single:
    st.subheader("🔍 個股深入技術診斷與三指標共振分析 (V2.8)")
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
                df['RSI5'] = 100 - (100 / (1 + (gain.ewm(com=4, adjust=False).mean() / (loss.ewm(com=4, adjust=False).mean() + 1e-9))))
                df['RSI14'] = 100 - (100 / (1 + (gain.ewm(com=13, adjust=False).mean() / (loss.ewm(com=13, adjust=False).mean() + 1e-9))))

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

                latest, prev = df.iloc[-1], df.iloc[-2]
                close, vol, low, high, open_p = float(latest['Close']), float(latest['Volume']), float(latest['Low']), float(latest['High']), float(latest['Open'])
                ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
                vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])
                rsi5_val, rsi14_val = float(latest['RSI5']), float(latest['RSI14'])
                k_val, d_val, prev_k = float(latest['K']), float(latest['D']), float(prev['K'])
                dif_val, macd_sig_val, osc_val, prev_osc = float(latest['DIF']), float(latest['MACD_SIG']), float(latest['OSC']), float(prev['OSC'])

                target_ma = ma10 if "10MA" in target_ma_choice else ma20
                buf = 1 + (buffer_pct / 100)
                cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df['MA20'].iloc[-4])
                cond_support = (low <= target_ma * buf) and (close >= target_ma * 0.99)
                cond_vol = (vol < vol_ma5) and (vol < vol_ma20) if "嚴格" in vol_mode else (vol < vol_ma5) or (vol < vol_ma20)
                cond_k = (abs(close - open_p) / open_p * 100) <= k_body_limit
                cond_rsi = (rsi5_val >= 40.0) and (45.0 <= rsi14_val <= rsi_upper_limit)
                cond_macd_res = (dif_val > 0) and (macd_sig_val > 0) and (osc_val > prev_osc)
                cond_kd_res = (30.0 <= k_val <= 70.0) and (k_val > prev_k) and (k_val >= d_val)
                is_ready = cond_trend and cond_support and cond_vol and cond_k and cond_rsi

                c_out1, c_out2, c_out3, c_out4 = st.columns(4)
                c_out1.metric("診斷收盤基準", f"${close:,.1f}")
                c_out2.metric("RSI (5T / 14T)", f"{rsi5_val:.1f} / {rsi14_val:.1f}")
                c_out3.metric("KD (K / D)", f"{k_val:.1f} / {d_val:.1f}", delta="金叉向上✅" if cond_kd_res else "未共振")
                c_out4.metric("MACD 柱狀體 (OSC)", f"{osc_val:.2f}", delta="動能遞增✅" if cond_macd_res else "動能收斂")

                if is_ready:
                    sl_p = high * (1 - stop_loss_pct / 100)
                    tp_p = high * (1 + take_profit_pct / 100)
                    rec_shares = (int(cap_state['suggested_slot_budget'] / (high * (1 + FEE_RATE))) // 10) * 10 if high > 0 else 0
                    st.success(f"🎯 **【{display_title} 觸發訊號】：符合量縮深蹲 ＋ 嚴格雙RSI蓄勢門檻！**")
                    st.markdown(f"""
                    * 🎯 **明日右側確認進場價**：`突破今日高點 ${high:,.1f}（建議於 13:20 尾盤確認收紅買進）`
                    * 💰 **依方案 B 資金建議股數**：`{rec_shares:,d} 股（預算上限 NT$ {int(cap_state['suggested_slot_budget']):,d}）`
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
    st.subheader("📋 自選股票清單總覽儀表板 (Watchlist Overview V2.8)")
    
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
        with st.spinner("正在取得自選股即時產業、規模、均線與嚴格三指標共振狀態..."):
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
                elif cap_val <= 90.0: cap_bracket_label = f"{cap_val:.1f}億 (中大型領頭羊)"
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
                    rsi5_s = 100 - (100 / (1 + (gain.ewm(com=4, adjust=False).mean() / (loss.ewm(com=4, adjust=False).mean() + 1e-9))))
                    rsi14_s = 100 - (100 / (1 + (gain.ewm(com=13, adjust=False).mean() / (loss.ewm(com=13, adjust=False).mean() + 1e-9))))
                    rsi5_val = float(rsi5_s.iloc[-1])
                    rsi14_val = float(rsi14_s.iloc[-1])

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
                    macd_sig_val = float(macd_sig.iloc[-1])
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
                    cond_rsi_hard = (rsi5_val >= 40.0) and (45.0 <= rsi14_val <= rsi_upper_limit)

                    is_squat = cond_trend and cond_support and cond_vol and cond_k and cond_rsi_hard

                    if is_squat: squat_tag = "🎯 均線量縮深蹲"
                    elif touch_10 or touch_20 or (abs(c_today - ma10) / ma10 <= 0.025): squat_tag = "⏳ 回測均線中"
                    elif c_today > ma10: squat_tag = "🚀 均線上強勢"
                    else: squat_tag = "🔻 均線反壓整理"

                    cond_macd_res = (dif_val > 0) and (macd_sig_val > 0) and (osc_val > prev_osc)
                    cond_kd_res = (30.0 <= k_val <= 70.0) and (k_val > prev_k) and (k_val >= d_val)

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

# ================= TAB 4: 策略手冊與 SOP 指南 (V2.8 嚴格共振完整版) =================
with tab_docs:
    st.subheader("📖 短線成長股・量縮深蹲 (Squat & Rebound) 全流程作戰手冊 V2.8")
    st.info("💡 本系統專為「不盯盤、每日 16:30 離線決策、次日紀律執行」設計。歷經 2024～2026 年大數據回測與 2026 年 10 月實戰檢討精煉，將勝率、賺賠比、資金防禦與嚴格三指標共振全面升級。")

    with st.expander("🎯 核心心法：量化短線成長股的獲利本質", expanded=True):
        st.markdown("""
        * **三成勝率、大賺小賠的數學模型**：
          * 歷史大數據實證顯示，本策略的長期統計勝率約在 **32% ～ 35%**，實戰賺賠比（Profit Factor）達 **3.60**。
          * 這意味著每出手 10 次，本來就有 6～7 次會以 -4% 停損或平手收場，獲利全靠抓住 3～4 檔主升段飆股（半倉 +8%、半倉抱波段）帶來暴利。
        * **拒絕情緒與盤中噪音**：
          * 絕不在盤中隨便追價、絕不在未定案的盤中掃描下單。
          * 一律以 **每日 16:30 證交所三大法人籌碼定案後** 的雷達戰報為唯一決策依據，隔日依照 SOP 冷靜執行。
        """)

    with st.expander("🛡️ 第一維：大盤三維環境風控（決定能不能開倉、開幾倉）", expanded=True):
        st.markdown("""
        在選股之前，雷達會先檢驗總體大環境的三道閘門，直接決定當日的資金曝險水位：
        1. **🔴 紅燈【空頭反壓強制休眠】**：
           * **判定**：加權指數 (`^TWII`) 收盤跌破 20MA（月線）。
           * **處置**：大盤處於月線反壓，全市場系統**強制休眠，停止開立任何新倉位**！在倉部位嚴格執行停損停利。
        2. **🟡 黃燈【結構背離 / 拉積盤防禦警戒】**：
           * **判定**：加權站上月線，但 **櫃買指數跌破月線**，或 **上市一般股票下跌家數超過上漲家數 1.5 倍**。
           * **處置（V2.8 實戰強化）**：
             * ⚠️ **嚴格限買 👑 S 級（雙共振）標的**！當日若只有 A 級或 B 級，黃燈期間一律空手觀望，徹底杜絕中小型股誘多假突破！
             * 🏦 **在倉總數上限降為 2 檔**（甚至 1 檔），且單槽預算降載為現有資金之 25%（約 **13.5 萬元**）。
        3. **🟢 綠燈【全面多頭健康】**：
           * **判定**：加權與櫃買同步站穩月線之上，且市場廣度良好。
           * **處置**：允許正常滿額配置（最多 3 檔在倉，S 級、A 級皆可進場）。
        """)

    with st.expander("🔍 第二維：盤後全自動獵股漏斗（3 → 1 → 2 順序過濾）", expanded=True):
        st.markdown("""
        每日 16:30 證交所籌碼出爐後，雷達從全市場 1,800 檔股票中依 **3 → 1 → 2** 順序層層篩選：
        * **步驟 3【投信 7 日累積鎖碼 ＆ 客觀建倉排序（第一道大漏斗）】**：
           * **門檻**：近 7 個交易日投信累計買超中型股（<=60億）需 $\ge 100$ 張；中大型股（60~90億）需 $\ge 250$ 張，且最新交易日投信未倒貨（買賣超 $\ge 0$ 張）。
           * **不限特定產業**：透過投信實質真金白銀買超，先一步淘汰全市場 90% 以上無法人照顧的冷門股，並自動捕捉市場當下正在發動輪動的強勢族群（無論電子或傳產）。
           * **核心排序機制**：最終篩出的候選股，雷達會**以「投信 7 日累積買超張數」由大到小自動排序**！第 1 名享有最高建倉優先權。
        * **步驟 1【精準股本規模 (20億～90億)】**：
           * 鎖定股本在 **20 億至 90 億** 之間的中型成長股與中大型領頭羊（排除 < 20 億極小型投機股與 > 90 億牛皮權值股）。
        * **步驟 2【業績加速動能 (基本面保護傘)】**：
           * 最新公告單月營收年增率 **YoY 必須 > 20%**，確保投信買盤背後有強勁的實質業績支撐。
        """)

    with st.expander("🧘 第三維：「量縮深蹲 (Squat)」技術面檢驗 SOP（含雙週期 RSI 把關）", expanded=True):
        st.markdown("""
        符合基本面與籌碼的股票，必須精準踩在均線起跑點上，方能觸發深蹲訊號：
        1. **均線多頭排列**：收盤價位於多頭排列（5MA > 10MA > 20MA），且 20 日均線（月線）斜率明確向上。
        2. **精確回踩支撐**：當日最低價回測 10MA 或 20MA 緩衝區（$Low \le MA \times 1.018$），且收盤守在均線之上（$Close \ge MA \times 0.99$）。
        3. **極致成交窒息量**：當日成交量必須**「同時低於 5 日均量（5MV）與 20 日均量（20MV）」**，代表洗盤完畢、主力浮額沈澱。
        4. **K 棒實體收斂**：當日開盤與收盤的振幅 $\le 3.5\%$，拒絕長黑摜壓實體。
        5. **雙週期 RSI 強勢蓄勢把關（V2.8 嚴格升級）**：
           * **短線 `RSI (5T) >= 40.0`**：確保近 5 日回檔未跌破多方防線，徹底剔除短線急殺失速股！
           * **波段 `45.0 <= RSI (14T) <= 70.0`**：確保中期趨勢維持在多頭蓄勢區，不買弱勢破底股與極端過熱股。
        """)

    with st.expander("🌟 第四維：獵股品質「嚴格動能共振星級評級 (Signal Quality)」", expanded=True):
        st.markdown("""
        針對通過深蹲檢驗的標的，系統以嚴格轉折公式進行共振打分（已堵死紅柱萎縮與死叉偷渡漏洞）：
        * **📊 MACD 嚴格亮燈條件**：
          * 必須同時滿足 **`DIF > 0` 且 `MACD(9) > 0`（雙線皆在零軸之上）且 `今日柱狀體 (OSC) > 昨日柱狀體`（動能必須遞增：綠柱縮短或紅柱放大）**。若紅柱正在萎縮（瀕臨死叉），一律不亮燈！
        * **📈 KD 嚴格亮燈條件**：
          * 必須同時滿足 **`30 <= K <= 70` 且 `今日 K > 昨日 K`（K 線打勾向上）且 `K >= D`（真黃金交叉狀態）**。只要處於 `K < D` 死叉或 K 值下彎，一律不亮燈！
        * **星級評等標準**：
          * **👑 頂級三指標共振 (S 級)**：深蹲 + 雙RSI守穩 + **MACD 亮燈** + **KD 亮燈** 雙雙達成！黃燈拉積盤時唯一放行對象。
          * **🎯 強勢動能深蹲 (A 級)**：符合深蹲 + 雙RSI守穩，且 MACD 或 KD 其一亮燈。
          * **🟢 標準量縮深蹲 (B 級)**：符合深蹲 + 雙RSI守穩，但 KD 與 MACD 尚在整理收斂中。
        """)

    with st.expander("🏹 第五維：實戰進場時機 SOP（預防早盤誘多假突破 ＆ 零股配額）", expanded=True):
        st.markdown("""
        1. **廢除早盤盲目追價，改採【13:20 尾盤收紅確認法】**：
           * 早盤不預掛觸價買單！等到 **下午 13:15 ～ 13:25（收盤前 10 分鐘）** 再觀察：
             * **情況 A（真突破）**：股價在 13:20 依然穩穩守在深蹲高點之上，且**當日收紅 K（Close $\ge$ Open）**，代表主力玩真的，此時在尾盤買進！
             * **情況 B（強勢守均線低接）**：若未過高但量縮小黑守在 10MA/20MA 之上，亦可在 13:20 於均線附近低接進場。
        2. **同族群避險原則（二擇一）**：
           * 同一天若出現相同產業族群，**最多只選「投信 7 日買超最多」的那 1 檔**，絕不重押同一產業。
        3. **善用「盤中零股」嚴格控管單筆資金**：
           * 嚴格禁止為了湊整張而超額買進！依系統建議股數以**「整張 + 盤中零股」**下單，把單筆風險鎖死在預算內。
        """)

    with st.expander("🛑 第六維：嚴格出場紀律 SOP（五大防線 ＋ 冷卻機制）", expanded=True):
        st.markdown("""
        * **🛑 防線 1【硬停損線 (-4.0%)】**：跌破進場成本價之 **-4.0%** 無條件市價砍單！首日（Day 0）以 13:30 收盤價防守，次日起（Day 1+）盤中預掛智慧觸價停損單。
        * **⏳ 防線 2【時間停損 (4 天 / 智慧展延 7 天)】**：持有滿 4 個實際開盤日漲幅未達 +3%，於第 5 日開盤換股出清；若期間再次符合深蹲且維持成本之上，自動展延至 7 天。
        * **🛡️ 防線 3【動態保本機制 (+4.0%)】**：盤中浮盈曾達 +4.0% 時，次日起停損防線調升至成本價 +0.2%。
        * **🎯 防線 4【第一階段停利 (+8.0%)】**：觸及成本價 +8.0% 時，掛單賣出部位 A（50% 股數）鎖住勝果。
        * **🏄 防線 5【第二階段波段落袋 (跌破 10MA)】**：剩餘部位 B 只要收盤跌破 10MA，次日開盤市價全數獲利了結。
        * **❄️ 防線 6【停損冷卻機制】**：凡觸發 -4% 硬停損之標的，未來 7～10 個交易日內嚴禁重複買進。
        """)

    with st.expander("💼 第七維：方案 B 現有資金與階梯式部位管理（54～55 萬實戰配置）", expanded=True):
        st.markdown("""
        * **🛡️ 當前階段：【止血復原期】（本金 54萬 ～ 57萬 適用）**：
          * **單倉上限**：現有資金之 25% $\\rightarrow$ **NT$ 13.5 萬元**（嚴格硬上限）。
          * **在倉限制**：最多同時持倉 **2 檔**（黃燈拉積盤時限 **1～2 檔且限買 S 級**）。
          * **單筆極限虧損 (-4%)**：約 **NT$ -5,400 元**（僅佔總本金 0.99%）。
        * **🚀 未來階段：【標準三槽順風期】（當本金回升至 57.5 萬以上）**：
          * **單倉上限**：現有資金之 1/3 $\\rightarrow$ **約 NT$ 18 萬 ～ 20 萬元**，恢復最多 **3 檔** 配置。
        """)
