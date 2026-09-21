#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富股票数据获取与分析报告生成器
从东方财富API获取股票数据,生成技术分析报告
"""

import requests
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
import re
import time


class EastMoneyStockAnalyzer:
    """东方财富股票分析器"""

    def __init__(self, stock_code: str):
        """
        初始化分析器
        :param stock_code: 股票代码,如 '600519' 或 '000001'
        """
        self.stock_code = stock_code
        self.secid = self._get_secid()
        self.base_url = "http://push2.eastmoney.com/api/qt"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'close',  # 关键:每次请求后关闭连接
            'Referer': 'http://quote.eastmoney.com/'
        }

    def _get_secid(self) -> str:
        """获取secid (0.深圳 1.上海)"""
        if self.stock_code.startswith('6'):
            return f"1.{self.stock_code}"
        else:
            return f"0.{self.stock_code}"

    def _request_with_retry(self, url: str, params: dict, max_retries: int = 3) -> dict:
        """带重试的请求,每次创建新连接"""
        for attempt in range(max_retries):
            try:
                # 每次都创建新请求,避免连接复用问题
                response = requests.get(url, params=params, headers=self.headers, timeout=15)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"请求失败，{wait_time}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    raise e

    def get_realtime_quote(self) -> Dict:
        """获取实时行情数据"""
        url = f"{self.base_url}/stock/get"
        params = {
            'secid': self.secid,
            'fields': 'f57,f58,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f60,f107,f137,f162,f168,f169,f170,f171,f152,f116,f117,f85'
        }

        try:
            result = self._request_with_retry(url, params)
            data = result.get('data', {})

            if not data:
                print("警告: 未获取到实时行情数据")
                return {}

            return {
                '股票代码': data.get('f57', ''),
                '股票名称': data.get('f58', ''),
                '最新价': data.get('f43', 0) / 100 if data.get('f43') else 0,
                '涨跌额': data.get('f169', 0) / 100 if data.get('f169') else 0,
                '涨跌幅': data.get('f170', 0) / 100 if data.get('f170') else 0,
                '今开': data.get('f46', 0) / 100 if data.get('f46') else 0,
                '昨收': data.get('f60', 0) / 100 if data.get('f60') else 0,
                '最高': data.get('f44', 0) / 100 if data.get('f44') else 0,
                '最低': data.get('f45', 0) / 100 if data.get('f45') else 0,
                '成交量': data.get('f47', 0),
                '成交额': data.get('f48', 0),
                '外盘': data.get('f49', 0),
                '内盘': max(data.get('f47', 0) - data.get('f49', 0), 0),
                '涨停价': data.get('f51', 0) / 100 if data.get('f51') else 0,
                '跌停价': data.get('f52', 0) / 100 if data.get('f52') else 0,
                '换手率': data.get('f168', 0) / 100 if data.get('f168') else 0,
                '振幅': data.get('f171', 0) / 100 if data.get('f171') else 0,
                '量比': data.get('f50', 0) / 100 if data.get('f50') else 0,
                '市盈率': data.get('f162', 0) / 100 if data.get('f162') else 0,
                '市净率': data.get('f167', 0) / 100 if data.get('f167') else 0,
                '总市值': data.get('f116', 0) / 100000000 if data.get('f116') else 0,
                '流通市值': data.get('f117', 0) / 100000000 if data.get('f117') else 0,
            }
        except Exception as e:
            print(f"获取实时行情失败: {e}")
            return {}

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        url = f"{self.base_url}/stock/get"
        params = {
            'secid': self.secid,
            'fields': 'f57,f58,f100,f127'
        }

        try:
            result = self._request_with_retry(url, params)
            data = result.get('data', {})

            if not data:
                print("警告: 未获取到股票基本信息")
                return {
                    '股票代码': self.stock_code,
                    '股票名称': self.stock_code,
                    '所属行业': '未知',
                    '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
                }

            return {
                '股票代码': self.stock_code,
                '股票名称': data.get('f58', ''),
                '所属行业': data.get('f127', ''),
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }
        except Exception as e:
            print(f"获取股票信息失败: {e}")
            return {
                '股票代码': self.stock_code,
                '股票名称': self.stock_code,
                '所属行业': '未知',
                '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
            }

    def get_kline_data(self, days: int = 60) -> pd.DataFrame:
        """
        获取K线数据
        :param days: 获取天数
        :return: DataFrame
        """
        url = f"{self.base_url}/stock/kline/get"
        params = {
            'secid': self.secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',  # 日K
            'fqt': '1',    # 前复权
            'lmt': str(days),
            'end': '20500101'
        }

        try:
            result = self._request_with_retry(url, params)
            data = result.get('data', {})

            if not data or 'klines' not in data:
                print("错误: 未获取到K线数据,可能股票代码不正确或停牌")
                return pd.DataFrame()

            klines = []
            for line in data['klines']:
                items = line.split(',')
                klines.append({
                    '日期': items[0],
                    '开盘': float(items[1]),
                    '收盘': float(items[2]),
                    '最高': float(items[3]),
                    '最低': float(items[4]),
                    '成交量': float(items[5]),
                    '成交额': float(items[6]),
                    '振幅': float(items[7]),
                    '涨跌幅': float(items[8]),
                    '涨跌额': float(items[9]),
                    '换手率': float(items[10])
                })

            df = pd.DataFrame(klines)
            df['日期'] = pd.to_datetime(df['日期'])
            print(f"✓ 成功获取 {len(df)} 天的K线数据")
            return df

        except Exception as e:
            print(f"获取K线数据失败: {e}")
            return pd.DataFrame()

    def calculate_ma(self, df: pd.DataFrame, periods: List[int]) -> pd.DataFrame:
        """计算移动平均线"""
        for period in periods:
            df[f'MA{period}'] = df['收盘'].rolling(window=period).mean()
        return df

    def calculate_macd(self, df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
        """计算MACD指标"""
        ema_fast = df['收盘'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['收盘'].ewm(span=slow, adjust=False).mean()
        df['MACD_DIF'] = ema_fast - ema_slow
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=signal, adjust=False).mean()
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2
        return df

    def calculate_kdj(self, df: pd.DataFrame, n=9, m1=3, m2=3) -> pd.DataFrame:
        """计算KDJ指标"""
        low_list = df['最低'].rolling(window=n, min_periods=1).min()
        high_list = df['最高'].rolling(window=n, min_periods=1).max()

        rsv = (df['收盘'] - low_list) / (high_list - low_list) * 100
        rsv = rsv.fillna(0)

        df['KDJ_K'] = rsv.ewm(com=m1-1, adjust=False).mean()
        df['KDJ_D'] = df['KDJ_K'].ewm(com=m2-1, adjust=False).mean()
        df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']

        return df

    def calculate_rsi(self, df: pd.DataFrame, periods=[6, 12, 24]) -> pd.DataFrame:
        """计算RSI指标"""
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

        is_multi = all(ma_list[i][1] > ma_list[i+1][1] for i in range(len(ma_list)-1) if ma_list[i][1] > 0 and ma_list[i+1][1] > 0)
        is_bear = all(ma_list[i][1] < ma_list[i+1][1] for i in range(len(ma_list)-1) if ma_list[i][1] > 0 and ma_list[i+1][1] > 0)

        if is_multi:
            trend = "多头排列,趋势向上"
        elif is_bear:
            trend = "空头排列,趋势向下"
        else:
            trend = "均线纠缠,趋势不明"

        # MACD分析
        macd_signal = "金叉" if latest['MACD_DIF'] > latest['MACD_DEA'] else "死叉"
        macd_status = "看多" if latest['MACD_BAR'] > 0 else "看空"

        # KDJ分析
        kdj_k = latest['KDJ_K']
        if kdj_k > 80:
            kdj_status = "超买"
        elif kdj_k < 20:
            kdj_status = "超卖"
        else:
            kdj_status = "正常"

        # RSI分析
        rsi6 = latest.get('RSI6', 50)
        if rsi6 > 70:
            rsi_status = "超买"
        elif rsi6 < 30:
            rsi_status = "超卖"
        else:
            rsi_status = "正常"

        # BOLL分析
        boll_upper = latest['BOLL_UPPER']
        boll_lower = latest['BOLL_LOWER']
        if close > boll_upper:
            boll_position = "上轨上方"
        elif close < boll_lower:
            boll_position = "下轨下方"
        else:
            boll_position = "轨道内"

        return {
            'trend': trend,
            'macd_signal': macd_signal,
            'macd_status': macd_status,
            'kdj_status': kdj_status,
            'rsi_status': rsi_status,
            'boll_position': boll_position
        }

    def calculate_support_resistance(self, df: pd.DataFrame) -> Dict:
        """计算支撑位和压力位"""
        recent = df.tail(20)

        # 使用最近的高低点作为压力和支撑
        highs = recent['最高'].nlargest(3).tolist()
        lows = recent['最低'].nsmallest(3).tolist()

        # MA线作为动态支撑压力
        latest = df.iloc[-1]
        ma_values = [latest.get('MA5', 0), latest.get('MA10', 0),
                     latest.get('MA20', 0), latest.get('MA60', 0)]

        close = latest['收盘']
        resistances = sorted([h for h in highs if h > close])[:3]
        supports = sorted([l for l in lows if l < close], reverse=True)[:3]

        # 补充均线支撑压力
        resistances.extend([ma for ma in ma_values if ma > close])
        supports.extend([ma for ma in ma_values if 0 < ma < close])

        resistances = sorted(set(resistances))[:3]
        supports = sorted(set(supports), reverse=True)[:3]

        return {
            'resistances': resistances if resistances else [close * 1.05],
            'supports': supports if supports else [close * 0.95]
        }

    def generate_report(self, template_path: str, output_path: str):
        """生成分析报告"""
        print("正在获取股票数据...")

        # 获取基础信息
        stock_info = self.get_stock_info()
        realtime = self.get_realtime_quote()

        # 获取历史数据
        df = self.get_kline_data(days=60)
        if df.empty:
            print("无法获取K线数据")
            return

        # 计算技术指标
        df = self.calculate_ma(df, [5, 10, 20, 60])
        df = self.calculate_macd(df)
        df = self.calculate_kdj(df)
        df = self.calculate_rsi(df)
        df = self.calculate_boll(df)

        # 分析
        analysis = self.analyze_trend(df)
        sr = self.calculate_support_resistance(df)

        # 获取近10日数据
        recent_10 = df.tail(10)

        # 读取模板
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()

        # 填充模板
        latest = df.iloc[-1]
        report = template

        # 基本信息
        report = report.replace('{{股票代码}}', stock_info.get('股票代码', self.stock_code))
        report = report.replace('{{股票名称}}', stock_info.get('股票名称', ''))
        report = report.replace('{{所属行业}}', stock_info.get('所属行业', ''))
        report = report.replace('{{交易所}}', stock_info.get('交易所', ''))
        report = report.replace('{{报告日期}}', datetime.now().strftime('%Y-%m-%d'))
        report = report.replace('{{最新日期}}', latest['日期'].strftime('%Y-%m-%d'))

        # 实时行情
        report = report.replace('{{最新价}}', f"{realtime.get('最新价', 0):.2f}")
        report = report.replace('{{涨跌额}}', f"{realtime.get('涨跌额', 0):.2f}")
        report = report.replace('{{涨跌幅}}', f"{realtime.get('涨跌幅', 0):.2f}")
        report = report.replace('{{今开}}', f"{realtime.get('今开', 0):.2f}")
        report = report.replace('{{昨收}}', f"{realtime.get('昨收', 0):.2f}")
        report = report.replace('{{最高}}', f"{realtime.get('最高', 0):.2f}")
        report = report.replace('{{最低}}', f"{realtime.get('最低', 0):.2f}")
        report = report.replace('{{成交量}}', f"{realtime.get('成交量', 0):,.0f}")
        report = report.replace('{{成交额}}', f"{realtime.get('成交额', 0)/10000:.2f}")
        report = report.replace('{{外盘}}', f"{realtime.get('外盘', 0):.0f}")
        report = report.replace('{{内盘}}', f"{realtime.get('内盘', 0):.0f}")
        report = report.replace('{{涨停价}}', f"{realtime.get('涨停价', 0):.2f}")
        report = report.replace('{{跌停价}}', f"{realtime.get('跌停价', 0):.2f}")
        report = report.replace('{{换手率}}', f"{realtime.get('换手率', 0):.2f}")
        report = report.replace('{{振幅}}', f"{realtime.get('振幅', 0):.2f}")
        report = report.replace('{{量比}}', f"{realtime.get('量比', 0):.2f}")
        report = report.replace('{{市盈率}}', f"{realtime.get('市盈率', 0):.2f}")
        report = report.replace('{{市净率}}', f"{realtime.get('市净率', 0):.2f}")
        report = report.replace('{{总市值}}', f"{realtime.get('总市值', 0):.2f}")
        report = report.replace('{{流通市值}}', f"{realtime.get('流通市值', 0):.2f}")

        # 近10日数据表格
        recent_table = ""
        for _, row in recent_10.iterrows():
            recent_table += f"| {row['日期'].strftime('%Y-%m-%d')} | {row['开盘']:.2f} | {row['最高']:.2f} | {row['最低']:.2f} | {row['收盘']:.2f} | {row['涨跌幅']:.2f} | {row['成交量']/10000:.2f} | {row['成交额']/10000:.2f} | {row['换手率']:.2f} | {row['振幅']:.2f} |\n"
        report = report.replace('{{近10日数据}}', recent_table)

        # 区间统计
        report = report.replace('{{期间最高}}', f"{recent_10['最高'].max():.2f}")
        report = report.replace('{{期间最低}}', f"{recent_10['最低'].min():.2f}")
        period_change = ((recent_10.iloc[-1]['收盘'] - recent_10.iloc[0]['收盘']) / recent_10.iloc[0]['收盘'] * 100)
        report = report.replace('{{期间涨跌幅}}', f"{period_change:.2f}")
        report = report.replace('{{平均换手率}}', f"{recent_10['换手率'].mean():.2f}")
        report = report.replace('{{总成交量}}', f"{recent_10['成交量'].sum()/10000:.2f}")
        report = report.replace('{{总成交额}}', f"{recent_10['成交额'].sum()/100000000:.2f}")
        report = report.replace('{{平均振幅}}', f"{recent_10['振幅'].mean():.2f}")

        # 技术指标
        report = report.replace('{{MA5}}', f"{latest.get('MA5', 0):.2f}")
        report = report.replace('{{MA10}}', f"{latest.get('MA10', 0):.2f}")
        report = report.replace('{{MA20}}', f"{latest.get('MA20', 0):.2f}")
        report = report.replace('{{MA60}}', f"{latest.get('MA60', 0):.2f}")

        close = latest['收盘']
        report = report.replace('{{MA5位置}}', "上方" if close > latest.get('MA5', 0) else "下方")
        report = report.replace('{{MA10位置}}', "上方" if close > latest.get('MA10', 0) else "下方")
        report = report.replace('{{MA20位置}}', "上方" if close > latest.get('MA20', 0) else "下方")
        report = report.replace('{{MA60位置}}', "上方" if close > latest.get('MA60', 0) else "下方")

        report = report.replace('{{均线排列}}', analysis['trend'])
        report = report.replace('{{趋势判断}}', analysis['trend'])

        # MACD
        report = report.replace('{{MACD_DIF}}', f"{latest['MACD_DIF']:.4f}")
        report = report.replace('{{MACD_DEA}}', f"{latest['MACD_DEA']:.4f}")
        report = report.replace('{{MACD_BAR}}', f"{latest['MACD_BAR']:.4f}")
        report = report.replace('{{MACD信号}}', analysis['macd_signal'])
        report = report.replace('{{MACD分析}}', f"当前处于{analysis['macd_signal']}状态,{analysis['macd_status']}")

        # KDJ
        report = report.replace('{{KDJ_K}}', f"{latest['KDJ_K']:.2f}")
        report = report.replace('{{KDJ_D}}', f"{latest['KDJ_D']:.2f}")
        report = report.replace('{{KDJ_J}}', f"{latest['KDJ_J']:.2f}")
        report = report.replace('{{KDJ状态}}', analysis['kdj_status'])
        report = report.replace('{{KDJ分析}}', f"KDJ指标显示{analysis['kdj_status']}状态")

        # RSI
        report = report.replace('{{RSI6}}', f"{latest.get('RSI6', 0):.2f}")
        report = report.replace('{{RSI12}}', f"{latest.get('RSI12', 0):.2f}")
        report = report.replace('{{RSI24}}', f"{latest.get('RSI24', 0):.2f}")
        report = report.replace('{{RSI状态}}', analysis['rsi_status'])
        report = report.replace('{{RSI分析}}', f"RSI指标显示{analysis['rsi_status']}状态")

        # BOLL
        report = report.replace('{{BOLL_UPPER}}', f"{latest['BOLL_UPPER']:.2f}")
        report = report.replace('{{BOLL_MID}}', f"{latest['BOLL_MID']:.2f}")
        report = report.replace('{{BOLL_LOWER}}', f"{latest['BOLL_LOWER']:.2f}")
        report = report.replace('{{当前价}}', f"{close:.2f}")
        report = report.replace('{{带宽}}', f"{latest['BOLL_WIDTH']:.2f}")
        report = report.replace('{{BOLL位置}}', analysis['boll_position'])
        report = report.replace('{{BOLL分析}}', f"股价位于布林带{analysis['boll_position']}")

        # 量能分析
        vol_change = "放量" if recent_10.iloc[-1]['成交量'] > recent_10['成交量'].mean() else "缩量"
        report = report.replace('{{量能变化}}', vol_change)

        price_up = recent_10.iloc[-1]['涨跌幅'] > 0
        vol_up = recent_10.iloc[-1]['成交量'] > recent_10.iloc[-2]['成交量']
        if price_up and vol_up:
            vol_price = "量价齐升"
        elif not price_up and not vol_up:
            vol_price = "量价齐跌"
        elif price_up and not vol_up:
            vol_price = "价升量缩"
        else:
            vol_price = "价跌量增"
        report = report.replace('{{量价关系}}', vol_price)

        turnover = recent_10['换手率'].mean()
        if turnover > 5:
            turnover_level = "活跃"
        elif turnover > 2:
            turnover_level = "正常"
        else:
            turnover_level = "低迷"
        report = report.replace('{{换手率水平}}', turnover_level)
        report = report.replace('{{成交量趋势分析}}', f"近期成交量{vol_change},换手率{turnover_level},反映市场参与度{turnover_level}")

        # 评分系统
        trend_score = 8 if "多头" in analysis['trend'] else (3 if "空头" in analysis['trend'] else 5)
        multi_score = 7 if analysis['macd_status'] == "看多" else 3
        active_score = int(turnover * 2) if turnover < 5 else 10
        resonance_score = sum([1 for x in [analysis['macd_status'], analysis['kdj_status'], analysis['rsi_status']] if "看多" in x or "超卖" in x]) * 2 + 2
        momentum_score = 8 if vol_price == "量价齐升" else (3 if vol_price == "量价齐跌" else 5)

        report = report.replace('{{趋势评分}}', str(trend_score))
        report = report.replace('{{趋势说明}}', analysis['trend'])
        report = report.replace('{{多空评分}}', str(multi_score))
        report = report.replace('{{多空说明}}', analysis['macd_status'])
        report = report.replace('{{活跃评分}}', str(active_score))
        report = report.replace('{{活跃说明}}', f"换手率{turnover:.2f}%")
        report = report.replace('{{共振评分}}', str(resonance_score))
        report = report.replace('{{共振说明}}', "多指标共振")
        report = report.replace('{{动能评分}}', str(momentum_score))
        report = report.replace('{{动能说明}}', vol_price)
        report = report.replace('{{综合评分}}', str(trend_score + multi_score + active_score + resonance_score + momentum_score))

        # 支撑压力位
        resistances = sr['resistances']
        supports = sr['supports']

        report = report.replace('{{强压力}}', f"{resistances[0]:.2f}" if len(resistances) > 0 else f"{close*1.05:.2f}")
        report = report.replace('{{强压力依据}}', "前期高点")
        report = report.replace('{{次压力}}', f"{resistances[1]:.2f}" if len(resistances) > 1 else f"{close*1.03:.2f}")
        report = report.replace('{{次压力依据}}', "均线压力")
        report = report.replace('{{弱压力}}', f"{resistances[2]:.2f}" if len(resistances) > 2 else f"{close*1.02:.2f}")
        report = report.replace('{{弱压力依据}}', "技术压力")

        report = report.replace('{{强支撑}}', f"{supports[0]:.2f}" if len(supports) > 0 else f"{close*0.95:.2f}")
        report = report.replace('{{强支撑依据}}', "前期低点")
        report = report.replace('{{次支撑}}', f"{supports[1]:.2f}" if len(supports) > 1 else f"{close*0.97:.2f}")
        report = report.replace('{{次支撑依据}}', "均线支撑")
        report = report.replace('{{弱支撑}}', f"{supports[2]:.2f}" if len(supports) > 2 else f"{close*0.98:.2f}")
        report = report.replace('{{弱支撑依据}}', "技术支撑")

        # 操作建议
        is_bullish = trend_score >= 6 and multi_score >= 5
        is_bearish = trend_score <= 4 and multi_score <= 4

        if is_bullish:
            short_direction = "看多,可适量做多"
            short_reason = "技术指标偏多,短期趋势向上"
            short_buy = f"{close * 0.98:.2f}"
            short_stop = f"{supports[0] if supports else close * 0.95:.2f}"
            short_target = f"{resistances[0] if resistances else close * 1.05:.2f}"

            mid_direction = "持有观察"
            mid_reason = "中期趋势需观察均线支撑"
            mid_watch = f"{latest.get('MA20', close):.2f}"
            mid_stop = f"{latest.get('MA60', close * 0.90):.2f}"
            mid_target = f"{close * 1.10:.2f}"
        elif is_bearish:
            short_direction = "看空,建议观望"
            short_reason = "技术指标偏空,短期趋势向下"
            short_buy = "等待企稳信号"
            short_stop = f"{close * 1.03:.2f}"
            short_target = "暂不建议"

            mid_direction = "观望为主"
            mid_reason = "中期趋势偏弱,等待转势信号"
            mid_watch = f"{supports[0] if supports else close * 0.95:.2f}"
            mid_stop = f"{close * 1.05:.2f}"
            mid_target = "暂不建议"
        else:
            short_direction = "震荡,短线为主"
            short_reason = "技术指标混杂,建议区间操作"
            short_buy = f"{supports[0] if supports else close * 0.98:.2f}"
            short_stop = f"{close * 0.95:.2f}"
            short_target = f"{resistances[0] if resistances else close * 1.03:.2f}"

            mid_direction = "观望为主"
            mid_reason = "趋势不明,等待方向选择"
            mid_watch = f"{close:.2f}"
            mid_stop = f"{close * 0.92:.2f}"
            mid_target = f"{close * 1.08:.2f}"

        report = report.replace('{{短线方向}}', short_direction)
        report = report.replace('{{短线理由}}', short_reason)
        report = report.replace('{{短线买入价}}', short_buy)
        report = report.replace('{{短线止损}}', short_stop)
        report = report.replace('{{短线目标}}', short_target)

        report = report.replace('{{中线方向}}', mid_direction)
        report = report.replace('{{中线理由}}', mid_reason)
        report = report.replace('{{中线关注}}', mid_watch)
        report = report.replace('{{中线止损}}', mid_stop)
        report = report.replace('{{中线目标}}', mid_target)

        # 风险提示
        risk_items = []
        if analysis['kdj_status'] == "超买" or analysis['rsi_status'] == "超买":
            risk_items.append("- 技术指标显示超买,短期存在回调风险")
        if vol_change == "缩量" and price_up:
            risk_items.append("- 价升量缩,上涨动能不足")
        if "空头" in analysis['trend']:
            risk_items.append("- 均线空头排列,趋势偏弱")
        if not risk_items:
            risk_items.append("- 请注意市场整体风险")
            risk_items.append("- 注意控制仓位,设置止损")

        report = report.replace('{{风险提示}}', '\n'.join(risk_items))

        # 时间信息
        report = report.replace('{{数据时间}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        report = report.replace('{{生成时间}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # 保存报告
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"分析报告已生成: {output_path}")


def main():
    """主函数"""
    import sys
    import os

    # 支持命令行参数或交互式输入
    if len(sys.argv) >= 2:
        stock_code = sys.argv[1]
    else:
        print("=" * 60)
        print("          东方财富股票技术分析报告生成器")
        print("=" * 60)
        print("\n常见股票代码示例:")
        print("  600519 - 贵州茅台")
        print("  000001 - 平安银行")
        print("  600036 - 招商银行")
        print("  000858 - 五粮液")
        print("  601318 - 中国平安")
        print("-" * 60)

        stock_code = input("\n请输入股票代码 (6位数字): ").strip()

        if not stock_code:
            print("错误: 股票代码不能为空")
            sys.exit(1)

        if not stock_code.isdigit() or len(stock_code) != 6:
            print("错误: 股票代码必须是6位数字")
            sys.exit(1)

    # 默认模板路径
    template_path = r"E:\trading\操作手册\stock_analysis_template.md"

    # 默认输出路径
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        output_dir = r"E:\trading\reports"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{stock_code}_{datetime.now().strftime('%Y%m%d')}.md")

    print(f"\n开始分析股票: {stock_code}")
    print(f"报告将保存至: {output_path}\n")

    # 创建分析器并生成报告
    try:
        analyzer = EastMoneyStockAnalyzer(stock_code)
        analyzer.generate_report(template_path, output_path)
        print(f"\n✓ 分析完成!")
        print(f"✓ 报告路径: {output_path}")
    except Exception as e:
        print(f"\n✗ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
