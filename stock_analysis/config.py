#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
"""

import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# 路径配置
PATHS = {
    'template': PROJECT_ROOT / 'docs' / 'stock_analysis_template.md',
    'reports': PROJECT_ROOT / 'reports',
    'cache': PROJECT_ROOT / '.cache',
}

# 数据源配置
DATASOURCE_CONFIG = {
    'eastmoney': {
        'enabled': False,  # push2.eastmoney.com 被屏蔽，暂时禁用
        'priority': 2,
        'timeout': 15,
        'clist_hosts': [
            'push2delay.eastmoney.com',
            '82.push2.eastmoney.com',
            'push2.eastmoney.com',
        ],
        'kline_hosts': [
            'push2his.eastmoney.com',
            '16.push2his.eastmoney.com',
        ],
    },
    'tencent': {
        'enabled': True,
        'priority': 1,  # 提升为首选数据源
        'timeout': 15,
        'realtime_url': 'http://qt.gtimg.cn',
        'kline_url': 'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
    },
    'akshare': {
        'enabled': False,  # Not implemented yet
        'priority': 3,
        'timeout': 20,
    },
    'csv': {
        'enabled': True,
        'required_columns': ['日期', '开盘', '收盘', '最高', '最低', '成交量'],
    }
}

# 技术指标默认参数
INDICATOR_PARAMS = {
    'ma_periods': [5, 10, 20, 60],
    'macd': {'fast': 12, 'slow': 26, 'signal': 9},
    'kdj': {'n': 9, 'm1': 3, 'm2': 3},
    'rsi_periods': [6, 12, 24],
    'boll': {'n': 20, 'k': 2},
}

# 分析参数
ANALYSIS_CONFIG = {
    'kline_days': 60,
    'recent_days': 10,
    'support_resistance_lookback': 20,
}

# HTTP请求配置
HTTP_CONFIG = {
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    },
    'max_retries': 3,
    'retry_backoff': 2.0,
}


def get_template_path() -> Path:
    """获取模板路径"""
    return PATHS['template']


def get_report_dir() -> Path:
    """获取报告目录，不存在则创建"""
    report_dir = PATHS['reports']
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def get_cache_dir() -> Path:
    """获取缓存目录，不存在则创建"""
    cache_dir = PATHS['cache']
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
