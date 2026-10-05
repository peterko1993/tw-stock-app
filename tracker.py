import yfinance as yf
import pandas as pd
import json
import os
import datetime

POSITIONS_FILE = "positions.json"
HISTORY_FILE = "trade_history.csv"
REPORT_FILE = "radar_report.json"

FEE_RATE = 0.001425 * 0.5
TAX_RATE = 0.003
SLOT_BUDGET = 200000.0  # 每個槽位 20 萬元
MAX_SLOTS = 3

def load_json(filepath, default):
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def run_tracker():
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    print(f"🚀 [Tracker] 啟動實盤部位追蹤引擎 ({today_str})...")

    positions = load_json(POSITIONS_FILE, [])
    report = load_json(REPORT_FILE, {})
    
    if os.path.exists(HISTORY_FILE):
        df_history = pd.read_csv(HISTORY_FILE)
    else:
        df_history = pd.DataFrame(columns=[
            "代號", "名稱", "進場日", "進場價", "出場日", "持股天數",
            "投入金額", "回收金額", "淨損益(NTD)", "部位A_損益%", "部位B_損益%",
            "綜合報酬率%", "出場原因"
        ])
        df_history.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")

    remaining_positions = []
    new_closed_trades = []

    # 取得今日雷達深蹲合格股票代號集合
    radar_squat_codes = set()
    if report and "stocks" in report:
        radar_squat_codes = {str(s['code']).split('.')[0].strip() for s in report.get("stocks", []) if s.get("is_squat")}

    # ================= 1. 檢驗既有持倉部位 =================
    for pos in positions:
        ticker = pos['ticker']
        code = str(pos['code']).split('.')[0].strip()
        name = pos['name']
        entry_p = float(pos['entry_price'])
        entry_d = str(pos['entry_date']).strip()
        
        try:
            df = yf.download(ticker, period="2mo", interval="1d", progress=False)
            if df.empty:
                remaining_positions.append(pos)
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df['MA10'] = df['Close'].rolling(10).mean()
            latest = df.iloc[-1]
            high = float(latest['High'])
            low = float(latest['Low'])
            close = float(latest['Close'])
            ma10 = float(latest['MA10'])
            
            # 以台股實際開盤日 K 棒計算開盤交易日天數 (進場當日為第 0 天)
            trade_dates_after = [idx.strftime('%Y-%m-%d') for idx in df.index if idx.strftime('%Y-%m-%d') > entry_d]
            d = len(trade_dates_after)
            pos['days_held'] = d

            # 智慧展延檢驗
            if "is_extended" not in pos:
                pos["is_extended"] = False
            
            if not pos["is_extended"] and (code in radar_squat_codes):
                if close >= (entry_p * 0.995):
                    pos["is_extended"] = True
                    print(f"   🔄 [智慧展延] {name} ({code}) 今日再次符合雷達深蹲且維持成本之上，上限放寬至 7 個交易日！")

            max_allowed_days = 7 if pos.get("is_extended") else 4

            # (1) 停損檢驗 (動態保本線 或 -4% 硬停損)
            effective_stop = (entry_p * 1.002) if (pos.get('is_breakeven') and d >= 1) else (entry_p * 0.96)
            if low <= effective_stop:
                exit_p = min(float(latest['Open']), effective_stop)
                shares_left = pos['shares_a'] + pos['shares_b']
                rev = shares_left * exit_p * (1 - FEE_RATE - TAX_RATE)
                pnl_amt = rev - (shares_left * entry_p * (1 + FEE_RATE))
                pnl_pct = (exit_p - entry_p) / entry_p * 100
                reason = "🛡️ 動態保本出場 (+0.2%)" if (pos.get('is_breakeven') and d >= 1) else "🛑 硬停損 (-4%)"

                new_closed_trades.append({
                    "代號": code, "名稱": name, "進場日": entry_d, "進場價": entry_p,
                    "出場日": today_str, "持股天數": d, "投入金額": int(pos['total_invested']),
                    "回收金額": int(rev), "淨損益(NTD)": int(pnl_amt), "部位A_損益%": round(pnl_pct, 2),
                    "部位B_損益%": round(pnl_pct, 2), "綜合報酬率%": round(pnl_pct, 2), "出場原因": reason
                })
                print(f"   [出場] {name} 觸發 {reason}，損益: {pnl_pct:+.2f}%")
                continue

            # (2) 標記動態保本 (+4%)
            if not pos.get('is_breakeven') and high >= entry_p * 1.04:
                pos['is_breakeven'] = True
                print(f"   [保本激活] {name} 盤中觸及 +4%，次個交易日起停損調升至成本線")

            # (3) 階段一停利 (+8% 出脫 50% 部位)
            if not pos.get('lot_a_sold') and high >= entry_p * 1.08:
                exit_p = max(float(latest['Open']), entry_p * 1.08)
                rev_a = pos['shares_a'] * exit_p * (1 - FEE_RATE - TAX_RATE)
                pos['lot_a_sold'] = True
                pos['lot_a_revenue'] = rev_a
                pos['lot_a_pnl_pct'] = (exit_p - entry_p) / entry_p * 100
                pos['is_breakeven'] = True
                print(f"   [階段一達成] {name} 半倉達成 +8% 停利！")

            # (4) 階段二移動停利 (部位 B 破 10MA)
            if pos.get('lot_a_sold') and close < ma10:
                exit_p = close
                rev_b = pos['shares_b'] * exit_p * (1 - FEE_RATE - TAX_RATE)
                tot_rev = pos['lot_a_revenue'] + rev_b
                pnl_amt = tot_rev - pos['total_invested']
                tot_pct = (pnl_amt / pos['total_invested']) * 100
                pnl_b_pct = (exit_p - entry_p) / entry_p * 100

                new_closed_trades.append({
                    "代號": code, "名稱": name, "進場日": entry_d, "進場價": entry_p,
                    "出場日": today_str, "持股天數": d, "投入金額": int(pos['total_invested']),
                    "回收金額": int(tot_rev), "淨損益(NTD)": int(pnl_amt),
                    "部位A_損益%": round(pos['lot_a_pnl_pct'], 2), "部位B_損益%": round(pnl_b_pct, 2),
                    "綜合報酬率%": round(tot_pct, 2), "出場原因": "🏆 完美停利 (半倉+8% & 破10MA)"
                })
                print(f"   [波段出場] {name} 破 10MA 全數落袋，綜合報酬: {tot_pct:+.2f}%")
                continue

            # (5) 時間停損：嚴格以開盤交易日判定
            if d >= max_allowed_days and not pos.get('lot_a_sold') and close <= entry_p * 1.03:
                exit_p = close
                shares_left = pos['shares_a'] + pos['shares_b']
                rev = shares_left * exit_p * (1 - FEE_RATE - TAX_RATE)
                pnl_amt = rev - pos['total_invested']
                pnl_pct = (exit_p - entry_p) / entry_p * 100
                ext_str = "展延滿7天" if pos.get("is_extended") else "滿4天"

                new_closed_trades.append({
                    "代號": code, "名稱": name, "進場日": entry_d, "進場價": entry_p,
                    "出場日": today_str, "持股天數": d, "投入金額": int(pos['total_invested']),
                    "回收金額": int(rev), "淨損益(NTD)": int(pnl_amt), "部位A_損益%": round(pnl_pct, 2),
                    "部位B_損益%": round(pnl_pct, 2), "綜合報酬率%": round(pnl_pct, 2),
                    "出場原因": f"⏳ 時間停損 ({ext_str}無動能)"
                })
                print(f"   [時間停損] {name} 持有{ext_str}未發動，平倉離場")
                continue

            pos['curr_price'] = round(close, 1)
            pos['unrealized_pct'] = round((close - entry_p) / entry_p * 100, 2)
            pos['ma10'] = round(ma10, 1)
            pos['curr_stop'] = round(effective_stop, 1)
            pos['tp_stage1'] = round(entry_p * 1.08, 1)
            remaining_positions.append(pos)

        except Exception as e:
            print(f"⚠️ 分析 {ticker} 異常: {e}")
            remaining_positions.append(pos)

    # ================= 2. 檢驗雷達候選股建倉 (次日右側過高確認 SOP) =================
    open_slots = MAX_SLOTS - len(remaining_positions)
    squat_candidates = [s for s in report.get("stocks", []) if s.get("is_squat")]
    report_scan_date = report.get("trade_date", "")

    if open_slots > 0 and squat_candidates:
        for cand in squat_candidates:
            if open_slots <= 0:
                break
            cand_code = str(cand['code']).split('.')[0].strip()
            if any(str(p['code']).split('.')[0].strip() == cand_code for p in remaining_positions):
                continue
            
            cand_ticker = cand['ticker']
            cand_name = cand['name']
            right_trigger = float(cand.get('right_trigger', cand.get('high', cand['close'])))
            
            # 💡【核心修正】：當天 16:30 剛掃描出的標的，當天已收盤無法交易，必須等待次日檢驗
            cand_scan_d = str(cand.get('scan_date', report_scan_date)).replace('-', '')
            today_clean = today_str.replace('-', '')
            
            if cand_scan_d >= today_clean:
                print(f"   ⏳ [候選待命] {cand_name} ({cand_code}) 為今日盤後深蹲標的，等待次日開盤檢驗右側過高確認 (突破 ${right_trigger})")
                continue
            
            # 若為前一日的深蹲候選，下載今日實際行情檢驗是否突破深蹲日高點
            try:
                df_cand = yf.download(cand_ticker, period="5d", interval="1d", progress=False)
                if df_cand.empty: continue
                if isinstance(df_cand.columns, pd.MultiIndex):
                    df_cand.columns = df_cand.columns.get_level_values(0)
                
                latest_cand = df_cand.iloc[-1]
                t1_high = float(latest_cand['High'])
                t1_open = float(latest_cand['Open'])
                t1_close = float(latest_cand['Close'])
                
                # SOP：盤中最高價突破深蹲日高點才准進場
                if t1_high >= right_trigger:
                    buy_price = max(t1_open, right_trigger)
                    total_shares = int(SLOT_BUDGET / (buy_price * (1 + FEE_RATE)))
                    if total_shares < 100: continue
                    
                    shares_a = total_shares // 2
                    shares_b = total_shares - shares_a
                    cost = total_shares * buy_price * (1 + FEE_RATE)
                    
                    remaining_positions.append({
                        "code": cand_code, "name": cand_name, "ticker": cand_ticker,
                        "entry_date": today_str,  # 💡 正確以次日（今日）為正式進場日！
                        "entry_price": round(buy_price, 1),
                        "total_invested": cost, "shares_a": shares_a, "shares_b": shares_b,
                        "days_held": 0,
                        "is_breakeven": False, "lot_a_sold": False,
                        "lot_a_revenue": 0.0, "lot_a_pnl_pct": 0.0,
                        "curr_price": round(t1_close, 1),
                        "unrealized_pct": round((t1_close - buy_price) / buy_price * 100, 2),
                        "curr_stop": round(buy_price * 0.96, 1),
                        "tp_stage1": round(buy_price * 1.08, 1),
                        "ma10": round(float(df_cand['Close'].rolling(10).mean().iloc[-1]), 1) if len(df_cand) >= 10 else round(buy_price * 0.99, 1),
                        "is_extended": False
                    })
                    open_slots -= 1
                    print(f"   🎯 [右側確認進場] {cand_name} ({cand_code}) 盤中最高 ${t1_high} 突破門檻 ${right_trigger}，於今日 ({today_str}) 正式建倉！成本 ${buy_price}")
                else:
                    print(f"   ❌ [放棄建倉] {cand_name} ({cand_code}) 今日最高 ${t1_high} 未能突破門檻 ${right_trigger}，轉折失敗放棄進場。")
            except Exception as e:
                print(f"   ⚠️ 檢驗 {cand_name} 異常: {e}")

    save_json(POSITIONS_FILE, remaining_positions)
    
    if new_closed_trades:
        df_new = pd.DataFrame(new_closed_trades)
        df_history = pd.concat([df_history, df_new], ignore_index=True)
        df_history.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")

    print(f"✅ [Tracker 完成] 當前在倉部位：{len(remaining_positions)} 檔，歷史累積結案：{len(df_history)} 筆")

if __name__ == "__main__":
    run_tracker()
