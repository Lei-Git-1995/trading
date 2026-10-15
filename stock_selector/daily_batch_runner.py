"""Run all configured screens on one dated quote and daily-bar snapshot."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time

import numpy as np
import pandas as pd
import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_selector.config import PROJECT_ROOT, ScreenerConfig
from stock_selector.data.providers.tencent_provider import TencentProvider, _to_symbol
from stock_selector.reports.markdown_report import generate
from stock_selector.reports.markdown_report_v2 import generate_v2_report
from stock_selector.strategies.short_term_selector import ShortTermSelector
from stock_selector.strategies.strategy_adapter import StrategyAdapter
from stock_selector.strategies.technical_selection import STRATEGIES, calculate_indicators
from stock_selector.strategy_runner import write_report
from stock_selector.utils.config_loader import load_presets_file
from stock_selector.utils.logger import setup_logger


def fetch_json(url, **kwargs):
    last = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=15, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(str(last))


def quote_snapshot(universe, date):
    records = []
    codes = universe['code'].tolist()
    for start in range(0, len(codes), 100):
        symbols = [_to_symbol(code) for code in codes[start:start + 100]]
        response = requests.get('https://qt.gtimg.cn/q=' + ','.join(symbols), timeout=15)
        response.raise_for_status()
        for symbol, raw in re.findall(r'v_(\w+)="([^"]*)"', response.content.decode('gb18030')):
            fields = raw.split('~')
            if len(fields) < 45:
                continue
            try:
                stamp = datetime.strptime(fields[30], '%Y%m%d%H%M%S')
                if stamp.strftime('%Y-%m-%d') != date:
                    continue
                volume, outer, inner = float(fields[6]), float(fields[7]), float(fields[8])
                records.append(dict(code=symbol[2:], name=fields[1], price=float(fields[3]),
                                    previous_close=float(fields[4]), change_pct=float(fields[32]),
                                    turnover=float(fields[38]), volume=volume,
                                    outer_vol=outer, inner_vol=inner,
                                    outer_ratio=outer / (outer + inner) if outer + inner else np.nan,
                                    inner_ratio=inner / (outer + inner) if outer + inner else np.nan,
                                    amount=float(fields[37]) / 10000,
                                    quote_time=stamp.isoformat(sep=' ')))
            except (ValueError, IndexError):
                continue
        if start % 1000 == 0:
            print(f'QUOTE {min(start + 100, len(codes))}/{len(codes)}', flush=True)
    if not records:
        raise RuntimeError('No quotes matching the requested date')
    stocks = pd.DataFrame(records).drop_duplicates('code')
    stocks = stocks.merge(universe[['code', 'sector']], on='code', how='left')
    return stocks


def current_history(stock, date, directory):
    """Require current bars; never silently use yesterday's history."""
    code = stock['code']
    path = directory / f'{code}.csv'
    if path.exists():
        hist = pd.read_csv(path, dtype={'日期': str})
    else:
        symbol = _to_symbol(code)
        # The proxy endpoint is less aggressive than the public web endpoint.
        # The latter is retained as a fallback because Tencent sometimes
        # rotates WAF rules between the two hosts.
        try:
            data = fetch_json('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get',
                              params={'param': f'{symbol},day,,,150,qfq'})['data'][symbol]
        except Exception:
            data = fetch_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                              params={'param': f'{symbol},day,,,150,qfq'})['data'][symbol]
        rows = data.get('qfqday') or data.get('day')
        if not rows:
            raise RuntimeError('No daily bars')
        hist = pd.DataFrame([row[:6] for row in rows],
                            columns=['日期', '开盘', '收盘', '最高', '最低', '成交量'])
        hist = hist.sort_values('日期').drop_duplicates('日期').tail(150).reset_index(drop=True)
        for column in hist.columns[1:]:
            hist[column] = pd.to_numeric(hist[column], errors='raise')
        if str(hist.iloc[-1]['日期']) != date:
            raise RuntimeError(f'Latest daily bar: {hist.iloc[-1]["日期"]}')
        # This endpoint uses hands for most shares and shares for some markets.
        # Compare its current volume with the quote in hands before normalizing.
        quote_volume = stock['volume']
        ratio = hist.iloc[-1]['成交量'] / quote_volume if quote_volume else 1
        if 90 < ratio < 110:
            hist['成交量'] /= 100
        elif quote_volume and not 0.9 < ratio < 1.1:
            raise RuntimeError(f'Unrecognized daily volume unit: ratio={ratio:.4f}')
        hist['涨跌额'] = hist['收盘'].diff().fillna(0)
        hist['涨跌幅'] = (hist['收盘'].pct_change() * 100).fillna(0)
        hist['振幅'] = ((hist['最高'] - hist['最低']) / hist['收盘'].shift(1) * 100).fillna(0)
        hist['换手率'] = np.nan
        hist['成交额'] = np.nan
        hist.loc[hist.index[-1], '换手率'] = stock['turnover']
        hist.loc[hist.index[-1], '成交额'] = stock['amount'] * 1e8
        hist.to_csv(path, index=False, encoding='utf-8-sig')
    if str(hist.iloc[-1]['日期']) != date:
        raise RuntimeError('Cached history has the wrong date')
    if abs(hist.iloc[-1]['收盘'] - stock['price']) > max(0.03, stock['price'] * 0.001):
        raise RuntimeError('Daily close differs from quote price')
    if hist[['开盘', '收盘', '最高', '最低', '成交量']].isna().any().any():
        raise RuntimeError('Incomplete OHLCV')
    return hist


