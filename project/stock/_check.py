# -*- coding: utf-8 -*-
import sys
import pymysql
sys.path.append(r'E:\trading\project\stock')
import instock.lib.database as mdb
tables = ['cn_stock_spot', 'cn_etf_spot', 'cn_stock_selection', 'cn_stock_attention',
          'cn_stock_indicators', 'cn_stock_lhb', 'cn_stock_bonus', 'cn_stock_fund_flow',
          'cn_stock_chip_race_open', 'cn_stock_limitup_reason', 'cn_stock_blocktrade',
          'cn_stock_chip_race_end', 'cn_stock_pattern']
conn = pymysql.connect(**mdb.MYSQL_CONN_DBAPI)
try:
    with conn.cursor() as db:
        for t in tables:
            try:
                db.execute("SELECT COUNT(*) FROM `%s`" % t)
                total = db.fetchone()[0]
                if t in ('cn_stock_attention',):
                    print('%-30s rows=%-6s maxdate=-' % (t, total))
                elif t in ('cn_stock_fund_flow','cn_stock_fund_flow_industry','cn_stock_fund_flow_concept'):
                    print('%-30s rows=%-6s' % (t, total))
                else:
                    db.execute("SELECT MAX(date) FROM `%s`" % t)
                    mx = db.fetchone()[0]
                    print('%-30s rows=%-6s maxdate=%s' % (t, total, mx))
            except Exception as e:
                print('%-30s ERR %s' % (t, e))
finally:
    conn.close()
