#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源基类
定义统一的数据源接口
"""

from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict


class DataSourceBase(ABC):
    """数据源基类"""

    def __init__(self, stock_code: str):
        """
        初始化数据源

        :param stock_code: 股票代码
        """
        self.stock_code = stock_code

    @abstractmethod
    def get_stock_info(self) -> Dict:
        """
        获取股票基本信息

        :return: 包含股票代码、名称、行业、交易所的字典
        """
        pass

    @abstractmethod
    def get_realtime_quote(self) -> Dict:
        """
        获取实时行情

        :return: 包含最新价、涨跌幅等实时数据的字典
        """
        pass

    @abstractmethod
    def get_kline_data(self, days: int = 60) -> pd.DataFrame:
        """
        获取K线历史数据

        :param days: 获取天数
        :return: 包含OHLCV数据的DataFrame
        """
        pass

    @property
    def name(self) -> str:
        """数据源名称"""
        return self.__class__.__name__.replace('DataSource', '')

    def is_available(self) -> bool:
        """
        检查数据源是否可用

        :return: 是否可用
        """
        try:
            # 尝试获取实时行情作为可用性测试
            quote = self.get_realtime_quote()
            return bool(quote)
        except Exception:
            return False
