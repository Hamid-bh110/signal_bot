#!/usr/bin/env python3
"""
رصد همه‌ی ارزهای USDT کوکوین و گیت: فهرست ارزهایی که الان شرط‌های شکست فعلی را دارند.
فقط رصد است؛ سیگنال خرید نیست.
"""
import os
import requests

import signal_bot as sb

MIN_QV = float(os.environ.get("MIN_QV", "500000"))
TOP = 60


def get(url, **kw):
    r = requests.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def kucoin_universe():
    d = get("https://api.kucoin.com/api/v1/market/allTickers")["data"]["ticker"]
    out = []
    for t in d:
        s = t.get("symbol", "")
        if not s.endswith("-USDT"):
            continue
        try:
            qv = float(t.get("volValue") or 0)
        except ValueError:
            continue
        if qv >= MIN_QV:
            out.append(("KC", s, qv))
    return out


def gate_universe():
    d = get("https://api.gateio.ws/api/v4/spot/tickers")
    out = []
    for t in d:
        s = t.get("currency_pair", "")
        if not s.endswith("_USDT"):
            continue
        try:
            qv = float(t.get("quote_volume") or 0)
        except ValueError:
            continue
        if qv >= MIN_QV:
            out.append(("GT", s, qv))
    return out


def candles(src, sym):
    """خروجی: لیست‌های o,h,l,c,v (v = حجم به دلار)، قدیمی به جدید"""
    if src == "KC":
        rows = get("https://api.kucoin.com/api/v1/market/candles",
                   params={"type": "1hour", "symbol": sym})["data"]
        rows = list(reversed(rows))  # KuCoin: جدیدترین اول
        o = [float(x[1]) for x in rows]
        c = [float(x[2]) for x in rows]
        h = [float(x[3]) for x in rows]
        l = [float(x[4]) for x in rows]
        v = [float(x[6]) for x in rows]  # turnover (quote)
    else:
        rows = get("https://api.gateio.ws/api/v4/spot/candlesticks",
                   params={"currency_pair": sym, "interval": "1h", "limit": 200})
        # Gate: [t, quote_vol, close, high, low, open, base_vol, closed]
        c = [float(x[2]) for x in rows]
        h = [float(x[3]) for x in rows]
        l = [float(x[4]) for x in rows]
        o = [float(x[5]) for x in rows]
        v = [float(x[1]) for x in rows]
    return o, h, l, c, v


def check(src, sym):
    o, h, l, c, v = candles(src, sym)
    if len(c) < 60:
        return None
    j = len(c) - 2  # آخرین کندل بسته‌شده
    if j < 60:
        return None
    last = c[j]
    prior_high = max(h[j - 24:j])
    avg_v = sum(v[j - 24:j]) / 24
    if avg_v <= 0:
        return None
    vol_ratio = v[j] / avg_v
    r = sb.rsi(c[:j + 1])
    a = sb.atr(h[:j + 1], l[:j + 1], c[:j + 1])
    if r is None or a is None:
        return None
    ok = (last > prior_high and c[j] > o[j] and vol_ratio >= sb.CEX_VOLUME_RATIO
          and sb.CEX_RSI_RANGE[0] <= r <= sb.CEX_RSI_RANGE[1]
          and a / last * 100 >= sb.CEX_MIN_ATR_PCT)
    if not ok:
        return None
    chg = (c[j] / c[j - 24] - 1) * 100
    return {"last": last, "rsi": r, "vr": vol_ratio, "chg": chg}


def main():
    uni = []
    for fn in (kucoin_universe, gate_universe):
        try:
            uni += fn()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] universe {fn.__name__}: {e}")
    uni.sort(key=lambda x: -x[2])
    uni = uni[:TOP * 3]
    hits = []
    for src, sym, _ in uni:
        try:
            res = check(src, sym)
        except Exception:  # noqa: BLE001
            continue
        if res:
            hits.append((src, sym, res))
    hits.sort(key=lambda x: -x[2]["chg"])
    lines = [f"👀 <b>رصد کوکوین + گیت (USDT)</b>",
             f"ارزهای بررسی‌شده: {len(uni)} | دارای شرط شکست: {len(hits)}", ""]
    for src, sym, r in hits[:TOP]:
        name = {"KC": "KuCoin", "GT": "Gate"}[src]
        lines.append(f"• {sym} ({name}) | {r['last']:.6g} | ۲۴ساعته {r['chg']:+.1f}٪ | "
                     f"RSI {r['rsi']:.0f} | حجم {r['vr']:.1f}×")
    if not hits:
        lines.append("هیچ ارزی الان شرط شکست را ندارد.")
    lines += ["", "⚠️ فقط رصد است؛ فهرست خرید نیست و سود تضمین نمی‌کند."]
    text = "\n".join(lines)
    print(text)
    sb.send(text)


if __name__ == "__main__":
    main()