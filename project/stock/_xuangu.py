# -*- coding: utf-8 -*-
import sys
sys.path.append(r'E:\trading\project\stock')
from instock.core.eastmoney_fetcher import eastmoney_fetcher
f = eastmoney_fetcher()
r = f.make_request('https://data.eastmoney.com/dataapi/xuangu/list', params={
    'sty': 'MAX_TRADE_DATE,RANK',
    'filter': '(MARKET+in+("上交所主板","深交所主板","深交所创业板"))(NEW_PRICE>0)',
    'p': 1, 'ps': 3, 'source': 'SELECT_SECURITIES', 'client': 'WEB'})
print('status', r.status_code)
js = r.json()
print('data_json keys:', list(js.keys()))
res = js.get('result')
print('result:', res)
if res and res.get('data'):
    print([x.get('MAX_TRADE_DATE') for x in res['data']])