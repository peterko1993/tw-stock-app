import requests
import pandas as pd
import numpy as np
import datetime
import yfinance as yf
import json
import os

REPORT_FILE = "radar_report.json"
PENDING_FILE = "pending_orders.json"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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

def run_screener():
    print("🚀 [1/4] 正在抓取證交所三大法人日報 (T86)...")
    today = datetime.date.today()
    df_t86 = None
    trade_date = None

    for delta in range(7):
        target_date = today - datetime.timedelta(days=delta)
        date_str = target_date.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            data = res.json()
            if data.get("stat") == "OK" and "data" in data and len(data["data"]) > 0:
                df_t86 = pd.DataFrame(data["data"], columns=data["fields"])
                trade_date = date_str
                break
        except Exception:
            continue

    if df_t86 is None:
        print("❌ 無法取得法人日報，終止執行。")
        return

    # 步驟 3：籌碼基礎過濾
    df_t86 = df_t86[df_t86['證券代號'].str.match(r'^\d{4}$')]
    trust_col = [c for c in df_t86.columns if "投信" in c and "買賣超" in c][0]
    df_t86['投信買賣超張數'] = df_t86[trust_col].str.replace(',', '').astype(float) / 1000
    df_step3 = df_t86[df_t86['投信買賣超張數'] >= 50][['證券代號', '證券名稱', '投信買賣超張數']].copy()

    # 步驟 1：比對股本規模 (20~150 億)
    print("📡 [2/4] 比對股本規模 (20億 ~ 150億)...")
    url_cap = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    res_cap = requests.get(url_cap, headers=headers, timeout=10)
    df_cap_raw = pd.DataFrame(res_cap.json())
    
    cap_cols = ['公司代號', '實收資本額']
    if '產業別' in df_cap_raw.columns: cap_cols.append('產業別')
    df_cap = df_cap_raw[cap_cols].copy()
    if '產業別' not in df_cap.columns: df_cap['產業別'] = "電子科技"

    df_cap['股本(億)'] = pd.to_numeric(df_cap['實收資本額'], errors='coerce') / 100_000_000
    df_step1 = pd.merge(df_step3, df_cap, left_on='證券代號', right_on='公司代號', how='inner')
    
    cond_mid = (df_step1['股本(億)'] >= 20.0) & (df_step1['股本(億)'] <= 60.0) & (df_step1['投信買賣超張數'] >= 50)
    cond_large = (df_step1['股本(億)'] > 60.0) & (df_step1['股本(億)'] <= 150.0) & (df_step1['投信買賣超張數'] >= 250)
    df_step1 = df_step1[cond_mid | cond_large].copy()

    # 步驟 2：比對最新月營收 (YoY > 20%)
    print("📡 [3/4] 比對最新月營收 (YoY > 20%)...")
    url_rev = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    res_rev = requests.get(url_rev, headers=headers, timeout=10)
    df_rev_raw = pd.DataFrame(res_rev.json())
    yoy_col = [c for c in df_rev_raw.columns if "去年同月增減" in c][0]
    df_rev = df_rev_raw[['公司代號', yoy_col]].copy()
    df_rev['營收YoY(%)'] = pd.to_numeric(df_rev[yoy_col], errors='coerce')

    df_funnel = pd.merge(df_step1, df_rev[['公司代號', '營收YoY(%)']], on='公司代號', how='inner')
    df_funnel = df_funnel[df_funnel['營收YoY(%)'] > 20.0]

    report_items = []
    total_squat_count = 0
    today_squat_candidates = []

    for _, row in df_funnel.iterrows():
        code = row['證券代號']
        name = row['證券名稱']
        ticker = f"{code}.TW"
        try:
            df_k = yf.download(ticker, period="4mo", interval="1d", progress=False)
            if df_k.empty or len(df_k) < 30: continue
            if isinstance(df_k.columns, pd.MultiIndex): df_k.columns = df_k.columns.get_level_values(0)

            df_k['MA5'] = df_k['Close'].rolling(5).mean()
            df_k['MA10'] = df_k['Close'].rolling(10).mean()
            df_k['MA20'] = df_k['Close'].rolling(20).mean()
            df_k['VOL_MA5'] = df_k['Volume'].rolling(5).mean()
            df_k['VOL_MA20'] = df_k['Volume'].rolling(20).mean()

            delta = df_k['Close'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(com=13, adjust=False).mean()
            avg_loss = loss.ewm(com=13, adjust=False).mean()
            rs = avg_gain / (avg_loss + 1e-9)
            df_k['RSI14'] = 100 - (100 / (1 + rs))

            low9 = df_k['Low'].rolling(9).min()
            high9 = df_k['High'].rolling(9).max()
            rsv = (df_k['Close'] - low9) / (high9 - low9 + 1e-9) * 100
            k_list, d_list = [50.0], [50.0]
            for r in rsv.fillna(50):
                new_k = (k_list[-1] * 2 / 3) + (r * 1 / 3)
                new_d = (d_list[-1] * 2 / 3) + (new_k * 1 / 3)
                k_list.append(new_k)
                d_list.append(new_d)
            df_k['K'] = k_list[1:]
            df_k['D'] = d_list[1:]

            ema12 = df_k['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df_k['Close'].ewm(span=26, adjust=False).mean()
            df_k['DIF'] = ema12 - ema26
            df_k['MACD_SIG'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
            df_k['OSC'] = df_k['DIF'] - df_k['MACD_SIG']

            latest = df_k.iloc[-1]
            prev = df_k.iloc[-2]
            
            close = float(latest['Close'])
            vol = float(latest['Volume'])
            low = float(latest['Low'])
            high = float(latest['High'])
            open_p = float(latest['Open'])
            ma5 = float(latest['MA5'])
            ma10 = float(latest['MA10'])
            ma20 = float(latest['MA20'])
            vol_ma5 = float(latest['VOL_MA5'])
            vol_ma20 = float(latest['VOL_MA20'])
            rsi_val = float(latest['RSI14'])
            k_val, d_val = float(latest['K']), float(latest['D'])
            dif_val, osc_val = float(latest['DIF']), float(latest['OSC'])

            cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df_k['MA20'].iloc[-4])
            touch_10 = (low <= ma10 * 1.018 and close >= ma10 * 0.99)
            touch_20 = (low <= ma20 * 1.018 and close >= ma20 * 0.99)
            cond_support = touch_10 or touch_20
            cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
            cond_k = abs(close - open_p) / open_p <= 0.035
            cond_rsi_hard = (40.0 <= rsi_val <= 65.0)

            is_squat = cond_trend and cond_support and cond_vol and cond_k and cond_rsi_hard

            cond_macd_res = (dif_val > 0) and ((osc_val > float(prev['OSC'])) or (osc_val > 0))
            cond_kd_res = (30.0 <= k_val <= 65.0) and ((k_val > float(prev['K'])) or (k_val >= d_val))

            if cond_macd_res and cond_kd_res:
                grade, grade_badge = "S", "👑 頂級三指標共振 (S級)"
            elif cond_macd_res or cond_kd_res:
                grade, grade_badge = "A", "🎯 強勢動能深蹲 (A級)"
            else:
                grade, grade_badge = "B", "🟢 標準量縮深蹲 (B級)"

            if is_squat:
                total_squat_count += 1
                today_squat_candidates.append({
                    "code": code, "name": name, "ticker": ticker,
                    "right_trigger": round(high, 1), "high": round(high, 1),
                    "close": round(close, 1), "scan_date": today.strftime("%Y-%m-%d")
                })

            cap_val = round(float(row['股本(億)']), 1)
            cap_bracket_label = f"{cap_val}億 (中型成長股)" if cap_val <= 60.0 else f"{cap_val}億 (旗艦領頭羊)"
            target_ma = ma10 if touch_10 else ma20
            support_name = "10MA" if touch_10 else ("20MA" if touch_20 else "無")

            report_items.append({
                "name": name, "code": code, "ticker": ticker,
                "industry": translate_industry(row.get('產業別', '電子科技')),
                "cap": cap_val, "cap_bracket": cap_bracket_label,
                "close": round(close, 1), "high": round(high, 1),
                "right_trigger": round(high, 1), "trust_buy": int(row['投信買賣超張數']),
                "rev_yoy": round(float(row['營收YoY(%)']), 1), "is_squat": bool(is_squat),
                "grade": grade, "grade_badge": grade_badge, "rsi": round(rsi_val, 1),
                "kd_desc": f"K:{round(k_val, 1)} / D:{round(d_val, 1)}",
                "macd_desc": "零軸上綠縮/翻紅" if cond_macd_res else "整理中",
                "support": support_name, "buy_min": round(target_ma, 1), "buy_max": round(close, 1),
                "stop_loss": round(target_ma * 0.96, 1), "take_profit": round(close * 1.08, 1),
                "scan_date": today.strftime("%Y-%m-%d")
            })
        except Exception:
            continue

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    report_data = {
        "update_time": now_str, "trade_date": trade_date,
        "total_funnel": len(df_funnel), "total_squat": total_squat_count,
        "stocks": report_items
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    # 💡 核心持久化：同步更新待突破候選佇列 (保留昨日與今日標的)
    existing_pending = load_json(PENDING_FILE, [])
    # 移除超過 3 天的過期殘留
    cutoff_d = (today - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    clean_pending = [p for p in existing_pending if str(p.get('scan_date', '')) >= cutoff_d]
    
    for cand in today_squat_candidates:
        if not any(p['code'] == cand['code'] for p in clean_pending):
            clean_pending.append(cand)
            
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_pending, f, ensure_ascii=False, indent=2)

    print(f"✅ 戰報生成完畢！待突破佇列共 {len(clean_pending)} 檔標的待命。")

if __name__ == "__main__":
    run_screener()
