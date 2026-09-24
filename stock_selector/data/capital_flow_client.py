"""资金流向和大单监控数据客户端（东方财富）"""
import time
from datetime import datetime
from typing import Optional, Dict, List

import pandas as pd
import requests


class CapitalFlowClient:
    """
    东方财富资金流向和大单数据客户端

    主要功能:
    1. 获取个股资金流向(主力/大单/中单/小单)
    2. 获取大单成交明细(买入/卖出)
    3. 获取分时资金流向
    """

    # 资金流向API
    CAPITAL_FLOW_URL = 'http://push2.eastmoney.com/api/qt/stock/fflow/kline/get'
    # 大单明细API
    BIG_ORDER_URL = 'http://push2.eastmoney.com/api/qt/stock/details/get'
    # 实时资金流向
    REALTIME_FLOW_URL = 'http://push2.eastmoney.com/api/qt/stock/fflow/daykline/get'

    def __init__(self, timeout: int = 15):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'http://quote.eastmoney.com/',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.timeout = timeout

    def get_capital_flow(self, code: str, days: int = 5) -> Optional[pd.DataFrame]:
        """
        获取个股资金流向(近N日)

        返回字段:
        - 日期
        - 主力净流入(万元)
        - 小单净流入(万元)
        - 中单净流入(万元)
        - 大单净流入(万元)
        - 超大单净流入(万元)
        """
        secid = f'1.{code}' if code.startswith('6') else f'0.{code}'

        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f7',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65',
            'klt': '101',  # 日K
            'lmt': str(days),
        }

        try:
            r = self.session.get(self.CAPITAL_FLOW_URL, params=params, timeout=self.timeout)
            data = r.json()
            klines = (data.get('data') or {}).get('klines')
            if not klines:
                return None

            rows = []
            for line in klines:
                parts = line.split(',')
                if len(parts) < 7:
                    continue
                rows.append({
                    '日期': parts[0],
                    '主力净流入': float(parts[1]),  # 万元
                    '小单净流入': float(parts[2]),
                    '中单净流入': float(parts[3]),
                    '大单净流入': float(parts[4]),
                    '超大单净流入': float(parts[5]),
                    '主力净占比': float(parts[6]),  # %
                })

            return pd.DataFrame(rows) if rows else None

        except Exception as e:
            print(f'  获取资金流向失败({code}): {e}')
            return None

    def get_big_orders(self, code: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        获取大单成交明细(最近N笔)

        返回字段:
        - 时间
        - 价格
        - 成交量(手)
        - 成交额(万元)
        - 买卖方向(1=买入, 2=卖出, 4=中性)
        """
        secid = f'1.{code}' if code.startswith('6') else f'0.{code}'

        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4',
            'fields2': 'f51,f52,f53,f54,f55',
            'pos': '-0',  # 最新数据
            'iscr': '0',
        }

        try:
            r = self.session.get(self.BIG_ORDER_URL, params=params, timeout=self.timeout)
            data = r.json()
            details = (data.get('data') or {}).get('details')
            if not details:
                return None

            rows = []
            for line in details[:limit]:
                parts = line.split(',')
                if len(parts) < 5:
                    continue

                # 计算成交额(万元)
                amount = float(parts[2]) * float(parts[1]) * 100 / 10000  # 手转股*价格/10000

                rows.append({
                    '时间': parts[0],
                    '价格': float(parts[1]),
                    '成交量': int(parts[2]),  # 手
                    '成交额': round(amount, 2),  # 万元
                    '方向': int(parts[4]),  # 1=买 2=卖 4=中性
                })

            return pd.DataFrame(rows) if rows else None

        except Exception as e:
            print(f'  获取大单明细失败({code}): {e}')
            return None

    def get_realtime_flow(self, code: str) -> Optional[Dict]:
        """
        获取实时资金流向(当日累计)

        返回:
        {
            '主力净流入': float,  # 万元
            '主力净占比': float,  # %
            '超大单净流入': float,
            '大单净流入': float,
            '中单净流入': float,
            '小单净流入': float,
        }
        """
        secid = f'1.{code}' if code.startswith('6') else f'0.{code}'

        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f7',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63',
        }

        try:
            r = self.session.get(self.REALTIME_FLOW_URL, params=params, timeout=self.timeout)
            data = r.json()
            info = (data.get('data') or {})

            if not info:
                return None

            return {
                '主力净流入': float(info.get('f62', 0)),  # 万元
                '主力净占比': float(info.get('f184', 0)),  # %
                '超大单净流入': float(info.get('f56', 0)),
                '大单净流入': float(info.get('f57', 0)),
                '中单净流入': float(info.get('f58', 0)),
                '小单净流入': float(info.get('f59', 0)),
            }

        except Exception as e:
            print(f'  获取实时资金流向失败({code}): {e}')
            return None

    def analyze_big_orders(
        self,
        orders: pd.DataFrame,
        threshold_millions: float = 50,
        time_window_minutes: int = 30
    ) -> Dict:
        """
        分析大单成交情况

        Args:
            orders: 大单明细DataFrame
            threshold_millions: 大单阈值(万元)
            time_window_minutes: 时间窗口(分钟)

        Returns:
            {
                'big_buy_count': int,      # 大单买入笔数
                'big_sell_count': int,     # 大单卖出笔数
                'big_buy_amount': float,   # 大单买入金额(万)
                'big_sell_amount': float,  # 大单卖出金额(万)
                'net_amount': float,       # 净流入(万)
                'is_grabbing': bool,       # 是否抢筹
                'is_suppressing': bool,    # 是否打压
            }
        """
        if orders is None or orders.empty:
            return self._empty_analysis()

        # 过滤大单(超过阈值)
        big_orders = orders[orders['成交额'] >= threshold_millions].copy()

        if big_orders.empty:
            return self._empty_analysis()

        # 统计买卖情况
        buy_orders = big_orders[big_orders['方向'] == 1]
        sell_orders = big_orders[big_orders['方向'] == 2]

        big_buy_amount = buy_orders['成交额'].sum()
        big_sell_amount = sell_orders['成交额'].sum()
        net_amount = big_buy_amount - big_sell_amount

        # 判断抢筹和打压
        # 抢筹: 大单买入 > 大单卖出 * 1.5 且净流入 > 500万
        is_grabbing = (big_buy_amount > big_sell_amount * 1.5) and (net_amount > 500)

        # 打压: 大单卖出 > 大单买入 * 1.5 且净流出 > 500万
        is_suppressing = (big_sell_amount > big_buy_amount * 1.5) and (net_amount < -500)

        return {
            'big_buy_count': len(buy_orders),
            'big_sell_count': len(sell_orders),
            'big_buy_amount': round(big_buy_amount, 2),
            'big_sell_amount': round(big_sell_amount, 2),
            'net_amount': round(net_amount, 2),
            'is_grabbing': is_grabbing,
            'is_suppressing': is_suppressing,
        }

    @staticmethod
    def _empty_analysis() -> Dict:
        """返回空分析结果"""
        return {
            'big_buy_count': 0,
            'big_sell_count': 0,
            'big_buy_amount': 0.0,
            'big_sell_amount': 0.0,
            'net_amount': 0.0,
            'is_grabbing': False,
            'is_suppressing': False,
        }
