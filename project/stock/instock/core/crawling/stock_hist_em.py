#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
Date: 2022/6/19 15:26
Desc: 东方财富网-行情首页-沪深京 A 股
"""
import random
import time
import datetime

import pandas as pd
import math
from functools import lru_cache
import logging
import numpy as np
from instock.core.eastmoney_fetcher import eastmoney_fetcher

__author__ = 'myh '
__date__ = '2025/12/31 '

# 创建全局实例，供所有函数使用
fetcher = eastmoney_fetcher()

# 东方财富不可用时使用腾讯（经 AkShare）作为备用数据源。
def _tencent_spot_fallback():
    import akshare as ak
    src = ak.stock_zh_a_spot_tx()
    if src is None or src.empty:
        return pd.DataFrame()
    src = src.copy()
    code = src["code"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)
    def num(name):
        return pd.to_numeric(src[name], errors="coerce") if name in src else np.nan
    return pd.DataFrame({
        "code": code, "name": src["name"].astype(str),
        "new_price": num("zxj"), "change_rate": num("zdf"), "ups_downs": num("zd"),
        "volume": num("volume"), "deal_amount": num("turnover"), "amplitude": num("zf"),
        "turnoverrate": num("hsl"), "volume_ratio": num("lb"),
        "open_price": np.nan, "high_price": np.nan, "low_price": np.nan, "pre_close_price": np.nan,
        "speed_increase": np.nan, "speed_increase_5": num("zdf_d5"), "speed_increase_60": num("zdf_d60"),
        "speed_increase_all": num("zdf_y"), "dtsyl": np.nan, "pe9": np.nan, "pe": num("pe_ttm"),
        "pbnewmrq": np.nan, "basic_eps": np.nan, "bvps": np.nan, "per_capital_reserve": np.nan,
        "per_unassign_profit": np.nan, "roe_weight": np.nan, "sale_gpr": np.nan, "debt_asset_ratio": np.nan,
        "total_operate_income": np.nan, "toi_yoy_ratio": np.nan, "parent_netprofit": np.nan,
        "netprofit_yoy_ratio": np.nan, "report_date": pd.NaT, "total_shares": np.nan, "free_shares": np.nan,
        "total_market_cap": num("zsz"), "free_cap": num("ltsz"), "industry": np.nan, "listing_date": pd.NaT,
    })


def _to_lots(volume, amount, close):
    """把不同通道返回的成交量统一换算成“手”。

    InStock 的 fetch_stock_hist 会把成交量再乘 100（手 -> 股），所以本函数
    必须返回“手”。腾讯/新浪的 volume 字段单位并不一致（腾讯对部分深市股票
    返回“手”，其余返回“股”），用 amount/close 反推真实股数来判断实际单位。
    """
    volume = pd.to_numeric(volume, errors="coerce")
    implied = pd.to_numeric(amount, errors="coerce") / pd.to_numeric(close, errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = volume / implied
    # ratio 约等于 1 说明通道已给“股”；约等于 0.01 说明通道给的是“手”。
    is_shares = ratio.between(0.9, 1.1).fillna(False)
    return np.where(is_shares, volume / 100.0, volume)


def _finalize_hist(date, open_, high, low, close, volume, amount, turnover):
    """补齐 InStock 需要的 11 列，并派生振幅/涨跌幅/涨跌额。"""
    out = pd.DataFrame({
        "date": pd.to_datetime(date, errors="coerce").dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(open_, errors="coerce"),
        "close": pd.to_numeric(close, errors="coerce"),
        "high": pd.to_numeric(high, errors="coerce"),
        "low": pd.to_numeric(low, errors="coerce"),
        "volume": volume,
        "amount": pd.to_numeric(amount, errors="coerce"),
        "amplitude": np.nan, "quote_change": np.nan, "ups_downs": np.nan,
        "turnover": pd.to_numeric(turnover, errors="coerce") * 100,
    })
    out["ups_downs"] = out["close"].diff().fillna(0.0)
    out["quote_change"] = out["close"].pct_change().mul(100).fillna(0.0)
    out["amplitude"] = (out["high"] - out["low"]).div(out["close"].shift(1)).mul(100).fillna(0.0)
    return out


def _market_symbol(symbol):
    return ("sh" if str(symbol).startswith(("6", "9")) else "sz") + str(symbol)


def _sina_hist_fallback(symbol, start_date, end_date, adjust="qfq"):
    """新浪日 K。volume 单位在全部样本上一致为“股”，是当前最可靠的替代通道。"""
    import akshare as ak
    end_date = end_date or datetime.date.today().strftime("%Y%m%d")
    src = ak.stock_zh_a_daily(symbol=_market_symbol(symbol), start_date=start_date,
                              end_date=end_date, adjust=adjust)
    if src is None or src.empty:
        return pd.DataFrame()
    lots = _to_lots(src["volume"], src["amount"], src["close"])
    return _finalize_hist(src["date"], src["open"], src["high"], src["low"], src["close"],
                          lots, src["amount"], src.get("turnover"))


def _tencent_hist_fallback(symbol, start_date, end_date, adjust="qfq"):
    import akshare as ak
    src = ak.stock_zh_a_hist_tx(symbol=_market_symbol(symbol), start_date=start_date,
                                end_date=end_date, adjust=adjust)
    if src is None or src.empty:
        return pd.DataFrame()
    lots = _to_lots(src["volume"], src["amount"], src["close"])
    return _finalize_hist(src["date"], src["open"], src["high"], src["low"], src["close"],
                          lots, src["amount"], src.get("turnover"))


def stock_zh_a_spot_em() -> pd.DataFrame:
    """
    东方财富网-沪深京 A 股-实时行情
    https://quote.eastmoney.com/center/gridlist.html#hs_a_board
    :return: 实时行情
    :rtype: pandas.DataFrame
    """
    # Prefer Tencent; EastMoney remains a fallback for compatibility.
    try:
        return _tencent_spot_fallback()
    except Exception as exc:
        logging.warning("Tencent spot unavailable, trying EastMoney: %s", exc)
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    page_size = 50
    page_current = 1
    params = {
        "pn": page_current,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f14,f15,f16,f17,f18,f20,f21,f22,f23,f24,f25,f26,f37,f38,f39,f40,f41,f45,f46,f48,f49,f57,f61,f100,f112,f113,f114,f115,f221",
        "_": str(int(time.time() * 1000)),
    }
    try:
        r = fetcher.make_request(url, params=params)
        data_json = r.json()
    except Exception as exc:
        logging.warning("EastMoney spot unavailable, falling back to Tencent: %s", exc)
        return _tencent_spot_fallback()
    data = data_json["data"]["diff"]
    if not data:
        return pd.DataFrame()

    data_count = data_json["data"]["total"]
    page_count = math.ceil(data_count/page_size)
    while page_count > 1:
        # 添加随机延迟，避免爬取过快
        time.sleep(random.uniform(1, 1.5))
        page_current = page_current + 1
        params["pn"] = page_current
        r =  fetcher.make_request(url, params=params)
        data_json = r.json()
        _data = data_json["data"]["diff"]
        data.extend(_data)
        page_count =page_count - 1

    temp_df = pd.DataFrame(data)
    temp_df.columns = [
        "最新价",
        "涨跌幅",
        "涨跌额",
        "成交量",
        "成交额",
        "振幅",
        "换手率",
        "市盈率动",
        "量比",
        "5分钟涨跌",
        "代码",
        "名称",
        "最高",
        "最低",
        "今开",
        "昨收",
        "总市值",
        "流通市值",
        "涨速",
        "市净率",
        "60日涨跌幅",
        "年初至今涨跌幅",
        "上市时间",
        "加权净资产收益率",
        "总股本",
        "已流通股份",
        "营业收入",
        "营业收入同比增长",
        "归属净利润",
        "归属净利润同比增长",
        "每股未分配利润",
        "毛利率",
        "资产负债率",
        "每股公积金",
        "所处行业",
        "每股收益",
        "每股净资产",
        "市盈率静",
        "市盈率TTM",
        "报告期"
    ]
    temp_df = temp_df[
        [
            "代码",
            "名称",
            "最新价",
            "涨跌幅",
            "涨跌额",
            "成交量",
            "成交额",
            "振幅",
            "换手率",
            "量比",
            "今开",
            "最高",
            "最低",
            "昨收",
            "涨速",
            "5分钟涨跌",
            "60日涨跌幅",
            "年初至今涨跌幅",
            "市盈率动",
            "市盈率TTM",
            "市盈率静",
            "市净率",
            "每股收益",
            "每股净资产",
            "每股公积金",
            "每股未分配利润",
            "加权净资产收益率",
            "毛利率",
            "资产负债率",
            "营业收入",
            "营业收入同比增长",
            "归属净利润",
            "归属净利润同比增长",
            "报告期",
            "总股本",
            "已流通股份",
            "总市值",
            "流通市值",
            "所处行业",
            "上市时间"
        ]
    ]
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"], errors="coerce")
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    temp_df["振幅"] = pd.to_numeric(temp_df["振幅"], errors="coerce")
    temp_df["量比"] = pd.to_numeric(temp_df["量比"], errors="coerce")
    temp_df["换手率"] = pd.to_numeric(temp_df["换手率"], errors="coerce")
    temp_df["最高"] = pd.to_numeric(temp_df["最高"], errors="coerce")
    temp_df["最低"] = pd.to_numeric(temp_df["最低"], errors="coerce")
    temp_df["今开"] = pd.to_numeric(temp_df["今开"], errors="coerce")
    temp_df["昨收"] = pd.to_numeric(temp_df["昨收"], errors="coerce")
    temp_df["涨速"] = pd.to_numeric(temp_df["涨速"], errors="coerce")
    temp_df["5分钟涨跌"] = pd.to_numeric(temp_df["5分钟涨跌"], errors="coerce")
    temp_df["60日涨跌幅"] = pd.to_numeric(temp_df["60日涨跌幅"], errors="coerce")
    temp_df["年初至今涨跌幅"] = pd.to_numeric(temp_df["年初至今涨跌幅"], errors="coerce")
    temp_df["市盈率动"] = pd.to_numeric(temp_df["市盈率动"], errors="coerce")
    temp_df["市盈率TTM"] = pd.to_numeric(temp_df["市盈率TTM"], errors="coerce")
    temp_df["市盈率静"] = pd.to_numeric(temp_df["市盈率静"], errors="coerce")
    temp_df["市净率"] = pd.to_numeric(temp_df["市净率"], errors="coerce")
    temp_df["每股收益"] = pd.to_numeric(temp_df["每股收益"], errors="coerce")
    temp_df["每股净资产"] = pd.to_numeric(temp_df["每股净资产"], errors="coerce")
    temp_df["每股公积金"] = pd.to_numeric(temp_df["每股公积金"], errors="coerce")
    temp_df["每股未分配利润"] = pd.to_numeric(temp_df["每股未分配利润"], errors="coerce")
    temp_df["加权净资产收益率"] = pd.to_numeric(temp_df["加权净资产收益率"], errors="coerce")
    temp_df["毛利率"] = pd.to_numeric(temp_df["毛利率"], errors="coerce")
    temp_df["资产负债率"] = pd.to_numeric(temp_df["资产负债率"], errors="coerce")
    temp_df["营业收入"] = pd.to_numeric(temp_df["营业收入"], errors="coerce")
    temp_df["营业收入同比增长"] = pd.to_numeric(temp_df["营业收入同比增长"], errors="coerce")
    temp_df["归属净利润"] = pd.to_numeric(temp_df["归属净利润"], errors="coerce")
    temp_df["归属净利润同比增长"] = pd.to_numeric(temp_df["归属净利润同比增长"], errors="coerce")
    temp_df["报告期"] = pd.to_datetime(temp_df["报告期"], format='%Y%m%d', errors="coerce")
    temp_df["总股本"] = pd.to_numeric(temp_df["总股本"], errors="coerce")
    temp_df["已流通股份"] = pd.to_numeric(temp_df["已流通股份"], errors="coerce")
    temp_df["总市值"] = pd.to_numeric(temp_df["总市值"], errors="coerce")
    temp_df["流通市值"] = pd.to_numeric(temp_df["流通市值"], errors="coerce")
    temp_df["上市时间"] = pd.to_datetime(temp_df["上市时间"], format='%Y%m%d', errors="coerce")

    return temp_df


@lru_cache()
def code_id_map_em() -> dict:
    """
    东方财富-股票和市场代码
    http://quote.eastmoney.com/center/gridlist.html#hs_a_board
    :return: 股票和市场代码
    :rtype: dict
    """
    url = "http://80.push2.eastmoney.com/api/qt/clist/get"
    page_size = 50
    page_current = 1
    params = {
        "pn": page_current,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:1 t:2,m:1 t:23",
        "fields": "f12",
        "_": "1623833739532",
    }
    r =  fetcher.make_request(url, params=params)
    data_json = r.json()
    data = data_json["data"]["diff"]
    if not data:
        return dict()

    data_count = data_json["data"]["total"]
    page_count = math.ceil(data_count/page_size)
    while page_count > 1:
        # 添加随机延迟，避免爬取过快
        time.sleep(random.uniform(1, 1.5))
        page_current = page_current + 1
        params["pn"] = page_current
        r =  fetcher.make_request(url, params=params)
        data_json = r.json()
        _data = data_json["data"]["diff"]
        data.extend(_data)
        page_count =page_count - 1

    temp_df = pd.DataFrame(data)
    temp_df["market_id"] = 1
    temp_df.columns = ["sh_code", "sh_id"]
    code_id_dict = dict(zip(temp_df["sh_code"], temp_df["sh_id"]))
    page_current = 1
    params = {
        "pn": page_current,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80",
        "fields": "f12",
        "_": "1623833739532",
    }
    r =  fetcher.make_request(url, params=params)
    data_json = r.json()
    data = data_json["data"]["diff"]
    if not data:
        return dict()

    data_count = data_json["data"]["total"]
    page_count = math.ceil(data_count/page_size)
    while page_count > 1:
        # 添加随机延迟，避免爬取过快
        time.sleep(random.uniform(1, 1.5))
        page_current = page_current + 1
        params["pn"] = page_current
        r =  fetcher.make_request(url, params=params)
        data_json = r.json()
        _data = data_json["data"]["diff"]
        data.extend(_data)
        page_count =page_count - 1

    temp_df_sz = pd.DataFrame(data)
    temp_df_sz["sz_id"] = 0
    code_id_dict.update(dict(zip(temp_df_sz["f12"], temp_df_sz["sz_id"])))
    page_current = 1
    params = {
        "pn": page_current,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:81 s:2048",
        "fields": "f12",
        "_": "1623833739532",
    }
    r =  fetcher.make_request(url, params=params)
    data_json = r.json()
    data = data_json["data"]["diff"]
    if not data:
        return dict()

    data_count = data_json["data"]["total"]
    page_count = math.ceil(data_count/page_size)
    while page_count > 1:
        # 添加随机延迟，避免爬取过快
        time.sleep(random.uniform(1, 1.5))
        page_current = page_current + 1
        params["pn"] = page_current
        r =  fetcher.make_request(url, params=params)
        data_json = r.json()
        _data = data_json["data"]["diff"]
        data.extend(_data)
        page_count =page_count - 1

    temp_df_sz = pd.DataFrame(data)
    temp_df_sz["bj_id"] = 0
    code_id_dict.update(dict(zip(temp_df_sz["f12"], temp_df_sz["bj_id"])))
    return code_id_dict


def stock_zh_a_hist(
    symbol: str = "000001",
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "20500101",
    adjust: str = "",
) -> pd.DataFrame:
    """
    东方财富网-行情首页-沪深京 A 股-每日行情
    https://quote.eastmoney.com/concept/sh603777.html?from=classic
    :param symbol: 股票代码
    :type symbol: str
    :param period: choice of {'daily', 'weekly', 'monthly'}
    :type period: str
    :param start_date: 开始日期
    :type start_date: str
    :param end_date: 结束日期
    :type end_date: str
    :param adjust: choice of {"qfq": "前复权", "hfq": "后复权", "": "不复权"}
    :type adjust: str
    :return: 每日行情
    :rtype: pandas.DataFrame
    """
    # 优先新浪（单位最稳定），其次腾讯，最后东财。
    for fetcher_fn in (_sina_hist_fallback, _tencent_hist_fallback):
        try:
            out = fetcher_fn(symbol, start_date, end_date, adjust)
            if out is not None and not out.empty:
                return out
        except Exception as exc:
            logging.warning("%s unavailable for %s: %s", fetcher_fn.__name__, symbol, exc)
    if period != "daily":
        logging.warning("non-daily period %s unsupported without EastMoney, using daily", period)
    adjust_dict = {"qfq": "1", "hfq": "2", "": "0"}
    period_dict = {"daily": "101", "weekly": "102", "monthly": "103"}
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": period_dict[period],
        "fqt": adjust_dict[adjust],
        "secid": f"1.{symbol}" if symbol.startswith('6') else f"0.{symbol}",
        "beg": start_date,
        "end": end_date,
        "_": "1623766962675",
    }
    try:
        r = fetcher.make_request(url, params=params)
        data_json = r.json()
        if not (data_json["data"] and data_json["data"]["klines"]):
            return pd.DataFrame()
    except Exception as exc:
        logging.warning("EastMoney history unavailable for %s, falling back to Tencent: %s", symbol, exc)
        return _tencent_hist_fallback(symbol, start_date, end_date, adjust)
    temp_df = pd.DataFrame(
        [item.split(",") for item in data_json["data"]["klines"]]
    )
    temp_df.columns = [
        "日期",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
    ]
    temp_df.index = pd.to_datetime(temp_df["日期"])
    temp_df.reset_index(inplace=True, drop=True)

    temp_df["开盘"] = pd.to_numeric(temp_df["开盘"])
    temp_df["收盘"] = pd.to_numeric(temp_df["收盘"])
    temp_df["最高"] = pd.to_numeric(temp_df["最高"])
    temp_df["最低"] = pd.to_numeric(temp_df["最低"])
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"])
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"])
    temp_df["振幅"] = pd.to_numeric(temp_df["振幅"])
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"])
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"])
    temp_df["换手率"] = pd.to_numeric(temp_df["换手率"])

    return temp_df


def stock_zh_a_hist_min_em(
    symbol: str = "000001",
    start_date: str = "1979-09-01 09:32:00",
    end_date: str = "2222-01-01 09:32:00",
    period: str = "5",
    adjust: str = "",
) -> pd.DataFrame:
    """
    东方财富网-行情首页-沪深京 A 股-每日分时行情
    https://quote.eastmoney.com/concept/sh603777.html?from=classic
    :param symbol: 股票代码
    :type symbol: str
    :param start_date: 开始日期
    :type start_date: str
    :param end_date: 结束日期
    :type end_date: str
    :param period: choice of {'1', '5', '15', '30', '60'}
    :type period: str
    :param adjust: choice of {'', 'qfq', 'hfq'}
    :type adjust: str
    :return: 每日分时行情
    :rtype: pandas.DataFrame
    """
    adjust_map = {
        "": "0",
        "qfq": "1",
        "hfq": "2",
    }
    if period == "1":
        url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "ndays": "5",
            "iscr": "0",
            "secid": f"1.{symbol}" if symbol.startswith('6') else f"0.{symbol}",
            "_": "1623766962675",
        }
        r =  fetcher.make_request(url, params=params)
        data_json = r.json()
        temp_df = pd.DataFrame(
            [item.split(",") for item in data_json["data"]["trends"]]
        )
        temp_df.columns = [
            "时间",
            "开盘",
            "收盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
            "最新价",
        ]
        temp_df.index = pd.to_datetime(temp_df["时间"])
        temp_df = temp_df[start_date:end_date]
        temp_df.reset_index(drop=True, inplace=True)
        temp_df["开盘"] = pd.to_numeric(temp_df["开盘"])
        temp_df["收盘"] = pd.to_numeric(temp_df["收盘"])
        temp_df["最高"] = pd.to_numeric(temp_df["最高"])
        temp_df["最低"] = pd.to_numeric(temp_df["最低"])
        temp_df["成交量"] = pd.to_numeric(temp_df["成交量"])
        temp_df["成交额"] = pd.to_numeric(temp_df["成交额"])
        temp_df["最新价"] = pd.to_numeric(temp_df["最新价"])
        temp_df["时间"] = pd.to_datetime(temp_df["时间"]).astype(str)
        return temp_df
    else:
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": period,
            "fqt": adjust_map[adjust],
            "secid": f"1.{symbol}" if symbol.startswith('6') else f"0.{symbol}",
            "beg": "0",
            "end": "20500000",
            "_": "1630930917857",
        }
        r =  fetcher.make_request(url, params=params)
        data_json = r.json()
        temp_df = pd.DataFrame(
            [item.split(",") for item in data_json["data"]["klines"]]
        )
        temp_df.columns = [
            "时间",
            "开盘",
            "收盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
            "振幅",
            "涨跌幅",
            "涨跌额",
            "换手率",
        ]
        temp_df.index = pd.to_datetime(temp_df["时间"])
        temp_df = temp_df[start_date:end_date]
        temp_df.reset_index(drop=True, inplace=True)
        temp_df["开盘"] = pd.to_numeric(temp_df["开盘"])
        temp_df["收盘"] = pd.to_numeric(temp_df["收盘"])
        temp_df["最高"] = pd.to_numeric(temp_df["最高"])
        temp_df["最低"] = pd.to_numeric(temp_df["最低"])
        temp_df["成交量"] = pd.to_numeric(temp_df["成交量"])
        temp_df["成交额"] = pd.to_numeric(temp_df["成交额"])
        temp_df["振幅"] = pd.to_numeric(temp_df["振幅"])
        temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"])
        temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"])
        temp_df["换手率"] = pd.to_numeric(temp_df["换手率"])
        temp_df["时间"] = pd.to_datetime(temp_df["时间"]).astype(str)
        temp_df = temp_df[
            [
                "时间",
                "开盘",
                "收盘",
                "最高",
                "最低",
                "涨跌幅",
                "涨跌额",
                "成交量",
                "成交额",
                "振幅",
                "换手率",
            ]
        ]
        return temp_df


def stock_zh_a_hist_pre_min_em(
    symbol: str = "000001",
    start_time: str = "09:00:00",
    end_time: str = "15:50:00",
) -> pd.DataFrame:
    """
    东方财富网-行情首页-沪深京 A 股-每日分时行情包含盘前数据
    http://quote.eastmoney.com/concept/sh603777.html?from=classic
    :param symbol: 股票代码
    :type symbol: str
    :param start_time: 开始时间
    :type start_time: str
    :param end_time: 结束时间
    :type end_time: str
    :return: 每日分时行情包含盘前数据
    :rtype: pandas.DataFrame
    """
    url = "https://push2.eastmoney.com/api/qt/stock/trends2/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "ndays": "1",
        "iscr": "1",
        "iscca": "0",
        "secid": f"1.{symbol}" if symbol.startswith('6') else f"0.{symbol}",
        "_": "1623766962675",
    }
    r =  fetcher.make_request(url, params=params)
    data_json = r.json()
    temp_df = pd.DataFrame(
        [item.split(",") for item in data_json["data"]["trends"]]
    )
    temp_df.columns = [
        "时间",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "最新价",
    ]
    temp_df.index = pd.to_datetime(temp_df["时间"])
    date_format = temp_df.index[0].date().isoformat()
    temp_df = temp_df[
        date_format + " " + start_time : date_format + " " + end_time
    ]
    temp_df.reset_index(drop=True, inplace=True)
    temp_df["开盘"] = pd.to_numeric(temp_df["开盘"])
    temp_df["收盘"] = pd.to_numeric(temp_df["收盘"])
    temp_df["最高"] = pd.to_numeric(temp_df["最高"])
    temp_df["最低"] = pd.to_numeric(temp_df["最低"])
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"])
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"])
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"])
    temp_df["时间"] = pd.to_datetime(temp_df["时间"]).astype(str)
    return temp_df


if __name__ == "__main__":
    stock_zh_a_spot_em_df = stock_zh_a_spot_em()
    print(stock_zh_a_spot_em_df)

    code_id_map_em_df = code_id_map_em()
    print(code_id_map_em_df)

    stock_zh_a_hist_df = stock_zh_a_hist(
        symbol="000001",
        period="daily",
        start_date="20220516",
        end_date="20220722",
        adjust="hfq",
    )
    print(stock_zh_a_hist_df)

    stock_zh_a_hist_min_em_df = stock_zh_a_hist_min_em(symbol="000001", period="1")
    print(stock_zh_a_hist_min_em_df)

    stock_zh_a_hist_pre_min_em_df = stock_zh_a_hist_pre_min_em(symbol="000001")
    print(stock_zh_a_hist_pre_min_em_df)

    stock_zh_a_spot_em_df = stock_zh_a_spot_em()
    print(stock_zh_a_spot_em_df)

    stock_zh_a_hist_min_em_df = stock_zh_a_hist_min_em(
        symbol="000001", period='1'
    )
    print(stock_zh_a_hist_min_em_df)

    stock_zh_a_hist_df = stock_zh_a_hist(
        symbol="000001",
        period="daily",
        start_date="20170301",
        end_date="20211115",
        adjust="hfq",
    )
    print(stock_zh_a_hist_df)

