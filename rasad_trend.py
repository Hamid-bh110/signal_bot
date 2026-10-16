#!/usr/bin/env python3
"""
رصد لحظه‌ای روند: برای همه‌ی ارزهای USDT کوکوین و گیت، وضعیت روند همین الان
(EMA20/EMA50، موقعیت قیمت، RSI، حجم، ATR) را حساب می‌کند و حد ضرر و تارگت می‌دهد.
خوانش لحظه‌ای اندیکاتور است؛ سیگنال خرید نیست.
"""
import rasad as rs
import signal_bot as sb

TOP = 60


def ema(vals, n):
    k = 2 / (n + 1)
    out, e = [], vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def read_trend(src, sym):
    o, h, l, c, v = rs.candles(src, sym)
    if len(c) < 60:
        return None
    j = len(c) - 2  # آخرین کندل بسته‌شده
    e20, e50 = ema(c[:j + 1], 20), ema(c[:j + 1], 50)
    if not e20[j] > e50[j]:
        return None  # فقط روند صعودی
    dist20 = (c[j] / e20[j] - 1) * 100
    if dist20 < -3 or dist20 > 3:
        return None  
    r = sb.rsi(c[:j + 1])
    a = sb.atr(h[:j + 1], l[:j + 1], c[:j + 1])
    if r is None or a is None:
        return None
    if not 35 <= r <= 60:
        return None  
    avg_v = sum(v[j - 24:j]) / 24 if j >= 24 else 0
    vr = v[j] / avg_v if avg_v > 0 else 0
    entry = c[j]
    stop = min(l[j - 5:j + 1]) * 0.998
    risk = entry - stop
    if risk <= 0 or risk / entry > 0.30:
        return None
    return {"entry": entry, "stop": stop, "t1": entry + 1.5 * risk, "t2": entry + 2 * risk,
            "rsi": r, "vr": vr, "dist20": dist20}


def main():
    uni = []
    for fn in (rs.kucoin_universe, rs.gate_universe):
        try:
            uni += fn()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {fn.__name__}: {e}")
    uni.sort(key=lambda x: -x[2])
    uni = uni[:TOP * 3]
    rows = []
    for src, sym, _ in uni:
        try:
            res = read_trend(src, sym)
        except Exception:  # noqa: BLE001
            continue
        if res:
            rows.append((src, sym, res))
    rows.sort(key=lambda x: -x[2]["vr"])
    name = {"KC": "KuCoin", "GT": "Gate"}
    lines = ["📡 <b>رصد لحظه‌ای روند صعودی (کوکوین + گیت)</b>",
             f"ارزهای بررسی‌شده: {len(uni)} | روند صعودی فعلی: {len(rows)}", ""]
    for src, sym, r in rows[:TOP]:
        lines.append(f"• {sym} ({name[src]}) | ورود {r['entry']:.6g} | حد ضرر {r['stop']:.6g} "
                     f"| هدف۱ {r['t1']:.6g} | هدف۲ {r['t2']:.6g} | RSI {r['rsi']:.0f} | "
                     f"حجم {r['vr']:.1f}× | فاصله از EMA20 {r['dist20']:+.1f}٪")
    if not rows:
        lines.append("الان هیچ ارزی روند صعودی با شرایط خوانده‌شده ندارد.")
    lines += ["", "⚠️ خوانش لحظه‌ای اندیکاتور است؛ سیگنال خرید نیست و سود تضمین نمی‌کند."]
    text = "\n".join(lines)
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()