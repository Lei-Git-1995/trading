"""东方财富行情客户端：实时行情列表（多主机容灾） + 个股历史K线（腾讯背靠背）"""
import time
from datetime import datetime

import pandas as pd
import requests

# 实时行情列表主机（按优先级依次尝试）
CLIST_HOSTS = [
    '82.push2.eastmoney.com',
    'push2.eastmoney.com',
    'push2delay.eastmoney.com',   # 延时行情镜像，本机网络可达
]
# 历史K线主机（东财若不可达则回退到腾讯）
KLINE_HOSTS = [
    'push2his.eastmoney.com',
    '16.push2his.eastmoney.com',
]
TENCENT_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'


class EastMoneyClient:
    """封装东方财富公开接口，返回 pandas DataFrame；东财不可达时有容灾降级"""

    def __init__(self, timeout=15, sleep=0.5):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.timeout = timeout
        self.sleep = sleep

    # ---------------- 实时行情列表 ----------------

    def get_all_stocks(self) -> pd.DataFrame:
        """
        获取沪深A股实时行情快照（东方财富原文格式）。
        注意：不使用 fltt 参数，返回原始整数单位（分 / 万分之一），
        与 stock_list.load_stock_list() 的换算（/100）保持一致。
        """
        host = self._first_ok_host(CLIST_HOSTS)
        if host is None:
            print('  所有东方财富行情主机均不可达')
            return pd.DataFrame()

        pz = self._detect_page_size(host)
        frames = []
        for market in ['m:0+t:6,m:0+t:80', 'm:1+t:2,m:1+t:23']:
            page = 1
            fails = 0
            while True:
                params = {
                    'pn': str(page),
                    'pz': str(pz),
                    'po': '1',
                    'np': '1',
                    'fid': 'f3',
                    'fs': market,
                    'fields': 'f12,f14,f2,f3,f5,f8,f34,f35,f100',
                }
                diff = None
                for _ in range(3):  # 瞬时网络错误自动重试，避免整页丢失导致漏选
                    data = self._get_json(f'http://{host}/api/qt/clist/get', params)
                    diff = (data.get('data') or {}).get('diff') if data else None
                    if diff:
                        break
                    time.sleep(1.0)
                if not diff:
                    fails += 1
                    if fails >= 2:
                        break
                    continue
                frames.append(pd.DataFrame(diff))
                if len(diff) < pz:
                    break
                page += 1
                time.sleep(self.sleep)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ---------------- 个股历史K线 ----------------

    def get_stock_history(self, stock_code: str, days: int = 5) -> pd.DataFrame:
        """获取个股近N个交易日的日K，统一列：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"""
        df = self._eastmoney_kline(stock_code, days)
        if df is None:
            df = self._tencent_kline(stock_code, days)
        return df

    def _eastmoney_kline(self, stock_code, days) -> pd.DataFrame:
        host = self._first_ok_host(
            KLINE_HOSTS,
            probe_path='/api/qt/stock/kline/get',
            probe_params={
                'secid': '1.600519',
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56',
                'klt': '101', 'fqt': '1', 'lmt': '1',
            })
        if host is None:
            return None

        secid = f'1.{stock_code}' if stock_code.startswith('6') else f'0.{stock_code}'
        end = datetime.now().strftime('%Y%m%d')
        start = (pd.Timestamp.now() - pd.Timedelta(days=days * 2)).strftime('%Y%m%d')

        data = self._get_json(f'http://{host}/api/qt/stock/kline/get', {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '1',
            'beg': start,
            'end': end,
        })
        klines = (data.get('data') or {}).get('klines') if data else None
        if not klines:
            return None

        cols = ['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']
        rows = [dict(zip(cols, [float(x) if i > 0 else x for i, x in enumerate(k.split(','))])) for k in klines]
        df = pd.DataFrame(rows)[-days:]
        df['日期'] = df['日期'].astype(str)
        return df

    def _tencent_kline(self, stock_code, days) -> pd.DataFrame:
        """腾讯行情 K 线回退通道；仅含 OHLCV，涨跌幅/振幅由收盘价推算，换手率缺失"""
        market = 'sh' if stock_code.startswith('6') else 'sz'
        param = f'{market}{stock_code},day,1990-01-01,{datetime.now().strftime("%Y-%m-%d")},{days},qfq'

        try:
            r = self.session.get(TENCENT_KLINE_URL, params={'param': param}, timeout=self.timeout)
            j = r.json()
            node = (j.get('data') or {}).get(f'{market}{stock_code}') or {}
            rows = node.get('qfqday') or node.get('day') or []
        except Exception as e:
            print(f'  腾讯K线获取失败({stock_code}): {type(e).__name__}')
            return None

        if not rows:
            return None

        out = []
        prev_close = None
        for row in rows[-days:]:
            date, op, cl, hi, lo, vol = row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
            chg = ((cl - prev_close) / prev_close * 100) if prev_close else 0.0
            out.append({
                '日期': str(date),
                '开盘': op,
                '收盘': cl,
                '最高': hi,
                '最低': lo,
                '成交量': vol,
                '成交额': float('nan'),
                '振幅': (hi - lo) / prev_close * 100 if prev_close else 0.0,
                '涨跌幅': chg,
                '涨跌额': cl - prev_close if prev_close else 0.0,
                '换手率': float('nan'),
            })
            prev_close = cl
        return pd.DataFrame(out)

    # ---------------- 内部 ----------------

    def _first_ok_host(self, hosts, probe_path='/api/qt/clist/get', probe_params=None):
        """探测第一个可用的主机；K线主机需用其自身接口探测（clist 接口它不支持）"""
        if probe_params is None:
            probe_params = {'pn': '1', 'pz': '1', 'fs': 'm:0+t:6', 'fields': 'f12'}
        for host in hosts:
            try:
                r = self.session.get(
                    f'http://{host}{probe_path}',
                    params=probe_params,
                    timeout=8)
                if r.status_code == 200 and r.text:
                    return host
            except Exception:
                continue
        return None

    def _detect_page_size(self, host):
        """
        不同镜像的单页上限不同（标准主机 1000/页，延时镜像 100/页）。
        以首页返回条数判断：明显小于 200 视为受限镜像，统一用 100 分页。
        """
        try:
            r = self.session.get(
                f'http://{host}/api/qt/clist/get',
                params={'pn': '1', 'pz': '1000', 'fs': 'm:0+t:6', 'fields': 'f12'},
                timeout=8)
            diff = (r.json().get('data') or {}).get('diff') or []
            return 100 if len(diff) < 200 else 1000
        except Exception:
            return 1000

    def _get_json(self, url, params):
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f'  网络错误: {e}')
        return None