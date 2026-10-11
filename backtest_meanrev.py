#!/usr/bin/env python3
"""
بک‌تست نوسان‌گیری (برگشت از کف): ورود وقتی RSI زیر ۳۰ بوده و کندل بعدی سبز شده.
حد ضرر: ۱.۵×ATR زیر ورود. هدف: ۱.۵×ریسک. حداکثر نگه‌داری ۲۴ کندل. کارمزد ۰.۱٪ هر طرف.
"""
import backtest_live as bt
import backtest_multi as m
import signal_bot as sb

RSI_ENTRY = 30
ATR_STOP_MULT = 1.5
RR = 1.5
MAX_HOLD = 24
FEE = 0.001


def run_symbol_mr(rows):
    o = [float(x[1]) for x in rows]
    h = [float(x[2]) for x in rows]
    l = [float(x[3]) for x in rows]
    c = [float(x[4]) for x in rows]
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
        r_prev = sb.rsi(c[:j])
        if r_prev is None or r_prev > RSI_ENTRY:
            continue
        if not c[j] > o[j]:
            continue
        a = sb.atr(h[:j + 1], l[:j + 1], c[:j + 1])
        if a is None:
            continue
        entry = o[i]
        stop = entry - ATR_STOP_MULT * a
        risk = entry - stop
        if risk <= 0:
            continue
        pos = {"entry": entry, "stop": stop, "target": entry + RR * risk, "i": i}
    return trades


def main():
    uni = m.universe()
    trades = []
    used = 0
    for base, src, sym in [(x[:-4], "BN", x) if isinstance(x, str) else (x if len(x) == 3 else (x[0], "BN", x[1])) for x in uni]:
        try:
            rows = bt.fetch(sym) if src == "BN" else m.fetch_kc(sym)
        except Exception as e:  # noqa: BLE001
            print(f"[error] {sym}: {e}")
            rows = []
        if len(rows) < 300:
            continue
        used += 1
        trades += run_symbol_mr(rows)
    text = "\n".join([
        "📊 <b>بک‌تست نوسان‌گیری (برگشت از کف، ۱ سال)</b>",
        f"ارز بررسی‌شده: {used} از {len(uni)}", "",
        f"{bt.stats(trades)}", bt.verdict(trades), "",
        "⚠️ فیلتر تبدیل تاریخی ممکن نیست؛ لیست فعلی استفاده شد. تاریخچه است، پیشنهاد خرید نیست."])
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()