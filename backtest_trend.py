#!/usr/bin/env python3
"""
بک‌تست ادامه‌ی روند: شروع روند (تقاطع طلایی EMA20/EMA50 در ۴۸ کندل اخیر)،
سپس برگشت به EMA20 و بسته‌شدن سبز بالای آن. حد ضرر: کف ۶ کندل. هدف: ۲R. زمان: ۴۸ کندل.
universe و داده از backtest_multi، آمار از backtest_live.
"""
import backtest_live as bt
import backtest_multi as m
import signal_bot as sb

RR = 2.0
MAX_HOLD = 48
FEE = 0.001


def ema_series(vals, n):
    k = 2 / (n + 1)
    out, e = [], vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def run_symbol_trend(rows):
    o = [float(x[1]) for x in rows]
    h = [float(x[2]) for x in rows]
    l = [float(x[3]) for x in rows]
    c = [float(x[4]) for x in rows]
    e20, e50 = ema_series(c, 20), ema_series(c, 50)
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
        if not e20[j] > e50[j]:
            continue
        # تقاطع طلایی در ۴۸ کندل اخیر
        recent_cross = any(e20[k - 1] <= e50[k - 1] and e20[k] > e50[k] for k in range(j - 48, j + 1))
        if not recent_cross:
            continue
        # برگشت به EMA20 و بسته‌شدن سبز بالای آن
        if not (min(l[j - 2:j + 1]) <= e20[j] * 1.005 and c[j] > e20[j] and c[j] > o[j]):
            continue
        entry = o[i]
        stop = min(l[j - 5:j + 1]) * 0.998
        risk = entry - stop
        if risk <= 0 or risk / entry > 0.30:
            continue
        pos = {"entry": entry, "stop": stop, "target": entry + RR * risk, "i": i}
    return trades


def main():
    uni = m.universe()
    trades, used = [], 0
    for base, sym in uni:
        try:
            rows = bt.fetch(sym)
        except Exception:  # noqa: BLE001
            rows = []
        if len(rows) < 300:
            continue
        used += 1
        trades += run_symbol_trend(rows)
    text = "\n".join([
        "📊 <b>بک‌تست ادامه‌ی روند (EMA، ۱ سال)</b>",
        f"ارز بررسی‌شده: {used} از {len(uni)}", "",
        bt.stats(trades), bt.verdict(trades), "",
        "⚠️ لیست فعلی تبدیل استفاده شد. تاریخچه است، پیشنهاد خرید نیست."])
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()