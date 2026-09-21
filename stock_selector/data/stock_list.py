"""股票列表：从东方财富原始快照整理出选股用的标准化数据"""
import pandas as pd

import numpy as np

STOCK_COLS = ['code', 'name', 'price', 'change_pct', 'turnover', 'volume',
              'inner_vol', 'outer_vol', 'outer_ratio', 'inner_ratio', 'sector']


def load_stock_list(raw: pd.DataFrame) -> pd.DataFrame:
    """
    处理实时行情快照：
      - 字段归一化（分→元、万分位→百分比）
      - 排除 ST / 退市 / 名称含 * 的股票
      - 计算外盘/内盘占比
    返回 DataFrame，列见 STOCK_COLS
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=STOCK_COLS)

    df = pd.DataFrame({
        'code': raw['f12'].astype(str),
        'name': raw['f14'].astype(str),
        'price': raw['f2'].astype(float) / 100,
        'change_pct': raw['f3'].astype(float) / 100,
        'turnover': raw['f8'].astype(float) / 100,
        'volume': raw['f5'].astype(float),
        'inner_vol': raw['f35'].astype(float),
        'outer_vol': raw['f34'].astype(float),
        'sector': raw['f100'].fillna('未分类').astype(str),
    })

    # 排除 ST / 退市 / *
    bad = df['name'].str.upper().str.contains('ST|退', na=False) | df['name'].str.contains(r'\*', na=False)
    df = df[~bad].copy()

    # 外盘 / 内盘占比
    total = (df['inner_vol'] + df['outer_vol']).replace(0, np.nan)
    df['outer_ratio'] = (df['outer_vol'] / total * 100).fillna(50.0)
    df['inner_ratio'] = 100 - df['outer_ratio']

    df['sector'] = df['sector'].replace({'': '未分类'}).fillna('未分类')
    return df[STOCK_COLS]