#!/usr/bin/env python3
"""
بک‌تست شکست سقف (همون منطق ربات سیگنال) روی ۱ سال دیتای بایننس، تایم ۱ ساعته.
ورود: باز شدن کندل بعد از سیگنال، وقتی کندل قبلی:
  - سقف ۲۴ کندل قبلش رو شکسته
  - رشد ۲۴ ساعته ≥ ۲۰٪
  - حجم ≥ ۲.۵ برابر میانگین ۲۰ کندل
  - RSI بین ۵۵ تا ۸۲
  - ATR ≥ ۱٪ قیمت
حد ضرر: ۰.۲٪ زیر پایین‌ترین کف ۶ کندل اخیر. تارگت: ۳ برابر ریسک. زمان: حداکثر ۴۸ کندل.
کارمزد ۰.۱٪ هر طرف.
"""
import time
import requests

BINANCE = "https://data-api.binance.vision"
SYMBOLS = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
           "APTUSDT", "DOTUSDT", "MAGICUSDT", "NEARUSDT", "INJUSDT", "SUIUSDT",
           "ARBUSDT", "OPUSDT", "FETUSDT", "ATOMUSDT"]
DAYS = 365
FEE = 0.001
PUMP_PCT = 0.20
VOL_MULT = 2.5
RSI_LO, RSI_HI = 55, 82
ATR_MIN = 0.01
STOP_BUFFER = 0.002
RR = 3.0
MAX_HOLD = 48


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


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def atr(h, l, c, n=14):
    trs = []
    for i in range(len(c) - n, len(c)):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return sum(trs) / n


def run_symbol(rows):
    o = [float(x[1]) for x in rows]
    h = [float(x[2]) for x in rows]
    l = [float(x[3]) for x in rows]
    c = [float(x[4]) for x in rows]
    v = [float(x[5]) for x in rows]
    n = len(rows)
    trades = []
    pos = None
    for i in range(30, n):
        if pos:
            ex = None
            if l[i] <= pos["stop"]:
                ex = (pos["stop"], "stop")
            elif h[i] >= pos["target"]:
                ex = (pos["target"], "target")
            elif i - pos["i"] >= MAX_HOLD:
                ex = (c[i], "time")
            if ex:
                trades.append({"ret": ex[0] / pos["entry"] - 1 - 2 * FEE,
                               "reason": ex[1]})
                pos = None
            continue

        j = i - 1
        if not c[j] > max(h[j - 24:j]):
            continue
        if c[j] / c[j - 24] - 1 < PUMP_PCT:
            continue
        avg_vol = sum(v[j - 20:j]) / 20
        if v[j] < VOL_MULT * avg_vol:
            continue
        r = rsi(c[:j + 1])
        if r is None or not (RSI_LO <= r <= RSI_HI):
            continue
        a = atr(h[:j + 1], l[:j + 1], c[:j + 1])
        if a / c[j] < ATR_MIN:
            continue
        entry = o[i]
        stop = min(l[j - 5:j + 1]) * (1 - STOP_BUFFER)
        risk = entry - stop
        if risk <= 0 or risk / entry > 0.30:
            continue
        pos = {"entry": entry, "stop": stop,
               "target": entry + RR * risk, "i": i}
    return trades


def summarize(name, trades, buyhold=None):
    if not trades:
        print(f"{name}: معامله‌ای نبود")
        return
    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else 0
    reasons = {k: sum(1 for t in trades if t["reason"] == k)
               for k in ("stop", "target", "time")}
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
    avg = sum(t["ret"] for t in all_trades) / n
    gp = sum(t["ret"] for t in all_trades if t["ret"] > 0)
    gl = -sum(t["ret"] for t in all_trades if t["ret"] < 0)
    pf = gp / gl if gl > 0 else 0
    if n < 30:
        return "تعداد معامله کمه: آماری قابل اتکا نیست"
    if avg > 0 and pf > 1.2:
        return "امیدوارکننده: قبل از هر پول واقعی، روی دوره‌ی دیگه هم تست کن"
    return "ضعیف یا نامطمئن: به ربات معامله‌گر اضافه نشه"


def main():
    all_trades = []
    for s in SYMBOLS:
        try:
            rows = fetch(s, DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"{s}: خطا در دریافت دیتا: {e}")
            continue
        if len(rows) < 300:
            print(f"{s}: دیتای کافی نیست ({len(rows)} کندل)")
            continue
        bh = float(rows[-1][4]) / float(rows[0][1]) - 1
        trades = run_symbol(rows)
        all_trades += trades
        summarize(s, trades, bh)
    print("=" * 60)
    summarize("TOTAL", all_trades)
    print(f"نتیجه: {verdict(all_trades)}")


if __name__ == "__main__":
    main()