"""板块数据客户端（东方财富）

用于获取板块涨跌幅，计算个股相对强度
"""
import time
from typing import Optional, Dict, List
import pandas as pd
import requests


class SectorClient:
    """
    板块数据客户端

    功能:
    1. 获取所有板块实时涨跌幅
    2. 查询个股所属板块
    3. 计算个股相对板块的强度
    """

    # 板块行情API
    SECTOR_LIST_URL = 'http://push2.eastmoney.com/api/qt/clist/get'

    # 板块映射表（缓存）
    _sector_cache: Dict[str, str] = {}
    _sector_change_cache: Dict[str, float] = {}
    _cache_time: float = 0
    CACHE_TTL = 300  # 5分钟缓存

    def __init__(self, timeout: int = 15):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'http://quote.eastmoney.com/',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.timeout = timeout

    def get_all_sectors(self) -> Optional[pd.DataFrame]:
        """
        获取所有板块实时行情

        返回字段:
        - 板块代码
        - 板块名称
        - 涨跌幅(%)
        - 涨跌额
        - 成交额(亿)
        - 领涨股
        """
        # 行业板块
        params = {
            'pn': '1',
            'pz': '200',
            'po': '1',
            'np': '1',
            'fid': 'f3',
            'fs': 'm:90+t:2',  # 行业板块
            'fields': 'f12,f14,f2,f3,f4,f6,f128',
        }

        try:
            r = self.session.get(self.SECTOR_LIST_URL, params=params, timeout=self.timeout)
            data = r.json()
            diff = (data.get('data') or {}).get('diff')

            if not diff:
                return None

            rows = []
            for item in diff:
                rows.append({
                    '板块代码': item.get('f12', ''),
                    '板块名称': item.get('f14', ''),
                    '涨跌幅': float(item.get('f3', 0)),
                    '涨跌额': float(item.get('f4', 0)),
                    '成交额': float(item.get('f6', 0)),
                    '领涨股': item.get('f128', ''),
                })

            df = pd.DataFrame(rows)

            # 更新缓存
            self._update_cache(df)

            return df

        except Exception as e:
            print(f'  获取板块数据失败: {e}')
            return None

    def get_sector_change(self, sector_name: str) -> Optional[float]:
        """
        获取指定板块的涨跌幅

        Args:
            sector_name: 板块名称（如"电力设备"）

        Returns:
            涨跌幅(%)
        """
        # 检查缓存
        if self._is_cache_valid():
            return self._sector_change_cache.get(sector_name)

        # 刷新缓存
        df = self.get_all_sectors()
        if df is None or df.empty:
            return None

        # 查询
        result = df[df['板块名称'] == sector_name]
        if result.empty:
            return None

        return result['涨跌幅'].iloc[0]

    def get_stock_sector(self, code: str) -> Optional[str]:
        """
        查询个股所属板块

        注意: 这个需要从股票行情中提取板块信息
        目前返回缓存的映射，实际应该从股票详情API获取

        Args:
            code: 股票代码

        Returns:
            板块名称
        """
        # 简化实现：从缓存查询
        # 实际应该调用个股详情API获取所属行业
        return self._sector_cache.get(code)

    def calculate_relative_strength(
        self,
        stock_code: str,
        stock_change: float,
        sector_name: Optional[str] = None
    ) -> Optional[float]:
        """
        计算个股相对强度

        相对强度 = 个股涨跌幅 - 板块涨跌幅

        Args:
            stock_code: 股票代码
            stock_change: 个股涨跌幅(%)
            sector_name: 板块名称（如未提供则自动查询）

        Returns:
            相对强度(%)

        Examples:
            个股 +4%, 板块 +2% -> 相对强度 +2%
            个股 +3%, 板块 +5% -> 相对强度 -2%
        """
        # 获取板块名称
        if sector_name is None:
            sector_name = self.get_stock_sector(stock_code)

        if sector_name is None:
            return None

        # 获取板块涨跌幅
        sector_change = self.get_sector_change(sector_name)

        if sector_change is None:
            return None

        # 计算相对强度
        return stock_change - sector_change

    def batch_calculate_relative_strength(
        self,
        stocks: List[Dict]
    ) -> List[Dict]:
        """
        批量计算相对强度

        Args:
            stocks: 股票列表，每个元素包含 code, change_pct, sector

        Returns:
            增加 relative_strength 字段的股票列表
        """
        # 确保板块数据已加载
        if not self._is_cache_valid():
            self.get_all_sectors()

        results = []
        for stock in stocks:
            code = stock.get('code')
            change = stock.get('change_pct', 0)
            sector = stock.get('sector')

            relative_strength = self.calculate_relative_strength(code, change, sector)

            results.append({
                **stock,
                'relative_strength': relative_strength
            })

        return results

    def _update_cache(self, sector_df: pd.DataFrame):
        """更新板块缓存"""
        self._sector_change_cache = {
            row['板块名称']: row['涨跌幅']
            for _, row in sector_df.iterrows()
        }
        self._cache_time = time.time()

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        return (time.time() - self._cache_time) < self.CACHE_TTL

    def update_stock_sector_mapping(self, code: str, sector: str):
        """
        更新股票-板块映射

        这个方法供外部调用，用于维护映射表
        """
        self._sector_cache[code] = sector
