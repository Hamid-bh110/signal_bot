#!/usr/bin/env python3
"""
ربات سیگنال (فقط اطلاع‌رسانی، بدون معامله خودکار)

۱) CEX: اسکن کندل‌های ۱ ساعته‌ی بایننس (دیتای عمومی) برای شکست سقف + جهش حجم،
   و علامت‌گذاری ارزهایی که در تبدیل (Tabdeal) هم لیست هستند.
۲) DEX: اسکن استخرهای ترند GeckoTerminal با فیلترهای ایمنی (نقدینگی، سن، هانی‌پات).

سیگنال‌ها از طریق تلگرام و بله فرستاده می‌شوند. این‌ها پیشنهاد خرید نیستند.
"""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------- تنظیمات
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BALE_TOKEN = os.environ.get("BALE_BOT_TOKEN", "")
BALE_CHAT_ID = os.environ.get("BALE_CHAT_ID", "")
TEST_MESSAGE = os.environ.get("TEST_MESSAGE", "0") == "1"
BALE_DISCOVER = os.environ.get("BALE_DISCOVER", "0") == "1"
STATE_FILE = "state.json"

COOLDOWN_HOURS = 12
MAX_SIGNALS_PER_RUN = 8

# CEX
BINANCE = "https://data-api.binance.vision"
CEX_MIN_QUOTE_VOLUME = 3_000_000
CEX_TOP_N = 120
CEX_MIN_ATR_PCT = 1.0
CEX_VOLUME_RATIO = 2.5
CEX_RSI_RANGE = (55, 82)
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "EUR", "EURI", "AEUR",
           "PAXG", "XUSD", "BFUSD", "USD1", "RLUSD"}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
MAJORS_EXCLUDED = {"BTC", "ETH", "BNB"}

TABDEAL_INFO_URLS = [
    "https://api1.tabdeal.org/r/api/v1/exchangeInfo",
    "https://api.tabdeal.org/r/api/v1/exchangeInfo",
]

# DEX
GT = "https://api.geckoterminal.com/api/v2"
GT_HEADERS = {"Accept": "application/json;version=20230302"}
DEX_MIN_LIQUIDITY = 150_000
DEX_MIN_VOLUME_24H = 300_000
DEX_MIN_AGE_HOURS = 48
DEX_H1_RANGE = (4, 40)
DEX_MAX_H24 = 250
DEX_MIN_BUY_SELL_RATIO = 1.3
DEX_MIN_BUYERS_H1 = 30
GOPLUS_CHAINS = {"eth": "1", "bsc": "56", "base": "8453", "polygon_pos": "137",
                 "arbitrum": "42161", "avax": "43114", "optimism": "10"}

UA = {"User-Agent": "signal-bot/1.0"}


def redact(msg):
    """توکن‌ها هیچ‌وقت تو لاگ چاپ نشن."""
    msg = str(msg)
    for secret in (TOKEN, BALE_TOKEN):
        if secret:
            msg = msg.replace(secret, "***")
    return msg


# ---------------------------------------------------------------- ابزارها
def http_get(url, params=None, headers=None, timeout=20):
    try:
        r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(redact(f"[warn] {url} -> {e}"), file=sys.stderr)
        return None


