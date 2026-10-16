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

TW_TZ = datetime.timezone(datetime.timedelta(hours=8))

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

def get_trust_buy_7d_map():
    """
    往回抓取最近 7 個有效交易日的證交所 (T86) 與櫃買中心三大法人報表，
    計算「最新單日投信買超 (trust_1d)」與「近 7 日累積投信買超 (trust_7d)」
    """
    trust_1d = {}
    trust_7d = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    now_tw = datetime.datetime.now(TW_TZ).date()

    # 1. 上市 (TWSE T86)
    twse_days_collected = 0
    for offset in range(0, 18):
        if twse_days_collected >= 7:
            break
        dt = now_tw - datetime.timedelta(days=offset)
        if dt.weekday() >= 5:
            continue
        d_twse = dt.strftime("%Y%m%d")
        try:
            url_twse = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={d_twse}&selectType=ALLBUT0999&response=json"
            res = requests.get(url_twse, headers=headers, timeout=8)
            if res.status_code == 200:
                j = res.json()
                if j.get("stat") == "OK" and j.get("data"):
                    twse_days_collected += 1
                    for row in j["data"]:
                        code = str(row[0]).strip()
                        if len(code) == 4 and code.isdigit():
                            try:
                                net_shares = int(str(row[10]).replace(",", "").strip())
                                net_lots = net_shares // 1000
                                if twse_days_collected == 1:
                                    trust_1d[code] = net_lots
                                trust_7d[code] = trust_7d.get(code, 0) + net_lots
                            except Exception:
                                pass
                    time.sleep(0.25)
        except Exception:
            pass

    # 2. 上櫃 (TPEX)
    tpex_days_collected = 0
    for offset in range(0, 18):
        if tpex_days_collected >= 7:
            break
        dt = now_tw - datetime.timedelta(days=offset)
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
                    tpex_days_collected += 1
                    for row in rows:
                        code = str(row[0]).strip()
                        if len(code) == 4 and code.isdigit():
                            try:
                                net_shares = int(str(row[13]).replace(",", "").strip())
                                net_lots = net_shares // 1000
                                if tpex_days_collected == 1:
                                    trust_1d[code] = net_lots
                                trust_7d[code] = trust_7d.get(code, 0) + net_lots
                            except Exception:
                                pass
                    time.sleep(0.25)
        except Exception:
            pass

    print(f"📊 已完成投信籌碼統計：上市收集 {twse_days_collected} 日、上櫃收集 {tpex_days_collected} 日")
    return trust_1d, trust_7d

