#!/usr/bin/env python3
import os
import sys

from signal_bot import BINANCE, STABLES, LEVERAGED_SUFFIXES, MAJORS_EXCLUDED, \
    http_get, send, tabdeal_coins

MIN_CHANGE_PCT = float(os.environ.get("MIN_CHANGE_PCT", "20"))
MIN_QUOTE_VOLUME = 500_000
MAX_ITEMS = 10


def gainers():
    tickers = http_get(f"{BINANCE}/api/v3/ticker/24hr")
    if not tickers:
        return None, "دیتای بایننس دریافت نشد"
    tabdeal = tabdeal_coins()
    rows = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base in STABLES or base in MAJORS_EXCLUDED or base.endswith(LEVERAGED_SUFFIXES):
            continue
        try:
            chg = float(t["priceChangePercent"])
            qv = float(t["quoteVolume"])
            last = float(t["lastPrice"])
        except (KeyError, ValueError):
            continue
        if chg < MIN_CHANGE_PCT or qv < MIN_QUOTE_VOLUME:
            continue
        if tabdeal is not None and base not in tabdeal:
            continue
        rows.append((chg, base, last, qv))
    rows.sort(reverse=True)
    note = "" if tabdeal is not None else "\n⚠️ لیست تبدیل دریافت نشد."
    return rows[:MAX_ITEMS], note


def build_message(rows, note):
    lines = [f"🚀 <b>ارزهای پرتحرک امروز (رشد ۲۴ ساعته ≥ {MIN_CHANGE_PCT:g}٪)</b>", ""]
    if not rows:
        lines.append("ارزی با این شرط پیدا نشد.")
    for chg, base, last, qv in rows:
        lines.append(f"<b>{base}</b>  +{chg:.1f}٪  |  قیمت: <code>{last:.6g}</code>  |  حجم: ${qv:,.0f}")
    lines += ["", "⚠️ <b>هشدار:</b> این لیست سیگنال خرید نیست و ارزهای این‌قدر بالا رفته پرریسک‌اند." + note]
    return "\n".join(lines)


def main():
    rows, note = gainers()
    if rows is None:
        print(note)
        sys.exit(1)
    msg = build_message(rows, note)
    print(msg)
    ok = send(msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()