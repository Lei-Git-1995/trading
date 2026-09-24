# -*- coding: utf-8 -*-
import sys
import pymysql
sys.path.append(r'E:\trading\project\stock')
import instock.lib.database as mdb
tables = ['cn_stock_spot', 'cn_etf_spot', 'cn_stock_selection', 'cn_stock_attention',
          'cn_stock_indicators', 'cn_stock_lhb', 'cn_stock_bonus', 'cn_stock_fund_flow',
          'cn_stock_chip_race_open', 'cn_stock_limitup_reason', 'cn_stock_blocktrade',
          'cn_stock_chip_race_end', 'cn_stock_pattern']
with pymysql.connect(**mdb.MYSQL_CONN_DBAPI) as conn:
    with conn.cursor() as db:
        for t in tables:
            try:
                db.execute("SELECT COUNT(*) FROM `%s`" % t)
                total = db.fetchone()[0]
                db.execute("SELECT MAX(date) FROM `%s`" % t) if t not in (
                    'cn_stock_attention', 'cn_stock_fund_flow', 'cn_stock_fund_flow_industry', 'cn_stock_fund_flow_concept') else db.execute("SELECT 1")
                mx = db.fetchone()[0] if t not in ('cn_stock_attention', 'cn_stock_fund_flow', 'cn_stock_fund_flow_industry', 'cn_stock_fund_flow_concept') else '-'
                print('%-30s rows=%-6s maxdate=%s' % (t, total, mx))
            except Exception as e:
                print('%-30s ERR %s' % (t, e))
conn.close()
