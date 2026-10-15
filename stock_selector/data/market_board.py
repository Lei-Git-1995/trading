"""大盘指数 + 行业板块数据（腾讯行情主源 + 新浪兜底，均无需东财）

参考「致富研究员」：右侧面板展示 A股指数 与 行业板块榜。
腾讯接口在盘后仍返回可用的 5日/20日统计，故用作主源，避免东财不可达时空白。

数据源：
- 指数：https://qt.gtimg.cn/q=sh000001,sz399001,...
- 行业板块榜：https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank?board_type=hy
- 新浪兜底指数：https://hq.sinajs.cn/list=s_sh000001,...
"""
import time
from typing import Dict, List, Optional

import requests

TENCENT_QUOTE_URL = 'https://qt.gtimg.cn/q='
TENCENT_RANK_URL = 'https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank'
SINA_QUOTE_URL = 'https://hq.sinajs.cn/list='
EASTMONEY_INDUSTRY_HOSTS = (
    'https://82.push2.eastmoney.com',
    'https://push2.eastmoney.com',
    'https://push2delay.eastmoney.com',
)

# 主要指数：腾讯代码 -> 名称
INDEX_CODES = [
    ('sh000001', '上证指数'),
    ('sz399001', '深证成指'),
    ('sz399006', '创业板指'),
    ('sh000688', '科创50'),
    ('sh000300', '沪深300'),
    ('sh000016', '上证50'),
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://gu.qq.com/',
}


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class MarketBoardClient:
    """大盘指数 / 行业板块 客户端"""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self.last_board_source = ''

    # ---------------- 指数 ----------------

    def fetch_indices(self) -> List[Dict]:
        rows = self._indices_tencent()
        if not rows:
            rows = self._indices_sina()
        return rows

    def _indices_tencent(self) -> List[Dict]:
        codes = ','.join(code for code, _ in INDEX_CODES)
        text = self._get_text(TENCENT_QUOTE_URL + codes, encoding='gb18030')
        if not text:
            return []
        by_code = {}
        for line in text.strip().split('\n'):
            if '=' not in line:
                continue
            left, right = line.split('=', 1)
            code = left.strip().replace('v_', '')
            fields = right.strip().strip(';').strip('"').split('~')
            if len(fields) < 33:
                continue
            by_code[code] = {
                'name': fields[1],
                'close': _num(fields[3]),
                'change': _num(fields[31]),
                'pct_chg': _num(fields[32]),
            }
        rows = []
        for code, name in INDEX_CODES:
            item = by_code.get(code)
            if item:
                item['name'] = item['name'] or name
                rows.append(item)
        return rows

    def _indices_sina(self) -> List[Dict]:
        codes = ','.join(self._sina_code(code) for code, _ in INDEX_CODES)
        text = self._get_text(SINA_QUOTE_URL + codes, encoding='gb18030')
        if not text:
            return []
        rows = []
        for code, name in INDEX_CODES:
            marker = f'hq_str_{self._sina_code(code)}="'
            start = text.find(marker)
            if start < 0:
                continue
            seg = text[start + len(marker):].split('"', 1)[0]
            parts = seg.split(',')
            if len(parts) < 4:
                continue
            rows.append({
                'name': parts[0] or name,
                'close': _num(parts[1]),
                'change': _num(parts[2]),
                'pct_chg': _num(parts[3]),
            })
        return rows

    @staticmethod
    def _sina_code(tencent_code: str) -> str:
        return 's_' + tencent_code

    # ---------------- 行业板块 ----------------

    def fetch_industry_boards(self, pz: int = 100) -> List[Dict]:
        """东方财富细分行业优先，失败时回退腾讯综合行业榜。"""
        rows = self._industry_boards_eastmoney(max(200, pz))
        if rows:
            self.last_board_source = '东方财富细分行业'
            return rows
        rows = self._industry_boards_tencent(pz)
        self.last_board_source = '腾讯综合行业（兜底）' if rows else '无可用行业数据'
        return rows

    def _industry_boards_eastmoney(self, pz: int = 200) -> List[Dict]:
        params = {
            'pn': '1', 'pz': str(pz), 'po': '1', 'np': '1', 'fid': 'f3',
            'fs': 'm:90+t:2',
            'fields': 'f12,f14,f3,f62,f104,f105,f106,f128,f184',
        }
        for host in EASTMONEY_INDUSTRY_HOSTS:
            data = self._get_json(host + '/api/qt/clist/get', params)
            items = (((data or {}).get('data') or {}).get('diff')) or []
            if not items:
                continue
            rows = []
            for item in items:
                up = int(_num(item.get('f104')))
                down = int(_num(item.get('f105')))
                flat = int(_num(item.get('f106')))
                member = up + down + flat
                rows.append({
                    'code': item.get('f12'),
                    'name': item.get('f14'),
                    'pct_chg': _num(item.get('f3')) / 100.0,
                    'pct_chg_5d': None,
                    'main_net_yi': _num(item.get('f62')) / 100000000.0,
                    'main_net_5d_yi': None,
                    'up': up, 'down': down, 'flat': flat, 'member': member,
                    'up_ratio': up / member if member else None,
                    'main_net_pct': _num(item.get('f184')),
                    'leader': item.get('f128'),
                })
            if rows:
                return rows
        return []

    def _industry_boards_tencent(self, pz: int = 100) -> List[Dict]:
        params = {
            'board_type': 'hy', 'sort_type': 'price', 'direct': 'down',
            'offset': '0', 'count': str(pz),
        }
        data = self._get_json(TENCENT_RANK_URL, params)
        items = (((data or {}).get('data') or {}).get('rank_list')) or []
        rows = []
        for it in items:
            lzg = it.get('lzg') or {}
            rows.append({
                'code': it.get('code'),
                'name': it.get('name'),
                'pct_chg': _num(it.get('zdf')),
                'pct_chg_5d': _num(it.get('zdf_d5')),
                'main_net_yi': _num(it.get('zljlr')) / 10000.0,
                'main_net_5d_yi': _num(it.get('zljlr_d5')) / 10000.0,
                'up': None, 'down': None, 'flat': None, 'member': None,
                'up_ratio': None, 'main_net_pct': None,
                'leader': lzg.get('name'),
            })
        return rows

    def fetch_snapshot(self, board_limit: int = 8) -> Dict:
        indices = self.fetch_indices()
        boards = self.fetch_industry_boards()
        # 与资金研究口径一致：优先按主力净流入排序；接口无资金字段时才按涨跌幅。
        has_flow = any(b.get('main_net_yi') is not None and abs(b.get('main_net_yi') or 0) > 1e-9
                       for b in boards)
        key = 'main_net_yi' if has_flow else (
            'pct_chg' if any(abs(b.get('pct_chg') or 0) > 1e-9 for b in boards) else 'pct_chg_5d')
        bullish = sorted(boards, key=lambda b: b.get(key, 0.0), reverse=True)
        bearish = sorted(boards, key=lambda b: b.get(key, 0.0))
        return {
            'indices': indices,
            'gainers': bullish[:board_limit],
            'losers': bearish[:board_limit],
            'sort_key': key,
            'board_source': self.last_board_source,
            'time': time.strftime('%H:%M:%S'),
        }

    # ---------------- 内部 ----------------

    def _get_text(self, url: str, encoding: str = 'utf-8') -> Optional[str]:
        try:
            r = self._session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                r.encoding = encoding
                return r.text
        except Exception:
            return None
        return None

    def _get_json(self, url: str, params: Dict):
        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            return None
        return None


def fetch_market_snapshot(board_limit: int = 8) -> Dict:
    """便捷函数：获取一次大盘/板块快照"""
    return MarketBoardClient().fetch_snapshot(board_limit=board_limit)
