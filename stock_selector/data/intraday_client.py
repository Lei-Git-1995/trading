"""分时数据客户端（新浪财经）

用于获取分时数据，支持盘中监控和超短线策略
"""
import time
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import pandas as pd
import requests


class IntradayClient:
    """
    分时数据客户端

    功能:
    1. 获取1/5/15/30分钟分时数据
    2. 计算日内最高价距离
    3. 盘中强度分析
    4. 集合竞价数据
    """

    # 新浪分时API
    SINA_MINUTE_URL = 'https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData'

    def __init__(self, timeout: int = 15):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.timeout = timeout

    def get_minute_data(
        self,
        code: str,
        period: int = 5,
        data_len: int = 48
    ) -> Optional[pd.DataFrame]:
        """
        获取分时K线数据

        Args:
            code: 股票代码
            period: 分钟周期（1/5/15/30/60）
            data_len: 数据条数（48条=当日一天的5分钟K线）

        Returns:
            DataFrame包含: 时间, 开盘, 收盘, 最高, 最低, 成交量
        """
        # 转换股票代码格式
        symbol = self._convert_code(code)

        params = {
            'symbol': symbol,
            'scale': str(period),
            'datalen': str(data_len),
        }

        try:
            r = self.session.get(self.SINA_MINUTE_URL, params=params, timeout=self.timeout)
            text = r.text

            # 解析JSONP格式
            import json
            start = text.find('[')
            end = text.rfind(']') + 1
            if start == -1 or end == 0:
                return None

            data = json.loads(text[start:end])

            if not data:
                return None

            rows = []
            for item in data:
                rows.append({
                    '时间': item['day'],
                    '开盘': float(item['open']),
                    '收盘': float(item['close']),
                    '最高': float(item['high']),
                    '最低': float(item['low']),
                    '成交量': float(item['volume']),
                })

            return pd.DataFrame(rows)

        except Exception as e:
            print(f'  获取分时数据失败({code}): {e}')
            return None

    def get_today_high_distance(
        self,
        code: str,
        current_price: float
    ) -> Optional[Dict]:
        """
        计算距离日内最高价的距离

        Args:
            code: 股票代码
            current_price: 当前价格

        Returns:
            {
                'today_high': 日内最高价,
                'today_low': 日内最低,
                'current_price': 当前价格,
                'high_distance': 距最高价距离(%),
                'low_distance': 距最低价距离(%),
                'amplitude': 振幅(%),
                'high_time': 最高价出现时间,
                'is_near_high': 是否接近最高价,
            }
        """
        # 获取当日分时数据
        minute_data = self.get_minute_data(code, period=5, data_len=48)

        if minute_data is None or minute_data.empty:
            return None

        today_high = minute_data['最高'].max()
        today_low = minute_data['最低'].min()

        # 找到最高价出现的时间
        high_idx = minute_data['最高'].idxmax()
        high_time = minute_data.loc[high_idx, '时间']

        # 计算距离
        high_distance = (current_price - today_high) / today_high * 100 if today_high > 0 else 0
        low_distance = (current_price - today_low) / today_low * 100 if today_low > 0 else 0
        amplitude = (today_high - today_low) / today_low * 100 if today_low > 0 else 0

        # 判断是否接近最高价（距离小于1%）
        is_near_high = abs(high_distance) < 1.0

        return {
            'today_high': today_high,
            'today_low': today_low,
            'current_price': current_price,
            'high_distance': round(high_distance, 2),
            'low_distance': round(low_distance, 2),
            'amplitude': round(amplitude, 2),
            'high_time': high_time,
            'is_near_high': is_near_high,
        }

    def get_intraday_strength(
        self,
        code: str,
        time_window: int = 30
    ) -> Optional[Dict]:
        """
        计算盘中强度

        Args:
            code: 股票代码
            time_window: 时间窗口（分钟）

        Returns:
            {
                'avg_change': 平均涨幅(%),
                'max_change': 最大涨幅(%),
                'min_change': 最小涨幅(%),
                'volatility': 波动率,
                'volume_surge': 成交量放大倍数,
                'is_strong': 是否强势,
            }
        """
        # 获取分时数据
        minute_data = self.get_minute_data(code, period=5, data_len=48)

        if minute_data is None or minute_data.empty:
            return None

        # 取最近time_window分钟的数据
        periods = time_window // 5
        recent_data = minute_data.tail(periods)

        if len(recent_data) < 2:
            return None

        # 计算涨跌幅
        first_price = recent_data['开盘'].iloc[0]
        changes = (recent_data['收盘'] - first_price) / first_price * 100

        avg_change = changes.mean()
        max_change = changes.max()
        min_change = changes.min()
        volatility = changes.std()

        # 成交量分析
        avg_volume = minute_data['成交量'].mean()
        recent_volume = recent_data['成交量'].mean()
        volume_surge = recent_volume / avg_volume if avg_volume > 0 else 1.0

        # 判断是否强势：平均涨幅>0 且 波动率适中 且 成交量放大
        is_strong = (avg_change > 0) and (volatility < 2.0) and (volume_surge > 1.2)

        return {
            'avg_change': round(avg_change, 2),
            'max_change': round(max_change, 2),
            'min_change': round(min_change, 2),
            'volatility': round(volatility, 2),
            'volume_surge': round(volume_surge, 2),
            'is_strong': is_strong,
        }

    def get_auction_data(self, code: str) -> Optional[Dict]:
        """
        获取集合竞价数据（9:20-9:25）

        注意: 此功能需要在竞价时段实时获取，盘后无法获取
        这里提供接口框架，实际需要在交易时段调用

        Args:
            code: 股票代码

        Returns:
            {
                'auction_price': 竞价成交价,
                'auction_volume': 竞价成交量,
                'auction_change': 竞价涨跌幅(%),
                'buy_orders': 买单数量,
                'sell_orders': 卖单数量,
                'is_strong_auction': 是否强势竞价,
            }
        """
        # TODO: 实现集合竞价数据获取
        # 东方财富集合竞价API: http://push2.eastmoney.com/api/qt/stock/get
        # 参数: secid, fields=f43,f44,f45,f46,f47,f48,f49,f50

        symbol = self._convert_code_for_eastmoney(code)

        params = {
            'secid': symbol,
            'fields': 'f43,f44,f45,f46,f47,f48,f49,f50,f51,f52',
        }

        try:
            r = self.session.get(
                'http://push2.eastmoney.com/api/qt/stock/get',
                params=params,
                timeout=self.timeout
            )
            data = r.json()
            info = (data.get('data') or {})

            if not info:
                return None

            # 解析竞价数据
            return {
                'auction_price': float(info.get('f43', 0)),  # 最新价
                'auction_volume': float(info.get('f47', 0)),  # 总手
                'auction_change': float(info.get('f170', 0)),  # 涨跌幅
                'buy_orders': float(info.get('f49', 0)),  # 买一量
                'sell_orders': float(info.get('f50', 0)),  # 卖一量
                'is_strong_auction': float(info.get('f49', 0)) > float(info.get('f50', 0)),
            }

        except Exception as e:
            print(f'  获取集合竞价数据失败({code}): {e}')
            return None

    def analyze_opening_strength(
        self,
        code: str,
        open_price: float,
        yesterday_close: float
    ) -> Dict:
        """
        分析开盘强度

        Args:
            code: 股票代码
            open_price: 开盘价
            yesterday_close: 昨日收盘价

        Returns:
            {
                'gap_pct': 跳空幅度(%),
                'gap_type': 跳空类型(高开/平开/低开),
                'first_5min_change': 开盘5分钟涨跌幅,
                'is_strong_open': 是否强势开盘,
            }
        """
        # 计算跳空幅度
        gap_pct = (open_price - yesterday_close) / yesterday_close * 100

        # 判断跳空类型
        if gap_pct > 1.0:
            gap_type = '高开'
        elif gap_pct < -1.0:
            gap_type = '低开'
        else:
            gap_type = '平开'

        # 获取开盘后5分钟数据
        minute_data = self.get_minute_data(code, period=5, data_len=2)

        first_5min_change = 0.0
        if minute_data is not None and not minute_data.empty:
            first_close = minute_data['收盘'].iloc[0]
            first_5min_change = (first_close - open_price) / open_price * 100

        # 判断强势开盘：高开 + 开盘后不回落
        is_strong_open = (gap_pct > 0.5) and (first_5min_change > -0.5)

        return {
            'gap_pct': round(gap_pct, 2),
            'gap_type': gap_type,
            'first_5min_change': round(first_5min_change, 2),
            'is_strong_open': is_strong_open,
        }

    @staticmethod
    def _convert_code(code: str) -> str:
        """
        转换股票代码为新浪格式

        Examples:
            600519 -> sh600519
            000001 -> sz000001
        """
        if code.startswith('6'):
            return f'sh{code}'
        else:
            return f'sz{code}'

    @staticmethod
    def _convert_code_for_eastmoney(code: str) -> str:
        """
        转换股票代码为东方财富格式

        Examples:
            600519 -> 1.600519
            000001 -> 0.000001
        """
        if code.startswith('6'):
            return f'1.{code}'
        else:
            return f'0.{code}'
