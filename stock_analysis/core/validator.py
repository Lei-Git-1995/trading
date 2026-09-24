#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据验证模块
检查数据质量和异常值
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple


class DataValidator:
    """数据验证器"""

    @staticmethod
    def validate_required_columns(df: pd.DataFrame, required: List[str]) -> Tuple[bool, List[str]]:
        """
        检查必需列是否存在

        :param df: DataFrame
        :param required: 必需列列表
        :return: (是否通过, 缺失列列表)
        """
        missing = [col for col in required if col not in df.columns]
        return len(missing) == 0, missing

    @staticmethod
    def validate_price_data(df: pd.DataFrame) -> Dict[str, List]:
        """
        验证价格数据的合理性

        :param df: 包含OHLC数据的DataFrame
        :return: 异常数据字典
        """
        issues = {
            'negative_prices': [],
            'invalid_ohlc': [],
            'extreme_changes': [],
            'zero_volume': []
        }

        for idx, row in df.iterrows():
            # 检查负价格
            if any(row[col] < 0 for col in ['开盘', '收盘', '最高', '最低'] if col in row):
                issues['negative_prices'].append(idx)

            # 检查OHLC逻辑关系
            if '最高' in row and '最低' in row and '开盘' in row and '收盘' in row:
                if not (row['最低'] <= row['开盘'] <= row['最高'] and
                       row['最低'] <= row['收盘'] <= row['最高']):
                    issues['invalid_ohlc'].append(idx)

            # 检查极端涨跌幅 (>50%)
            if '涨跌幅' in row and abs(row['涨跌幅']) > 50:
                issues['extreme_changes'].append((idx, row['涨跌幅']))

            # 检查零成交量
            if '成交量' in row and row['成交量'] == 0:
                issues['zero_volume'].append(idx)

        return issues

    @staticmethod
    def clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗数据：填充缺失值、移除异常值

        :param df: 原始DataFrame
        :return: 清洗后的DataFrame
        """
        df = df.copy()

        # 转换日期
        if '日期' in df.columns:
            df['日期'] = pd.to_datetime(df['日期'], errors='coerce')

        # 转换数值类型
        numeric_cols = ['开盘', '收盘', '最高', '最低', '成交量', '成交额',
                       '涨跌幅', '振幅', '换手率']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 计算衍生字段
        if '涨跌额' not in df.columns and '收盘' in df.columns:
            df['涨跌额'] = df['收盘'].diff()

        if '涨跌幅' not in df.columns and '收盘' in df.columns:
            df['涨跌幅'] = df['收盘'].pct_change() * 100

        if '振幅' not in df.columns and all(col in df.columns for col in ['最高', '最低', '收盘']):
            df['振幅'] = ((df['最高'] - df['最低']) / df['收盘'].shift(1) * 100)

        # 填充缺失值
        df = df.fillna(0)

        # 排序
        if '日期' in df.columns:
            df = df.sort_values('日期')

        return df

    @staticmethod
    def get_data_quality_report(df: pd.DataFrame) -> Dict:
        """
        生成数据质量报告

        :param df: DataFrame
        :return: 数据质量报告字典
        """
        report = {
            'total_rows': len(df),
            'date_range': None,
            'missing_values': {},
            'data_types': {},
            'summary_stats': {}
        }

        # 日期范围
        if '日期' in df.columns:
            report['date_range'] = {
                'start': df['日期'].min(),
                'end': df['日期'].max(),
                'days': (df['日期'].max() - df['日期'].min()).days
            }

        # 缺失值统计
        report['missing_values'] = df.isnull().sum().to_dict()

        # 数据类型
        report['data_types'] = df.dtypes.astype(str).to_dict()

        # 数值列统计
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            report['summary_stats'][col] = {
                'mean': float(df[col].mean()),
                'std': float(df[col].std()),
                'min': float(df[col].min()),
                'max': float(df[col].max())
            }

        return report
