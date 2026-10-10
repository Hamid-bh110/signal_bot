#!/usr/bin/env python3
"""
اسکنر کوکوین: فقط ارزهایی که هم کوکوین و هم تبدیل دارن، با رشد ۲۴ ساعته ≥ ۲۰٪
و شرط شکست سقف (همون check_breakout ربات سیگنال). فقط پیام می‌فرسته؛ هیچ سفارشی ثبت نمی‌کنه.
"""
import sys
import time

import signal_bot as sb

KC = "https://api.kucoin.com"
PUMP_PCT = 20.0
MIN_VOL_USDT = 500_000
MAX_CHECK = 30
MAX_SIGNALS = 5


def kc_tickers():
    d = sb.http_get(f"{KC}/api/v1/market/allTickers")
    if not d or d.get("code") != "200000":
        return None
    return d["data"]["ticker"]


def kc_klines(sym, hours=120):
    end = int(time.time())
    start = end - hours * 3600
    d = sb.http_get(f"{KC}/api/v1/market/candles",
                    params={"type": "1hour", "symbol": sym, "startAt": start, "endAt": end})
    if not d or d.get("code") != "200000":
        return []
    rows = []
    # کوکوین: جدیدترین اول → به ترتیب زمانی و ساختار بایننس تبدیل می‌کنیم
    for r in reversed(d["data"]):
        t = int(r[0]) * 1000
        o, c, h, l = float(r[1]), float(r[2]), float(r[3]), float(r[4])
        vol, amt = float(r[5]), float(r[6])
        rows.append([t, o, h, l, c, vol, t + 3599999, amt, 0, 0, 0, 0])
    return rows


def candidates():
    tk = kc_tickers()
    if tk is None:
        return None, "دیتای کوکوین دریافت نشد"
    tab = sb.tabdeal_coins()
    if tab is None:
        return None, "لیست تبدیل دریافت نشد؛ اسکن انجام نشد"
    out = []
    for t in tk:
        sym = t.get("symbol", "")
        if not sym.endswith("-USDT"):
            continue
        base = sym[:-5]
        if base in sb.STABLES or base in sb.MAJORS_EXCLUDED or base.endswith(sb.LEVERAGED_SUFFIXES):
            continue
        if base not in tab:
            continue
        try:
            pct = float(t["changeRate"]) * 100
            vol = float(t["volValue"])
            last = float(t.get("last") or 0)
        except (KeyError, ValueError, TypeError):
            continue
        if pct < PUMP_PCT or vol < MIN_VOL_USDT:
            continue
        out.append((pct, sym, base, last, vol))
    out.sort(reverse=True)
    return out, ""


def build_message(items):
    lines = ["🔵 <b>سیگنال کوکوین + تبدیل (شکست سقف)</b>"]
    for pct, base, sig in items:
        lines.append(
            f"\n<b>{base}</b> | رشد ۲۴ ساعته +{pct:.1f}٪\n"
            f"ورود: <code>{sig['entry']:.6g}</code> | حد ضرر: <code>{sig['stop']:.6g}</code> "
            f"({sig['risk_pct']:.1f}٪)\n"
            f"هدف ۱: <code>{sig['t1']:.6g}</code> | هدف ۲: <code>{sig['t2']:.6g}</code>\n"
            f"RSI: {sig['rsi']:.0f} | حجم: {sig['vol_ratio']:.1f} برابر میانگین")
    lines.append("\n⚠️ <b>پیشنهاد خرید نیست.</b> قیمت تبدیل ممکنه کمی متفاوت باشه، و "
                 "ارزهای این‌قدر بالا رفته پرریسک‌اند.")
    return "\n".join(lines)


def main():
    cands, err = candidates()
    if cands is None:
        print(err)
        sys.exit(1)
    print(f"candidates: {len(cands)}")
    found = []
    for pct, sym, base, _last, _vol in cands[:MAX_CHECK]:
        kl = kc_klines(sym)
        sig = sb.check_breakout(kl) if kl else None
        if sig:
            found.append((pct, base, sig))
            print(f"signal: {base} +{pct:.1f}%")
        time.sleep(0.3)
        if len(found) >= MAX_SIGNALS:
            break
    if not found:
        print("no signals")
        return
    msg = build_message(found)
    print(msg)
    sb.send(msg)


if __name__ == "__main__":
    main()