def fmt(x):
    return f"{x:.6g}"


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def atr(highs, lows, closes, n=14):
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
           for i in range(1, len(closes))]
    if len(trs) < n:
        return None
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def strip_html(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def send_telegram(text):
    """True/False = موفق/ناموفق، None = تنظیم نشده."""
    if not (TOKEN and CHAT_ID):
        return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[warn] telegram {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(redact(f"[warn] telegram -> {e}"), file=sys.stderr)
        return False


def send_bale(text):
    """ارسال از طریق پیام‌رسان بله (متن ساده). None = تنظیم نشده."""
    if not (BALE_TOKEN and BALE_CHAT_ID):
        return None
    chat = int(BALE_CHAT_ID) if BALE_CHAT_ID.lstrip("-").isdigit() else BALE_CHAT_ID
    try:
        r = requests.post(
            f"https://tapi.bale.ai/bot{BALE_TOKEN}/sendMessage",
            json={"chat_id": chat, "text": strip_html(text)[:4000]},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[warn] bale {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(redact(f"[warn] bale -> {e}"), file=sys.stderr)
        return False


def send(text):
    """به همه‌ی کانال‌های تنظیم‌شده می‌فرسته؛ اگه حداقل یکی رسید، موفقه."""
    results = [send_telegram(text), send_bale(text)]
    configured = [r for r in results if r is not None]
    if not configured:
        print("[dry-run]\n" + text + "\n")
        return True
    return any(configured)


# ---------------------------------------------------------------- CEX
def tabdeal_coins():
    """مجموعه‌ی ارزهای قابل معامله در تبدیل؛ اگه API جواب نداد None برمی‌گردونه."""
    for url in TABDEAL_INFO_URLS:
        data = http_get(url)
        if data and isinstance(data.get("symbols"), list):
            return {s["baseAsset"].upper() for s in data["symbols"]
                    if s.get("status") == "TRADING" and s.get("baseAsset")}
    return None


def check_breakout(klines):
    """شکست سقف ۲۴ کندل قبل با جهش حجم. فقط کندل‌های بسته‌شده."""
    k = klines[:-1]
    if len(k) < 50:
        return None
    o = [float(x[1]) for x in k]
    h = [float(x[2]) for x in k]
    l = [float(x[3]) for x in k]
    c = [float(x[4]) for x in k]
    v = [float(x[7]) for x in k]
    last = c[-1]
    prior_high = max(h[-25:-1])
    avg_vol = sum(v[-25:-1]) / 24
    if avg_vol <= 0:
        return None
    vol_ratio = v[-1] / avg_vol
    r = rsi(c)
    a = atr(h, l, c)
    if r is None or a is None:
        return None
    atr_pct = a / last * 100
    if atr_pct < CEX_MIN_ATR_PCT:
        return None
    if not (last > prior_high and c[-1] > o[-1] and vol_ratio >= CEX_VOLUME_RATIO
            and CEX_RSI_RANGE[0] <= r <= CEX_RSI_RANGE[1]):
        return None
    stop = max(min(l[-6:]), last - 2.5 * a)
    if stop >= last:
        return None
    risk = last - stop
    return {"entry": last, "stop": stop, "t1": last + 1.5 * risk, "t2": last + 3 * risk,
            "risk_pct": risk / last * 100, "vol_ratio": vol_ratio, "rsi": r, "atr_pct": atr_pct}


def cex_scan():
    out = []
    tickers = http_get(f"{BINANCE}/api/v3/ticker/24hr")
    if not tickers:
        return out
    tabdeal = tabdeal_coins()
    cands = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base in STABLES or base in MAJORS_EXCLUDED or base.endswith(LEVERAGED_SUFFIXES):
            continue
        try:
            qv = float(t["quoteVolume"])
        except (KeyError, ValueError):
            continue
        if qv < CEX_MIN_QUOTE_VOLUME:
            continue
        if tabdeal is not None and base not in tabdeal:
            continue
        cands.append((qv, sym, base))
    cands.sort(reverse=True)
    for _, sym, base in cands[:CEX_TOP_N]:
        kl = http_get(f"{BINANCE}/api/v3/klines", params={"symbol": sym, "interval": "1h", "limit": 100})
        if not kl:
            continue
        sig = check_breakout(kl)
        if sig:
            sig.update(base=base, symbol=sym, tabdeal=(tabdeal is not None))
            out.append((f"cex:{sym}", cex_message(sig)))
        time.sleep(0.1)
    return out


def cex_message(s):
    note = ("✅ این ارز در تبدیل قابل معامله است" if s["tabdeal"]
            else "❓ لیست تبدیل چک نشد؛ دستی بررسی کن")
    return (
        f"🟢 <b>سیگنال CEX: {s['base']}/USDT</b>  (۱ ساعته)\n"
        f"📈 شکست سقف ۲۴ ساعته با حجم {s['vol_ratio']:.1f} برابر میانگین\n\n"
        f"ورود (حدود): <code>{fmt(s['entry'])}</code>\n"
        f"حد ضرر: <code>{fmt(s['stop'])}</code>  (−{s['risk_pct']:.1f}٪)\n"
        f"هدف ۱: <code>{fmt(s['t1'])}</code>\n"
        f"هدف ۲: <code>{fmt(s['t2'])}</code>\n\n"
        f"RSI: {s['rsi']:.0f} | نوسان (ATR): {s['atr_pct']:.1f}٪\n"
        f"{note}\n\n"
        f"⚠️ پیشنهاد خرید نیست. قیمت تبدیل ممکنه با بایننس فرق کنه."
    )


# ---------------------------------------------------------------- DEX
def goplus_check(net, addr):
    """True = سالم به‌نظر می‌رسه، False = رد، None = بررسی نشد."""
    cid = GOPLUS_CHAINS.get(net)
    if not cid:
        return None
    d = http_get(f"https://api.gopluslabs.io/api/v1/token_security/{cid}",
                 params={"contract_addresses": addr})
    try:
        info = d["result"][addr.lower()]
    except Exception:  # noqa: BLE001
        return None
    if info.get("is_honeypot") == "1":
        return False
    if info.get("is_open_source") == "0":
        return False
    for key in ("buy_tax", "sell_tax"):
        try:
            if float(info.get(key) or 0) > 0.10:
                return False
        except ValueError:
            pass
    return True


def pool_age_hours(created):
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return 0


def check_dex_pool(a):
    """a = attributes استخر. در صورت قبولی دیکشنری سیگنال، وگرنه None."""
    try:
        liq = float(a.get("reserve_in_usd") or 0)
        vol24 = float((a.get("volume_usd") or {}).get("h24") or 0)
        pc = a.get("price_change_percentage") or {}
        h1, h6, h24 = (float(pc.get(k) or 0) for k in ("h1", "h6", "h24"))
        tx = (a.get("transactions") or {}).get("h1") or {}
        buys, sells, buyers = tx.get("buys", 0), tx.get("sells", 0), tx.get("buyers", 0)
        price = float(a.get("base_token_price_usd") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0 or liq < DEX_MIN_LIQUIDITY or vol24 < DEX_MIN_VOLUME_24H:
        return None
    if pool_age_hours(a.get("pool_created_at") or "") < DEX_MIN_AGE_HOURS:
        return None
    if not (DEX_H1_RANGE[0] <= h1 <= DEX_H1_RANGE[1]) or h6 <= 0 or h24 > DEX_MAX_H24:
        return None
    if buys < DEX_MIN_BUY_SELL_RATIO * max(sells, 1) or buyers < DEX_MIN_BUYERS_H1:
        return None
    return {"price": price, "liq": liq, "vol24": vol24, "h1": h1, "h6": h6, "h24": h24,
            "buys": buys, "sells": sells, "buyers": buyers}


def dex_scan():
    out = []
    seen = set()
    for page in (1, 2):
        data = http_get(f"{GT}/networks/trending_pools", params={"include": "base_token", "page": page},
                        headers=GT_HEADERS)
        if not data:
            continue
        for p in data.get("data", []):
            a = p.get("attributes", {})
            pool = a.get("address")
            if not pool or pool in seen:
                continue
            seen.add(pool)
            sig = check_dex_pool(a)
            if not sig:
                continue
            try:
                tid = p["relationships"]["base_token"]["data"]["id"]
                net, addr = tid.split("_", 1)
            except Exception:  # noqa: BLE001
                continue
            safe = goplus_check(net, addr)
            if safe is False:
                continue
            sig.update(name=a.get("name", "?"), net=net, pool=pool, addr=addr, safe=safe)
            out.append((f"dex:{pool}", dex_message(sig)))
        time.sleep(1)
    return out


def dex_message(s):
    safe = {True: "✅ بررسی هانی‌پات/مالیات: سالم به‌نظر می‌رسه",
            None: "❓ بررسی امنیتی خودکار انجام نشد؛ حتماً دستی چک کن (rugcheck.xyz)"}[s["safe"]]
    p = s["price"]
    link = f"https://www.geckoterminal.com/{s['net']}/pools/{s['pool']}"
    return (
        f"🔵 <b>سیگنال DEX: {html.escape(s['name'])}</b>  ({s['net']})\n"
        f"📈 رشد ۱ ساعته {s['h1']:+.1f}٪ | ۶ ساعته {s['h6']:+.1f}٪ | ۲۴ ساعته {s['h24']:+.1f}٪\n"
        f"خریدار در ۱ ساعت: {s['buyers']} | خرید/فروش: {s['buys']}/{s['sells']}\n"
        f"نقدینگی: ${s['liq']:,.0f} | حجم ۲۴ ساعته: ${s['vol24']:,.0f}\n\n"
        f"ورود (حدود): <code>{fmt(p)}</code>\n"
        f"حد ضرر پیشنهادی: <code>{fmt(p * 0.90)}</code>  (−۱۰٪)\n"
        f"هدف ۱: <code>{fmt(p * 1.15)}</code>  (+۱۵٪)\n"
        f"هدف ۲: <code>{fmt(p * 1.30)}</code>  (+۳۰٪)\n\n"
        f"{safe}\n"
        f"<code>{s['addr']}</code>\n{link}\n\n"
        f"⚠️ ریسک بسیار بالا. فقط مبلغی که تحمل از دست دادنش رو داری."
    )


# ---------------------------------------------------------------- اجرا
def bale_discover():
    """شماره‌ی چت‌هایی که به ربات بله پیام داده‌ان رو چاپ می‌کنه."""
    if not BALE_TOKEN:
        print("BALE_BOT_TOKEN تنظیم نشده.")
        return 1
    try:
        r = requests.get(f"https://tapi.bale.ai/bot{BALE_TOKEN}/getUpdates", timeout=20)
    except Exception as e:  # noqa: BLE001
        print(redact(f"خطا در اتصال به بله: {e}"))
        return 1
    print(f"وضعیت پاسخ بله: {r.status_code}")
    if r.status_code != 200:
        print("بله جواب درست نداد (توکن اشتباه است یا دسترسی از خارج بسته است).")
        return 1
    found = {}
    try:
        for u in r.json().get("result", []):
            chat = (u.get("message") or {}).get("chat") or {}
            if "id" in chat:
                found[chat["id"]] = (u["message"].get("from") or {}).get("first_name", "")
    except Exception as e:  # noqa: BLE001
        print(redact(f"پاسخ نامعتبر: {e}"))
        return 1
    if not found:
        print("هیچ پیامی پیدا نشد. اول تو بله به ربات خودت یه پیام بده، بعد دوباره اجرا کن.")
        return 1
    for cid, name in found.items():
        print(f"BALE_CHAT_ID = {cid}   (نام: {name})")
    return 0


def main():
    if BALE_DISCOVER:
        sys.exit(bale_discover())
    if TEST_MESSAGE:
        ok = send("✅ ربات سیگنال فعاله و اتصال پیام‌رسان درسته.")
        sys.exit(0 if ok else 1)

    now = time.time()
    state = {k: t for k, t in load_state().items() if now - t < 48 * 3600}

    signals = []
    for scan in (cex_scan, dex_scan):
        try:
            signals += scan()
        except Exception as e:  # noqa: BLE001
            print(f"[error] {scan.__name__}: {e}", file=sys.stderr)

    fresh = [(k, t) for k, t in signals if now - state.get(k, 0) >= COOLDOWN_HOURS * 3600]
    print(f"signals found: {len(signals)}, new: {len(fresh)}")
    for key, text in fresh[:MAX_SIGNALS_PER_RUN]:
        if send(text):
            state[key] = now
        time.sleep(1)
    save_state(state)


if __name__ == "__main__":
    main()
