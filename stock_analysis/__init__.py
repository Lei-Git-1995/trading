#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票分析统一框架
提供技术分析、多数据源支持、报告生成
"""

__version__ = "2.0.0"
__author__ = "Stock Analysis Framework"

from .analyzer import StockAnalyzer
from .datasources import DataSourceFactory

__all__ = ['StockAnalyzer', 'DataSourceFactory']
