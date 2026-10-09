#!/usr/bin/env python3
"""
بک‌تست NDS (فقط خرید، تایم ۱ ساعته، دیتای عمومی بایننس)
دو حالت جدا: HOOK (هوک تنها) و HHR (Hook-Hook-Rally)
تفسیر من از قواعد کتاب است؛ نتیجه فقط برای همین تفسیر معتبره.
"""
import time
import requests

BINANCE = "https://data-api.binance.vision"
SYMBOLS = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
           "LINKUSDT", "APTUSDT", "DOTUSDT"]
DAYS = 365
PIVOT_N = 3           # سوئینگ: بالاترین/پایین‌ترین کندل در ۳ کندل دو طرف
FEE = 0.001           # کارمزد هر طرف
RR = 2.0              # نسبت سود به ریسک
STOP_BUFFER = 0.002   # حد ضرر کمی پایین‌تر از کف سوم
MAX_HOLD = 72         # حداکثر نگه‌داری (کندل)
SETUP_EXPIRY = 48     # ستاپ اگر ظرف این تعداد کندل شکسته نشه، منقضی میشه
HHR_TIME_RATIO = 1.0  # هوک دوم حداقل این نسبت از هوک اول طول زمانی داشته باشه
MODES = ["HOOK", "HHR"]


