import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.storage import StockStorage
from strategy.news_predictor import NewsPredictor

def test():
    storage = StockStorage()
    with storage._get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, title, date_wib, forecast, previous, impact, news_type 
            FROM economic_calendar 
            WHERE impact = 'High' AND date_utc >= '2026-10-01 00:00:00' 
            ORDER BY date_utc ASC
        """)
        rows = [dict(r) for r in c.fetchall()]

    print(f"Total High Impact upcoming events: {len(rows)}")
    for r in rows:
        print(f"[{r['news_type']}] {r['title']} | WIB: {r['date_wib']} | FC: {r['forecast']} | PV: {r['previous']}")

    # Analisis event NFP
    nfp_ev = [r for r in rows if r['title'] == 'Non-Farm Employment Change'][0]
    print("\n--- ANALISIS NFP TERDEKAT ---")
    print(nfp_ev)
    analysis = NewsPredictor.analyze_pre_news(nfp_ev, live_gold_price=4165.0)
    print("Recommendation:", analysis.get('primary_recommendation'))
    print("Confidence:", analysis.get('confidence_pct'))
    print("Fundamental Bias:", analysis.get('fundamental_bias'))

if __name__ == '__main__':
    test()
