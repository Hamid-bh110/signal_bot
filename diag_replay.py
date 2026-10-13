#!/usr/bin/env python3
"""
ابزار تشخیصی: ساعت به ساعت نشون می‌ده شرط‌های شکست سقف (بدون رشد ۲۰٪)
قبل از رسیدن رشد ۲۴ ساعته به ۲۰٪ برقرار بودن یا نه. فقط گزارش؛ هیچ سیگنالی نمی‌فرسته.
"""
import datetime as dt
import os

import signal_bot as sb

BINANCE = sb.BINANCE
SYMBOLS = [s.strip() for s in os.environ.get(
    "DIAG_SYMBOLS", "SUSDT,BATUSDT,CKBUSDT").split(",") if s.strip()]
HOURS = int(os.environ.get("DIAG_HOURS", "72"))


def fetch(sym):
    return sb.http_get(f"{BINANCE}/api/v3/klines",
                       params={"symbol": sym, "interval": "1h", "limit": 200}) or []


def shape_ok(kl, i):
    k = kl[:i + 1]
    o = [float(x[1]) for x in k]
    h = [float(x[2]) for x in k]
    l = [float(x[3]) for x in k]
    c = [float(x[4]) for x in k]
    v = [float(x[7]) for x in k]
    if len(k) < 50:
        return None
    last = c[-1]
    prior_high = max(h[-25:-1])
    avg_vol = sum(v[-25:-1]) / 24
    if avg_vol <= 0:
        return None
    vol_ratio = v[-1] / avg_vol
    r = sb.rsi(c)
    a = sb.atr(h, l, c)
    if r is None or a is None:
        return None
    checks = {
        "شکست سقف": last > prior_high,
        "کندل سبز": c[-1] > o[-1],
        "حجم": vol_ratio >= sb.CEX_VOLUME_RATIO,
        "RSI": sb.CEX_RSI_RANGE[0] <= r <= sb.CEX_RSI_RANGE[1],
        "ATR": a / last * 100 >= sb.CEX_MIN_ATR_PCT,
    }
    return checks, r, vol_ratio


def analyze(sym):
    kl = fetch(sym)
    if len(kl) < 80:
        return f"{sym}: دیتای کافی نیست"
    n = len(kl)
    start = max(50, n - 1 - HOURS)
    first_shape = None
    first_20 = None
    for i in range(start, n - 1):
        close_i = float(kl[i][4])
        close_24 = float(kl[i - 24][4])
        pct = (close_i / close_24 - 1) * 100
        if pct >= 20 and first_20 is None:
            first_20 = (i, pct)
        res = shape_ok(kl, i)
        if res and all(res[0].values()) and first_shape is None:
            first_shape = (i, pct, res[1], res[2])

    def ts(i):
        return dt.datetime.utcfromtimestamp(int(kl[i][0]) / 1000).strftime("%m-%d %H:%M")

    lines = [f"<b>{sym}</b>"]
    if first_20:
        lines.append(f"  اولین رشد ≥۲۰٪: {ts(first_20[0])} UTC ({first_20[1]:+.1f}٪)")
    if first_shape:
        i, pct, r, vr = first_shape
        lines.append(f"  اولین شکل کامل: {ts(i)} UTC | رشد {pct:+.1f}٪ | RSI {r:.0f} | حجم {vr:.1f}×")
        if first_20 and first_shape[0] < first_20[0]:
            lines.append("  ⚠️ شکل کامل قبل از ۲۰٪ بوده")
        elif first_20:
            lines.append("  شکل کامل بعد از ۲۰٪ دیده شد (شرط ۲۰٪ یا RSI دیر کرده)")
    else:
        lines.append("  شکل کامل در بازه دیده نشد")
    return "\n".join(lines)


def main():
    parts = ["🔎 <b>بازپخش تشخیصی (قبل از ۲۰٪)</b>", f"بازه: {HOURS} ساعت گذشته", ""]
    for s in SYMBOLS:
        try:
            parts.append(analyze(s))
        except Exception as e:  # noqa: BLE001
            parts.append(f"{s}: خطا: {e}")
        parts.append("")
    parts.append("⚠️ فقط تاریخچه‌ست؛ پیشنهاد خرید نیست.")
    text = "\n".join(parts)
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()