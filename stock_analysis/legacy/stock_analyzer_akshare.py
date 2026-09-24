#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用AkShare库的股票数据获取与分析报告生成器
AkShare是更稳定的开源金融数据接口
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
import os


class AkShareStockAnalyzer:
    """AkShare股票分析器"""

    def __init__(self, stock_code: str):
        """
        初始化分析器
        :param stock_code: 股票代码,如 '600519' 或 '000001'
        """
        self.stock_code = stock_code
        # AkShare使用带市场前缀的代码
        if stock_code.startswith('6'):
            self.symbol = f"sh{stock_code}"
        elif stock_code.startswith(('0', '3')):
            self.symbol = f"sz{stock_code}"
        else:
            self.symbol = stock_code

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        try:
            # 获取股票基本信息
            stock_info = ak.stock_individual_info_em(symbol=self.stock_code)
            info_dict = dict(zip(stock_info['item'], stock_info['value']))

            return {
                '股票代码': self.stock_code,
                '股票名称': info_dict.get('股票简称', self.stock_code),
                '所属行业': info_dict.get('行业', '未知'),
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }
        except Exception as e:
            print(f"获取基本信息失败: {e}")
            return {
                '股票代码': self.stock_code,
                '股票名称': self.stock_code,
                '所属行业': '未知',
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }

    def get_realtime_quote(self) -> Dict:
        """获取实时行情"""
        try:
            # 获取实时行情
            df = ak.stock_zh_a_spot_em()
            stock_data = df[df['代码'] == self.stock_code]

            if stock_data.empty:
                print(f"未找到股票 {self.stock_code} 的实时行情")
                return {}

            row = stock_data.iloc[0]

            return {
                '股票代码': row['代码'],
                '股票名称': row['名称'],
                '最新价': float(row['最新价']),
                '涨跌额': float(row['涨跌额']),
                '涨跌幅': float(row['涨跌幅']),
                '今开': float(row['今开']),
                '昨收': float(row['昨收']),
                '最高': float(row['最高']),
