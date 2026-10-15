"""大盘指数 + 行业板块数据（腾讯行情主源 + 新浪兜底，均无需东财）

参考「致富研究员」：右侧面板展示 A股指数 与 行业板块榜。
腾讯接口在盘后仍返回可用的 5日/20日统计，故用作主源，避免东财不可达时空白。

数据源：
- 指数：https://qt.gtimg.cn/q=sh000001,sz399001,...
- 行业板块榜：https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank?board_type=hy
- 新浪兜底指数：https://hq.sinajs.cn/list=s_sh000001,...
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

TENCENT_QUOTE_URL = 'https://qt.gtimg.cn/q='
TENCENT_RANK_URL = 'https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank'
SINA_QUOTE_URL = 'https://hq.sinajs.cn/list='
EASTMONEY_LIMIT_UP_URL = 'https://push2ex.eastmoney.com/getTopicZTPool'
RESEARCHER_MARKET_SNAPSHOT = Path(os.getenv(
    'STOCK_SELECTOR_RESEARCHER_MARKET_SNAPSHOT',
    r'E:\trading\致富研究员\money\paper\market_overview.json'))
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

_LIMIT_UP_CACHE = {'day': '', 'at': 0.0, 'counts': None}


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_zgb(value):
    """腾讯板块 zgb 形如 "25/122"（上涨家数/成分家数）→ (up, down, member)。"""
    try:
        parts = str(value or '').split('/')
        if len(parts) != 2:
            return None, None, None
        up = int(float(parts[0]))
        member = int(float(parts[1]))
        if member <= 0:
            return None, None, None
        up = max(0, min(up, member))
        down = member - up
        return up, down, member
    except (TypeError, ValueError):
        return None, None, None


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
        rows = self._industry_boards_researcher_snapshot()
        if rows:
            self.last_board_source = '致富研究员当日行业快照'
            return rows
        rows = self._industry_boards_tencent(pz)
        self.last_board_source = '腾讯综合行业（兜底）' if rows else '无可用行业数据'
        return rows

    def _industry_boards_eastmoney(self, pz: int = 200) -> List[Dict]:
        params = {
            'pn': '1', 'pz': str(pz), 'po': '1', 'np': '1', 'fid': 'f3',
            'fs': 'm:90+t:2',
            # f104/f105/f106 是行业成分上涨/下跌/平盘数；涨停数另由涨停池按行业聚合。
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
                    'limit_up': None,
                    'main_net_pct': _num(item.get('f184')),
                    'leader': item.get('f128'),
                })
            if rows:
                limit_map = self._fetch_limit_up_by_industry()
                if limit_map is not None:
                    for row in rows:
                        row['limit_up'] = limit_map.get(self._normalize_board_name(row['name']), 0)
                return rows
        return []

    @staticmethod
    def _normalize_board_name(name) -> str:
        return ''.join(str(name or '').strip().lower().split())

    def _fetch_limit_up_by_industry(self):
        """读取东方财富涨停池并按所属行业统计。接口失败时返回 None。"""
        now = time.time()
        day = datetime.now().strftime('%Y%m%d')
        if _LIMIT_UP_CACHE['day'] == day and now - _LIMIT_UP_CACHE['at'] < 30:
            return _LIMIT_UP_CACHE['counts']
        params = {
            'ut': '7eea3edcaed734bea9cbfc24409ed989',
            'dpt': 'wz.ztzt', 'Pageindex': '0', 'pagesize': '10000',
            'sort': 'fbt:asc', 'date': day,
        }
        data = self._get_json(EASTMONEY_LIMIT_UP_URL, params)
        payload = (data or {}).get('data')
        counts = None
        if isinstance(payload, dict) and str(payload.get('qdate', day)) == day:
            pool = payload.get('pool')
            if isinstance(pool, list):
                counts = self._aggregate_limit_up_by_industry(
                    item.get('hybk') for item in pool if isinstance(item, dict))
        _LIMIT_UP_CACHE.update(day=day, at=now, counts=counts)
        return counts

    @classmethod
    def _aggregate_limit_up_by_industry(cls, industries):
        counts = {}
        for industry in industries:
            key = cls._normalize_board_name(industry)
            if key:
                counts[key] = counts.get(key, 0) + 1
        return counts

    def _industry_boards_researcher_snapshot(self) -> List[Dict]:
        """东财行业接口故障时读取本机研究员的同日有效快照。"""
        try:
            stat = RESEARCHER_MARKET_SNAPSHOT.stat()
            file_time = datetime.fromtimestamp(stat.st_mtime)
            now = datetime.now()
            if file_time.date() != now.date() or now.timestamp() - stat.st_mtime > 180:
                # 收盘后，同日最后一份快照依然是当天的有效收盘数据。
                if not (file_time.date() == now.date() and now.hour >= 15 and file_time.hour >= 15):
                    return []
            data = json.loads(RESEARCHER_MARKET_SNAPSHOT.read_text(encoding='utf-8'))
            if not data.get('ok') or data.get('stale') or not data.get('boards_fresh'):
                return []
            # all_boards 在致富研究员中只保留流入/流出各前20，不能拿这个截断集合
            # 再排序生成跌幅榜；直接组合对应的资金流入榜和流出榜。
            raw = (data.get('up_boards') or []) + (data.get('down_boards') or [])
            if not raw:
                raw = data.get('all_boards') or []
            limit_map = self._fetch_limit_up_by_industry()
            rows = []
            seen = set()
            for item in raw:
                code = str(item.get('code') or '')
                if not code or code in seen:
                    continue
                seen.add(code)
                name = item.get('name') or ''
                rows.append({
                    'code': code, 'name': name,
                    'pct_chg': item.get('pct_chg'), 'pct_chg_5d': None,
                    'main_net_yi': item.get('main_net_yi'),
                    'main_net_5d_yi': None,
                    'up': item.get('up'), 'down': item.get('down'),
                    'flat': item.get('flat'), 'member': item.get('member'),
                    'up_ratio': item.get('up_ratio'),
                    'limit_up': (limit_map.get(self._normalize_board_name(name), 0)
                                 if limit_map is not None else None),
                    'main_net_pct': item.get('main_net_pct'),
                    'leader': item.get('leader'),
                })
            return rows
        except (OSError, ValueError, TypeError, KeyError):
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
            up, down, member = _parse_zgb(it.get('zgb'))
            rows.append({
                'code': it.get('code'),
                'name': it.get('name'),
                'pct_chg': _num(it.get('zdf')),
                'pct_chg_5d': _num(it.get('zdf_d5')),
                'main_net_yi': _num(it.get('zljlr')) / 10000.0,
                'main_net_5d_yi': _num(it.get('zljlr_d5')) / 10000.0,
                'up': up, 'down': down, 'flat': None, 'member': member,
                'up_ratio': (up / member) if up is not None and member else None,
                'limit_up': None, 'main_net_pct': None,
                'leader': lzg.get('name'),
            })
        limit_map = self._fetch_limit_up_by_industry()
        if limit_map:
            for row in rows:
                key = self._normalize_board_name(row['name'])
                if key in limit_map:
                    row['limit_up'] = limit_map[key]
        return rows

    def fetch_snapshot(self, board_limit: int = 8) -> Dict:
        indices = self.fetch_indices()
        boards = self.fetch_industry_boards()
        stale = False
        if not boards:
            cached = _load_cache()
            if cached:
                boards = cached.get('boards') or []
                if not indices:
                    indices = cached.get('indices') or indices
                self.last_board_source = f"{cached.get('board_source') or '上次缓存'}(缓存)"
                stale = True
        elif indices:
            _save_cache(indices, boards, self.last_board_source)
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
            'stale': stale,
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


def _cache_path():
    try:
        from stock_selector.config import CACHE_DIR
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / 'market_board.json'
    except Exception:
        return None


def _save_cache(indices, boards, source):
    path = _cache_path()
    if path is None:
        return
    try:
        import json
        path.write_text(json.dumps(
            {'indices': indices, 'boards': boards, 'board_source': source,
             'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
            ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _load_cache() -> Optional[Dict]:
    path = _cache_path()
    if path is None or not path.exists():
        return None
    try:
        import json
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_market_snapshot(board_limit: int = 8) -> Dict:
    """便捷函数：获取一次大盘/板块快照"""
    return MarketBoardClient().fetch_snapshot(board_limit=board_limit)
