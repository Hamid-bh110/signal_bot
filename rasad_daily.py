#!/usr/bin/env python3
"""
رصد روزانه‌ی روند: روند صعودی وقتی تأیید میشه که EMA20 بالای EMA50 در ۵ روز بسته‌شده‌ی آخر باشه.
شرط رشد امروز: حداقل ۱۵٪ نسبت به دیروز. کندل روزانه، کوکوین + گیت. فقط رصد؛ سیگنال خرید نیست.
"""
import os
import requests

import signal_bot as sb

MIN_QV = float(os.environ.get("MIN_QV", "500000"))
CONFIRM_DAYS = 5
TODAY_MIN_PCT = 15
TOP = 60


def get(url, **kw):
    r = requests.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def ema(vals, n):
    k = 2 / (n + 1)
    out, e = [], vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def universe():
    out = []
    for t in get("https://api.kucoin.com/api/v1/market/allTickers")["data"]["ticker"]:
        s = t.get("symbol", "")
        if s.endswith("-USDT") and float(t.get("volValue") or 0) >= MIN_QV:
            out.append(("KC", s))
    for t in get("https://api.gateio.ws/api/v4/spot/tickers"):
        s = t.get("currency_pair", "")
        if s.endswith("_USDT") and float(t.get("quote_volume") or 0) >= MIN_QV:
            out.append(("GT", s))
    return out


def daily(src, sym):
    if src == "KC":
        rows = list(reversed(get("https://api.kucoin.com/api/v1/market/candles",
                                 params={"type": "1day", "symbol": sym})["data"]))
        o = [float(x[1]) for x in rows]
        c = [float(x[2]) for x in rows]
        h = [float(x[3]) for x in rows]
        l = [float(x[4]) for x in rows]
        v = [float(x[6]) for x in rows]
    else:
        rows = get("https://api.gateio.ws/api/v4/spot/candlesticks",
                   params={"currency_pair": sym, "interval": "1d", "limit": 200})
        c = [float(x[2]) for x in rows]
        h = [float(x[3]) for x in rows]
        l = [float(x[4]) for x in rows]
        o = [float(x[5]) for x in rows]
        v = [float(x[1]) for x in rows]
    return o, h, l, c, v


def read_daily(src, sym):
    o, h, l, c, v = daily(src, sym)
    if len(c) < 60:
        return None
    j = len(c) - 2  # آخرین روز بسته‌شده
    e20, e50 = ema(c[:j + 1], 20), ema(c[:j + 1], 50)
    if not all(e20[k] > e50[k] for k in range(j - CONFIRM_DAYS + 1, j + 1)):
        return None  # روند در ۵ روز آخر تأیید نشده
    dist20 = (c[j] / e20[j] - 1) * 100
    if dist20 < -3 or dist20 > 3:
        return None
    today_pct = (c[j] / c[j - 1] - 1) * 100
    if today_pct < TODAY_MIN_PCT:
        return None  # فقط ارزهایی که امروز حداقل ۱۵٪ بالا رفتن
    r = sb.rsi(c[:j + 1])
    a = sb.atr(h[:j + 1], l[:j + 1], c[:j + 1])
    if r is None or a is None:
        return None
    entry = c[j]
    stop = min(l[j - 5:j + 1]) * 0.998
    risk = entry - stop
    if risk <= 0 or risk / entry > 0.30:
        return None
    avg_v = sum(v[j - 20:j]) / 20
    vr = v[j] / avg_v if avg_v > 0 else 0
    return {"entry": entry, "stop": stop, "t1": entry + 1.5 * risk, "t2": entry + 2 * risk,
            "rsi": r, "vr": vr, "dist20": dist20, "today": today_pct}


def main():
    uni = universe()[:TOP * 3]
    rows = []
    for src, sym in uni:
        try:
            res = read_daily(src, sym)
        except Exception:  # noqa: BLE001
            continue
        if res:
            rows.append((src, sym, res))
    rows.sort(key=lambda x: -x[2]["today"])
    name = {"KC": "KuCoin", "GT": "Gate"}
    lines = ["📅 <b>رصد روزانه: روند تأییدشده + رشد امروز ≥ ۱۵٪</b>",
             f"ارزهای بررسی‌شده: {len(uni)} | موارد: {len(rows)}", ""]
    for src, sym, r in rows[:TOP]:
        lines.append(f"• {sym} ({name[src]}) | امروز {r['today']:+.1f}٪ | ورود {r['entry']:.6g} "
                     f"| حد ضرر {r['stop']:.6g} | هدف۱ {r['t1']:.6g} | هدف۲ {r['t2']:.6g} "
                     f"| RSI {r['rsi']:.0f} | حجم {r['vr']:.1f}×")
    if not rows:
        lines.append("امروز هیچ ارزی با این شرط‌ها نیست.")
    lines += ["", "⚠️ خوانش روزانه‌ی اندیکاتور؛ سیگنال خرید نیست و سود تضمین نمی‌کند."]
    text = "\n".join(lines)
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()