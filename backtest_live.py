#!/usr/bin/env python3
"""
بک‌تست همون منطق سیگنال فعلی روی تمام ارزهای پرحجم بایننس (USDT)، ۱ سال، تایم ۱ ساعته.
دو حالت جدا:
  LIVE  : همون سیگنال فعلی (رشد ۲۴ ساعته ≥ ۲۰٪ + شکست سقف + حجم + RSI + ATR + سبز)
  EARLY : همون شرط‌ها بدون شرط رشد ۲۰٪
"""
import time

import requests

import signal_bot as sb

BINANCE = sb.BINANCE
DAYS = 365
TOP_N = 120
MIN_QV = 3_000_000
FEE = 0.001
PUMP_PCT = 0.20
VOL_MULT = 2.5
RSI_LO, RSI_HI = 55, 82
ATR_MIN = 0.01
STOP_BUFFER = 0.002
RR = 3.0
MAX_HOLD = 48


def universe():
    tk = sb.http_get(f"{BINANCE}/api/v3/ticker/24hr") or []
    out = []
    for t in tk:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base in sb.STABLES or base in sb.MAJORS_EXCLUDED or base.endswith(sb.LEVERAGED_SUFFIXES):
            continue
        try:
            qv = float(t["quoteVolume"])
        except (KeyError, ValueError):
            continue
        if qv >= MIN_QV:
            out.append((qv, sym))
    out.sort(reverse=True)
    return [s for _, s in out[:TOP_N]]


def fetch(sym):
    end = int(time.time() * 1000)
    start = end - DAYS * 86_400_000
    rows = []
    while start < end:
        r = requests.get(f"{BINANCE}/api/v3/klines", params={
            "symbol": sym, "interval": "1h", "startTime": start, "limit": 1000}, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        rows.extend(data)
        start = data[-1][0] + 1
        time.sleep(0.15)
    return rows


def run_symbol(rows, pump_filter):
    o = [float(x[1]) for x in rows]
    h = [float(x[2]) for x in rows]
    l = [float(x[3]) for x in rows]
    c = [float(x[4]) for x in rows]
    v = [float(x[7]) for x in rows]
    n = len(rows)
    trades, pos = [], None
    for i in range(60, n):
        if pos:
            ex = None
            if l[i] <= pos["stop"]:
                ex = (pos["stop"], "stop")
            elif h[i] >= pos["target"]:
                ex = (pos["target"], "target")
            elif i - pos["i"] >= MAX_HOLD:
                ex = (c[i], "time")
            if ex:
                trades.append({"ret": ex[0] / pos["entry"] - 1 - 2 * FEE, "reason": ex[1]})
                pos = None
            continue
        j = i - 1
        if not c[j] > max(h[j - 24:j]):
            continue
        if pump_filter and c[j] / c[j - 24] - 1 < PUMP_PCT:
            continue
        avg_v = sum(v[j - 24:j]) / 24
        if avg_v <= 0 or v[j] / avg_v < VOL_MULT:
            continue
        if not c[j] > o[j]:
            continue
        r = sb.rsi(c[:j + 1])
        if r is None or not (RSI_LO <= r <= RSI_HI):
            continue
        a = sb.atr(h[:j + 1], l[:j + 1], c[:j + 1])
        if a is None or a / c[j] * 100 < ATR_MIN * 100:
            continue
        entry = o[i]
        stop = min(l[j - 5:j + 1]) * (1 - STOP_BUFFER)
        risk = entry - stop
        if risk <= 0 or risk / entry > 0.30:
            continue
        pos = {"entry": entry, "stop": stop, "target": entry + RR * risk, "i": i}
    return trades


def stats(trades):
    if not trades:
        return "معامله‌ای نبود"
    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else 0
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    reasons = {k: sum(1 for t in trades if t["reason"] == k) for k in ("stop", "target", "time")}
    return (f"معامله={len(rets)} | برد={len(wins) / len(rets):.0%} | میانگین={sum(rets) / len(rets):.2%} | "
            f"PF={pf:.2f} | افت حداکثر={mdd:.1%} | خروج={reasons}")


def verdict(trades):
    n = len(trades)
    if n < 30:
        return "تعداد معامله کمه (<۳۰): آماری قابل اتکا نیست"
    rets = [t["ret"] for t in trades]
    avg = sum(rets) / n
    gp = sum(r for r in rets if r > 0)
    gl = -sum(r for r in rets if r < 0)
    pf = gp / gl if gl > 0 else 0
    if avg > 0 and pf > 1.2:
        return "امیدوارکننده: قبل از هر پول واقعی، دوره‌ی دیگه هم تست کن"
    return "ضعیف یا نامطمئن: این شرط‌ها سود کافی نداشتن"


def main():
    syms = universe()
    print(f"universe: {len(syms)} symbols")
    live, early = [], []
    for s in syms:
        rows = fetch(s)
        if len(rows) < 300:
            continue
        live += run_symbol(rows, pump_filter=True)
        early += run_symbol(rows, pump_filter=False)
    out = ["📊 <b>بک‌تست سیگنال فعلی (۱ سال، کل بایننس پرحجم)</b>",
           f"تعداد ارز: {len(syms)}", "",
           f"<b>LIVE (با شرط ۲۰٪):</b>\n{stats(live)}\n{verdict(live)}", "",
           f"<b>EARLY (بدون شرط ۲۰٪):</b>\n{stats(early)}\n{verdict(early)}", "",
           "⚠️ فیلتر تبدیل تاریخی ممکن نیست؛ نتیجه کمی خوش‌بینانه‌تره. تاریخچه است، پیشنهاد خرید نیست."]
    text = "\n".join(out)
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()