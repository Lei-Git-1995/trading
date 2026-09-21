"""
短线选股系统入口（主程序）

用法（任选其一）:
    在 E:\\trading 目录下：
        py -3.11 -m stock_selector.main
        py -3.11 -m stock_selector.main --turnover 10 --change -2,2 --volume 2.0
        py -3.11 -m stock_selector.main -i
        py -3.11 -m stock_selector.main --preset aggressive
    或直接进入包目录运行（自动处理包路径）:
        cd stock_selector && py -3.11 main.py -i

输出: stock_selector/output/YYYY-MM-DD.md
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_selector.config import OUTPUT_DIR, build_config
from stock_selector.data.cache import KlineCache
from stock_selector.data.providers import create_provider, interactive_select, list_providers
from stock_selector.reports.markdown_report import generate
from stock_selector.strategies.short_term_selector import ShortTermSelector
from stock_selector.utils.logger import setup_logger, get_logger, get_default_log_file
from stock_selector.utils.config_loader import list_presets, load_preset, print_preset_info, merge_with_preset
from stock_selector.utils.timer import timeit, print_stats, format_time

logger = get_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description='每日短线选股系统（多数据源支持）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例：\n'
               '  py -3.11 -m stock_selector.main --preset aggressive       # 使用激进预设\n'
               '  py -3.11 -m stock_selector.main --turnover 8 --change 0,5 # 自定义参数\n'
               '  py -3.11 -m stock_selector.main -i                         # 交互式输入\n'
               '  py -3.11 -m stock_selector.main --list-presets             # 列出所有预设',
    )

    # 预设相关
    parser.add_argument('--preset', type=str, default=None,
                        help=f'使用预设策略：{", ".join(list_presets())}')
    parser.add_argument('--list-presets', action='store_true',
                        help='列出所有可用的预设策略并退出')

    # 筛选参数（会覆盖预设中的对应值）
    parser.add_argument('--turnover', type=float, default=None, help='最低换手率门槛（%%），默认15')
    parser.add_argument('--change', type=str, default=None,
                        help='涨跌幅区间（%%），格式：最小值,最大值，默认1,3（支持负数，如-2,2）')
    parser.add_argument('--volume', type=float, default=None, help='量能放大倍数，默认1.5')
    parser.add_argument('--sector', type=int, default=None, help='每个板块最多数量，默认20（0不限制）')
    parser.add_argument('--no-outer', action='store_true', help='不检查外盘内盘关系（默认要求外盘>内盘）')
    parser.add_argument('--no-kdj', action='store_true', help='不检查KDJ超买（默认要求K<80）')
    parser.add_argument('--no-rsi', action='store_true', help='不检查RSI超买（默认要求RSI6<70）')
    parser.add_argument('--no-cyb', action='store_true', help='过滤创业板（3开头）')
    parser.add_argument('--no-kcb', action='store_true', help='过滤科创板（688开头）')
    parser.add_argument('--mainboard-only', action='store_true', help='只选主板（同时过滤创业板和科创板）')

    # 交互与数据源
    parser.add_argument('-i', '--interactive', action='store_true',
                        help='交互式手动输入筛选参数（直接回车使用默认值）')
    parser.add_argument('--no-cache', action='store_true', help='不使用K线本地缓存，强制重新拉取')
    parser.add_argument('--source', type=str, default='',
                        help=f'数据源: {", ".join(n for n, _ in list_providers())}，留空则交互选择（默认东财）')

    # 日志相关
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='日志级别，默认INFO')
    parser.add_argument('--log-file', type=str, default=None,
                        help='日志文件路径（默认：logs/YYYY-MM-DD.log）')
    parser.add_argument('--no-log-file', action='store_true',
                        help='不写入日志文件')

    # 输出相关
    parser.add_argument('--show-stats', action='store_true',
                        help='显示详细的执行统计（默认已开启）')

    return parser.parse_args()


def prompt_float(name: str, default: float) -> float:
    raw = input(f'{name}（默认 {default}）: ').strip()
    return float(raw) if raw else default


def prompt_params(args) -> None:
    """交互式手动输入筛选参数"""
    logger.info('—— 手动输入筛选参数（直接回车使用默认值）——')

    # 如果有预设，显示当前值
    default_turnover = args.turnover if args.turnover is not None else 15.0
    default_change = args.change if args.change is not None else '1,3'
    default_volume = args.volume if args.volume is not None else 1.5
    default_sector = args.sector if args.sector is not None else 20

    args.turnover = prompt_float('最低换手率 %', default_turnover)
    raw = input(f'涨跌幅区间 最小值,最大值（默认 {default_change}）: ').strip()
    if raw:
        args.change = raw
    else:
        args.change = default_change
    args.volume = prompt_float('量能放大倍数', default_volume)
    raw_sector = input(f'每个板块最多数量，0不限制（默认 {default_sector}）: ').strip()
    if raw_sector:
        args.sector = int(raw_sector)
    else:
        args.sector = default_sector
    logger.info('-' * 70)


def main():
    # 确保控制台输出使用UTF-8编码
    import sys
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    args = parse_args()

    # 处理 --list-presets
    if args.list_presets:
        print('\n可用的预设策略：')
        print('=' * 70)
        presets = list_presets()
        for preset_name in presets:
            print_preset_info(preset_name)
            print()
        return

    # 初始化日志系统
    log_level_map = {
        'DEBUG': 10,
        'INFO': 20,
        'WARNING': 30,
        'ERROR': 40
    }
    log_level = log_level_map.get(args.log_level.upper(), 20)

    log_file = None
    if not args.no_log_file:
        log_file = args.log_file if args.log_file else get_default_log_file()

    setup_logger(level=log_level, log_file=log_file, enable_color=True)
    logger.info(f'日志级别: {args.log_level}')
    if log_file:
        logger.info(f'日志文件: {log_file}')

    # 加载预设配置
    preset_config = {}
    if args.preset:
        try:
            logger.info(f'加载预设策略: {args.preset}')
            preset_config = load_preset(args.preset)
            print_preset_info(args.preset)
        except ValueError as e:
            logger.error(str(e))
            return

    # 合并预设和命令行参数
    # 预设提供默认值，命令行参数覆盖
    if args.preset:
        # 从预设加载默认值
        if args.turnover is None:
            args.turnover = preset_config.get('turnover', 15.0)
        if args.change is None:
            change_range = preset_config.get('change', [1, 3])
            args.change = f'{change_range[0]},{change_range[1]}'
        if args.volume is None:
            args.volume = preset_config.get('volume', 1.5)
        if args.sector is None:
            args.sector = preset_config.get('sector', 20)

        # 布尔参数：如果预设有设置且命令行未指定，使用预设值
        if not args.no_outer and 'check_outer_inner' in preset_config:
            args.no_outer = not preset_config['check_outer_inner']
        if not args.no_kdj and 'check_kdj' in preset_config:
            args.no_kdj = not preset_config['check_kdj']
        if not args.no_rsi and 'check_rsi' in preset_config:
            args.no_rsi = not preset_config['check_rsi']
        if not args.no_cyb and 'filter_cyb' in preset_config:
            args.no_cyb = preset_config['filter_cyb']
        if not args.no_kcb and 'filter_kcb' in preset_config:
            args.no_kcb = preset_config['filter_kcb']
        if not args.mainboard_only and 'mainboard_only' in preset_config:
            args.mainboard_only = preset_config['mainboard_only']
    else:
        # 没有预设，使用默认值
        if args.turnover is None:
            args.turnover = 15.0
        if args.change is None:
            args.change = '1,3'
        if args.volume is None:
            args.volume = 1.5
        if args.sector is None:
            args.sector = 20

    # 交互式输入
    if args.interactive:
        prompt_params(args)

    # 处理 --mainboard-only 参数
    if args.mainboard_only:
        args.no_cyb = True
        args.no_kcb = True
        logger.info('启用主板模式：已过滤创业板和科创板')

    # 解析涨跌幅区间
    try:
        lo, hi = args.change.split(',')
        change_min, change_max = float(lo), float(hi)
        if change_min > change_max:
            logger.error('错误：涨跌幅最小值不能大于最大值')
            return
    except ValueError:
        logger.error('错误：--change 格式应为 "最小值,最大值"，如 1,3 或 -2,2')
        return

    config = build_config(
        turnover_min=args.turnover,
        change_min=change_min,
        change_max=change_max,
        volume_ratio=args.volume,
        top_per_sector=args.sector,
        check_outer_inner=not args.no_outer,
        check_kdj=not args.no_kdj,
        check_rsi=not args.no_rsi,
        filter_cyb=args.no_cyb,
        filter_kcb=args.no_kcb,
    )

    # 0. 数据源选择
    source = args.source if args.source else interactive_select()
    if source not in {n for n, _ in list_providers()}:
        logger.error(f'错误：未知数据源 {source}，可选: {", ".join(n for n, _ in list_providers())}')
        return
    provider = create_provider(source)

    logger.info('=' * 70)
    logger.info('每日短线选股系统')
    logger.info(f'执行时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    logger.info(f'数据源: {[d for n, d in list_providers() if n == source][0]}')
    logger.info(f'筛选参数: 换手>{args.turnover}%  涨幅{change_min}~{change_max}%  '
                f'量能>{args.volume}倍  板块上限={config.top_per_sector}')
    logger.info('=' * 70)

    # 1. 获取行情列表
    with timeit('获取行情列表'):
        logger.info('[1/4] 获取沪深A股行情...')
        stock_list = provider.get_all_stocks()
        if stock_list is None or stock_list.empty:
            logger.error('\n错误：无法获取股票数据，请检查网络')
            return
        logger.info(f'  有效A股: {len(stock_list)} 只')

    # 2. 策略筛选
    cache = None if args.no_cache else KlineCache(ttl_hours=config.cache_ttl_hours, namespace=source)
    selector = ShortTermSelector(config, client=provider, cache=cache)

    with timeit('策略筛选'):
        results = selector.run(stock_list)

    # 3. 生成 Markdown 报告
    data_date = datetime.now().strftime('%Y-%m-%d')
    if results:
        hist_dates = []
        for s in results:
            hd = s.get('hist_data')
            if hd is not None and not hd.empty:
                hist_dates.append(str(hd['日期'].iloc[-1]))
        if hist_dates:
            data_date = max(hist_dates)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = str(OUTPUT_DIR / f'{datetime.now().strftime("%Y-%m-%d")}.md')

    with timeit('生成报告'):
        generate(results, data_date, output_file, config)

    logger.info('\n' + '=' * 70)
    logger.info(f'完成: 选出 {len(results)} 只')
    for i, s in enumerate(results[:5], 1):
        logger.info(f'  {i}. {s["code"]} {s["name"]}  '
                    f'涨{s["change_pct"]:.2f}%  换手{s["turnover"]:.1f}%  '
                    f'量比{s["volume_ratio"]:.2f}  {s["score"]}分')
    logger.info(f'报告: {output_file}')
    logger.info('=' * 70)

    # 显示性能统计
    print_stats()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n程序被用户中断')
    except Exception as e:
        print(f'\n程序执行出错: {e}')
        import traceback
        traceback.print_exc()