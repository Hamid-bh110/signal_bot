#!/usr/bin/env python3
"""
دمو معامله (پول فرضی، بدون کلید و بدون سفارش واقعی).
هر اجرا: بستن پوزیشن‌های باز اگه به حد ضرر/تارگت/زمان رسیدن، ورود به سیگنال‌های جدید،
ذخیره وضعیت در paper_state.json، و گزارش به تلگرام/بله.
"""
import json
import os
import sys
from datetime import datetime, timezone

import signal_bot as sb

BINANCE = sb.BINANCE
STATE_FILE = "paper_state.json"
START_EQUITY = 1000.0
RISK_PCT = 0.01
MAX_OPEN = 3
MAX_NOTIONAL_FRAC = 1.0 / MAX_OPEN
FEE = 0.001
PUMP_PCT = 20.0
MIN_QV = 5_000_000
RR = 3.0
MAX_HOLD = 48
STOP_BUFFER = 0.002
VOL_MULT = 2.5
RSI_LO, RSI_HI = 55, 82
ATR_MIN = 0.01


def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"equity": START_EQUITY, "open": {}, "closed": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_klines(sym, limit=100):
    kl = sb.http_get(f"{BINANCE}/api/v3/klines",
                     params={"symbol": sym, "interval": "1h", "limit": limit})
    return kl or []


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
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
           for i in range(len(c) - n, len(c))]
    return sum(trs) / n


def check_signal(kl, pct24):
    if len(kl) < 40 or pct24 < PUMP_PCT:
        return None
    o = [float(x[1]) for x in kl]
    h = [float(x[2]) for x in kl]
    l = [float(x[3]) for x in kl]
    c = [float(x[4]) for x in kl]
    v = [float(x[5]) for x in kl]
    j = len(kl) - 2
    if not c[j] > max(h[j - 24:j]):
        return None
    avg_vol = sum(v[j - 20:j]) / 20
    if v[j] < VOL_MULT * avg_vol:
        return None
    r = rsi(c[:j + 1])
    if r is None or not (RSI_LO <= r <= RSI_HI):
        return None
    a = atr(h[:j + 1], l[:j + 1], c[:j + 1])
    if a / c[j] < ATR_MIN:
        return None
    entry = o[-1]
    stop = min(l[j - 5:j + 1]) * (1 - STOP_BUFFER)
    risk = entry - stop
    if risk <= 0 or risk / entry > 0.30:
        return None
    return {"entry": entry, "stop": stop, "target": entry + RR * risk,
            "risk": risk, "rsi": round(r, 1)}


def close_position(state, sym, pos, price, reason, when_ms):
    units = pos["units"]
    gross = units * (price - pos["entry"])
    fees = FEE * (units * pos["entry"] + units * price)
    pnl = gross - fees
    state["equity"] += pnl
    state["closed"].append({
        "sym": sym, "entry": pos["entry"], "exit": price, "reason": reason,
        "pnl": round(pnl, 2), "opened": pos["opened_str"],
        "closed": datetime.fromtimestamp(when_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
    })
    return f"🔴 بسته شد {sym} | {reason} | خروج {price:.6g} | سود/زیان {pnl:+.2f}$"


def manage_open(state):
    events = []
    for sym in list(state["open"].keys()):
        pos = state["open"][sym]
        kl = get_klines(sym, 100)
        for k in kl:
            open_ms = int(k[0])
            if open_ms <= pos["entry_ms"]:
                continue
            lo, hi, cl = float(k[3]), float(k[2]), float(k[4])
            pos["bars"] = pos.get("bars", 0) + 1
            if lo <= pos["stop"]:
                events.append(close_position(state, sym, pos, pos["stop"], "حد ضرر", open_ms))
                del state["open"][sym]
                break
            if hi >= pos["target"]:
                events.append(close_position(state, sym, pos, pos["target"], "تارگت", open_ms))
                del state["open"][sym]
                break
            if pos["bars"] >= MAX_HOLD:
                events.append(close_position(state, sym, pos, cl, "زمان", open_ms))
                del state["open"][sym]
                break
    return events


def candidates():
    tickers = sb.http_get(f"{BINANCE}/api/v3/ticker/24hr") or []
    tab = sb.tabdeal_coins()
    out = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base in sb.STABLES or base in sb.MAJORS_EXCLUDED or base.endswith(sb.LEVERAGED_SUFFIXES):
            continue
        try:
            pct = float(t["priceChangePercent"])
            qv = float(t["quoteVolume"])
        except (KeyError, ValueError):
            continue
        if pct < PUMP_PCT or qv < MIN_QV:
            continue
        if tab is not None and base not in tab:
            continue
        out.append((pct, sym))
    out.sort(reverse=True)
    return out[:30]


def open_new(state):
    events = []
    if len(state["open"]) >= MAX_OPEN:
        return events
    for pct, sym in candidates():
        if len(state["open"]) >= MAX_OPEN:
            break
        if sym in state["open"]:
            continue
        kl = get_klines(sym, 100)
        sig = check_signal(kl, pct)
        if not sig:
            continue
        equity = state["equity"]
        units = equity * RISK_PCT / sig["risk"]
        notional = min(units * sig["entry"], equity * MAX_NOTIONAL_FRAC)
        units = notional / sig["entry"]
        state["open"][sym] = {
            "entry": sig["entry"], "stop": sig["stop"], "target": sig["target"],
            "units": units, "entry_ms": int(kl[-1][0]), "bars": 0,
            "opened_str": now_str(),
        }
        events.append(f"🟢 ورود آزمایشی {sym} | ورود {sig['entry']:.6g} | "
                      f"حد ضرر {sig['stop']:.6g} | هدف {sig['target']:.6g} | "
                      f"حجم ${notional:.0f}")
    return events


def summary(state):
    closed = state["closed"]
    n = len(closed)
    wins = [t for t in closed if t["pnl"] > 0]
    net = state["equity"] - START_EQUITY
    wr = f"{len(wins) / n:.0%}" if n else "-"
    return (f"📊 گزارش دمو ({now_str()})\n"
            f"سرمایه‌ی فرضی: ${state['equity']:.2f} (سود/زیان خالص: {net:+.2f}$)\n"
            f"پوزیشن باز: {len(state['open'])} | معامله‌ی بسته‌شده: {n} | برد: {wr}")


def main():
    state = load_state()
    events = manage_open(state)
    events += open_new(state)
    save_state(state)
    print("\n".join(events) or "no events")
    parts = []
    if events:
        parts.append("\n".join(events))
    if datetime.now(timezone.utc).hour == 0:
        parts.append(summary(state))
    if parts:
        sb.send("\n\n".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)