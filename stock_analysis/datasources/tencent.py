#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯财经数据源
作为备用数据源
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict
from .base import DataSourceBase
from ..config import DATASOURCE_CONFIG, HTTP_CONFIG


class TencentDataSource(DataSourceBase):
    """腾讯财经数据源"""

    def __init__(self, stock_code: str):
        super().__init__(stock_code)
        self.config = DATASOURCE_CONFIG['tencent']
        self.timeout = self.config['timeout']
        self.session = requests.Session()
        self.session.headers.update(HTTP_CONFIG['headers'])
        self.market = 'sh' if stock_code.startswith('6') else 'sz'
        self.symbol = f'{self.market}{stock_code}'

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        try:
            quote = self.get_realtime_quote()
            return {
                '股票代码': self.stock_code,
                '股票名称': quote.get('股票名称', self.stock_code),
                '所属行业': '未知',
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }
        except Exception:
            return {
                '股票代码': self.stock_code,
                '股票名称': self.stock_code,
                '所属行业': '未知',
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }

    def get_realtime_quote(self) -> Dict:
        """获取实时行情"""
        url = f"{self.config['realtime_url']}/q={self.symbol}"

        try:
            r = self.session.get(url, timeout=self.timeout, headers={
                'Referer': 'http://gu.qq.com/'
            })
            r.raise_for_status()

            # 解析响应: v_sh600664="1~哈药股份~600664~8.14~9.04~..."
            content = r.text.strip()
            if '="' not in content:
                raise Exception("响应格式错误")

            data = content.split('="')[1].rstrip('";').split('~')

            if len(data) < 50:
                raise Exception(f"数据字段不足: {len(data)}")

            return {
                '股票代码': self.stock_code,
                '股票名称': data[1],
                '最新价': float(data[3]),
                '昨收': float(data[4]),
                '今开': float(data[5]),
                '成交量': float(data[36]) / 100,  # 字段36，单位：手 -> 万手
                '外盘': float(data[7]) / 100,     # 单位：手 -> 万手
                '内盘': float(data[8]) / 100,     # 单位：手 -> 万手
                '最高': float(data[33]),
                '最低': float(data[34]),
                '涨跌额': float(data[31]),
                '涨跌幅': float(data[32]),
                '成交额': float(data[37]) / 10000,  # 字段37，单位：万元 -> 亿元
                '换手率': float(data[38]),
                '市盈率': float(data[39]),
                '振幅': float(data[43]),           # 字段43
                '量比': float(data[49]),           # 字段49
                '市净率': float(data[46]),         # 字段46
                '总市值': float(data[44]),         # 字段44，单位：亿元
                '流通市值': float(data[45]),       # 字段45，单位：亿元
                '涨停价': float(data[47]),         # 字段47
                '跌停价': float(data[48]),         # 字段48
            }

        except Exception as e:
            raise Exception(f"腾讯实时行情获取失败: {e}")

    def get_kline_data(self, days: int = 60) -> pd.DataFrame:
        """获取K线历史数据"""
        url = self.config['kline_url']
        param = f'{self.symbol},day,1990-01-01,{datetime.now().strftime("%Y-%m-%d")},{days},qfq'

        try:
            r = self.session.get(url, params={'param': param}, timeout=self.timeout)
            j = r.json()
            node = (j.get('data') or {}).get(self.symbol) or {}
            rows = node.get('qfqday') or node.get('day') or []
        except Exception as e:
            raise Exception(f'腾讯K线获取失败: {type(e).__name__}')

        if not rows:
            raise Exception("未获取到K线数据")

        out = []
        prev_close = None
        for row in rows[-days:]:
            date, op, cl, hi, lo, vol = (
                row[0], float(row[1]), float(row[2]),
                float(row[3]), float(row[4]), float(row[5])
            )
            chg = ((cl - prev_close) / prev_close * 100) if prev_close else 0.0
            out.append({
                '日期': str(date),
                '开盘': op,
                '收盘': cl,
                '最高': hi,
                '最低': lo,
                '成交量': vol,
                '成交额': (hi + lo + cl) / 3 * vol * 100,  # 估算
                '振幅': (hi - lo) / prev_close * 100 if prev_close else 0.0,
                '涨跌幅': chg,
                '涨跌额': cl - prev_close if prev_close else 0.0,
                '换手率': float('nan'),  # 缺流通股本
            })
            prev_close = cl

        df = pd.DataFrame(out)
        df['日期'] = pd.to_datetime(df['日期'])
        return df
