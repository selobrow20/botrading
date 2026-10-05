import sqlite3

def main():
    conn = sqlite3.connect('data/stock_data.db')
    c = conn.cursor()

    # 1. Hapus dummy synthetic events
    c.execute("""
        DELETE FROM economic_calendar 
        WHERE id <= 12 
           OR id = 4065
           OR forecast = 'Tariff Risk' 
           OR title LIKE '%& Unemployment Rate%'
           OR title LIKE '%Trump Tariff Watch%'
           OR title LIKE '%EIA Crude Oil Inventories & Petroleum Status%'
    """)
    deleted = c.rowcount
    print('Deleted dummy rows:', deleted)

    # 2. Update ADP agar news_type = 'ADP' (bukan NFP)
    c.execute("UPDATE economic_calendar SET news_type = 'ADP' WHERE title LIKE '%ADP%'")
    print('Updated ADP rows:', c.rowcount)

    # 3. Pastikan data rilis NFP esok hari (Oct 2) 100% presisi sesuai Forex Factory web
    c.execute("""
        UPDATE economic_calendar 
        SET forecast = '90K', previous = '162K', news_type = 'NFP', impact = 'High'
        WHERE title = 'Non-Farm Employment Change' AND date_wib LIKE '2026-10-02%'
    """)
    print('Updated NFP row:', c.rowcount)

    c.execute("""
        UPDATE economic_calendar 
        SET forecast = '0.3%', previous = '0.3%', news_type = 'NFP', impact = 'High'
        WHERE title = 'Average Hourly Earnings m/m' AND date_wib LIKE '2026-10-02%'
    """)

    c.execute("""
        UPDATE economic_calendar 
        SET forecast = '4.1%', previous = '4.1%', news_type = 'NFP', impact = 'High'
        WHERE title = 'Unemployment Rate' AND date_wib LIKE '2026-10-02%'
    """)

    conn.commit()
    conn.close()
    print('Database cleaned and updated successfully!')

if __name__ == '__main__':
    main()
