import requests
import pandas as pd
import yfinance as yf
import json
import datetime
import os
import time

REPORT_FILE = "radar_report.json"
PENDING_FILE = "pending_orders.json"
POSITIONS_FILE = "positions.json"

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

# 💡 V2.8 剔除牛皮傳產類股黑名單 (水泥、食品、塑膠、紡織、玻璃、造紙、鋼鐵、橡膠、汽車、營建、航運、觀光、金融、百貨等)
EXCLUDED_INDUSTRIES = {
    "水泥工業", "食品工業", "塑膠工業", "紡織纖維", "玻璃陶瓷",
    "造紙工業", "鋼鐵工業", "橡膠工業", "汽車工業", "建材營造",
    "航運業", "觀光餐旅", "金融保險業", "貿易百貨業", "油電燃氣業", "綜合"
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

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_company_profiles():
    profiles = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    # 上市
    try:
        r1 = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", headers=headers, timeout=10)
        if r1.status_code == 200:
            for item in r1.json():
                c = str(item.get("公司代號", "")).strip()
                n = str(item.get("公司簡稱", "") or item.get("公司名稱", "")).strip()
                cap = float(item.get("實收資本額", 0)) / 100_000_000
                ind = translate_industry(item.get("產業別", ""))
                if len(c) == 4 and c.isdigit():
                    profiles[c] = {"name": n, "cap": round(cap, 1), "market": ".TW", "industry": ind}
    except Exception as e:
        print(f"上市基本資料抓取異常: {e}")

    # 上櫃
    try:
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", headers=headers, timeout=10)
        if r2.status_code == 200:
            for item in r2.json():
                c = str(item.get("SecuritiesCompanyCode", "") or item.get("公司代號", "")).strip()
                n = str(item.get("CompanyBriefName", "") or item.get("公司簡稱", "")).strip()
                cap_raw = float(item.get("PaidInCapital", 0) or item.get("實收資本額", 0))
                cap = cap_raw / 100_000_000
                ind = translate_industry(item.get("SectorName", "") or item.get("產業別", ""))
                if len(c) == 4 and c.isdigit():
                    profiles[c] = {"name": n, "cap": round(cap, 1), "market": ".TWO", "industry": ind}
    except Exception as e:
        print(f"上櫃基本資料抓取異常: {e}")

    return profiles

def get_revenue_map():
    rev_map = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in [
        "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
    ]:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                for item in r.json():
                    c = str(item.get("公司代號", "") or item.get("SecuritiesCompanyCode", "")).strip()
                    yoy_str = str(item.get("去年同月增減(%)", "") or item.get("營業收入-去年同月增減(%)", "")).replace(",", "").strip()
                    try:
                        rev_map[c] = round(float(yoy_str), 2)
                    except Exception:
                        pass
        except Exception:
            pass
    return rev_map

# 💡【核心修復】：真正抓取過去 7 個交易日投信買賣超，計算「單日買超 (1d)」與「7日累計買超 (7d)」
def get_trust_buy_stats():
    trust_1d = {}
    trust_7d = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. 上市 (TWSE T86)：往回掃描最近 14 個日曆天，收集最多 7 個有效開盤日
    twse_days_found = 0
    for offset in range(0, 14):
        if twse_days_found >= 7:
            break
        dt = datetime.date.today() - datetime.timedelta(days=offset)
        if dt.weekday() >= 5:
            continue
        d_twse = dt.strftime("%Y%m%d")
        try:
            url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={d_twse}&selectType=ALLBUT0999&response=json"
            res = requests.get(url_twse, headers=headers, timeout=8)
            if res.status_code == 200:
                j = res.json()
                if j.get("stat") == "OK" and j.get("data"):
                    for row in j["data"]:
                        code = str(row[0]).strip()
                        if len(code) == 4 and code.isdigit():
                            try:
                                net_lots = int(str(row[10]).replace(",", "").strip()) // 1000
                                if twse_days_found == 0:
                                    trust_1d[code] = net_lots
                                trust_7d[code] = trust_7d.get(code, 0) + net_lots
                            except Exception:
                                pass
                    twse_days_found += 1
                    time.sleep(0.25)
        except Exception:
            pass

    # 2. 上櫃 (TPEX)：往回掃描最近 14 個日曆天，收集最多 7 個有效開盤日
    tpex_days_found = 0
    for offset in range(0, 14):
        if tpex_days_found >= 7:
            break
        dt = datetime.date.today() - datetime.timedelta(days=offset)
        if dt.weekday() >= 5:
            continue
        roc_yr = dt.year - 1911
        d_tpex = f"{roc_yr}/{dt.strftime('%m/%d')}"
        try:
            url_tpex = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={d_tpex}&o=json"
            res = requests.get(url_tpex, headers=headers, timeout=8)
            if res.status_code == 200:
                j = res.json()
                rows = j.get("aaData") or j.get("tables", [{}])[0].get("data", [])
                if rows:
                    for row in rows:
                        code = str(row[0]).strip()
                        if len(code) == 4 and code.isdigit():
                            try:
                                net_lots = int(str(row[13]).replace(",", "").strip()) // 1000
                                if tpex_days_found == 0:
                                    trust_1d[code] = net_lots
                                trust_7d[code] = trust_7d.get(code, 0) + net_lots
                            except Exception:
                                pass
                    tpex_days_found += 1
                    time.sleep(0.25)
        except Exception:
            pass

    return trust_1d, trust_7d

def run_screener():
    print("📡 [Screener V2.8] 啟動全自動獵股漏斗 (含投信7日累計籌碼 + 剔除牛皮傳產 + 股本20~100億)...")
    profiles = get_company_profiles()
    rev_map = get_revenue_map()
    trust_1d_map, trust_7d_map = get_trust_buy_stats()

    funnel_candidates = []
    all_codes = set(list(trust_1d_map.keys()) + list(trust_7d_map.keys()))

    for code in all_codes:
        net_1d = trust_1d_map.get(code, 0)
        net_7d = trust_7d_map.get(code, 0)

        p = profiles.get(code)
        if not p:
            continue

        cap = p["cap"]
        industry = p["industry"]

        # 💡 步驟 1：V2.8 股本收斂至 20億 ~ 100億，並剔除傳產牛皮股 (如鋼鐵 20xx)
        if not (20.0 <= cap <= 100.0):
            continue
        if industry in EXCLUDED_INDUSTRIES or code.startswith("20"):
            continue

        # 💡 步驟 3：投信 7 日累計買超核心門檻 (與 Colab 回測 100% 對齊)
        min_7d_req = 100 if cap <= 60.0 else 250
        if net_7d < min_7d_req:
            continue
        # 最新一日投信不可站在大賣方 (至少小買或持平 >= 0，若單日買超 >= 20 張更佳)
        if net_1d < 0:
            continue

        # 💡 步驟 2：月營收 YoY > 20%
        yoy = rev_map.get(code, None)
        if yoy is None or yoy <= 20.0:
            continue

        funnel_candidates.append({
            "code": code,
            "name": p["name"],
            "ticker": f"{code}{p['market']}",
            "cap": cap,
            "industry": industry,
            "trust_buy": net_1d,
            "trust_7d": net_7d,
            "rev_yoy": yoy
        })

    print(f"🔎 通過基本面與【投信7日累計籌碼】漏斗共 {len(funnel_candidates)} 檔，開始進行量縮深蹲檢驗...")

    results = []
    squat_count = 0
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    for item in funnel_candidates:
        ticker = item["ticker"]
        try:
            df = yf.download(ticker, period="6mo", interval="1d", progress=False)
            if df.empty or len(df) < 35:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['VOL_MA5'] = df['Volume'].rolling(5).mean()
            df['VOL_MA20'] = df['Volume'].rolling(20).mean()

            # 1. RSI (14)
            delta = df['Close'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(com=13, adjust=False).mean()
            avg_loss = loss.ewm(com=13, adjust=False).mean()
            rs = avg_gain / (avg_loss + 1e-9)
            df['RSI14'] = 100 - (100 / (1 + rs))

            # 2. KD (9, 3, 3)
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

            # 3. MACD (12, 26, 9)
            ema12 = df['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df['Close'].ewm(span=26, adjust=False).mean()
            df['DIF'] = ema12 - ema26
            df['MACD_SIG'] = df['DIF'].ewm(span=9, adjust=False).mean()
            df['OSC'] = df['DIF'] - df['MACD_SIG']

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest['Close'])
            open_p = float(latest['Open'])
            high = float(latest['High'])
            low = float(latest['Low'])
            vol = float(latest['Volume'])
            ma5, ma10, ma20 = float(latest['MA5']), float(latest['MA10']), float(latest['MA20'])
            vol_ma5, vol_ma20 = float(latest['VOL_MA5']), float(latest['VOL_MA20'])
            rsi_val = float(latest['RSI14'])
            k_val, d_val = float(latest['K']), float(latest['D'])
            prev_k = float(prev['K'])
            dif_val, osc_val, prev_osc = float(latest['DIF']), float(latest['OSC']), float(prev['OSC'])

            cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > float(df['MA20'].iloc[-4]))
            touch_10 = (low <= ma10 * 1.018) and (close >= ma10 * 0.99)
            touch_20 = (low <= ma20 * 1.018) and (close >= ma20 * 0.99)
            cond_support = touch_10 or touch_20
            cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
            cond_k = (abs(close - open_p) / open_p) <= 0.035
            cond_rsi = (40.0 <= rsi_val <= 70.0)

            is_squat = cond_trend and cond_support and cond_vol and cond_k and cond_rsi
            support_str = "10MA" if touch_10 else ("20MA" if touch_20 else "未回踩")

            cond_macd_res = (dif_val > 0) and ((osc_val > prev_osc) or (osc_val > 0))
            cond_kd_res = (30.0 <= k_val <= 65.0) and ((k_val > prev_k) or (k_val >= d_val))

            if cond_macd_res and cond_kd_res:
                grade_badge = "👑 頂級共振 (S級)"
                grade_rank = 3
            elif cond_macd_res or cond_kd_res:
                grade_badge = "🎯 強勢動能 (A級)"
                grade_rank = 2
            else:
                grade_badge = "🟢 標準深蹲 (B級)"
                grade_rank = 1

            kd_desc = f"K={k_val:.1f} (打勾/金叉)" if cond_kd_res else f"K={k_val:.1f} (整理中)"
            macd_desc = "零軸上翻紅/收斂" if cond_macd_res else "動能整理中"

            if is_squat:
                squat_count += 1

            item.update({
                "close": round(close, 1),
                "high": round(high, 1),
                "right_trigger": round(high, 1),
                "support": support_str,
                "is_squat": bool(is_squat),
                "rsi": round(rsi_val, 1),
                "kd_desc": kd_desc,
                "macd_desc": macd_desc,
                "grade_badge": grade_badge,
                "grade_rank": grade_rank
            })
            results.append(item)
        except Exception:
            pass

    # 💡 嚴格依照：是否深蹲 -> 星級評級 (S>A>B) -> 投信7日累計買超 (trust_7d) 由大到小排序
    results.sort(key=lambda x: (x.get("is_squat", False), x.get("grade_rank", 0), x.get("trust_7d", 0), x.get("trust_buy", 0)), reverse=True)

    report_data = {
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_funnel": len(funnel_candidates),
        "total_squat": squat_count,
        "stocks": results
    }
    save_json(REPORT_FILE, report_data)

    positions = load_json(POSITIONS_FILE, [])
    active_codes = {str(p['code']).split('.')[0].strip() for p in positions}
    pending_list = []
    for s in results:
        if s.get("is_squat") and s["code"] not in active_codes:
            pending_list.append({
                "code": s["code"],
                "name": s["name"],
                "ticker": s["ticker"],
                "right_trigger": s["right_trigger"],
                "scan_date": today_str,
                "grade_badge": s.get("grade_badge", "🟢 標準深蹲 (B級)"),
                "trust_7d": s.get("trust_7d", s.get("trust_buy", 0))
            })
    save_json(PENDING_FILE, pending_list)
    print(f"✅ [Screener V2.8 完成] 符合深蹲共 {squat_count} 檔，已依投信7日累計買超排序寫入戰報！")

if __name__ == "__main__":
    run_screener()
