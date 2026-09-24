"""大单监控选股策略"""
import time
from typing import List, Dict, Optional

import pandas as pd
from tqdm import tqdm

from stock_selector.config import ScreenerConfig
from stock_selector.data.capital_flow_client import CapitalFlowClient
from stock_selector.utils.logger import get_logger

logger = get_logger(__name__)


class BigOrderStrategy:
    """
    大单监控策略

    核心逻辑:
    1. 检测30分钟内大单买入/卖出
    2. 识别资金抢筹信号(大单买入>卖出且持续净流入)
    3. 识别猛烈打压信号(大单卖出>买入且持续净流出)
    """

    def __init__(self, config: ScreenerConfig = None):
        self.config = config or ScreenerConfig()
        self.client = CapitalFlowClient()

    def screen_big_order_inflow(
        self,
        stock_list: pd.DataFrame,
        threshold_millions: float = 500,
        min_net_inflow: float = 500
    ) -> List[Dict]:
        """
        大单净流入选股

        Args:
            stock_list: 股票列表
            threshold_millions: 大单阈值(万元), 默认500万
            min_net_inflow: 最小净流入(万元), 默认500万

        Returns:
            符合条件的股票列表
        """
        logger.info(f'\n[大单净流入] 筛选参数:')
        logger.info(f'  - 大单阈值: {threshold_millions}万')
        logger.info(f'  - 最小净流入: {min_net_inflow}万')

        results = []
        total = len(stock_list)

        for idx, (_, stock) in enumerate(tqdm(stock_list.iterrows(),
                                              total=total,
                                              desc='  扫描进度',
                                              unit='只')):
            code = stock['code']

            # 获取大单明细
            orders = self.client.get_big_orders(code, limit=200)
            if orders is None or orders.empty:
                continue

            # 分析大单情况
            analysis = self.client.analyze_big_orders(
                orders,
                threshold_millions=threshold_millions
            )

            # 筛选条件: 净流入 > 阈值
            if analysis['net_amount'] < min_net_inflow:
                continue

            # 获取实时资金流向
            flow = self.client.get_realtime_flow(code)
            if flow is None:
                continue

            results.append({
                'code': code,
                'name': stock.get('name', ''),
                'price': stock.get('price', 0),
                'change_pct': stock.get('change_pct', 0),
                'turnover': stock.get('turnover', 0),
                'big_buy_amount': analysis['big_buy_amount'],
                'big_sell_amount': analysis['big_sell_amount'],
                'net_amount': analysis['net_amount'],
                'big_buy_count': analysis['big_buy_count'],
                'big_sell_count': analysis['big_sell_count'],
                'main_force_flow': flow['主力净流入'],
                'main_force_ratio': flow['主力净占比'],
                'is_grabbing': analysis['is_grabbing'],
                'strategy': 'big_order_inflow'
            })

            time.sleep(0.1)  # 避免请求过快

        # 按净流入排序
        results.sort(key=lambda x: x['net_amount'], reverse=True)

        logger.info(f'  筛选完成: {len(results)} 只')
        return results

    def screen_capital_grab(
        self,
        stock_list: pd.DataFrame,
        min_net_inflow: float = 1000,
        min_main_ratio: float = 5.0
    ) -> List[Dict]:
        """
        资金抢筹选股

        特征:
        1. 主力资金持续净流入
        2. 大单买入明显多于卖出
        3. 主力净占比较高

        Args:
            stock_list: 股票列表
            min_net_inflow: 最小主力净流入(万元)
            min_main_ratio: 最小主力净占比(%)
        """
        logger.info(f'\n[资金抢筹] 筛选参数:')
        logger.info(f'  - 最小主力净流入: {min_net_inflow}万')
        logger.info(f'  - 最小主力净占比: {min_main_ratio}%')

        results = []
        total = len(stock_list)

        for idx, (_, stock) in enumerate(tqdm(stock_list.iterrows(),
                                              total=total,
                                              desc='  扫描进度',
                                              unit='只')):
            code = stock['code']

            # 获取实时资金流向
            flow = self.client.get_realtime_flow(code)
            if flow is None:
                continue

            # 筛选条件
            if flow['主力净流入'] < min_net_inflow:
                continue
            if flow['主力净占比'] < min_main_ratio:
                continue

            # 获取大单分析
            orders = self.client.get_big_orders(code, limit=200)
            analysis = self.client.analyze_big_orders(orders, threshold_millions=50)

            # 抢筹特征: 大单买入 > 卖出
            if not analysis['is_grabbing']:
                continue

            results.append({
                'code': code,
                'name': stock.get('name', ''),
                'price': stock.get('price', 0),
                'change_pct': stock.get('change_pct', 0),
                'turnover': stock.get('turnover', 0),
                'main_force_flow': flow['主力净流入'],
                'main_force_ratio': flow['主力净占比'],
                'super_big_flow': flow['超大单净流入'],
                'big_flow': flow['大单净流入'],
                'big_buy_amount': analysis['big_buy_amount'],
                'net_amount': analysis['net_amount'],
                'strategy': 'capital_grab'
            })

            time.sleep(0.1)

        # 按主力净流入排序
        results.sort(key=lambda x: x['main_force_flow'], reverse=True)

        logger.info(f'  筛选完成: {len(results)} 只')
        return results

    def screen_violent_suppress(
        self,
        stock_list: pd.DataFrame,
        min_net_outflow: float = 1000,
        max_change_pct: float = -2.0
    ) -> List[Dict]:
        """
        猛烈打压选股(寻找洗盘机会)

        特征:
        1. 主力资金大幅净流出
        2. 大单卖出明显多于买入
        3. 股价下跌但跌幅不深(可能是洗盘而非出货)

        Args:
            stock_list: 股票列表
            min_net_outflow: 最小净流出(万元,负数)
            max_change_pct: 最大跌幅(%)
        """
        logger.info(f'\n[猛烈打压] 筛选参数:')
        logger.info(f'  - 最小净流出: {min_net_outflow}万')
        logger.info(f'  - 最大跌幅: {max_change_pct}%')

        results = []
        total = len(stock_list)

        for idx, (_, stock) in enumerate(tqdm(stock_list.iterrows(),
                                              total=total,
                                              desc='  扫描进度',
                                              unit='只')):
            code = stock['code']
            change_pct = stock.get('change_pct', 0)

            # 跌幅筛选
            if change_pct > max_change_pct:
                continue

            # 获取实时资金流向
            flow = self.client.get_realtime_flow(code)
            if flow is None:
                continue

            # 筛选条件: 主力净流出
            if flow['主力净流入'] > -min_net_outflow:
                continue

            # 获取大单分析
            orders = self.client.get_big_orders(code, limit=200)
            analysis = self.client.analyze_big_orders(orders, threshold_millions=50)

            # 打压特征: 大单卖出 > 买入
            if not analysis['is_suppressing']:
                continue

            results.append({
                'code': code,
                'name': stock.get('name', ''),
                'price': stock.get('price', 0),
                'change_pct': change_pct,
                'turnover': stock.get('turnover', 0),
                'main_force_flow': flow['主力净流入'],
                'main_force_ratio': flow['主力净占比'],
                'big_sell_amount': analysis['big_sell_amount'],
                'net_amount': analysis['net_amount'],
                'strategy': 'violent_suppress'
            })

            time.sleep(0.1)

        # 按净流出排序(从大到小)
        results.sort(key=lambda x: x['main_force_flow'])

        logger.info(f'  筛选完成: {len(results)} 只')
        return results
