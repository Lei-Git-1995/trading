#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新浪财经股票数据获取与分析报告生成器
使用新浪财经API获取股票数据,生成技术分析报告
"""

import requests
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, List
import re
import time


class SinaStockAnalyzer:
    """新浪财经股票分析器"""

    def __init__(self, stock_code: str):
        """
        初始化分析器
        :param stock_code: 股票代码,如 '600519' 或 '000001'
        """
        self.stock_code = stock_code
        # 新浪使用 sh/sz 前缀
        if stock_code.startswith('6'):
            self.symbol = f"sh{stock_code}"
        else:
            self.symbol = f"sz{stock_code}"

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/'
        }

    def get_realtime_quote(self) -> Dict:
        """获取实时行情"""
        url = f"http://hq.sinajs.cn/list={self.symbol}"

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'gbk'
            content = response.text

            # 解析返回数据
            if not content or 'FAILED' in content:
                print(f"获取实时行情失败,可能股票代码不正确: {self.stock_code}")
                return {}

            # 提取数据部分
            match = re.search(r'"(.+)"', content)
            if not match:
                print("解析实时行情数据失败")
                return {}

            data = match.group(1).split(',')

            if len(data) < 33:
                print("实时行情数据格式不正确")
                return {}

            return {
                '股票代码': self.stock_code,
                '股票名称': data[0],
                '今开': float(data[1]),
                '昨收': float(data[2]),
                '最新价': float(data[3]),
                '最高': float(data[4]),
                '最低': float(data[5]),
                '成交量': int(data[8]),  # 手
                '成交额': float(data[9]),  # 元
                '涨跌额': float(data[3]) - float(data[2]) if data[3] and data[2] else 0,
                '涨跌幅': ((float(data[3]) - float(data[2])) / float(data[2]) * 100) if data[2] and float(data[2]) > 0 else 0,
                '换手率': 0,  # 新浪实时接口不提供,后续从历史数据补充
                '振幅': ((float(data[4]) - float(data[5])) / float(data[2]) * 100) if data[2] and float(data[2]) > 0 else 0,
                '量比': 0,
                '市盈率': 0,
                '市净率': 0,
                '总市值': 0,
                '流通市值': 0,
            }
        except Exception as e:
            print(f"获取实时行情失败: {e}")
            return {}

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        # 先从实时行情获取名称
        realtime = self.get_realtime_quote()

        return {
            '股票代码': self.stock_code,
            '股票名称': realtime.get('股票名称', self.stock_code),
            '所属行业': '未知',  # 新浪接口不直接提供,需要额外接口
            '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
        }

    def get_kline_data(self, days: int = 60) -> pd.DataFrame:
        """
        获取K线历史数据
        使用新浪财经历史数据接口
        """
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days+30)  # 多获取一些以防不够

        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            'symbol': self.symbol,
            'scale': '240',  # 日K线
            'ma': 'no',
            'datalen': str(days + 20)
        }

        try:
            print(f"正在获取K线数据...")
            response = requests.get(url, params=params, headers=self.headers, timeout=15)

            if response.status_code != 200:
                print(f"请求失败,状态码: {response.status_code}")
                return pd.DataFrame()

            data = response.json()

            if not data or len(data) == 0:
                print("未获取到K线数据")
                return pd.DataFrame()

            # 转换为DataFrame
            df = pd.DataFrame(data)
            df['day'] = pd.to_datetime(df['day'])
            df = df.rename(columns={
                'day': '日期',
                'open': '开盘',
                'high': '最高',
                'low': '最低',
                'close': '收盘',
                'volume': '成交量'
            })

            # 转换数据类型
            df['开盘'] = df['开盘'].astype(float)
            df['最高'] = df['最高'].astype(float)
            df['最低'] = df['最低'].astype(float)
            df['收盘'] = df['收盘'].astype(float)
            df['成交量'] = df['成交量'].astype(float)

            # 计算其他指标
            df['涨跌额'] = df['收盘'].diff()
            df['涨跌幅'] = df['收盘'].pct_change() * 100
            df['振幅'] = ((df['最高'] - df['最低']) / df['收盘'].shift(1) * 100)
            df['成交额'] = 0  # 新浪接口不提供,设为0
            df['换手率'] = 0  # 新浪接口不提供,设为0

            # 填充第一行的NaN
            df = df.fillna(0)

            print(f"✓ 成功获取 {len(df)} 天的K线数据")
            return df.tail(days)  # 只返回需要的天数

        except Exception as e:
            print(f"获取K线数据失败: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
