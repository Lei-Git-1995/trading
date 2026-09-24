#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富数据源
支持多主机容灾
"""

import requests
import pandas as pd
import time
from typing import Dict
from .base import DataSourceBase
from ..config import DATASOURCE_CONFIG, HTTP_CONFIG


class EastMoneyDataSource(DataSourceBase):
    """东方财富数据源"""

    def __init__(self, stock_code: str):
        super().__init__(stock_code)
        self.config = DATASOURCE_CONFIG['eastmoney']
        self.timeout = self.config['timeout']
        self.secid = self._get_secid()
        self.session = requests.Session()
        self.session.headers.update(HTTP_CONFIG['headers'])
        self.session.headers.update({
            'Connection': 'close',
            'Referer': 'http://quote.eastmoney.com/'
        })

    def _get_secid(self) -> str:
        """获取secid (1.上海 0.深圳)"""
        return f"1.{self.stock_code}" if self.stock_code.startswith('6') else f"0.{self.stock_code}"

    def _first_ok_host(self, hosts, probe_path='/api/qt/clist/get', probe_params=None):
        """探测第一个可用的主机"""
        if probe_params is None:
            probe_params = {'pn': '1', 'pz': '1', 'fs': 'm:0+t:6', 'fields': 'f12'}

        for host in hosts:
            try:
                r = self.session.get(
                    f'http://{host}{probe_path}',
                    params=probe_params,
                    timeout=8
                )
                if r.status_code == 200 and r.text:
                    return host
            except Exception:
                continue
        return None

    def _request_with_retry(self, url: str, params: dict, max_retries: int = None) -> dict:
        """带重试的请求"""
        if max_retries is None:
            max_retries = HTTP_CONFIG['max_retries']

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = HTTP_CONFIG['retry_backoff'] ** attempt
                    time.sleep(wait_time)
                else:
                    raise e

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        host = self._first_ok_host(self.config['clist_hosts'])
        if not host:
            return self._get_fallback_info()

        params = {
            'secid': self.secid,
            'fields': 'f57,f58,f100,f127'
        }

        try:
            result = self._request_with_retry(f'http://{host}/api/qt/stock/get', params)
            data = result.get('data', {})

            if not data:
                return self._get_fallback_info()

            return {
                '股票代码': self.stock_code,
                '股票名称': data.get('f58', ''),
                '所属行业': data.get('f127', ''),
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }
        except Exception:
            return self._get_fallback_info()

    def get_realtime_quote(self) -> Dict:
        """获取实时行情"""
        host = self._first_ok_host(self.config['clist_hosts'])
        if not host:
            raise Exception("所有东方财富主机均不可达")

        params = {
            'secid': self.secid,
            'fields': 'f57,f58,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f60,f152,f168,f169,f170,f171,f162,f167,f116,f117'
        }

        result = self._request_with_retry(f'http://{host}/api/qt/stock/get', params)
        data = result.get('data', {})

        if not data:
            raise Exception("未获取到实时行情数据")

        return {
            '股票代码': self.stock_code,
            '股票名称': data.get('f58', ''),
            '最新价': data.get('f43', 0) / 100,
            '涨跌额': data.get('f169', 0) / 100,
            '涨跌幅': data.get('f170', 0) / 100,
            '今开': data.get('f46', 0) / 100,
            '昨收': data.get('f60', 0) / 100,
            '最高': data.get('f44', 0) / 100,
            '最低': data.get('f45', 0) / 100,
            '成交量': data.get('f47', 0),
            '成交额': data.get('f48', 0),
            '外盘': data.get('f49', 0),
            '内盘': max(data.get('f47', 0) - data.get('f49', 0), 0),
            '涨停价': data.get('f51', 0) / 100,
            '跌停价': data.get('f52', 0) / 100,
            '换手率': data.get('f168', 0) / 100,
            '振幅': data.get('f171', 0) / 100,
            '量比': data.get('f50', 0) / 100,
            '市盈率': data.get('f162', 0) / 100,
            '市净率': data.get('f167', 0) / 100,
            '总市值': data.get('f116', 0) / 100000000,
            '流通市值': data.get('f117', 0) / 100000000,
        }

    def get_kline_data(self, days: int = 60) -> pd.DataFrame:
        """获取K线历史数据"""
        host = self._first_ok_host(
            self.config['kline_hosts'],
            probe_path='/api/qt/stock/kline/get',
            probe_params={
                'secid': '1.600519',
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56',
                'klt': '101', 'fqt': '1', 'lmt': '1',
            }
        )

        if not host:
            raise Exception("所有K线主机均不可达")

        params = {
            'secid': self.secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',  # 日K
            'fqt': '1',    # 前复权
            'lmt': str(days + 20),
            'end': '20500101'
        }

        result = self._request_with_retry(f'http://{host}/api/qt/stock/kline/get', params)
        data = result.get('data', {})

        if not data or 'klines' not in data:
            raise Exception("未获取到K线数据")

        klines = []
        for line in data['klines']:
            items = line.split(',')
            klines.append({
                '日期': items[0],
                '开盘': float(items[1]),
                '收盘': float(items[2]),
                '最高': float(items[3]),
                '最低': float(items[4]),
                '成交量': float(items[5]),
                '成交额': float(items[6]),
                '振幅': float(items[7]),
                '涨跌幅': float(items[8]),
                '涨跌额': float(items[9]),
                '换手率': float(items[10])
            })

        df = pd.DataFrame(klines)
        df['日期'] = pd.to_datetime(df['日期'])
        return df.tail(days)

    def _get_fallback_info(self) -> Dict:
        """获取后备基本信息"""
        return {
            '股票代码': self.stock_code,
            '股票名称': self.stock_code,
            '所属行业': '未知',
            '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
        }
