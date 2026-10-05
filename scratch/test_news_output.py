import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from data.storage import StockStorage
from data.economic_calendar import EconomicCalendar
from strategy.news_predictor import NewsPredictor
from datetime import datetime, timezone
import html

def main():
    storage = StockStorage()
    cal = EconomicCalendar(storage=storage)
    events = cal.get_this_week_schedule()

    live_price = 4165.67
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    upcoming_events = [e for e in events if e.get("date_utc", "") >= now_str]
    nfp_candidates = [
        e for e in (upcoming_events or events)
        if "non-farm employment change" in str(e.get("title", "")).lower()
    ]
    major_events = [
        e for e in (upcoming_events or events)
        if e.get("impact") == "High" or e.get("news_type") in ["NFP", "CPI", "FOMC", "PCE"]
    ]
    closest_ev = nfp_candidates[0] if nfp_candidates else (major_events[0] if major_events else (upcoming_events[0] if upcoming_events else events[0]))
    closest_analysis = NewsPredictor.analyze_pre_news(closest_ev, live_gold_price=live_price)

    lines = [
        "📅 <b>JADWAL HIGH-IMPACT NEWS (FOMC / CPI / PCE / NFP / TRUMP / OIL)</b> 🌎",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💵 <b>Harga Live XAU/USD:</b> <code>${live_price:,.2f}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for idx, ev in enumerate(events[:5], 1):
        ntype = ev.get("news_type", "NEWS")
        badge = (
            "🔴 FOMC" if ntype == "FOMC"
            else "🟠 CPI" if ntype == "CPI"
            else "🔵 PCE" if ntype == "PCE"
            else "🟣 NFP" if ntype == "NFP"
            else "🇺🇸 TRUMP" if ntype == "TRUMP"
            else "🛢️ OIL" if ntype == "OIL"
            else "⚪ NEWS"
        )
        t_wib = ev.get("date_wib", "-")
        fc = ev.get("forecast") or "-"
        pv = ev.get("previous") or "-"
        lines.append(f"<b>{idx}. {badge}</b>: <b>{html.escape(ev.get('title', ''))}</b>")
        lines.append(f"   ⏰ Waktu: <code>{t_wib} WIB</code>")
        lines.append(f"   📊 Forecast: <code>{fc}</code> | Prev: <code>{pv}</code>")
        lines.append("──────────────────────")

    if closest_analysis and closest_ev:
        rec = closest_analysis.get("primary_recommendation", "BUY")
        conf = closest_analysis.get("confidence_pct", 75)
        setup = closest_analysis.get("trade_setup", {})
        fund = closest_analysis.get("fundamental_bias", {})
        badge_rec = "🟢 BUY" if "BUY" in rec else "🔴 SELL" if "SELL" in rec else "🟡 STRADDLE"

        lines.extend([
            f"🎯 <b>SARAN UTAMA EVENT TERDEKAT ({closest_analysis['news_type']} - {html.escape(closest_ev.get('title', ''))}):</b>",
            f"• ⏰ <b>Waktu Rilis:</b> <code>{closest_ev.get('date_wib', '-')} WIB</code>",
            f"• 📊 <b>Konsensus Web:</b> Forecast <code>{closest_ev.get('forecast', '-')}</code> | Prev <code>{closest_ev.get('previous', '-')}</code>",
            f"• 🏆 <b>Rekomendasi:</b> <b>{badge_rec}</b> (<b>{conf}% Confidence</b>)",
            f"• 🎯 <b>Target TP1:</b> <code>${setup.get('tp1', 0):,.2f}</code> | 🛑 <b>SL:</b> <code>${setup.get('sl', 0):,.2f}</code>",
            f"• 🌐 <b>Bias Web:</b> <i>{html.escape(fund.get('reason', '-'))}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "⚡ <i>Sistem otomatis membunyikan Alert & Live Chart 10 menit sebelum rilis!</i>",
        ])

    print("\n".join(lines))

if __name__ == '__main__':
    main()