def fetch(symbol, days):
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    rows = []
    while start < end:
        r = requests.get(f"{BINANCE}/api/v3/klines", params={
            "symbol": symbol, "interval": "1h", "startTime": start, "limit": 1000},
            timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows.extend(data)
        start = data[-1][0] + 1
        time.sleep(0.2)
    return rows


def valid_hook(p):
    """p = شش نقطه‌ی سوئینگ متناوب: T(H), L1, H1, L2, H2, L3.
    برمی‌گرداند (درست/نادرست، طول زمانی هوک بر حسب کندل)."""
    T, L1, H1, L2, H2, L3 = p
    ok = (T[2] > H2[2] and L2[2] < L1[2] and L3[2] < L2[2]
          and H2[2] > H1[2] and H2[2] >= L3[2] + 0.864 * (T[2] - L3[2]))
    return ok, L3[1] - T[1]


def run_symbol(rows, mode):
    o = [float(x[1]) for x in rows]
    h = [float(x[2]) for x in rows]
    l = [float(x[3]) for x in rows]
    c = [float(x[4]) for x in rows]
    n = len(rows)
    pivots = []           # (نوع 'H'/'L', اندیس کندل, قیمت)
    trades = []
    setup = None
    pos = None
    last_pivot_count = -1

    def add_pivot(t, idx, price):
        if pivots and pivots[-1][0] == t:
            better = price > pivots[-1][2] if t == 'H' else price < pivots[-1][2]
            if better:
                pivots[-1] = (t, idx, price)
            return
        pivots.append((t, idx, price))

    for i in range(2 * PIVOT_N, n):
        cidx = i - PIVOT_N
        if h[cidx] == max(h[cidx - PIVOT_N:cidx + PIVOT_N + 1]):
            add_pivot('H', cidx, h[cidx])
        if l[cidx] == min(l[cidx - PIVOT_N:cidx + PIVOT_N + 1]):
            add_pivot('L', cidx, l[cidx])

        # ۱) مدیریت پوزیشن باز
        if pos:
            exit_px, reason = None, None
            if l[i] <= pos['stop']:
                exit_px, reason = pos['stop'], 'stop'
            elif h[i] >= pos['target']:
                exit_px, reason = pos['target'], 'target'
            elif i - pos['entry_i'] >= MAX_HOLD:
                exit_px, reason = c[i], 'time'
            if exit_px is not None:
                trades.append({'ret': exit_px / pos['entry'] - 1 - 2 * FEE,
                               'reason': reason})
                pos = None
            continue

        # ۲) ساخت ستاپ، فقط وقتی نقطه‌ی سوئینگ جدیدی اضافه شده
        if len(pivots) != last_pivot_count:
            last_pivot_count = len(pivots)
            if setup is None:
                if mode == "HOOK" and len(pivots) >= 6:
                    types = ''.join(p[0] for p in pivots[-6:])
                    if types == 'HLHLHL':
                        ok, _ = valid_hook(pivots[-6:])
                        if ok:
                            H2 = pivots[-2][2]
                            L3 = pivots[-1][2]
                            setup = {'trigger': H2, 'stop': L3 * (1 - STOP_BUFFER),
                                     'created': i}
                elif mode == "HHR" and len(pivots) >= 12:
                    types = ''.join(p[0] for p in pivots[-12:])
                    if types == 'HLHLHLHLHLHL':
                        h1, h2 = pivots[-12:-6], pivots[-6:]
                        ok1, d1 = valid_hook(h1)
                        ok2, d2 = valid_hook(h2)
                        if (ok1 and ok2 and d1 > 0
                                and d2 >= HHR_TIME_RATIO * d1
                                and h2[4][2] > h1[4][2]):
                            setup = {'trigger': h2[4][2],
                                     'stop': h2[5][2] * (1 - STOP_BUFFER),
                                     'created': i}

        # ۳) ورود وقتی قیمت ستاپ رو بشکنه
        if setup:
            if i - setup['created'] > SETUP_EXPIRY or l[i] <= setup['stop']:
                setup = None
            elif h[i] >= setup['trigger']:
                entry = max(o[i], setup['trigger'])
                risk = entry - setup['stop']
                if risk > 0:
                    pos = {'entry': entry, 'stop': setup['stop'],
                           'target': entry + RR * risk, 'entry_i': i}
                setup = None
    return trades


def summarize(name, trades, buyhold=None):
    if not trades:
        print(f"{name}: معامله‌ای نبود")
        return
    rets = [t['ret'] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else 0
    reasons = {k: sum(1 for t in trades if t['reason'] == k)
               for k in ('stop', 'target', 'time')}
    line = (f"{name}: معامله={len(rets)} | برد={len(wins) / len(rets):.0%} | "
            f"میانگین={sum(rets) / len(rets):.2%} | PF={pf:.2f} | "
            f"افت حداکثر={mdd:.1%} | خروج={reasons}")
    if buyhold is not None:
        line += f" | خرید-و-نگهدار={buyhold:.1%}"
    print(line)


def verdict(all_trades):
    n = len(all_trades)
    if n == 0:
        return "بدون معامله: قابل ارزیابی نیست"
    avg = sum(t['ret'] for t in all_trades) / n
    gp = sum(t['ret'] for t in all_trades if t['ret'] > 0)
    gl = -sum(t['ret'] for t in all_trades if t['ret'] < 0)
    pf = gp / gl if gl > 0 else 0
    if n >= 50 and avg > 0 and pf > 1.2:
        return "امیدوارکننده: قبل از اضافه شدن به ربات، روی دوره‌ی دیگه هم تست کن"
    return "ضعیف یا نامطمئن: به ربات اضافه نشه"


def main():
    buyhold_cache = {}
    results = {m: [] for m in MODES}
    for s in SYMBOLS:
        try:
            rows = fetch(s, DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"{s}: خطا در دریافت دیتا: {e}")
            continue
        if len(rows) < 300:
            print(f"{s}: دیتای کافی نیست ({len(rows)} کندل)")
            continue
        buyhold_cache[s] = float(rows[-1][4]) / float(rows[0][1]) - 1
        for m in MODES:
            trades = run_symbol(rows, m)
            results[m] += trades
            summarize(f"{m} {s}", trades, buyhold_cache[s])
    print("=" * 60)
    for m in MODES:
        summarize(f"TOTAL {m}", results[m])
        print(f"نتیجه {m}: {verdict(results[m])}")
        print("-" * 60)


if __name__ == "__main__":
    main()
