#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票分析器
整合数据源、技术指标、报告生成
"""

import pandas as pd
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

from .datasources import DataSourceFactory, DataSourceBase
from .core import TechnicalIndicators, ReportGenerator, DataValidator
from .config import get_template_path, get_report_dir, ANALYSIS_CONFIG


class StockAnalyzer:
    """股票分析器"""

    def __init__(self, stock_code: str, datasource: Optional[DataSourceBase] = None):
        """
        初始化分析器

        :param stock_code: 股票代码
        :param datasource: 数据源实例（可选，默认自动选择）
        """
        self.stock_code = stock_code
        self.datasource = datasource or DataSourceFactory.create_auto(stock_code)
        self.df = None
        self.stock_info = None
        self.realtime = None

    def load_data(self, days: int = None) -> pd.DataFrame:
        """
        加载股票数据

        :param days: 获取天数
        :return: 包含OHLCV数据的DataFrame
        """
        if days is None:
            days = ANALYSIS_CONFIG['kline_days']

        print(f"\n正在获取 {self.stock_code} 的历史数据...")

        # 获取基础信息
        self.stock_info = self.datasource.get_stock_info()
        print(f"[OK] 股票信息: {self.stock_info.get('股票名称', self.stock_code)}")

        # 获取实时行情
        self.realtime = self.datasource.get_realtime_quote()
        if self.realtime:
            print(f"[OK] 最新价: {self.realtime.get('最新价', 0):.2f}")

        # 获取K线数据
        self.df = self.datasource.get_kline_data(days)
        if self.df.empty:
            raise Exception("未获取到K线数据")

        print(f"[OK] 成功获取 {len(self.df)} 天K线数据")

        # 数据验证
        issues = DataValidator.validate_price_data(self.df)
        if any(issues.values()):
            print("⚠ 数据质量警告:")
            for key, items in issues.items():
                if items:
                    print(f"  - {key}: {len(items)} 处异常")

        return self.df

    def calculate_indicators(self) -> pd.DataFrame:
        """
        计算所有技术指标

        :return: 添加了技术指标的DataFrame
        """
        if self.df is None:
            raise Exception("请先调用 load_data() 加载数据")

        print("\n正在计算技术指标...")
        self.df = TechnicalIndicators.calculate_all(self.df)
        print("[OK] 技术指标计算完成")

        return self.df

    def analyze(self) -> Dict:
        """
        执行技术分析

        :return: 分析结果字典
        """
        if self.df is None:
            raise Exception("请先调用 load_data() 加载数据")

        # 确保计算了技术指标
        if 'MA5' not in self.df.columns:
            self.calculate_indicators()

        print("\n正在分析趋势...")
        analysis = TechnicalIndicators.analyze_trend(self.df)
        print(f"[OK] 趋势: {analysis['trend']}")
        print(f"[OK] MACD: {analysis['macd_signal']} ({analysis['macd_status']})")
        print(f"[OK] KDJ: {analysis['kdj_status']}")

        return analysis

    def get_support_resistance(self) -> Dict:
        """
        获取支撑压力位

        :return: 支撑压力位字典
        """
        if self.df is None:
            raise Exception("请先调用 load_data() 加载数据")

        lookback = ANALYSIS_CONFIG['support_resistance_lookback']
        sr = TechnicalIndicators.calculate_support_resistance(self.df, lookback)

        print(f"\n支撑位: {', '.join([f'{s:.2f}' for s in sr['supports']])}")
        print(f"压力位: {', '.join([f'{r:.2f}' for r in sr['resistances']])}")

        return sr

    def generate_report(self, output_path: Optional[str] = None,
                        template_path: Optional[str] = None) -> str:
        """
        生成分析报告

        :param output_path: 输出路径（可选）
        :param template_path: 模板路径（可选）
        :return: 报告文件路径
        """
        # 加载数据并分析
        if self.df is None:
            self.load_data()

        if 'MA5' not in self.df.columns:
            self.calculate_indicators()

        analysis = self.analyze()
        sr = self.get_support_resistance()

        # 确定输出路径
        if output_path is None:
            report_dir = get_report_dir()
            timestamp = datetime.now().strftime('%Y%m%d')
            output_path = report_dir / f"{self.stock_code}_{timestamp}.md"

        # 确定模板路径
        if template_path is None:
            template_path = get_template_path()

        # 生成报告
        print("\n正在生成分析报告...")
        generator = ReportGenerator(str(template_path))

        stock_name = self.stock_info.get('股票名称', self.stock_code)
        report_path = generator.generate(
            stock_code=self.stock_code,
            stock_name=stock_name,
            df=self.df,
            realtime=self.realtime,
            analysis=analysis,
            sr=sr,
            output_path=str(output_path)
        )

        print(f"[OK] 报告已生成: {report_path}")
        return report_path

    def get_data_quality_report(self) -> Dict:
        """
        获取数据质量报告

        :return: 数据质量报告
        """
        if self.df is None:
            raise Exception("请先调用 load_data() 加载数据")

        return DataValidator.get_data_quality_report(self.df)

    @classmethod
    def from_csv(cls, csv_file: str, stock_code: str = None,
                 stock_name: str = None) -> 'StockAnalyzer':
        """
        从CSV文件创建分析器

        :param csv_file: CSV文件路径
        :param stock_code: 股票代码（可选）
        :param stock_name: 股票名称（可选）
        :return: StockAnalyzer实例
        """
        from .datasources import CSVDataSource
        datasource = CSVDataSource(csv_file, stock_code, stock_name)
        return cls(stock_code or "000000", datasource)

    @classmethod
    def from_datasource(cls, stock_code: str, source_name: str) -> 'StockAnalyzer':
        """
        使用指定数据源创建分析器

        :param stock_code: 股票代码
        :param source_name: 数据源名称（eastmoney, tencent等）
        :return: StockAnalyzer实例
        """
        datasource = DataSourceFactory.create(source_name, stock_code=stock_code)
        return cls(stock_code, datasource)
