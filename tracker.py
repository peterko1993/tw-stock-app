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

    # ================= 1. 檢驗既有持倉部位 =================
    for pos in positions:
        ticker = pos['ticker']
        code = pos['code']
        name = pos['name']
        entry_p = float(pos['entry_price'])
        
        try:
            df = yf.download(ticker, period="1mo", interval="1d", progress=False)
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
            
            pos['days_held'] += 1
            d = pos['days_held']

            # (1) 停損檢驗 (動態保本線 或 -4% 硬停損)
            effective_stop = (entry_p * 1.002) if (pos.get('is_breakeven') and d > 1) else (entry_p * 0.96)
            if low <= effective_stop:
                exit_p = min(float(latest['Open']), effective_stop)
                shares_left = pos['shares_a'] + pos['shares_b']
                rev = shares_left * exit_p * (1 - FEE_RATE - TAX_RATE)
                pnl_amt = rev - (shares_left * entry_p * (1 + FEE_RATE))
                pnl_pct = (exit_p - entry_p) / entry_p * 100
                reason = "🛡️ 動態保本出場 (+0.2%)" if (pos.get('is_breakeven') and d > 1) else "🛑 硬停損 (-4%)"

                new_closed_trades.append({
                    "代號": code, "名稱": name, "進場日": pos['entry_date'], "進場價": entry_p,
                    "出場日": today_str, "持股天數": d, "投入金額": int(pos['total_invested']),
                    "回收金額": int(rev), "淨損益(NTD)": int(pnl_amt), "部位A_損益%": round(pnl_pct, 2),
                    "部位B_損益%": round(pnl_pct, 2), "綜合報酬率%": round(pnl_pct, 2), "出場原因": reason
                })
                print(f"   [出場] {name} 觸發 {reason}，損益: {pnl_pct:+.2f}%")
                continue

            # (2) 標記動態保本 (+4%)
            if not pos.get('is_breakeven') and high >= entry_p * 1.04:
                pos['is_breakeven'] = True
                print(f"   [保本激活] {name} 盤中觸及 +4%，次日起停損調升至成本線")

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
                    "代號": code, "名稱": name, "進場日": pos['entry_date'], "進場價": entry_p,
                    "出場日": today_str, "持股天數": d, "投入金額": int(pos['total_invested']),
                    "回收金額": int(tot_rev), "淨損益(NTD)": int(pnl_amt),
                    "部位A_損益%": round(pos['lot_a_pnl_pct'], 2), "部位B_損益%": round(pnl_b_pct, 2),
                    "綜合報酬率%": round(tot_pct, 2), "出場原因": "🏆 完美停利 (半倉+8% & 破10MA)"
                })
                print(f"   [波段出場] {name} 破 10MA 全數落袋，綜合報酬: {tot_pct:+.2f}%")
                continue

            # (5) 時間停損 (4天無動能)
            if d >= 4 and not pos.get('lot_a_sold') and close <= entry_p * 1.03:
                exit_p = close
                shares_left = pos['shares_a'] + pos['shares_b']
                rev = shares_left * exit_p * (1 - FEE_RATE - TAX_RATE)
                pnl_amt = rev - pos['total_invested']
                pnl_pct = (exit_p - entry_p) / entry_p * 100

                new_closed_trades.append({
                    "代號": code, "名稱": name, "進場日": pos['entry_date'], "進場價": entry_p,
                    "出場日": today_str, "持股天數": d, "投入金額": int(pos['total_invested']),
                    "回收金額": int(rev), "淨損益(NTD)": int(pnl_amt), "部位A_損益%": round(pnl_pct, 2),
                    "部位B_損益%": round(pnl_pct, 2), "綜合報酬率%": round(pnl_pct, 2), "出場原因": "⏳ 時間停損 (4天無動能)"
                })
                print(f"   [時間停損] {name} 持有滿 4 天未發動，平倉離場")
                continue

            # 💡 記錄最新即時關鍵價位
            pos['curr_price'] = round(close, 1)
            pos['unrealized_pct'] = round((close - entry_p) / entry_p * 100, 2)
            pos['ma10'] = round(ma10, 1)
            pos['curr_stop'] = round(effective_stop, 1)
            pos['tp_stage1'] = round(entry_p * 1.08, 1)
            remaining_positions.append(pos)

        except Exception as e:
            print(f"⚠️ 分析 {ticker} 異常: {e}")
            remaining_positions.append(pos)

    # ================= 2. 檢驗今日雷達新候選股建倉 =================
    open_slots = MAX_SLOTS - len(remaining_positions)
    squat_candidates = [s for s in report.get("stocks", []) if s.get("is_squat")]

    if open_slots > 0 and squat_candidates:
        for cand in squat_candidates[:open_slots]:
            cand_code = cand['code']
            if any(p['code'] == cand_code for p in remaining_positions):
                continue
            
            cand_ticker = cand['ticker']
            cand_name = cand['name']
            buy_price = float(cand['close'])
            
            total_shares = int(SLOT_BUDGET / (buy_price * (1 + FEE_RATE)))
            if total_shares < 100: continue
            
            shares_a = total_shares // 2
            shares_b = total_shares - shares_a
            cost = total_shares * buy_price * (1 + FEE_RATE)
            
            remaining_positions.append({
                "code": cand_code, "name": cand_name, "ticker": cand_ticker,
                "entry_date": today_str, "entry_price": buy_price,
                "total_invested": cost, "shares_a": shares_a, "shares_b": shares_b,
                "days_held": 0, "is_breakeven": False, "lot_a_sold": False,
                "lot_a_revenue": 0.0, "lot_a_pnl_pct": 0.0,
                "curr_price": buy_price, "unrealized_pct": 0.0,
                "curr_stop": round(buy_price * 0.96, 1),
                "tp_stage1": round(buy_price * 1.08, 1),
                "ma10": round(buy_price * 0.99, 1)
            })
            print(f"   [新開倉] 建立實盤虛擬持倉：{cand_name} ({cand_code})，買入價 ${buy_price}")

    save_json(POSITIONS_FILE, remaining_positions)
    
    if new_closed_trades:
        df_new = pd.DataFrame(new_closed_trades)
        df_history = pd.concat([df_history, df_new], ignore_index=True)
        df_history.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")

    print(f"✅ [Tracker 完成] 當前在倉部位：{len(remaining_positions)} 檔，歷史累積結案：{len(df_history)} 筆")

if __name__ == "__main__":
    run_tracker()
