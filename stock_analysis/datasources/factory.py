#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源工厂
根据配置自动选择最优数据源
"""

from typing import Union, List
from .base import DataSourceBase
from .eastmoney import EastMoneyDataSource
from .tencent import TencentDataSource
from .csv_source import CSVDataSource
from ..config import DATASOURCE_CONFIG


class DataSourceFactory:
    """数据源工厂"""

    # 注册所有数据源
    _datasources = {
        'eastmoney': EastMoneyDataSource,
        'tencent': TencentDataSource,
        'csv': CSVDataSource,
    }

    @classmethod
    def create(cls, source_name: str, **kwargs) -> DataSourceBase:
        """
        创建指定数据源

        :param source_name: 数据源名称（eastmoney, tencent, csv等）
        :param kwargs: 数据源初始化参数
        :return: 数据源实例
        """
        if source_name not in cls._datasources:
            raise ValueError(f"未知数据源: {source_name}")

        datasource_class = cls._datasources[source_name]
        return datasource_class(**kwargs)

    @classmethod
    def create_auto(cls, stock_code: str, fallback: bool = True) -> DataSourceBase:
        """
        自动选择最优数据源（按优先级）

        :param stock_code: 股票代码
        :param fallback: 是否启用降级策略
        :return: 数据源实例
        """
        # 按优先级排序
        sources = sorted(
            [(name, config) for name, config in DATASOURCE_CONFIG.items()
             if config.get('enabled', False) and name != 'csv'],
            key=lambda x: x[1].get('priority', 999)
        )

        last_error = None
        for source_name, config in sources:
            try:
                print(f"尝试数据源: {source_name}")
                datasource = cls.create(source_name, stock_code=stock_code)

                # 测试可用性
                if datasource.is_available():
                    print(f"[OK] 使用数据源: {source_name}")
                    return datasource
                else:
                    print(f"[X] 数据源不可用: {source_name} (网络连接失败或服务不可达)")
            except Exception as e:
                last_error = e
                print(f"[X] 数据源失败: {source_name} - {str(e)}")
                if not fallback:
                    raise

        # 所有数据源都失败
        raise Exception(f"所有数据源均不可用。最后错误: {last_error}")

    @classmethod
    def create_multi(cls, stock_code: str,
                     sources: List[str] = None) -> 'MultiDataSource':
        """
        创建多数据源组合（用于容灾）

        :param stock_code: 股票代码
        :param sources: 数据源列表，默认按配置优先级
        :return: 多数据源实例
        """
        if sources is None:
            sources = [name for name, config in
                      sorted(DATASOURCE_CONFIG.items(), key=lambda x: x[1].get('priority', 999))
                      if config.get('enabled', False) and name != 'csv']

        return MultiDataSource(stock_code, sources)


class MultiDataSource(DataSourceBase):
    """
    多数据源组合
    自动切换到可用数据源
    """

    def __init__(self, stock_code: str, sources: List[str]):
        super().__init__(stock_code)
        self.sources = sources
        self._current_source = None
        self._source_instances = {}

    def _get_source(self, prefer: str = None) -> DataSourceBase:
        """获取可用数据源"""
        # 如果指定了首选数据源，优先使用
        sources_to_try = [prefer] + self.sources if prefer else self.sources

        for source_name in sources_to_try:
            if source_name not in self.sources:
                continue

            # 复用已创建的实例
            if source_name not in self._source_instances:
                try:
                    self._source_instances[source_name] = DataSourceFactory.create(
                        source_name, stock_code=self.stock_code
                    )
                except Exception:
                    continue

            source = self._source_instances[source_name]
            if source.is_available():
                return source

        raise Exception("所有数据源均不可用")

    def get_stock_info(self) -> dict:
        """获取股票基本信息"""
        source = self._get_source()
        return source.get_stock_info()

    def get_realtime_quote(self) -> dict:
        """获取实时行情"""
        source = self._get_source()
        return source.get_realtime_quote()

    def get_kline_data(self, days: int = 60):
        """获取K线数据（支持降级到备用源）"""
        # 优先使用东方财富，失败则使用腾讯
        try:
            source = self._get_source(prefer='eastmoney')
            return source.get_kline_data(days)
        except Exception as e:
            print(f"主数据源K线失败: {e}")
            print("切换到备用数据源...")
            source = self._get_source(prefer='tencent')
            return source.get_kline_data(days)
