#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据分析报告生成器 - CSV导入版本
适用于从任何来源导出的CSV数据
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List
import os


class CSVStockAnalyzer:
    """CSV数据股票分析器"""

    def __init__(self, csv_file: str, stock_code: str = None, stock_name: str = None):
        """
        初始化分析器
        :param csv_file: CSV文件路径
        :param stock_code: 股票代码(可选)
        :param stock_name: 股票名称(可选)
        """
        self.csv_file = csv_file
        self.stock_code = stock_code or "000000"
        self.stock_name = stock_name or "未知股票"
        self.df = None

    def load_data(self) -> bool:
        """
        加载CSV数据
        CSV格式要求:
        日期,开盘,收盘,最高,最低,成交量,成交额,涨跌幅,振幅,换手率
        """
        try:
            self.df = pd.read_csv(self.csv_file, encoding='utf-8-sig')

            # 检查必需列
            required_cols = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
            missing_cols = [col for col in required_cols if col not in self.df.columns]

            if missing_cols:
                print(f"CSV缺少必需列: {missing_cols}")
                print(f"当前列: {list(self.df.columns)}")
                return False

            # 转换日期
            self.df['日期'] = pd.to_datetime(self.df['日期'])

            # 转换数值类型
            for col in ['开盘', '收盘', '最高', '最低', '成交量']:
                self.df[col] = pd.to_numeric(self.df[col], errors='coerce')

            # 补充缺失列
            if '成交额' not in self.df.columns:
                self.df['成交额'] = 0
            if '涨跌幅' not in self.df.columns:
                self.df['涨跌幅'] = self.df['收盘'].pct_change() * 100
            if '振幅' not in self.df.columns:
                self.df['振幅'] = ((self.df['最高'] - self.df['最低']) / self.df['收盘'].shift(1) * 100)
            if '换手率' not in self.df.columns:
                self.df['换手率'] = 0
            if '涨跌额' not in self.df.columns:
                self.df['涨跌额'] = self.df['收盘'].diff()

            self.df = self.df.fillna(0)
            self.df = self.df.sort_values('日期')

            print(f"✓ 成功加载 {len(self.df)} 条数据")
            return True

        except Exception as e:
            print(f"加载CSV失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_stock_info(self) -> Dict:
        """获取股票基本信息"""
        return {
            '股票代码': self.stock_code,
            '股票名称': self.stock_name,
            '所属行业': '未知',
            '交易所': '上海证券交易所' if self.stock_code.startswith('6') else '深圳证券交易所'
        }

    def get_realtime_quote(self) -> Dict:
        """获取最新行情"""
        if self.df is None or len(self.df) == 0:
            return {}

        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2] if len(self.df) > 1 else latest

        return {
            '股票代码': self.stock_code,
            '股票名称': self.stock_name,
            '最新价': float(latest['收盘']),
            '涨跌额': float(latest['涨跌额']),
            '涨跌幅': float(latest['涨跌幅']),
            '今开': float(latest['开盘']),
            '昨收': float(prev['收盘']),
            '最高': float(latest['最高']),
            '最低': float(latest['最低']),
            '成交量': int(latest['成交量']),
            '成交额': float(latest.get('成交额', 0)),
            '换手率': float(latest.get('换手率', 0)),
            '振幅': float(latest['振幅']),
            '量比': 0,
            '市盈率': 0,
            '市净率': 0,
            '总市值': 0,
            '流通市值': 0,
        }

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
        if not self.load_data():
            print("数据加载失败,无法生成报告")
            return

        print("正在计算技术指标...")

        # 计算技术指标
        self.df = self.calculate_ma(self.df, [5, 10, 20, 60])
        self.df = self.calculate_macd(self.df)
        self.df = self.calculate_kdj(self.df)
        self.df = self.calculate_rsi(self.df)
        self.df = self.calculate_boll(self.df)

        # 分析
        analysis = self.analyze_trend(self.df)
        sr = self.calculate_support_resistance(self.df)

        # 获取基础信息
        stock_info = self.get_stock_info()
        realtime = self.get_realtime_quote()

        # 获取近10日数据
        recent_10 = self.df.tail(10)

        # 读取模板
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()

        # 填充模板
        latest = self.df.iloc[-1]
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
        report = report.replace('{{成交量}}', f"{realtime.get('成交量', 0)/100:.0f}")
        report = report.replace('{{成交额}}', f"{realtime.get('成交额', 0)/10000:.2f}")
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
            recent_table += f"| {row['日期'].strftime('%Y-%m-%d')} | {row['开盘']:.2f} | {row['最高']:.2f} | {row['最低']:.2f} | {row['收盘']:.2f} | {row['涨跌幅']:.2f} | {row['成交量']/10000:.2f} | {row.get('成交额', 0)/10000:.2f} | {row.get('换手率', 0):.2f} | {row['振幅']:.2f} |\n"
        report = report.replace('{{近10日数据}}', recent_table)

        # 区间统计
        report = report.replace('{{期间最高}}', f"{recent_10['最高'].max():.2f}")
        report = report.replace('{{期间最低}}', f"{recent_10['最低'].min():.2f}")
        period_change = ((recent_10.iloc[-1]['收盘'] - recent_10.iloc[0]['收盘']) / recent_10.iloc[0]['收盘'] * 100)
        report = report.replace('{{期间涨跌幅}}', f"{period_change:.2f}")
        report = report.replace('{{平均换手率}}', f"{recent_10.get('换手率', pd.Series([0])).mean():.2f}")
        report = report.replace('{{总成交量}}', f"{recent_10['成交量'].sum()/10000:.2f}")
        report = report.replace('{{总成交额}}', f"{recent_10.get('成交额', pd.Series([0])).sum()/100000000:.2f}")
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
        vol_up = recent_10.iloc[-1]['成交量'] > recent_10.iloc[-2]['成交量'] if len(recent_10) > 1 else True
        if price_up and vol_up:
            vol_price = "量价齐升"
        elif not price_up and not vol_up:
            vol_price = "量价齐跌"
        elif price_up and not vol_up:
            vol_price = "价升量缩"
        else:
            vol_price = "价跌量增"
        report = report.replace('{{量价关系}}', vol_price)

        turnover = recent_10.get('换手率', pd.Series([0])).mean()
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

        print(f"\n✓ 分析报告已生成: {output_path}")


