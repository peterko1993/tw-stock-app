import requests
import pandas as pd
import datetime
import yfinance as yf
import json
import os

REPORT_FILE = "radar_report.json"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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

    # ================= 步驟 3：籌碼基礎過濾 =================
    df_t86 = df_t86[df_t86['證券代號'].str.match(r'^\d{4}$')]
    trust_col = [c for c in df_t86.columns if "投信" in c and "買賣超" in c][0]
    df_t86['投信買賣超張數'] = df_t86[trust_col].str.replace(',', '').astype(float) / 1000
    
    # 初篩：投信單日買超 >= 50 張之潛力標的
    df_step3 = df_t86[df_t86['投信買賣超張數'] >= 50][['證券代號', '證券名稱', '投信買賣超張數']].copy()
    print(f"   步驟 3 完成：投信買超 >= 50 張共 {len(df_step3)} 檔")

    # ================= 步驟 1：股本放寬至 20~150 億 + 階梯式籌碼過濾 =================
    print("📡 [2/4] 比對股本規模 (20億 ~ 150億) 並實施階梯籌碼篩選...")
    url_cap = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    res_cap = requests.get(url_cap, headers=headers, timeout=10)
    df_cap = pd.DataFrame(res_cap.json())[['公司代號', '實收資本額']].copy()
    df_cap['股本(億)'] = pd.to_numeric(df_cap['實收資本額'], errors='coerce') / 100_000_000
    
    df_step1 = pd.merge(df_step3, df_cap, left_on='證券代號', right_on='公司代號', how='inner')
    
    # 💡 核心進化：階梯式過濾
    # 條件 A：中型成長股 (20億~60億)，投信單日買超 >= 50 張
    cond_mid = (df_step1['股本(億)'] >= 20.0) & (df_step1['股本(億)'] <= 60.0) & (df_step1['投信買賣超張數'] >= 50)
    # 條件 B：大中型動能股 (60億~150億)，投信買超門檻提高至 >= 250 張（鎖定真正被重押的族群指標）
    cond_large = (df_step1['股本(億)'] > 60.0) & (df_step1['股本(億)'] <= 150.0) & (df_step1['投信買賣超張數'] >= 250)
    
    df_step1 = df_step1[cond_mid | cond_large].copy()
    print(f"   步驟 1 完成：符合階梯股本與法人規模共 {len(df_step1)} 檔")

    # ================= 步驟 2：單月營收年增率 (YoY > 20%) =================
    print("📡 [3/4] 比對最新月營收 (YoY > 20%)...")
    url_rev = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    res_rev = requests.get(url_rev, headers=headers, timeout=10)
    df_rev_raw = pd.DataFrame(res_rev.json())
    yoy_col = [c for c in df_rev_raw.columns if "去年同月增減" in c][0]
    df_rev = df_rev_raw[['公司代號', yoy_col]].copy()
    df_rev['營收YoY(%)'] = pd.to_numeric(df_rev[yoy_col], errors='coerce')

    df_funnel = pd.merge(df_step1, df_rev[['公司代號', '營收YoY(%)']], on='公司代號', how='inner')
    df_funnel = df_funnel[df_funnel['營收YoY(%)'] > 20.0]

    print(f"🎯 3-1-2 漏斗精選出 {len(df_funnel)} 檔強勢標的，開始技術面深蹲比對...")

    # ================= 技術面量縮深蹲檢驗 =================
    report_items = []
    total_squat_count = 0

    for _, row in df_funnel.iterrows():
        code = row['證券代號']
        name = row['證券名稱']
        ticker = f"{code}.TW"
        try:
            df_k = yf.download(ticker, period="3mo", interval="1d", progress=False)
            if df_k.empty or len(df_k) < 25:
                continue
            if isinstance(df_k.columns, pd.MultiIndex):
                df_k.columns = df_k.columns.get_level_values(0)

            df_k['MA5'] = df_k['Close'].rolling(5).mean()
            df_k['MA10'] = df_k['Close'].rolling(10).mean()
            df_k['MA20'] = df_k['Close'].rolling(20).mean()
            df_k['VOL_MA5'] = df_k['Volume'].rolling(5).mean()
            df_k['VOL_MA20'] = df_k['Volume'].rolling(20).mean()

            latest = df_k.iloc[-1]
            close = float(latest['Close'])
            vol = float(latest['Volume'])
            low = float(latest['Low'])
            open_p = float(latest['Open'])
            ma5 = float(latest['MA5'])
            ma10 = float(latest['MA10'])
            ma20 = float(latest['MA20'])
            vol_ma5 = float(latest['VOL_MA5'])
            vol_ma20 = float(latest['VOL_MA20'])

            cond_trend = (ma5 > ma10) and (ma10 > ma20) and (ma20 > df_k['MA20'].iloc[-4])
            touch_10 = (low <= ma10 * 1.018 and close >= ma10 * 0.99)
            touch_20 = (low <= ma20 * 1.018 and close >= ma20 * 0.99)
            cond_support = touch_10 or touch_20
            cond_vol = (vol < vol_ma5) and (vol < vol_ma20)
            cond_k = abs(close - open_p) / open_p <= 0.035

            target_ma = ma10 if touch_10 else ma20
            support_name = "10MA" if touch_10 else ("20MA" if touch_20 else "無")
            is_squat = cond_trend and cond_support and cond_vol and cond_k
            if is_squat: total_squat_count += 1

            item_data = {
                "name": name, "code": code, "ticker": ticker,
                "close": round(close, 1), "trust_buy": int(row['投信買賣超張數']),
                "cap": round(float(row['股本(億)']), 1), "rev_yoy": round(float(row['營收YoY(%)']), 1),
                "is_squat": bool(is_squat), "support": support_name,
                "buy_min": round(target_ma, 1), "buy_max": round(close, 1),
                "stop_loss": round(target_ma * 0.96, 1), "take_profit": round(close * 1.08, 1)
            }
            report_items.append(item_data)
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

    print(f"✅ 戰報生成完畢！共記錄 {len(report_items)} 檔獵物至 {REPORT_FILE}")

if __name__ == "__main__":
    run_screener()
