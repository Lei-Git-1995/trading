# -*- coding: utf-8 -*-
import sys
import pymysql
sys.path.append(r'E:\trading\project\stock')
import instock.lib.database as mdb
conn = pymysql.connect(**mdb.MYSQL_CONN_DBAPI)
try:
    with conn.cursor() as db:
        db.execute('SELECT MAX(date) FROM cn_stock_selection')
        print('max:', db.fetchone()[0])
        db.execute("SELECT date, COUNT(*) FROM cn_stock_selection WHERE date='2026-09-23'")
        r = db.fetchone()
        print('23:', r)
        db.execute("SELECT date, COUNT(*) FROM cn_stock_selection WHERE date='2026-09-22'")
        print('22:', db.fetchone())
finally:
    conn.close()
