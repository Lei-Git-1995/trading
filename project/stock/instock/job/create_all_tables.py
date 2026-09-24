# -*- coding: utf-8 -*-
import os.path
import sys
import pymysql

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
import sqlalchemy.dialects.mysql.pymysql as mdb_dialect
import instock.core.tablestructure as tbs
import instock.lib.database as mdb


def main():
    tables = {}
    tables[tbs.TABLE_CN_STOCK_ATTENTION['name']] = tbs.TABLE_CN_STOCK_ATTENTION
    tables[tbs.TABLE_CN_ETF_SPOT['name']] = tbs.TABLE_CN_ETF_SPOT
    tables[tbs.TABLE_CN_STOCK_SPOT['name']] = tbs.TABLE_CN_STOCK_SPOT
    tables[tbs.TABLE_CN_STOCK_SPOT_BUY['name']] = tbs.TABLE_CN_STOCK_SPOT_BUY
    tables[tbs.TABLE_CN_STOCK_FUND_FLOW['name']] = tbs.TABLE_CN_STOCK_FUND_FLOW
    tables[tbs.TABLE_CN_STOCK_FUND_FLOW_INDUSTRY['name']] = tbs.TABLE_CN_STOCK_FUND_FLOW_INDUSTRY
    tables[tbs.TABLE_CN_STOCK_FUND_FLOW_CONCEPT['name']] = tbs.TABLE_CN_STOCK_FUND_FLOW_CONCEPT
    tables[tbs.TABLE_CN_STOCK_BONUS['name']] = tbs.TABLE_CN_STOCK_BONUS
    tables[tbs.TABLE_CN_STOCK_lHB['name']] = tbs.TABLE_CN_STOCK_lHB
    tables[tbs.TABLE_CN_STOCK_BLOCKTRADE['name']] = tbs.TABLE_CN_STOCK_BLOCKTRADE
    tables[tbs.TABLE_CN_STOCK_INDICATORS['name']] = tbs.TABLE_CN_STOCK_INDICATORS
    tables[tbs.TABLE_CN_STOCK_INDICATORS_BUY['name']] = tbs.TABLE_CN_STOCK_INDICATORS_BUY
    tables[tbs.TABLE_CN_STOCK_INDICATORS_SELL['name']] = tbs.TABLE_CN_STOCK_INDICATORS_SELL
    tables[tbs.TABLE_CN_STOCK_KLINE_PATTERN['name']] = tbs.TABLE_CN_STOCK_KLINE_PATTERN
    tables[tbs.TABLE_CN_STOCK_SELECTION['name']] = tbs.TABLE_CN_STOCK_SELECTION
    tables[tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN['name']] = tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN
    tables[tbs.TABLE_CN_STOCK_CHIP_RACE_END['name']] = tbs.TABLE_CN_STOCK_CHIP_RACE_END
    tables[tbs.TABLE_CN_STOCK_LIMITUP_REASON['name']] = tbs.TABLE_CN_STOCK_LIMITUP_REASON
    for t in tbs.TABLE_CN_STOCK_STRATEGIES:
        tables[t['name']] = t

    conn = pymysql.connect(**mdb.MYSQL_CONN_DBAPI)
    dialect = mdb_dialect.dialect()
    for name, tbl in tables.items():
        col_sql = []
        for c, c_info in tbl['columns'].items():
            col_type = c_info['type']
            if isinstance(col_type, type):
                col_type = col_type()
            comp = col_type.compile(dialect=dialect)
            col_sql.append("`%s` %s" % (c, comp))
        sql = 'CREATE TABLE IF NOT EXISTS `%s` (%s) CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci' % (
            name, ", ".join(col_sql))
        with conn.cursor() as db:
            try:
                db.execute(sql)
                print("OK   %s" % name)
            except Exception as e:
                print("ERR  %s : %s" % (name, e))
    conn.close()


if __name__ == '__main__':
    main()