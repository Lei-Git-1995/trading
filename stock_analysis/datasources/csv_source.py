#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV数据源
支持从CSV文件导入历史数据
"""

import pandas as pd
from typing import Dict
from .base import DataSourceBase
from ..core.validator import DataValidator
from ..config import DATASOURCE_CONFIG


class CSVDataSource(DataSourceBase):
    """CSV数据源"""

    def __init__(self, csv_file: str, stock_code: str = None, stock_name: str = None):
        """
        初始化CSV数据源

        :param csv_file: CSV文件路径
        :param stock_code: 股票代码（可选）
        :param stock_name: 股票名称（可选）
        """
        super().__init__(stock_code or "000000")
        self.csv_file = csv_file
        self.stock_name = stock_name or "未知股票"
        self.df = None
        self._load_data()

    def _load_data(self):
        """加载CSV数据"""
        try:
            self.df = pd.read_csv(self.csv_file, encoding='utf-8-sig')

            # 检查必需列
            required = DATASOURCE_CONFIG['csv']['required_columns']
            is_valid, missing = DataValidator.validate_required_columns(self.df, required)

            if not is_valid:
                raise ValueError(f"CSV缺少必需列: {missing}")

            # 清洗数据
            self.df = DataValidator.clean_data(self.df)

            print(f"✓ 成功加载 {len(self.df)} 条数据")

        except Exception as e:
            raise Exception(f"加载CSV失败: {e}")

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        return {
            '股票代码': self.stock_code,
            '股票名称': self.stock_name,
            '所属行业': '未知',
            '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
        }

    def get_realtime_quote(self) -> Dict:
        """获取最新行情（从CSV最后一行）"""
        if self.df is None or len(self.df) == 0:
            return {}

        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2] if len(self.df) > 1 else latest

        return {
            '股票代码': self.stock_code,
            '股票名称': self.stock_name,
            '最新价': float(latest['收盘']),
            '涨跌额': float(latest['涨跌额']),
            '涨跌幅': float(latest['涨跌幅']),
            '今开': float(latest['开盘']),
            '昨收': float(prev['收盘']),
            '最高': float(latest['最高']),
            '最低': float(latest['最低']),
            '成交量': int(latest['成交量']),
            '成交额': float(latest.get('成交额', 0)),
            '换手率': float(latest.get('换手率', 0)),
            '振幅': float(latest['振幅']),
            '量比': 0,
            '市盈率': 0,
            '市净率': 0,
            '总市值': 0,
            '流通市值': 0,
        }

    def get_kline_data(self, days: int = 60) -> pd.DataFrame:
        """获取K线数据（从CSV）"""
        if self.df is None:
            raise Exception("CSV数据未加载")

        return self.df.tail(days).copy()
