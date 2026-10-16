# -*- coding: utf-8 -*-
"""Agent 命令行入口。

用法（项目根 E:\\trading 下）：
    py -3.11 -m stock_selector.agent init
    py -3.11 -m stock_selector.agent once [--session intraday|learn]
    py -3.11 -m stock_selector.agent run
    py -3.11 -m stock_selector.agent list [--limit 20]
    py -3.11 -m stock_selector.agent show --id 3

大模型参数读取项目根目录的 config.local.json（见 stock_selector.utils.app_config）。
"""
from __future__ import annotations

import argparse
import sys

from stock_selector.agent import config as agent_config
from stock_selector.agent.scheduler import AgentScheduler, run_analysis_once
from stock_selector.agent.storage import AgentStore
from stock_selector.data.postgres_store import PostgresStore
from stock_selector.utils import app_config


def _make_stores(dsn=None):
    store = PostgresStore(dsn)
    if not store.try_ensure_schema():
        print(f'数据库连接失败：{store.last_error}')
        return None, None
    agent_store = AgentStore(store)
    if not agent_store.try_ensure_schema():
        print(f'Agent 表初始化失败：{store.last_error}')
        return None, None
    return store, agent_store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m stock_selector.agent',
        description='LLM 持续分析 Agent：盘中定期分析候选股票并入库。')
    parser.add_argument('--dsn', help='PostgreSQL DSN')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('init', help='创建 Agent 相关数据表')

    p_once = sub.add_parser('once', help='立即执行一次分析')
    p_once.add_argument('--session', default='intraday', choices=('intraday', 'learn'))

    p_run = sub.add_parser('run', help='前台运行调度器（盘中每5分钟 + 学习时段）')

    p_list = sub.add_parser('list', help='列出最近分析批次')
    p_list.add_argument('--limit', type=int, default=20)

    p_show = sub.add_parser('show', help='查看某批次分析明细')
    p_show.add_argument('--id', type=int, required=True)

    args = parser.parse_args(argv)
    if args.command is None:
        args.command = 'init'

    store, agent_store = _make_stores(args.dsn)
    if store is None:
        return 1

    if args.command == 'init':
        print('Agent 表结构初始化完成。')
        return 0

    if args.command == 'once':
        cfg = agent_config.merge_config(app_config.get_agent_config(), {'enabled': True})
        result = run_analysis_once(store=store, agent_store=agent_store,
                                   llm_settings=app_config.get_llm_config(),
                                   agent_cfg=cfg,
                                   trigger='manual', session=args.session, log=print)
        print(f"\n状态: {result.get('status')}  模型: {result.get('model')}")
        if result.get('summary'):
            print(f"摘要: {result['summary']}")
        if result.get('market_view'):
            print(f"研判: {result['market_view']}")
        for pick in result.get('picks') or []:
            print(f"  #{pick.get('rank')} {pick.get('code')} {pick.get('name')} "
                  f"{pick.get('action')} 置信{pick.get('confidence')} — {pick.get('reason')}")
        if result.get('error'):
            print(f"错误: {result['error']}")
        return 0

    if args.command == 'run':
        cfg = agent_config.merge_config(app_config.get_agent_config(), {'enabled': True})
        scheduler = AgentScheduler(store=store, agent_store=agent_store,
                                   llm_settings=app_config.get_llm_config(),
                                   agent_cfg=cfg, log=print)
        scheduler.start()
        print('调度器运行中，按 Ctrl+C 退出…')
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop()
            print('\n已退出。')
        return 0

    if args.command == 'list':
        for row in agent_store.list_analyses(limit=args.limit):
            print(f"#{row['id']} {row['created_at']} {row['session']}/{row['trigger']} "
                  f"[{row['status']}] picks={row['picks_count']} tools={row['tool_calls']} "
                  f"- {(row['summary'] or row['error'] or '')[:60]}")
        return 0

    if args.command == 'show':
        info = agent_store.get_analysis(args.id)
        if not info:
            print(f'未找到批次 #{args.id}')
            return 1
        print(f"批次 #{info['id']}  {info['created_at']}  {info['session']}/{info['trigger']} "
              f"[{info['status']}]  model={info['model']}")
        if info.get('summary'):
            print(f"摘要: {info['summary']}")
        if info.get('market_view'):
            print(f"研判: {info['market_view']}")
        for pick in agent_store.get_picks(args.id):
            print(f"  #{pick['rank']} {pick['code']} {pick['name']} {pick['action']} "
                  f"置信{pick['confidence']} — {pick['reason']}")
        if info.get('error'):
            print(f"错误: {info['error']}")
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