class SnapshotProvider:
    def __init__(self, histories):
        self.histories = histories

    def get_stock_history(self, code, days=10):
        hist = self.histories.get(code)
        return hist.tail(days).copy() if hist is not None else None


class UnavailableIntraday:
    def get_today_high_distance(self, *args):
        return None


def plain_rows(rows):
    result = []
    for row in rows:
        result.append({key: json.dumps(value, ensure_ascii=False, default=str)
                       if isinstance(value, (dict, list)) else value
                       for key, value in row.items() if key != 'hist_data'})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--db-dsn', help='PostgreSQL DSN（默认读取 STOCK_SELECTOR_PG_DSN）')
    parser.add_argument('--no-db', action='store_true', help='不保存批量选股结果到 PostgreSQL')
    args = parser.parse_args()
    root = args.output or PROJECT_ROOT / 'output' / args.date
    root.mkdir(parents=True, exist_ok=True)
    setup_logger(log_file=str(root / 'run.log'), enable_color=False)
    hist_dir = root / 'snapshot' / 'history'
    hist_dir.mkdir(parents=True, exist_ok=True)
    quote_path = root / 'snapshot' / 'quotes.csv'
    if quote_path.exists():
        stocks = pd.read_csv(quote_path, dtype={'code': str})
        if not stocks['quote_time'].str.startswith(args.date).all():
            raise RuntimeError('Quote snapshot has the wrong date')
        universe_size = int(json.loads((root / 'snapshot' / 'universe.json').read_text())['count'])
    else:
        universe = TencentProvider().get_all_stocks()
        if universe.empty:
            raise RuntimeError('Unable to load the stock universe')
        universe_size = len(universe)
        stocks = quote_snapshot(universe, args.date)
        stocks.to_csv(quote_path, index=False, encoding='utf-8-sig')
        (root / 'snapshot' / 'universe.json').write_text(json.dumps({'count': universe_size}), encoding='utf-8')
    # Zero-volume quotes cannot be screened using current OHLCV.
    active = stocks[(stocks['volume'] > 0) & (stocks['price'] > 0)].copy()
    histories, failures = {}, []
    print(f'SNAPSHOT dated_quotes={len(stocks)} active={len(active)} universe={universe_size}', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(current_history, stock, args.date, hist_dir): stock['code']
                   for stock in active.to_dict('records')}
        for done, future in enumerate(as_completed(pending), 1):
            code = pending[future]
            try:
                histories[code] = future.result()
            except Exception as exc:
                failures.append({'code': code, 'reason': str(exc)})
            if done % 100 == 0 or done == len(pending):
                print(f'HISTORY {done}/{len(pending)} valid={len(histories)} failed={len(failures)}', flush=True)
    pd.DataFrame(failures, columns=['code', 'reason']).to_csv(root / 'snapshot' / 'history_failures.csv', index=False, encoding='utf-8-sig')
    if not histories:
        raise RuntimeError('No daily bars for the requested date')
    eligible = active[active['code'].isin(histories)].copy()
    provider = SnapshotProvider(histories)
    coverage = dict(date=args.date, universe=universe_size, dated_quotes=len(stocks),
                    active=len(active), current_histories=len(histories), excluded_histories=len(failures),
                    first_quote_time=stocks['quote_time'].min(), last_quote_time=stocks['quote_time'].max())
    (root / 'snapshot' / 'coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding='utf-8')
    note = (f'## 数据核对\n\n- 请求日期和实际 K 线日期：{args.date}\n'
            f'- 数据源：腾讯实时报价 + 前复权日线（fqkline）\n'
            f'- 股票列表 {universe_size} 只；当天报价 {len(stocks)} 只；活跃股票 {len(active)} 只；'
            f'当天有效日线 {len(histories)} 只；排除缺失/过期日线 {len(failures)} 只。\n'
            f'- 报价时间：{coverage["first_quote_time"]} 至 {coverage["last_quote_time"]}\n'
            '- 外盘/内盘使用腾讯报价真实字段；板块为代码推断的市场类别，未提供行业分组。\n'
            '- 完整行情快照、日线和排除名单保存在上级 snapshot 文件夹。\n\n')
    manifest = []
    db_store = None
    if not args.no_db:
        from stock_selector.data.postgres_store import PostgresStore
        db_store = PostgresStore(args.db_dsn)
        if not db_store.try_ensure_schema():
            print(f'DATABASE unavailable; reports will still be generated: {db_store.last_error}', flush=True)
            db_store = None

    def save(strategy_id, family, rows, config, status='完成', extra=''):
        directory = root / strategy_id
        directory.mkdir(exist_ok=True)
        report = directory / 'report.md'
        if family == '常规':
            generate(rows, args.date, str(report), config)
        elif family == 'v2':
            generate_v2_report(rows, args.date, str(report), config)
        elif family == '技术':
            write_report({strategy_id: rows}, report)
        else:
            report.write_text(f'# {strategy_id}\n\n状态：{status}\n\n{extra}\n', encoding='utf-8')
        content = report.read_text(encoding='utf-8')
        report.write_text(f'**策略 ID：** {strategy_id}  \n**执行状态：** {status}\n\n' + note + extra + '\n\n' + content, encoding='utf-8')
        pd.DataFrame(plain_rows(rows)).to_csv(directory / 'results.csv', index=False, encoding='utf-8-sig')
        (directory / 'config.json').write_text(json.dumps(config if isinstance(config, dict) else vars(config), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        manifest.append(dict(strategy=strategy_id, family=family, status=status,
                             count=len(rows) if status != '数据不可用' else None,
                             report=f'{strategy_id}/report.md'))
        if db_store is not None:
            try:
                display_name = config.get('name', strategy_id) if isinstance(config, dict) else strategy_id
                if family == '常规':
                    from stock_selector.utils.strategy_names import strategy_display_name
                    display_name = strategy_display_name(
                        strategy_id, config if isinstance(config, dict) else {})
                db_store.save_selection_run(
                    trade_date=datetime.strptime(args.date, '%Y-%m-%d').date(),
                    category=family,
                    strategy_id=strategy_id,
                    strategy_name=display_name,
                    source='tencent',
                    rows=rows,
                    parameters={'status': status, 'batch_output': str(root), 'config': config},
                )
            except Exception as exc:  # noqa: BLE001
                print(f'DATABASE save failed for {strategy_id}: {exc}', flush=True)
        (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'REPORT {strategy_id}: {status}, count={len(rows)}', flush=True)

    presets = load_presets_file()['presets']
    for name, preset in presets.items():
        if preset.get('strategy_type'):
            continue
        config = ScreenerConfig(turnover_min=preset['turnover'], change_min=preset['change'][0],
                                change_max=preset['change'][1], volume_ratio=preset['volume'],
                                top_per_sector=preset['sector'],
                                check_outer_inner=preset['check_outer_inner'], check_kdj=preset['check_kdj'],
                                check_rsi=preset['check_rsi'], filter_cyb=preset['filter_cyb'],
                                filter_kcb=preset['filter_kcb'], request_sleep=0)
        pool = eligible
        if preset.get('mainboard_only'):
            pool = pool[pool['sector'].isin(['上证主板', '深证主板'])]
        rows = ShortTermSelector(config, provider).run(pool)
        save(name, '常规', rows, config)

    technical_results = {item['id']: [] for item in STRATEGIES}
    technical_errors = []
    for done, stock in enumerate(eligible.to_dict('records'), 1):
        code = stock['code']
        prepared = calculate_indicators(histories[code])
        for item in STRATEGIES:
            try:
                match = item['func'](prepared)
                if match['matched']:
                    technical_results[item['id']].append(dict(
                        code=code, name=stock['name'], price=stock['price'],
                        change_pct=stock['change_pct'], sector=stock['sector'],
                        latest_date=args.date, reason=match['reason'], metrics=match['metrics']))
            except Exception as exc:
                technical_errors.append(dict(code=code, strategy=item['id'], reason=str(exc)))
        if done % 500 == 0:
            print(f'TECHNICAL {done}/{len(eligible)}', flush=True)
    pd.DataFrame(technical_errors, columns=['code', 'strategy', 'reason']).to_csv(root / 'snapshot' / 'technical_errors.csv', index=False, encoding='utf-8-sig')
    for item in STRATEGIES:
        count_errors = sum(error['strategy'] == item['id'] for error in technical_errors)
        save(item['id'], '技术', technical_results[item['id']],
             {key: value for key, value in item.items() if key != 'func'},
             '部分完成' if count_errors else '完成', f'计算异常：{count_errors} 只。')

    # Probe data dependencies before running scoring. Missing capital data is
    # stated explicitly; a zero-filled fallback must not appear as a full screen.
    from stock_selector.data.capital_flow_client import CapitalFlowClient
    probes = []
    capital = CapitalFlowClient(timeout=5)
    for code in ['600000', '002565', '600227']:
        flow = capital.get_realtime_flow(code)
        orders = capital.get_big_orders(code)
        probes.append(dict(code=code, flow=flow, orders=0 if orders is None else len(orders)))
    (root / 'snapshot' / 'capital_probes.json').write_text(json.dumps(probes, ensure_ascii=False, indent=2), encoding='utf-8')
    capital_available = any(probe['flow'] and any(probe['flow'].values()) and probe['orders'] for probe in probes)
    if capital_available:
        # Existing client has no validated observation date or current daily-flow
        # schema, so full capital screens require additional validation.
        capital_note = '资金接口返回数据，但当前客户端未校验资金日期/字段单位，未生成资金筛选结论。'
    else:
        capital_note = '资金流向及大单接口探测失败，无法执行有效的资金筛选；此状态不代表没有符合条件的股票。'

    with (PROJECT_ROOT / 'presets_v2.yaml').open(encoding='utf-8') as handle:
        v2_configs = yaml.safe_load(handle)['strategies']
    enhanced = None
    for name in v2_configs:
        adapter = StrategyAdapter(name)
        # Same default fallback as the existing adapter, without repeated network
        # calls after dependency failure. Intraday fields do not enter scoring.
        adapter.sector_client = None
        adapter.capital_client = None
        adapter.intraday_client = UnavailableIntraday()
        if enhanced is None:
            min_turnover = min(cfg['filters']['liquidity']['turnover_min'] for cfg in v2_configs.values())
            min_change = min(cfg['filters']['price']['change_min'] for cfg in v2_configs.values())
            candidates = eligible[(eligible['turnover'] >= min_turnover) & (eligible['change_pct'] >= min_change)]
            enhanced = []
            for _, stock in candidates.iterrows():
                data = adapter._enhance_stock_data(stock, provider)
                if data:
                    enhanced.append(data)
            print(f'V2 enhanced={len(enhanced)} candidates={len(candidates)}', flush=True)
        rows = adapter._convert_to_legacy_format(adapter.scoring_engine.batch_evaluate(enhanced))
        save('v2_' + name, 'v2', rows, adapter.strategy_config, '降级完成',
             '## v2 数据限制\n\n行业相对强度和主力资金数据不可用，沿用现有适配器默认值 0；'
             '外盘比例来自当天报价、成交额单位为亿元。评分仅为降级运行结果，空结果不能证明完整策略无匹配。')
    for name, preset in presets.items():
        if preset.get('strategy_type'):
            save(name, '资金', [], preset, '数据不可用', capital_note)

    lines = [f'# {args.date} 多策略选股汇总', '', note,
             '| 类别 | 策略 | 状态 | 匹配数量 | 报告 |', '|---|---|---|---:|---|']
    for item in manifest:
        count = '未判定' if item['count'] is None else str(item['count'])
        lines.append(f'| {item["family"]} | {item["strategy"]} | {item["status"]} | {count} | [查看]({item["report"]}) |')
    lines.extend(['', 'v2 使用缺失数据默认值运行，资金策略因依赖接口不可用未形成选股结论。',
                  '各策略匹配数包含重复股票，不能相加作为去重股票数。'])
    (root / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'FINISHED {len(manifest)} strategy reports: {root / "summary.md"}', flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