def main():
    """主函数"""
    import sys

    print("=" * 60)
    print("          股票技术分析报告生成器 (CSV版)")
    print("=" * 60)
    print("\n本工具可以分析CSV格式的股票数据")
    print("CSV格式要求: 日期,开盘,收盘,最高,最低,成交量,...")
    print("-" * 60)

    # 获取CSV文件路径
    if len(sys.argv) >= 2:
        csv_file = sys.argv[1]
    else:
        csv_file = input("\n请输入CSV文件路径: ").strip().strip('"')

    if not os.path.exists(csv_file):
        print(f"错误: 文件不存在: {csv_file}")
        sys.exit(1)

    # 获取股票代码和名称
    stock_code = input("请输入股票代码 (可选,回车跳过): ").strip() or "000000"
    stock_name = input("请输入股票名称 (可选,回车跳过): ").strip() or "未知股票"

    # 默认模板路径
    template_path = r"E:\trading\操作手册\stock_analysis_template.md"

    # 默认输出路径
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        output_dir = r"E:\trading\reports"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{stock_code}_{datetime.now().strftime('%Y%m%d')}.md")

    print(f"\n开始分析...")
    print(f"报告将保存至: {output_path}\n")

    # 创建分析器并生成报告
    try:
        analyzer = CSVStockAnalyzer(csv_file, stock_code, stock_name)
        analyzer.generate_report(template_path, output_path)
        print(f"\n✓ 分析完成!")
    except Exception as e:
        print(f"\n✗ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
