#!/usr/bin/env python3
"""
بک‌تست با شرط رشد ۱۰٪ (به‌جای ۲۰٪)، بقیه‌ی شرط‌ها دقیقاً مثل سیگنال فعلی.
همان universe و داده‌ی بک‌تست یک‌ساله. فقط گزارش؛ هیچ سیگنالی نمی‌فرسته.
"""
import backtest_live as bt
import backtest_multi as m
import signal_bot as sb

bt.PUMP_PCT = 0.10  # تنها تفاوت: آستانه‌ی رشد ۲۴ ساعته ۱۰٪

_orig_send = sb.send


def _send(text):
    return _orig_send("🧪 <b>تست حد وسط: رشد ۱۰٪ (به‌جای ۲۰٪)</b>\n" + text)


sb.send = _send

if __name__ == "__main__":
    m.main()