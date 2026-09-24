#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票技术分析报告生成器
使用东方财富多主机容灾 + 腾讯财经备用通道
参考 stock_selector 的 EastMoneyClient 实现
"""

import time
from datetime import datetime
import pandas as pd
import numpy as np
from typing import Dict, List
import requests
import sys
import os


# 东方财富多主机容灾 (根据网络环境调整优先级)
CLIST_HOSTS = [
    'push2delay.eastmoney.com',   # 延时行情镜像,当前网络环境可达
    '82.push2.eastmoney.com',
    'push2.eastmoney.com',
]
KLINE_HOSTS = [
    'push2his.eastmoney.com',
    '16.push2his.eastmoney.com',
]
TENCENT_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'


class StockDataClient:
    """股票数据客户端 - 多主机容灾"""

    def __init__(self, timeout=15):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.timeout = timeout

    def _first_ok_host(self, hosts, probe_path='/api/qt/clist/get', probe_params=None):
        """探测第一个可用的主机"""
        if probe_params is None:
            probe_params = {'pn': '1', 'pz': '1', 'fs': 'm:0+t:6', 'fields': 'f12'}
        for host in hosts:
            try:
                r = self.session.get(
                    f'http://{host}{probe_path}',
                    params=probe_params,
                    timeout=8)
                if r.status_code == 200 and r.text:
                    print(f"OK 使用主机: {host}")
                    return host
            except Exception:
                continue
        return None

    def _get_json(self, url, params):
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"  请求失败: {e}")
        return None

    def get_realtime_quote(self, stock_code: str) -> Dict:
        """获取实时行情"""
        host = self._first_ok_host(CLIST_HOSTS)
        if host is None:
            print('  所有东方财富主机均不可达')
            return {}

        # 构造查询
        secid = f'1.{stock_code}' if stock_code.startswith('6') else f'0.{stock_code}'
        params = {
            'secid': secid,
            'fields': 'f57,f58,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f60,f152,f168,f169,f170,f171,f162,f167,f116,f117'
        }

        data = self._get_json(f'http://{host}/api/qt/stock/get', params)
        if not data or 'data' not in data:
            return {}

        d = data['data']
        return {
            '股票代码': stock_code,
            '股票名称': d.get('f58', ''),
            '最新价': d.get('f43', 0) / 100,
            '涨跌额': d.get('f169', 0) / 100,
            '涨跌幅': d.get('f170', 0) / 100,
            '今开': d.get('f46', 0) / 100,
            '昨收': d.get('f60', 0) / 100,
            '最高': d.get('f44', 0) / 100,
            '最低': d.get('f45', 0) / 100,
            '成交量': d.get('f47', 0),
            '成交额': d.get('f48', 0),
            '外盘': d.get('f49', 0),
            '内盘': max(d.get('f47', 0) - d.get('f49', 0), 0),
            '涨停价': d.get('f51', 0) / 100,
            '跌停价': d.get('f52', 0) / 100,
            '换手率': d.get('f168', 0) / 100,
            '振幅': d.get('f171', 0) / 100,
            '量比': d.get('f50', 0) / 100,
            '市盈率': d.get('f162', 0) / 100,
            '市净率': d.get('f167', 0) / 100,
            '总市值': d.get('f116', 0) / 100000000,
            '流通市值': d.get('f117', 0) / 100000000,
        }

    def get_kline_data(self, stock_code: str, days: int = 60) -> pd.DataFrame:
        """获取K线历史数据 - 东财优先,腾讯备用"""
        print(f"正在获取 {stock_code} 的K线数据...")

        df = self._eastmoney_kline(stock_code, days)
        if df is None or df.empty:
            print("  东财K线不可达,切换到腾讯财经...")
            df = self._tencent_kline(stock_code, days)

        if df is None or df.empty:
            print("  ERROR K线数据获取失败")
            return pd.DataFrame()

        print(f"  OK 成功获取 {len(df)} 天K线数据")
        return df

    def _eastmoney_kline(self, stock_code, days) -> pd.DataFrame:
        """东方财富K线"""
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
        """腾讯财经K线 - 备用通道"""
        market = 'sh' if stock_code.startswith('6') else 'sz'
        param = f'{market}{stock_code},day,1990-01-01,{datetime.now().strftime("%Y-%m-%d")},{days},qfq'

        try:
            r = self.session.get(TENCENT_KLINE_URL, params={'param': param}, timeout=self.timeout)
            j = r.json()
            node = (j.get('data') or {}).get(f'{market}{stock_code}') or {}
            rows = node.get('qfqday') or node.get('day') or []
        except Exception as e:
            print(f'  腾讯K线获取失败: {type(e).__name__}')
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
                # 腾讯 qfqday 不返回成交额，用均价×成交量估算（成交量单位为手=100股）
                '成交额': (hi + lo + cl) / 3 * vol * 100,
                '振幅': (hi - lo) / prev_close * 100 if prev_close else 0.0,
                '涨跌幅': chg,
                '涨跌额': cl - prev_close if prev_close else 0.0,
                '换手率': float('nan'),  # 缺流通股本，无法计算
            })
            prev_close = cl
        return pd.DataFrame(out)


class StockAnalyzer:
    """股票技术分析器"""

    def __init__(self, stock_code: str):
        self.stock_code = stock_code
        self.client = StockDataClient()

    def calculate_ma(self, df: pd.DataFrame, periods: List[int]) -> pd.DataFrame:
        """计算移动平均线"""
        for period in periods:
            df[f'MA{period}'] = df['收盘'].rolling(window=period).mean()
        return df

    def calculate_macd(self, df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
        """计算MACD"""
        ema_fast = df['收盘'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['收盘'].ewm(span=slow, adjust=False).mean()
        df['MACD_DIF'] = ema_fast - ema_slow
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=signal, adjust=False).mean()
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2
        return df

    def calculate_kdj(self, df: pd.DataFrame, n=9, m1=3, m2=3) -> pd.DataFrame:
        """计算KDJ"""
        low_list = df['最低'].rolling(window=n, min_periods=1).min()
        high_list = df['最高'].rolling(window=n, min_periods=1).max()
        rsv = (df['收盘'] - low_list) / (high_list - low_list) * 100
        rsv = rsv.fillna(0)
        df['KDJ_K'] = rsv.ewm(com=m1-1, adjust=False).mean()
        df['KDJ_D'] = df['KDJ_K'].ewm(com=m2-1, adjust=False).mean()
        df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']
        return df

    def calculate_rsi(self, df: pd.DataFrame, periods=[6, 12, 24]) -> pd.DataFrame:
        """计算RSI"""
        for period in periods:
            delta = df['收盘'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            df[f'RSI{period}'] = 100 - (100 / (1 + rs))
        return df

    def calculate_boll(self, df: pd.DataFrame, n=20, k=2) -> pd.DataFrame:
        """计算布林带"""
        df['BOLL_MID'] = df['收盘'].rolling(window=n).mean()
        std = df['收盘'].rolling(window=n).std()
        df['BOLL_UPPER'] = df['BOLL_MID'] + k * std
        df['BOLL_LOWER'] = df['BOLL_MID'] - k * std
        df['BOLL_WIDTH'] = ((df['BOLL_UPPER'] - df['BOLL_LOWER']) / df['BOLL_MID'] * 100)
        return df

    def analyze_trend(self, df: pd.DataFrame) -> Dict:
        """趋势分析"""
        latest = df.iloc[-1]
        close = latest['收盘']

        # 均线排列
        ma_list = [(5, latest.get('MA5', 0)), (10, latest.get('MA10', 0)),
                   (20, latest.get('MA20', 0)), (60, latest.get('MA60', 0))]
        is_multi = all(ma_list[i][1] > ma_list[i+1][1] for i in range(len(ma_list)-1)
                      if ma_list[i][1] > 0 and ma_list[i+1][1] > 0)
        is_bear = all(ma_list[i][1] < ma_list[i+1][1] for i in range(len(ma_list)-1)
                     if ma_list[i][1] > 0 and ma_list[i+1][1] > 0)

        trend = "多头排列,趋势向上" if is_multi else ("空头排列,趋势向下" if is_bear else "均线纠缠,趋势不明")
        macd_signal = "金叉" if latest['MACD_DIF'] > latest['MACD_DEA'] else "死叉"
        macd_status = "看多" if latest['MACD_BAR'] > 0 else "看空"

        kdj_k = latest['KDJ_K']
        kdj_status = "超买" if kdj_k > 80 else ("超卖" if kdj_k < 20 else "正常")

        rsi6 = latest.get('RSI6', 50)
        rsi_status = "超买" if rsi6 > 70 else ("超卖" if rsi6 < 30 else "正常")

        boll_upper, boll_lower = latest['BOLL_UPPER'], latest['BOLL_LOWER']
        boll_position = "上轨上方" if close > boll_upper else ("下轨下方" if close < boll_lower else "轨道内")

        return {
            'trend': trend, 'macd_signal': macd_signal, 'macd_status': macd_status,
            'kdj_status': kdj_status, 'rsi_status': rsi_status, 'boll_position': boll_position
        }

    def calculate_support_resistance(self, df: pd.DataFrame) -> Dict:
        """计算支撑压力位"""
        recent = df.tail(20)
        highs = recent['最高'].nlargest(3).tolist()
        lows = recent['最低'].nsmallest(3).tolist()

        latest = df.iloc[-1]
        close = latest['收盘']
        ma_values = [latest.get('MA5', 0), latest.get('MA10', 0),
                     latest.get('MA20', 0), latest.get('MA60', 0)]

        resistances = sorted([h for h in highs if h > close])[:3]
        supports = sorted([l for l in lows if l < close], reverse=True)[:3]

        resistances.extend([ma for ma in ma_values if ma > close])
        supports.extend([ma for ma in ma_values if 0 < ma < close])

        return {
            'resistances': sorted(set(resistances))[:3] or [close * 1.05],
            'supports': sorted(set(supports), reverse=True)[:3] or [close * 0.95]
        }

    def generate_report(self, template_path: str, output_path: str):
        """生成分析报告"""
        print("\n" + "=" * 60)
        print(f"  股票技术分析报告生成器")
        print("=" * 60)

        # 获取数据
        print(f"\n[1/3] 获取 {self.stock_code} 实时行情...")
        realtime = self.client.get_realtime_quote(self.stock_code)
        if not realtime:
            print("ERROR 无法获取实时行情数据")
            return

        stock_name = realtime.get('股票名称', self.stock_code)
        print(f"  OK {stock_name} ({self.stock_code})")

        print(f"\n[2/3] 获取历史K线数据...")
        df = self.client.get_kline_data(self.stock_code, days=60)
        if df.empty:
            print("ERROR 无法获取K线数据")
            return

        # 计算指标
        print(f"\n[3/3] 计算技术指标...")
        df = self.calculate_ma(df, [5, 10, 20, 60])
        df = self.calculate_macd(df)
        df = self.calculate_kdj(df)
        df = self.calculate_rsi(df)
        df = self.calculate_boll(df)
        print("  OK 技术指标计算完成")

        # 分析
        analysis = self.analyze_trend(df)
        sr = self.calculate_support_resistance(df)
        recent_10 = df.tail(10)
        latest = df.iloc[-1]

        # 读取模板并填充
        with open(template_path, 'r', encoding='utf-8') as f:
            report = f.read()

        # 基本信息
        report = report.replace('{{股票代码}}', self.stock_code)
        report = report.replace('{{股票名称}}', stock_name)
        report = report.replace('{{所属行业}}', '未知')
        report = report.replace('{{交易所}}', '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所')
        report = report.replace('{{报告日期}}', datetime.now().strftime('%Y-%m-%d'))
        report = report.replace('{{最新日期}}', datetime.now().strftime('%Y-%m-%d'))

        # 实时行情
        for k, v in realtime.items():
            if k in ['股票代码', '股票名称']:
                continue
            if not isinstance(v, (int, float)):
                continue
            if k in ('成交量', '外盘', '内盘'):
                text = f"{v:,.0f}"
            elif k == '成交额':
                text = f"{v / 10000:,.2f}"
            else:
                text = f"{v:.2f}"
            report = report.replace('{{' + k + '}}', text)

        # 近10日数据
        def fmt(v, scale=1.0, nd=2):
            """缺失值显示为 -，避免 nan 出现在报告里"""
            return '-' if pd.isna(v) else f"{v / scale:.{nd}f}"

        # 换手率兜底:东财备用通道若拿不到换手率,用 成交量/流通股本 推算
        # 流通股本 = 流通市值 / 昨收(或最新收盘)
        float_mktcap = float(realtime.get('流通市值', 0) or 0)
        float_shares = 0.0
        if float_mktcap > 0:
            base_price = float(realtime.get('昨收', 0) or latest['收盘'] or 0)
            float_shares = float_mktcap * 1e8 / base_price if base_price > 0 else 0.0

        def turnover_of(row):
            tr = row['换手率']
            if pd.notna(tr):
                return tr
            if float_shares > 0:
                return row['成交量'] * 100 / float_shares * 100
            return float('nan')

        recent_table = ""
        for _, row in recent_10.iterrows():
            recent_table += (
                f"| {row['日期']} | {row['开盘']:.2f} | {row['最高']:.2f} | {row['最低']:.2f} "
                f"| {row['收盘']:.2f} | {row['涨跌幅']:.2f} | {fmt(row['成交量'], 10000)} "
                f"| {fmt(row['成交额'], 10000)} | {fmt(turnover_of(row))} | {row['振幅']:.2f} |\n"
            )
        report = report.replace('{{近10日数据}}', recent_table)

        # 区间统计
        period_change = ((recent_10.iloc[-1]['收盘'] - recent_10.iloc[0]['收盘']) / recent_10.iloc[0]['收盘'] * 100)
        report = report.replace('{{期间最高}}', f"{recent_10['最高'].max():.2f}")
        report = report.replace('{{期间最低}}', f"{recent_10['最低'].min():.2f}")
        report = report.replace('{{期间涨跌幅}}', f"{period_change:.2f}")
        turnover_values = [turnover_of(row) for _, row in recent_10.iterrows()]
        report = report.replace('{{平均换手率}}', fmt(pd.Series(turnover_values).mean()))
        report = report.replace('{{总成交量}}', fmt(recent_10['成交量'].sum(), 10000))
        report = report.replace('{{总成交额}}', fmt(recent_10['成交额'].sum(), 100000000))
        report = report.replace('{{平均振幅}}', f"{recent_10['振幅'].mean():.2f}")

        # 技术指标
        close = latest['收盘']
        report = report.replace('{{MA5}}', f"{latest.get('MA5', 0):.2f}")
        report = report.replace('{{MA10}}', f"{latest.get('MA10', 0):.2f}")
        report = report.replace('{{MA20}}', f"{latest.get('MA20', 0):.2f}")
        report = report.replace('{{MA60}}', f"{latest.get('MA60', 0):.2f}")
        report = report.replace('{{MA5位置}}', "上方" if close > latest.get('MA5', 0) else "下方")
        report = report.replace('{{MA10位置}}', "上方" if close > latest.get('MA10', 0) else "下方")
        report = report.replace('{{MA20位置}}', "上方" if close > latest.get('MA20', 0) else "下方")
        report = report.replace('{{MA60位置}}', "上方" if close > latest.get('MA60', 0) else "下方")
        report = report.replace('{{均线排列}}', analysis['trend'])
        report = report.replace('{{趋势判断}}', analysis['trend'])

        # MACD/KDJ/RSI/BOLL
        report = report.replace('{{MACD_DIF}}', f"{latest['MACD_DIF']:.4f}")
        report = report.replace('{{MACD_DEA}}', f"{latest['MACD_DEA']:.4f}")
        report = report.replace('{{MACD_BAR}}', f"{latest['MACD_BAR']:.4f}")
        report = report.replace('{{MACD信号}}', analysis['macd_signal'])
        report = report.replace('{{MACD分析}}', f"当前处于{analysis['macd_signal']}状态,{analysis['macd_status']}")

        report = report.replace('{{KDJ_K}}', f"{latest['KDJ_K']:.2f}")
        report = report.replace('{{KDJ_D}}', f"{latest['KDJ_D']:.2f}")
        report = report.replace('{{KDJ_J}}', f"{latest['KDJ_J']:.2f}")
        report = report.replace('{{KDJ状态}}', analysis['kdj_status'])
        report = report.replace('{{KDJ分析}}', f"KDJ指标显示{analysis['kdj_status']}状态")

        report = report.replace('{{RSI6}}', f"{latest.get('RSI6', 0):.2f}")
        report = report.replace('{{RSI12}}', f"{latest.get('RSI12', 0):.2f}")
        report = report.replace('{{RSI24}}', f"{latest.get('RSI24', 0):.2f}")
        report = report.replace('{{RSI状态}}', analysis['rsi_status'])
        report = report.replace('{{RSI分析}}', f"RSI指标显示{analysis['rsi_status']}状态")

        report = report.replace('{{BOLL_UPPER}}', f"{latest['BOLL_UPPER']:.2f}")
        report = report.replace('{{BOLL_MID}}', f"{latest['BOLL_MID']:.2f}")
        report = report.replace('{{BOLL_LOWER}}', f"{latest['BOLL_LOWER']:.2f}")
        report = report.replace('{{当前价}}', f"{close:.2f}")
        report = report.replace('{{带宽}}', f"{latest['BOLL_WIDTH']:.2f}")
        report = report.replace('{{BOLL位置}}', analysis['boll_position'])
        report = report.replace('{{BOLL分析}}', f"股价位于布林带{analysis['boll_position']}")

        # 量能/评分/支撑压力/操作建议/风险提示 (简化版)
        vol_change = "放量" if recent_10.iloc[-1]['成交量'] > recent_10['成交量'].mean() else "缩量"
        report = report.replace('{{量能变化}}', vol_change)
        report = report.replace('{{量价关系}}', "量价齐升" if vol_change == "放量" and recent_10.iloc[-1]['涨跌幅'] > 0 else "量价背离")
        report = report.replace('{{换手率水平}}', "活跃" if recent_10['换手率'].mean() > 5 else "正常")
        report = report.replace('{{成交量趋势分析}}', f"近期成交量{vol_change}")

        trend_score = 8 if "多头" in analysis['trend'] else 3
        report = report.replace('{{趋势评分}}', str(trend_score))
        report = report.replace('{{趋势说明}}', analysis['trend'])
        report = report.replace('{{多空评分}}', "7" if analysis['macd_status'] == "看多" else "3")
        report = report.replace('{{多空说明}}', analysis['macd_status'])
        report = report.replace('{{活跃评分}}', "8")
        report = report.replace('{{活跃说明}}', "正常")
        report = report.replace('{{共振评分}}', "6")
        report = report.replace('{{共振说明}}', "多指标共振")
        report = report.replace('{{动能评分}}', str(trend_score))
        report = report.replace('{{动能说明}}', vol_change)
        report = report.replace('{{综合评分}}', str(trend_score * 5))

        # 支撑压力
        resistances, supports = sr['resistances'], sr['supports']
        report = report.replace('{{强压力}}', f"{resistances[0]:.2f}" if resistances else f"{close*1.05:.2f}")
        report = report.replace('{{强压力依据}}', "前期高点")
        report = report.replace('{{次压力}}', f"{resistances[1]:.2f}" if len(resistances) > 1 else f"{close*1.03:.2f}")
        report = report.replace('{{次压力依据}}', "均线压力")
        report = report.replace('{{弱压力}}', f"{resistances[2]:.2f}" if len(resistances) > 2 else f"{close*1.02:.2f}")
        report = report.replace('{{弱压力依据}}', "技术压力")

        report = report.replace('{{强支撑}}', f"{supports[0]:.2f}" if supports else f"{close*0.95:.2f}")
        report = report.replace('{{强支撑依据}}', "前期低点")
        report = report.replace('{{次支撑}}', f"{supports[1]:.2f}" if len(supports) > 1 else f"{close*0.97:.2f}")
        report = report.replace('{{次支撑依据}}', "均线支撑")
        report = report.replace('{{弱支撑}}', f"{supports[2]:.2f}" if len(supports) > 2 else f"{close*0.98:.2f}")
        report = report.replace('{{弱支撑依据}}', "技术支撑")

        # 操作建议
        is_bullish = trend_score >= 6
        short_direction = "看多,可适量做多" if is_bullish else "观望为主"
        report = report.replace('{{短线方向}}', short_direction)
        report = report.replace('{{短线理由}}', "技术指标偏多" if is_bullish else "趋势不明")
        report = report.replace('{{短线买入价}}', f"{close * 0.98:.2f}")
        report = report.replace('{{短线止损}}', f"{supports[0]:.2f}" if supports else f"{close*0.95:.2f}")
        report = report.replace('{{短线目标}}', f"{resistances[0]:.2f}" if resistances else f"{close*1.05:.2f}")
        report = report.replace('{{中线方向}}', "持有观察" if is_bullish else "观望")
        report = report.replace('{{中线理由}}', "中期趋势需观察")
        report = report.replace('{{中线关注}}', f"{latest.get('MA20', close):.2f}")
        report = report.replace('{{中线止损}}', f"{latest.get('MA60', close*0.9):.2f}")
        report = report.replace('{{中线目标}}', f"{close*1.1:.2f}")

        report = report.replace('{{风险提示}}', "- 请注意市场整体风险\n- 注意控制仓位,设置止损")
        report = report.replace('{{数据时间}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        report = report.replace('{{生成时间}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # 保存报告
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"\nOK 报告已生成: {output_path}")
        print("=" * 60 + "\n")


def main():
    """主函数"""
    print("=" * 60)
    print("     股票技术分析报告生成器 (多主机容灾版)")
    print("=" * 60)
    print("\n常见股票代码:")
    print("  600519 - 贵州茅台   600036 - 招商银行")
    print("  000001 - 平安银行   000858 - 五粮液")
    print("-" * 60)

    if len(sys.argv) >= 2:
        stock_code = sys.argv[1]
    else:
        stock_code = input("\n请输入股票代码 (6位数字): ").strip()

    if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
        print("错误: 股票代码必须是6位数字")
        sys.exit(1)

    template_path = r"E:\trading\操作手册\stock_analysis_template.md"
    output_dir = r"E:\trading\reports"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{stock_code}_{datetime.now().strftime('%Y%m%d')}.md")

    try:
        analyzer = StockAnalyzer(stock_code)
        analyzer.generate_report(template_path, output_path)
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
    except Exception as e:
        print(f"\nERROR 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
