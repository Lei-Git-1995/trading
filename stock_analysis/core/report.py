#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模块
统一的报告生成逻辑
"""

import pandas as pd
from datetime import datetime
from typing import Dict
from pathlib import Path


class ReportGenerator:
    """报告生成器"""

    def __init__(self, template_path: str):
        """
        初始化报告生成器

        :param template_path: 模板文件路径
        """
        self.template_path = Path(template_path)
        if not self.template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")

        with open(self.template_path, 'r', encoding='utf-8') as f:
            self.template = f.read()

    def generate(self, stock_code: str, stock_name: str, df: pd.DataFrame,
                 realtime: Dict, analysis: Dict, sr: Dict, output_path: str) -> str:
        """
        生成分析报告

        :param stock_code: 股票代码
        :param stock_name: 股票名称
        :param df: 包含技术指标的历史数据DataFrame
        :param realtime: 实时行情字典
        :param analysis: 技术分析结果字典
        :param sr: 支撑压力位字典
        :param output_path: 输出路径
        :return: 生成的报告路径
        """
        report = self.template
        latest = df.iloc[-1]
        recent_10 = df.tail(10)

        # 基本信息
        report = self._fill_basic_info(report, stock_code, stock_name, latest)

        # 实时行情
        report = self._fill_realtime_quote(report, realtime)

        # 近10日数据表格
        report = self._fill_recent_data(report, recent_10, realtime)

        # 区间统计
        report = self._fill_period_stats(report, recent_10)

        # 技术指标
        report = self._fill_technical_indicators(report, df, analysis)

        # 量能分析
        report = self._fill_volume_analysis(report, recent_10)

        # 评分系统
        report = self._fill_scoring(report, analysis, recent_10)

        # 支撑压力位
        report = self._fill_support_resistance(report, sr, latest['收盘'])

        # 操作建议
        report = self._fill_operation_advice(report, analysis, sr, latest)

        # 风险提示
        report = self._fill_risk_warning(report, analysis, recent_10)

        # 时间信息
        report = report.replace('{{数据时间}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        report = report.replace('{{生成时间}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        # 保存报告
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        return str(output_path)

    def _fill_basic_info(self, report: str, stock_code: str, stock_name: str,
                         latest: pd.Series) -> str:
        """填充基本信息"""
        report = report.replace('{{股票代码}}', stock_code)
        report = report.replace('{{股票名称}}', stock_name)
        report = report.replace('{{所属行业}}', '未知')
        exchange = '上海证券交易所' if stock_code.startswith('6') else '深圳证券交易所'
        report = report.replace('{{交易所}}', exchange)
        report = report.replace('{{报告日期}}', datetime.now().strftime('%Y-%m-%d'))
        report = report.replace('{{最新日期}}', str(latest['日期'])[:10])
        return report

    def _fill_realtime_quote(self, report: str, realtime: Dict) -> str:
        """填充实时行情"""
        for k, v in realtime.items():
            if k in ['股票代码', '股票名称']:
                continue
            if not isinstance(v, (int, float)):
                continue
            if k in ('成交量', '外盘', '内盘'):
                text = f"{v:,.2f}"  # 已经是万手
            elif k == '成交额':
                text = f"{v:,.2f}"  # 已经是亿元
            else:
                text = f"{v:.2f}"
            report = report.replace('{{' + k + '}}', text)
        return report

    def _fill_recent_data(self, report: str, recent_10: pd.DataFrame,
                          realtime: Dict) -> str:
        """填充近10日数据表格"""
        def fmt(v, scale=1.0):
            """格式化数值，NaN显示为-"""
            return '-' if pd.isna(v) else f"{v / scale:.2f}"

        # 计算换手率（如果缺失）
        float_shares = self._estimate_float_shares(realtime)

        recent_table = ""
        for _, row in recent_10.iterrows():
            turnover = self._get_turnover(row, float_shares)
            recent_table += (
                f"| {str(row['日期'])[:10]} | {row['开盘']:.2f} | {row['最高']:.2f} | "
                f"{row['最低']:.2f} | {row['收盘']:.2f} | {row['涨跌幅']:.2f} | "
                f"{fmt(row['成交量'], 10000)} | {fmt(row['成交额'], 10000)} | "
                f"{fmt(turnover)} | {row['振幅']:.2f} |\n"
            )
        report = report.replace('{{近10日数据}}', recent_table)
        return report

    def _fill_period_stats(self, report: str, recent_10: pd.DataFrame) -> str:
        """填充区间统计"""
        period_change = ((recent_10.iloc[-1]['收盘'] - recent_10.iloc[0]['收盘']) /
                        recent_10.iloc[0]['收盘'] * 100)
        report = report.replace('{{期间最高}}', f"{recent_10['最高'].max():.2f}")
        report = report.replace('{{期间最低}}', f"{recent_10['最低'].min():.2f}")
        report = report.replace('{{期间涨跌幅}}', f"{period_change:.2f}")

        avg_turnover = recent_10['换手率'].mean()
        report = report.replace('{{平均换手率}}',
                               f"{avg_turnover:.2f}" if pd.notna(avg_turnover) else "-")
        report = report.replace('{{总成交量}}', f"{recent_10['成交量'].sum()/10000:.2f}")
        report = report.replace('{{总成交额}}', f"{recent_10['成交额'].sum()/100000000:.2f}")
        report = report.replace('{{平均振幅}}', f"{recent_10['振幅'].mean():.2f}")
        return report

    def _fill_technical_indicators(self, report: str, df: pd.DataFrame,
                                    analysis: Dict) -> str:
        """填充技术指标"""
        latest = df.iloc[-1]
        close = latest['收盘']

        # 均线
        for period in [5, 10, 20, 60]:
            ma_val = latest.get(f'MA{period}', 0)
            report = report.replace(f'{{{{MA{period}}}}}', f"{ma_val:.2f}")
            position = "上方" if close > ma_val else "下方"
            report = report.replace(f'{{{{MA{period}位置}}}}', position)

        report = report.replace('{{均线排列}}', analysis['trend'])
        report = report.replace('{{趋势判断}}', analysis['trend'])

        # MACD
        report = report.replace('{{MACD_DIF}}', f"{latest['MACD_DIF']:.4f}")
        report = report.replace('{{MACD_DEA}}', f"{latest['MACD_DEA']:.4f}")
        report = report.replace('{{MACD_BAR}}', f"{latest['MACD_BAR']:.4f}")
        report = report.replace('{{MACD信号}}', analysis['macd_signal'])
        macd_analysis = f"当前处于{analysis['macd_signal']}状态,{analysis['macd_status']}"
        report = report.replace('{{MACD分析}}', macd_analysis)

        # KDJ
        report = report.replace('{{KDJ_K}}', f"{latest['KDJ_K']:.2f}")
        report = report.replace('{{KDJ_D}}', f"{latest['KDJ_D']:.2f}")
        report = report.replace('{{KDJ_J}}', f"{latest['KDJ_J']:.2f}")
        report = report.replace('{{KDJ状态}}', analysis['kdj_status'])
        report = report.replace('{{KDJ分析}}', f"KDJ指标显示{analysis['kdj_status']}状态")

        # RSI
        for period in [6, 12, 24]:
            rsi_val = latest.get(f'RSI{period}', 0)
            report = report.replace(f'{{{{RSI{period}}}}}', f"{rsi_val:.2f}")
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

        return report

    def _fill_volume_analysis(self, report: str, recent_10: pd.DataFrame) -> str:
        """填充量能分析"""
        vol_change = "放量" if recent_10.iloc[-1]['成交量'] > recent_10['成交量'].mean() else "缩量"
        report = report.replace('{{量能变化}}', vol_change)

        price_up = recent_10.iloc[-1]['涨跌幅'] > 0
        vol_up = (recent_10.iloc[-1]['成交量'] > recent_10.iloc[-2]['成交量']
                 if len(recent_10) > 1 else True)

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
        if pd.notna(turnover):
            if turnover > 5:
                turnover_level = "活跃"
            elif turnover > 2:
                turnover_level = "正常"
            else:
                turnover_level = "低迷"
        else:
            turnover_level = "未知"
        report = report.replace('{{换手率水平}}', turnover_level)
        report = report.replace('{{成交量趋势分析}}',
                               f"近期成交量{vol_change},换手率{turnover_level},反映市场参与度{turnover_level}")
        return report

    def _fill_scoring(self, report: str, analysis: Dict, recent_10: pd.DataFrame) -> str:
        """填充评分系统"""
        trend_score = 8 if "多头" in analysis['trend'] else (3 if "空头" in analysis['trend'] else 5)
        multi_score = 7 if analysis['macd_status'] == "看多" else 3

        turnover = recent_10['换手率'].mean()
        active_score = int(turnover * 2) if pd.notna(turnover) and turnover < 5 else 10

        resonance_score = sum([1 for x in [analysis['macd_status'], analysis['kdj_status'],
                                           analysis['rsi_status']]
                              if "看多" in x or "超卖" in x]) * 2 + 2

        vol_change = "放量" if recent_10.iloc[-1]['成交量'] > recent_10['成交量'].mean() else "缩量"
        price_up = recent_10.iloc[-1]['涨跌幅'] > 0
        vol_up = recent_10.iloc[-1]['成交量'] > recent_10.iloc[-2]['成交量'] if len(recent_10) > 1 else True
        vol_price = "量价齐升" if price_up and vol_up else "量价背离"
        momentum_score = 8 if vol_price == "量价齐升" else (3 if "齐跌" in vol_price else 5)

        report = report.replace('{{趋势评分}}', str(trend_score))
        report = report.replace('{{趋势说明}}', analysis['trend'])
        report = report.replace('{{多空评分}}', str(multi_score))
        report = report.replace('{{多空说明}}', analysis['macd_status'])
        report = report.replace('{{活跃评分}}', str(active_score))
        report = report.replace('{{活跃说明}}',
                               f"换手率{turnover:.2f}%" if pd.notna(turnover) else "未知")
        report = report.replace('{{共振评分}}', str(resonance_score))
        report = report.replace('{{共振说明}}', "多指标共振")
        report = report.replace('{{动能评分}}', str(momentum_score))
        report = report.replace('{{动能说明}}', vol_price)
        total_score = trend_score + multi_score + active_score + resonance_score + momentum_score
        report = report.replace('{{综合评分}}', str(total_score))

        return report

    def _fill_support_resistance(self, report: str, sr: Dict, close: float) -> str:
        """填充支撑压力位"""
        resistances = sr['resistances']
        supports = sr['supports']

        report = report.replace('{{强压力}}',
                               f"{resistances[0]:.2f}" if resistances else f"{close*1.05:.2f}")
        report = report.replace('{{强压力依据}}', "前期高点")
        report = report.replace('{{次压力}}',
                               f"{resistances[1]:.2f}" if len(resistances) > 1 else f"{close*1.03:.2f}")
        report = report.replace('{{次压力依据}}', "均线压力")
        report = report.replace('{{弱压力}}',
                               f"{resistances[2]:.2f}" if len(resistances) > 2 else f"{close*1.02:.2f}")
        report = report.replace('{{弱压力依据}}', "技术压力")

        report = report.replace('{{强支撑}}',
                               f"{supports[0]:.2f}" if supports else f"{close*0.95:.2f}")
        report = report.replace('{{强支撑依据}}', "前期低点")
        report = report.replace('{{次支撑}}',
                               f"{supports[1]:.2f}" if len(supports) > 1 else f"{close*0.97:.2f}")
        report = report.replace('{{次支撑依据}}', "均线支撑")
        report = report.replace('{{弱支撑}}',
                               f"{supports[2]:.2f}" if len(supports) > 2 else f"{close*0.98:.2f}")
        report = report.replace('{{弱支撑依据}}', "技术支撑")

        return report

    def _fill_operation_advice(self, report: str, analysis: Dict, sr: Dict,
                                latest: pd.Series) -> str:
        """填充操作建议"""
        close = latest['收盘']
        resistances = sr['resistances']
        supports = sr['supports']

        trend_score = 8 if "多头" in analysis['trend'] else (3 if "空头" in analysis['trend'] else 5)
        multi_score = 7 if analysis['macd_status'] == "看多" else 3

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

        return report

    def _fill_risk_warning(self, report: str, analysis: Dict,
                           recent_10: pd.DataFrame) -> str:
        """填充风险提示"""
        risk_items = []

        if analysis['kdj_status'] == "超买" or analysis['rsi_status'] == "超买":
            risk_items.append("- 技术指标显示超买,短期存在回调风险")

        vol_change = "放量" if recent_10.iloc[-1]['成交量'] > recent_10['成交量'].mean() else "缩量"
        price_up = recent_10.iloc[-1]['涨跌幅'] > 0
        if vol_change == "缩量" and price_up:
            risk_items.append("- 价升量缩,上涨动能不足")

        if "空头" in analysis['trend']:
            risk_items.append("- 均线空头排列,趋势偏弱")

        if not risk_items:
            risk_items.append("- 请注意市场整体风险")
            risk_items.append("- 注意控制仓位,设置止损")

        report = report.replace('{{风险提示}}', '\n'.join(risk_items))
        return report

    @staticmethod
    def _estimate_float_shares(realtime: Dict) -> float:
        """估算流通股本"""
        float_mktcap = float(realtime.get('流通市值', 0) or 0)
        if float_mktcap > 0:
            base_price = float(realtime.get('昨收', 0) or 0)
            if base_price > 0:
                return float_mktcap * 1e8 / base_price
        return 0.0

    @staticmethod
    def _get_turnover(row: pd.Series, float_shares: float) -> float:
        """获取换手率（如果缺失则估算）"""
        tr = row['换手率']
        if pd.notna(tr) and tr > 0:
            return tr
        if float_shares > 0:
            return row['成交量'] * 100 / float_shares * 100
        return float('nan')