def run_screener():
    print("📡 [Screener V2.8] 啟動全自動獵股漏斗 (3 -> 1 -> 2 全產業 + 嚴格雙RSI/KD/MACD共振)...")
    profiles = get_company_profiles()
    rev_map = get_revenue_map()
    trust_1d_map, trust_7d_map = get_trust_buy_7d_map()

    funnel_candidates = []
    all_codes = set(trust_7d_map.keys()) | set(trust_1d_map.keys())

    for code in all_codes:
        p = profiles.get(code)
        if not p:
            continue

        # 步驟 3：投信 7 日累積鎖碼過濾 (中型股>=100張, 中大型股>=250張, 且最新日買超>=0)
        cap = p["cap"]
        lots_7d = trust_7d_map.get(code, 0)
        lots_1d = trust_1d_map.get(code, 0)
        min_7d_req = 100 if cap <= 60.0 else 250

        if lots_7d < min_7d_req:
            continue
        if lots_1d < 0:
            continue

        # 步驟 1：股本規模 20億 ~ 90億 (不限產業，順勢追蹤資金輪動)
        if not (20.0 <= cap <= 90.0):
            continue

        # 步驟 2：月營收 YoY > 20%
        yoy = rev_map.get(code, None)
        if yoy is None or yoy <= 20.0:
            continue

        funnel_candidates.append({
            "code": code,
            "name": p["name"],
            "ticker": f"{code}{p['market']}",
            "cap": cap,
            "industry": p["industry"],
            "trust_buy": lots_1d,
            "trust_1d": lots_1d,
            "trust_7d": lots_7d,
            "rev_yoy": yoy
        })

    print(f"🔎 通過 3 -> 1 -> 2 漏斗共 {len(funnel_candidates)} 檔，開始進行量縮深蹲與嚴格技術指標檢驗...")

    results = []
    squat_count = 0
    now_tw = datetime.datetime.now(TW_TZ)
    today_str = now_tw.strftime("%Y-%m-%d")

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

            # 💡 1. 雙週期 RSI：同時計算 5日 RSI (RSI5) 與 14日 RSI (RSI14)
            delta = df['Close'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)

            avg_gain5 = gain.ewm(com=4, adjust=False).mean()
            avg_loss5 = loss.ewm(com=4, adjust=False).mean()
            rs5 = avg_gain5 / (avg_loss5 + 1e-9)
            df['RSI5'] = 100 - (100 / (1 + rs5))

            avg_gain14 = gain.ewm(com=13, adjust=False).mean()
            avg_loss14 = loss.ewm(com=13, adjust=False).mean()
            rs14 = avg_gain14 / (avg_loss14 + 1e-9)
            df['RSI14'] = 100 - (100 / (1 + rs14))

            # 💡 2. KD (9, 3, 3)
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

            # 💡 3. MACD (12, 26, 9)
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
            rsi5_val = float(latest['RSI5'])
            rsi14_val = float(latest['RSI14'])
            k_val, d_val = float(latest['K']), float(latest['D'])
            prev_k = float(prev['K'])
            dif_val = float(latest['DIF'])
            macd_sig_val = float(latest['MACD_SIG'])
            osc_val = float(latest['OSC'])
            prev_osc = float(prev['OSC'])

            cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > float(df['MA20'].iloc[-4]))
            touch_10 = (low <= ma10 * 1.018) and (close >= ma10 * 0.99)
            touch_20 = (low <= ma20 * 1.018) and (close >= ma20 * 0.99)
            cond_support = touch_10 or touch_20
            cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
            cond_k = (abs(close - open_p) / open_p) <= 0.035

            # 💡【嚴格修正 1】：RSI 雙週期把關 (5T >= 40 且 14T 介於 45~70，徹底排除短線急跌股)
            cond_rsi = (rsi5_val >= 40.0) and (45.0 <= rsi14_val <= 70.0)

            is_squat = cond_trend and cond_support and cond_vol and cond_k and cond_rsi
            support_str = "10MA" if touch_10 else ("20MA" if touch_20 else "未回踩")

            # 💡【嚴格修正 2】：MACD 必須零軸上 (DIF>0 且 MACD>0) 且 柱狀體動能遞增 (今日OSC > 昨日OSC)，排除紅柱萎縮！
            cond_macd_res = (dif_val > 0) and (macd_sig_val > 0) and (osc_val > prev_osc)

            # 💡【嚴格修正 3】：KD 必須同時滿足 K>=D (真金叉) 且 今日K > 昨日K (勾頭向上)，排除死叉與下彎！
            cond_kd_res = (30.0 <= k_val <= 70.0) and (k_val > prev_k) and (k_val >= d_val)

            if cond_macd_res and cond_kd_res:
                grade_badge = "👑 頂級共振 (S級)"
                grade_rank = 3
            elif cond_macd_res or cond_kd_res:
                grade_badge = "🎯 強勢動能 (A級)"
                grade_rank = 2
            else:
                grade_badge = "🟢 標準深蹲 (B級)"
                grade_rank = 1

            if cond_kd_res:
                kd_desc = f"K={k_val:.1f}>D={d_val:.1f} (金叉向上✅)"
            elif k_val < d_val:
                kd_desc = f"K={k_val:.1f}<D={d_val:.1f} (死叉整理)"
            else:
                kd_desc = f"K={k_val:.1f}, D={d_val:.1f} (彎頭整理)"

            if cond_macd_res:
                macd_desc = f"OSC={osc_val:.2f} (零軸上遞增✅)"
            else:
                macd_desc = f"OSC={osc_val:.2f} (柱狀體收斂/整理)"

            if is_squat:
                squat_count += 1

            item.update({
                "close": round(close, 1),
                "high": round(high, 1),
                "right_trigger": round(high, 1),
                "support": support_str,
                "is_squat": bool(is_squat),
                "rsi": round(rsi14_val, 1),
                "rsi5": round(rsi5_val, 1),
                "kd_desc": kd_desc,
                "macd_desc": macd_desc,
                "grade_badge": grade_badge,
                "grade_rank": grade_rank
            })
            results.append(item)
        except Exception:
            pass

    results.sort(key=lambda x: (x.get("is_squat", False), x.get("trust_7d", 0), x.get("grade_rank", 1)), reverse=True)

    report_data = {
        "update_time": now_tw.strftime("%Y-%m-%d %H:%M"),
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
                "trust_7d": s.get("trust_7d", 0)
            })
    save_json(PENDING_FILE, pending_list)
    print(f"✅ [Screener V2.8 完成] 符合深蹲共 {squat_count} 檔，已寫入戰報！")

if __name__ == "__main__":
    run_screener()
