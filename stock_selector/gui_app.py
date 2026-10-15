#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股选股器 · 图形界面入口

功能：
    - 选择免费数据源（腾讯 / 东方财富 / 新浪-AKShare / 智能）
    - 选择策略（常规预设 / 技术形态 / v2 评分）
    - 一键拉取行情并选股，表格展示结果
    - 导出结果为 CSV

可打包为 exe（见 stock_selector/build_gui.ps1）。
"""
from __future__ import annotations

import io
import queue
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from stock_selector.data.postgres_store import PostgresStore
from stock_selector.data.market_board import fetch_market_snapshot


# ---------------------------------------------------------------
# stdout / stderr 重定向到界面日志框
# ---------------------------------------------------------------

class _QueueWriter(io.TextIOBase):
    def __init__(self, q: "queue.Queue[str]"):
        self._q = q

    def write(self, s):  # noqa: D401
        n = len(s)
        if not s:
            return n
        # 忽略纯空白填充（tqdm 清行产生的空格）
        if not s.strip() and '\n' not in s:
            return n
        if '\r' in s:
            # tqdm 之类用 '\r' 刷新进度：只保留最后一个回车之后的内容
            tail = s.rsplit('\r', 1)[-1]
            # 若剩下部分仍像进度条（含 '|' 且含 '%' / 'it/s'），整体丢弃
            if '|' in tail and ('%' in tail or 'it/s' in tail or '/s' in tail):
                return n
            s = tail
        if s:
            self._q.put(s)
        return n

    def flush(self):
        pass


# ---------------------------------------------------------------
# 配置
# ---------------------------------------------------------------

SOURCE_CHOICES = [
    ('智能选择', None),
    ('腾讯', 'tencent'),
    ('东方财富', 'eastmoney'),
    ('新浪(AKShare)', 'akshare'),
]

CATEGORY_PRESET = '常规预设'
CATEGORY_TECH = '技术形态'
CATEGORY_V2 = 'v2评分'
CATEGORY_CHOICES = [CATEGORY_PRESET, CATEGORY_TECH, CATEGORY_V2]

# 表格列（顺序）
COLUMNS = ('代码', '名称', '行业/板块', '价格', '涨跌幅%', '换手%', '量比',
           '成交量', '成交额(亿)', '评分', '日期', '说明')
COL_WIDTHS = {'代码': 70, '名称': 100, '行业/板块': 110, '价格': 70, '涨跌幅%': 70,
              '换手%': 70, '量比': 60, '成交量': 85, '成交额(亿)': 90,
              '评分': 60, '日期': 90, '说明': 420}
# 数值列右对齐，其余左对齐；表头与单元格用同一对齐方式，避免表头/数据错位
COL_RIGHT = {'价格', '涨跌幅%', '换手%', '量比', '成交量', '成交额(亿)', '评分'}


def _fmt(value, nd=2):
    if value is None:
        return ''
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f'{f:.{nd}f}'


class StockSelectorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('A股选股器 · 免费数据源')
        self.root.geometry('1180x720')
        self.root.minsize(980, 600)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.result_rows: list[dict] = []
        self.last_export_columns: list[str] = []
        self.strategy_ids_by_label: dict[str, str] = {}
        self.db_store = PostgresStore()
        self.db_ready = False
        self.auto_refresh_job = None
        self.running = False
        self.market_refreshing = False

        self._install_stdout_redirect()
        self._init_logging()
        self._build_ui()
        self._refresh_strategies()

        self.root.after(120, self._poll_log)
        self.root.after(300, self._init_database)
        self.root.after(600, self._market_timer)

    # ---------------- 基础 ----------------

    def _install_stdout_redirect(self):
        writer = _QueueWriter(self.log_queue)
        sys.stdout = writer
        sys.stderr = writer

    def _init_logging(self):
        try:
            from stock_selector.utils.logger import setup_logger
            setup_logger(level=20, log_file=None, enable_color=False, force=True)
        except Exception:
            pass

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill='x')

        ttk.Label(top, text='数据源:').grid(row=0, column=0, padx=(0, 4))
        self.source_var = tk.StringVar(value=SOURCE_CHOICES[0][0])
        self.source_box = ttk.Combobox(
            top, textvariable=self.source_var, width=14, state='readonly',
            values=[name for name, _ in SOURCE_CHOICES])
        self.source_box.grid(row=0, column=1, padx=(0, 14))

        ttk.Label(top, text='策略类别:').grid(row=0, column=2, padx=(0, 4))
        self.category_var = tk.StringVar(value=CATEGORY_PRESET)
        self.category_box = ttk.Combobox(
            top, textvariable=self.category_var, width=12, state='readonly',
            values=CATEGORY_CHOICES)
        self.category_box.grid(row=0, column=3, padx=(0, 14))
        self.category_box.bind('<<ComboboxSelected>>', lambda e: self._refresh_strategies())

        ttk.Label(top, text='策略:').grid(row=0, column=4, padx=(0, 4))
        self.strategy_var = tk.StringVar(value='')
        self.strategy_box = ttk.Combobox(
            top, textvariable=self.strategy_var, width=26, state='readonly', values=[])
        self.strategy_box.grid(row=0, column=5, padx=(0, 14))

        ttk.Label(top, text='处理上限(0=全部):').grid(row=0, column=6, padx=(0, 4))
        self.limit_var = tk.StringVar(value='500')
        ttk.Entry(top, textvariable=self.limit_var, width=7).grid(row=0, column=7, padx=(0, 14))

        self.exclude_st_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text='排除ST/退市', variable=self.exclude_st_var).grid(
            row=0, column=8, padx=(0, 14))

        self.run_btn = ttk.Button(top, text='开始选股', command=self._on_run)
        self.run_btn.grid(row=0, column=9, padx=(0, 8))

        self.export_btn = ttk.Button(top, text='导出CSV', command=self._on_export, state='disabled')
        self.export_btn.grid(row=0, column=10)

        refresh = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        refresh.pack(fill='x')
        self.auto_refresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(refresh, text='自动刷新', variable=self.auto_refresh_var,
                        command=self._toggle_auto_refresh).pack(side='left')
        ttk.Label(refresh, text='间隔(秒):').pack(side='left', padx=(10, 3))
        self.refresh_interval_var = tk.StringVar(value='60')
        ttk.Combobox(refresh, textvariable=self.refresh_interval_var, width=6,
                     state='readonly', values=('30', '60', '120', '300')).pack(side='left')
        self.filter_cyb_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(refresh, text='排除创业板(3开头)', variable=self.filter_cyb_var).pack(
            side='left', padx=(14, 0))
        self.filter_kcb_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(refresh, text='排除科创板(688开头)', variable=self.filter_kcb_var).pack(
            side='left', padx=(14, 0))
        ttk.Label(refresh, text='首次运行会建立 K 线缓存，后续刷新会复用缓存。').pack(
            side='left', padx=(12, 0))

        # 结果表格 + 右侧大盘/板块面板
        body = ttk.PanedWindow(self.root, orient='horizontal')
        body.pack(fill='both', expand=True, padx=10, pady=(6, 0))

        tree_frame = ttk.Frame(body)
        body.add(tree_frame, weight=4)
        self.tree = ttk.Treeview(tree_frame, columns=COLUMNS, show='headings', height=16)
        for col in COLUMNS:
            anchor = 'e' if col in COL_RIGHT else 'w'
            self.tree.heading(col, text=col, anchor=anchor)
            self.tree.column(col, width=COL_WIDTHS.get(col, 90), anchor=anchor,
                             stretch=(col == '说明'))
        vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')

        market_frame = ttk.Frame(body, width=340)
        body.add(market_frame, weight=1)
        self._build_market_panel(market_frame)

        # 自选股 / 历史选股查询（可切换标签页，避免纵向无限拉长）
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='x', padx=10, pady=(6, 0))
        watch_frame = ttk.Frame(notebook, padding=(6, 6))
        query_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(watch_frame, text='自选股分组')
        notebook.add(query_frame, text='历史选股查询')

        # AI 交易
        trade_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(trade_frame, text='AI 交易')
        trade_top = ttk.Frame(trade_frame)
        trade_top.pack(fill='x')
        ttk.Label(trade_top, text='账户:').pack(side='left')
        self.trade_account_var = tk.StringVar(value='模拟盘')
        self.trade_account_box = ttk.Combobox(trade_top, textvariable=self.trade_account_var, width=14, values=[])
        self.trade_account_box.pack(side='left', padx=(4, 8))
        self.trade_account_box.bind('<<ComboboxSelected>>', lambda e: self._load_trade_account())
        ttk.Label(trade_top, text='通道:').pack(side='left')
        self.trade_channel_var = tk.StringVar(value='manual')
        ttk.Combobox(trade_top, textvariable=self.trade_channel_var, width=12, state='readonly',
                     values=('manual', 'easytrader')).pack(side='left', padx=(4, 8))
        ttk.Button(trade_top, text='保存账户', command=self._save_trade_account).pack(side='left', padx=2)
        ttk.Button(trade_top, text='AI 分析当前结果', command=self._ai_analyze).pack(side='left', padx=(12, 2))
        ttk.Button(trade_top, text='执行 AI 委托', command=self._execute_ai_orders).pack(side='left', padx=2)
        trade_settings = ttk.Frame(trade_frame)
        trade_settings.pack(fill='x', pady=(6, 0))
        ttk.Label(trade_settings, text='API Key:').grid(row=0, column=0, sticky='w')
        self.ai_key_var = tk.StringVar(value='')
        ttk.Entry(trade_settings, textvariable=self.ai_key_var, width=30, show='*').grid(row=0, column=1, padx=(4, 12), sticky='w')
        ttk.Label(trade_settings, text='模型:').grid(row=0, column=2, sticky='w')
        self.ai_model_var = tk.StringVar(value='gpt-4o-mini')
        ttk.Entry(trade_settings, textvariable=self.ai_model_var, width=16).grid(row=0, column=3, padx=(4, 12), sticky='w')
        ttk.Label(trade_settings, text='API 地址:').grid(row=0, column=4, sticky='w')
        self.ai_base_url_var = tk.StringVar(value='https://api.openai.com/v1')
        ttk.Entry(trade_settings, textvariable=self.ai_base_url_var, width=30).grid(row=0, column=5, padx=(4, 12), sticky='w')
        ttk.Label(trade_settings, text='同花顺路径(可选):').grid(row=1, column=0, sticky='w', pady=(5, 0))
        self.ths_exe_var = tk.StringVar(value='')
        ttk.Entry(trade_settings, textvariable=self.ths_exe_var, width=30).grid(row=1, column=1, padx=(4, 12), sticky='w', pady=(5, 0))
        ttk.Label(trade_settings, text='单只最大仓位%:').grid(row=1, column=2, sticky='w', pady=(5, 0))
        self.ai_position_var = tk.StringVar(value='10')
        ttk.Entry(trade_settings, textvariable=self.ai_position_var, width=8).grid(row=1, column=3, padx=(4, 12), sticky='w', pady=(5, 0))
        ttk.Label(trade_frame, text='manual 只生成待确认委托；easytrader 需要先安装并登录同花顺客户端。', foreground='#666').pack(anchor='w', pady=(8, 0))

        # 自选股分组
        watch_controls = ttk.Frame(watch_frame)
        watch_controls.pack(fill='x')
        ttk.Label(watch_controls, text='分组:').pack(side='left')
        self.watch_group_var = tk.StringVar(value='')
        self.watch_group_box = ttk.Combobox(
            watch_controls, textvariable=self.watch_group_var, width=16, state='readonly', values=[])
        self.watch_group_box.pack(side='left', padx=(4, 6))
        self.watch_group_box.bind('<<ComboboxSelected>>', lambda e: self._refresh_watch_stocks())
        ttk.Button(watch_controls, text='新建分组', command=self._on_new_watch_group).pack(side='left', padx=2)
        ttk.Button(watch_controls, text='加入选中结果',
                   command=self._on_add_selected_watch).pack(side='left', padx=(12, 2))
        ttk.Label(watch_controls, text='代码:').pack(side='left', padx=(12, 2))
        self.watch_code_var = tk.StringVar(value='')
        ttk.Entry(watch_controls, textvariable=self.watch_code_var, width=9).pack(side='left')
        ttk.Label(watch_controls, text='名称:').pack(side='left', padx=(6, 2))
        self.watch_name_var = tk.StringVar(value='')
        ttk.Entry(watch_controls, textvariable=self.watch_name_var, width=12).pack(side='left')
        ttk.Button(watch_controls, text='添加', command=self._on_add_watch).pack(side='left', padx=4)
        ttk.Button(watch_controls, text='移除选中', command=self._on_remove_watch).pack(side='left', padx=2)

        self.watch_tree = ttk.Treeview(
            watch_frame, columns=('代码', '名称', '备注'), show='headings', height=3)
        for col, width in (('代码', 80), ('名称', 120), ('备注', 300)):
            self.watch_tree.heading(col, text=col)
            self.watch_tree.column(col, width=width, anchor='w')
        self.watch_tree.pack(fill='x', expand=True, pady=(4, 0))

        # 历史选股查询（PostgreSQL 后端）
        q_controls = ttk.Frame(query_frame)
        q_controls.pack(fill='x')
        ttk.Label(q_controls, text='日期:').pack(side='left')
        self.q_date_var = tk.StringVar(value='')
        self.q_date_box = ttk.Combobox(
            q_controls, textvariable=self.q_date_var, width=12, values=[])
        self.q_date_box.pack(side='left', padx=(4, 8))
        ttk.Label(q_controls, text='类别:').pack(side='left')
        self.q_category_var = tk.StringVar(value='')
        self.q_category_box = ttk.Combobox(
            q_controls, textvariable=self.q_category_var, width=10, state='readonly', values=[])
        self.q_category_box.pack(side='left', padx=(4, 8))
        self.q_category_box.bind('<<ComboboxSelected>>', lambda e: self._refresh_query_strategies())
        ttk.Label(q_controls, text='策略:').pack(side='left')
        self.q_strategy_var = tk.StringVar(value='')
        self.q_strategy_box = ttk.Combobox(
            q_controls, textvariable=self.q_strategy_var, width=22, state='readonly', values=[])
        self.q_strategy_box.pack(side='left', padx=(4, 8))
        ttk.Button(q_controls, text='查询批次', command=self._on_query_runs).pack(side='left', padx=2)

        q_row2 = ttk.Frame(query_frame)
        q_row2.pack(fill='x', pady=(6, 0))
        ttk.Label(q_row2, text='批次:').pack(side='left')
        self.q_run_var = tk.StringVar(value='')
        self.q_run_box = ttk.Combobox(
            q_row2, textvariable=self.q_run_var, width=64, state='readonly', values=[])
        self.q_run_box.pack(side='left', padx=(4, 8))
        self.q_run_box.bind('<<ComboboxSelected>>', lambda e: self._on_query_run_selected())
        ttk.Label(query_frame, text='查询结果展示在上方主表格，可点击「导出CSV」保存。',
                  foreground='#666').pack(anchor='w', pady=(6, 0))

        # 日志区
        log_frame = ttk.LabelFrame(self.root, text='运行日志', padding=(6, 4))
        log_frame.pack(fill='both', expand=False, padx=10, pady=(6, 4))
        self.log_text = tk.Text(log_frame, height=8, wrap='word', state='disabled')
        log_scroll = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        log_scroll.pack(side='right', fill='y')

        self.status_var = tk.StringVar(value='就绪')
        ttk.Label(self.root, textvariable=self.status_var, anchor='w', padding=(12, 2)).pack(
            fill='x', side='bottom')

    # ---------------- 大盘 / 板块面板 ----------------

    def _build_market_panel(self, parent):
        market = ttk.LabelFrame(parent, text='大盘数据', padding=(6, 4))
        market.pack(fill='x')
        self.market_state_var = tk.StringVar(value='加载中…')
        ttk.Label(market, textvariable=self.market_state_var, anchor='w',
                  foreground='#666').pack(fill='x')
        self.idx_tree = ttk.Treeview(
            market, columns=('指数', '点位', '涨跌幅'), show='headings', height=6)
        for col, width, anchor in (('指数', 90, 'w'), ('点位', 90, 'e'), ('涨跌幅', 80, 'e')):
            self.idx_tree.heading(col, text=col, anchor=anchor)
            self.idx_tree.column(col, width=width, anchor=anchor, stretch=(col == '指数'))
        self.idx_tree.tag_configure('up', foreground='#d0021b')
        self.idx_tree.tag_configure('down', foreground='#009900')
        self.idx_tree.pack(fill='x', pady=(4, 0))

        board = ttk.LabelFrame(parent, text='行业板块', padding=(6, 4))
        board.pack(fill='both', expand=True, pady=(6, 0))
        self.board_sort_var = tk.StringVar(value='')
        ttk.Label(board, textvariable=self.board_sort_var, anchor='w',
                  foreground='#666').pack(fill='x')
        ttk.Label(board, text='涨幅榜', anchor='w').pack(fill='x')
        self.board_up_tree = self._mk_board_tree(board, 7)
        ttk.Label(board, text='跌幅榜', anchor='w').pack(fill='x')
        self.board_down_tree = self._mk_board_tree(board, 7)

        ttk.Button(parent, text='刷新大盘/板块', command=self._on_refresh_market).pack(
            fill='x', pady=(6, 0))

    @staticmethod
    def _mk_board_tree(parent, height):
        tree = ttk.Treeview(
            parent, columns=('板块', '涨跌%', '上涨比', '主力亿', '主力%'), show='headings', height=height)
        for col, width, anchor in (('板块', 90, 'w'), ('涨跌%', 58, 'e'),
                                   ('上涨比', 58, 'e'), ('主力亿', 70, 'e'), ('主力%', 58, 'e')):
            tree.heading(col, text=col, anchor=anchor)
            tree.column(col, width=width, anchor=anchor)
        tree.tag_configure('up', foreground='#d0021b')
        tree.tag_configure('down', foreground='#009900')
        tree.pack(fill='x')
        return tree

    def _on_refresh_market(self):
        self._refresh_market_async()

    def _market_timer(self):
        self._refresh_market_async()
        self.root.after(30000, self._market_timer)

    def _refresh_market_async(self):
        if self.market_refreshing:
            return
        self.market_refreshing = True
        self.market_state_var.set('刷新中…')
        threading.Thread(target=self._fetch_market_worker, daemon=True).start()

    def _fetch_market_worker(self):
        try:
            data = fetch_market_snapshot(board_limit=8)
        except Exception:
            data = None
        self.log_queue.put(('market', data))

    def _render_market(self, data):
        self.market_refreshing = False
        if not data:
            self.market_state_var.set('大盘数据获取失败')
            return
        self.idx_tree.delete(*self.idx_tree.get_children())
        for idx in data.get('indices', []):
            pct = idx.get('pct_chg', 0.0)
            tag = 'up' if pct > 0.005 else ('down' if pct < -0.005 else '')
            self.idx_tree.insert(
                '', 'end', tags=(tag,) if tag else (),
                values=(idx.get('name', ''), f"{idx.get('close', 0):.2f}", f"{pct:+.2f}%"))
        self._fill_board_tree(self.board_up_tree, data.get('gainers', []))
        self._fill_board_tree(self.board_down_tree, data.get('losers', []))
        label = {
            'main_net_yi': '主力净流入',
            'pct_chg_5d': '5日涨跌幅',
            'pct_chg': '今日涨跌幅',
        }.get(data.get('sort_key'), '主力净流入')
        source = data.get('board_source')
        self.board_sort_var.set(f'按{label}排序 · {source}' if source else f'按{label}排序')
        self.market_state_var.set(f"更新 {data.get('time', '')}")

    def _fill_board_tree(self, tree, rows):
        tree.delete(*tree.get_children())
        for b in rows:
            pct = b.get('pct_chg')
            pct5 = b.get('pct_chg_5d')
            ref = pct if pct is not None else pct5
            ref = ref or 0.0
            tag = 'up' if ref > 0.005 else ('down' if ref < -0.005 else '')
            up_ratio = b.get('up_ratio')
            tree.insert(
                '', 'end', tags=(tag,) if tag else (),
                values=(b.get('name', ''), self._fmt_signed(pct),
                        '—' if up_ratio is None else f'{up_ratio * 100:.1f}%',
                        self._fmt_signed(b.get('main_net_yi')),
                        self._fmt_signed(b.get('main_net_pct'))))

    @staticmethod
    def _fmt_signed(value):
        return '—' if value is None else f'{value:+.2f}'

    # ---------------- 策略列表 ----------------

    def _init_database(self):
        if self.db_store.try_ensure_schema():
            self.db_ready = True
            print('数据库：PostgreSQL 已连接，选股结果会自动保存。')
            self._refresh_watch_groups()
            self._refresh_query_sources()
            self._refresh_trade_accounts()
        else:
            self.db_ready = False
            print(f'数据库：未连接，仍可正常选股（{self.db_store.last_error}）。')

    def _ensure_db_ready(self):
        if self.db_ready:
            return True
        if self.db_store.try_ensure_schema():
            self.db_ready = True
            print('数据库：PostgreSQL 已连接。')
            self._refresh_watch_groups()
            self._refresh_query_sources()
            return True
        return False

    def _refresh_watch_groups(self):
        if not self.db_ready:
            return
        try:
            names = [item['name'] for item in self.db_store.list_groups()]
            self.watch_group_box.configure(values=names)
            current = self.watch_group_var.get()
            if current not in names:
                self.watch_group_var.set(names[0] if names else '')
            self._refresh_watch_stocks()
        except Exception as exc:  # noqa: BLE001
            self.db_ready = False
            print(f'数据库读取失败：{exc}')

    def _refresh_watch_stocks(self):
        if not hasattr(self, 'watch_tree'):
            return
        self.watch_tree.delete(*self.watch_tree.get_children())
        group = self.watch_group_var.get()
        if not self.db_ready or not group:
            return
        try:
            for stock in self.db_store.list_stocks(group):
                self.watch_tree.insert('', 'end', values=(stock['code'], stock['name'], stock['note']))
        except Exception as exc:  # noqa: BLE001
            print(f'自选股读取失败：{exc}')

    def _refresh_trade_accounts(self):
        if not hasattr(self, 'trade_account_box') or not self.db_ready:
            return
        try:
            accounts = self.db_store.list_accounts()
            names = [item['name'] for item in accounts]
            self.trade_account_box.configure(values=names)
            if names and self.trade_account_var.get() not in names:
                self.trade_account_var.set(names[0])
            self._load_trade_account()
        except Exception as exc:  # noqa: BLE001
            print(f'交易账户读取失败: {exc}')

    def _load_trade_account(self):
        if not self.db_ready:
            return
        try:
            account = self.db_store.get_account(self.trade_account_var.get().strip())
            if not account:
                return
            settings = account.get('settings') or {}
            self.trade_channel_var.set(account.get('channel') or 'manual')
            self.ai_key_var.set(settings.get('api_key') or '')
            self.ai_base_url_var.set(settings.get('base_url') or 'https://api.openai.com/v1')
            self.ai_model_var.set(settings.get('model') or 'gpt-4o-mini')
            self.ths_exe_var.set(settings.get('exe_path') or '')
            self.ai_position_var.set(str(settings.get('max_position_pct', 10)))
        except Exception as exc:  # noqa: BLE001
            print(f'交易账户加载失败: {exc}')

    def _save_trade_account(self):
        if not self._ensure_db_ready():
            messagebox.showwarning('数据库未连接', '请先启动本地 PostgreSQL。')
            return
        name = self.trade_account_var.get().strip() or '模拟盘'
        try:
            max_pct = float(self.ai_position_var.get() or 10)
        except ValueError:
            max_pct = 10.0
        settings = {'api_key': self.ai_key_var.get().strip(),
                    'base_url': self.ai_base_url_var.get().strip(),
                    'model': self.ai_model_var.get().strip(),
                    'exe_path': self.ths_exe_var.get().strip(),
                    'max_position_pct': max_pct}
        try:
            self.db_store.upsert_account(name, self.trade_channel_var.get(), settings)
            self._refresh_trade_accounts()
            messagebox.showinfo('保存成功', '交易账户配置已保存。')
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('保存失败', str(exc))

    def _trade_account(self):
        if not self._ensure_db_ready():
            return None
        account = self.db_store.get_account(self.trade_account_var.get().strip())
        if not account:
            messagebox.showwarning('提示', '请先填写并保存交易账户配置。')
        return account

    def _ai_analyze(self):
        if not self.result_rows:
            messagebox.showwarning('提示', '请先运行选股，生成候选股票。')
            return
        account = self._trade_account()
        if not account:
            return
        settings = account.get('settings') or {}
        from stock_selector.trading.ai_trader import AIAdvisor
        try:
            max_pct = float(settings.get('max_position_pct', self.ai_position_var.get() or 10))
            advisor = AIAdvisor(settings.get('api_key') or self.ai_key_var.get(),
                                settings.get('base_url') or self.ai_base_url_var.get(),
                                settings.get('model') or self.ai_model_var.get())
            self.last_ai_decision = advisor.analyze(self.result_rows, max_position_pct=max_pct)
            orders = advisor.normalize_orders(self.last_ai_decision)
            summary = self.last_ai_decision.get('summary', '')
            lines = [f"{o['action']} {o['code']} {o['volume']}股 @ {o['price']}：{o['reason']}" for o in orders]
            messagebox.showinfo('AI 交易计划', f'{summary}\n\n计划委托 {len(orders)} 笔:\n' + '\n'.join(lines))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('AI 分析失败', str(exc))

    def _execute_ai_orders(self):
        account = self._trade_account()
        decision = getattr(self, 'last_ai_decision', None)
        if not account or not decision:
            messagebox.showwarning('提示', '请先保存账户并执行 AI 分析。')
            return
        from stock_selector.trading.ai_trader import AIAdvisor
        from stock_selector.trading.ths_client import make_executor
        orders = AIAdvisor.normalize_orders(decision)
        if not orders:
            messagebox.showinfo('提示', '当前没有可执行委托。')
            return
        if not messagebox.askyesno('确认执行', f'将处理 {len(orders)} 笔委托，是否继续？'):
            return
        settings = account.get('settings') or {}
        executor = make_executor(account.get('channel'), settings)
        results = []
        for order in orders:
            order_id = self.db_store.save_order(account['id'], **order)
            try:
                result = (executor.buy if order['action'] == 'buy' else executor.sell)(order['code'], order['price'], order['volume'])
                self.db_store.update_order_status(order_id, result.get('status', 'submitted'), result)
                results.append(f"{order['code']} {result.get('message', result.get('status', '完成'))}")
            except Exception as exc:  # noqa: BLE001
                self.db_store.update_order_status(order_id, 'failed', {'error': str(exc)})
                results.append(f"{order['code']} 失败: {exc}")
        messagebox.showinfo('委托结果', '\n'.join(results))

    def _toggle_auto_refresh(self):
        if self.auto_refresh_job is not None:
            self.root.after_cancel(self.auto_refresh_job)
            self.auto_refresh_job = None
        if self.auto_refresh_var.get():
            self._schedule_auto_refresh()

    def _schedule_auto_refresh(self):
        try:
            seconds = max(10, int(self.refresh_interval_var.get() or '60'))
        except ValueError:
            seconds = 60
        self.auto_refresh_job = self.root.after(seconds * 1000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        self.auto_refresh_job = None
        if self.auto_refresh_var.get():
            if not self.running:
                self._on_run()
            self._schedule_auto_refresh()

    def _on_new_watch_group(self):
        if not self._ensure_db_ready():
            messagebox.showwarning('数据库未连接', '请先启动本地 PostgreSQL 并配置数据库连接。')
            return
        from tkinter import simpledialog
        name = simpledialog.askstring('新建分组', '分组名称：', parent=self.root)
        if not name:
            return
        try:
            self.db_store.create_group(name)
            self._refresh_watch_groups()
            self.watch_group_var.set(name.strip())
            self._refresh_watch_stocks()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('新建分组失败', str(exc))

    def _on_add_watch(self, code=None, name=None):
        if not self._ensure_db_ready():
            messagebox.showwarning('数据库未连接', '请先启动本地 PostgreSQL 并配置数据库连接。')
            return
        group = self.watch_group_var.get()
        code = code or self.watch_code_var.get()
        name = name if name is not None else self.watch_name_var.get()
        if not group:
            messagebox.showwarning('提示', '请先新建或选择一个分组。')
            return
        try:
            self.db_store.add_stock(group, code, name)
            self.watch_code_var.set('')
            self.watch_name_var.set('')
            self._refresh_watch_stocks()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('添加自选股失败', str(exc))

    def _on_add_selected_watch(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning('提示', '请先在选股结果中选择一只股票。')
            return
        values = self.tree.item(selected[0], 'values')
        self._on_add_watch(values[0], values[1])

    def _on_remove_watch(self):
        selected = self.watch_tree.selection()
        group = self.watch_group_var.get()
        if not selected or not group:
            return
        try:
            for item in selected:
                self.db_store.remove_stock(group, self.watch_tree.item(item, 'values')[0])
            self._refresh_watch_stocks()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('移除自选股失败', str(exc))

    # ---------------- 历史选股查询（PostgreSQL 后端） ----------------

    def _refresh_query_sources(self):
        if not hasattr(self, 'q_date_box'):
            return
        try:
            dates = self.db_store.list_run_dates()
            self.q_date_box.configure(values=dates)
            if dates and self.q_date_var.get() not in dates:
                self.q_date_var.set(dates[0])
            categories = self.db_store.list_run_categories()
            self.q_category_box.configure(values=categories)
            if categories:
                self.q_category_var.set(categories[0])
                self._refresh_query_strategies()
        except Exception as exc:  # noqa: BLE001
            print(f'查询：读取日期/类别失败：{exc}')

    def _refresh_query_strategies(self):
        try:
            category = self.q_category_var.get()
            items = self.db_store.list_run_strategies(category or None)
            self.q_strategy_ids_by_label = {}
            for item in items:
                label = item['strategy_name'] or item['strategy_id']
                if label in self.q_strategy_ids_by_label:
                    label = f'{label}（{item["strategy_id"]}）'
                self.q_strategy_ids_by_label[label] = item['strategy_id']
            values = list(self.q_strategy_ids_by_label)
            self.q_strategy_box.configure(values=values)
            self.q_strategy_var.set(values[0] if values else '')
        except Exception as exc:  # noqa: BLE001
            print(f'查询：读取策略列表失败：{exc}')

    def _on_query_runs(self):
        if not self._ensure_db_ready():
            messagebox.showwarning('数据库未连接', '请先启动本地 PostgreSQL 并配置数据库连接。')
            return
        strategy_id = self.q_strategy_ids_by_label.get(self.q_strategy_var.get()) if hasattr(
            self, 'q_strategy_ids_by_label') else None
        try:
            runs = self.db_store.list_runs(
                trade_date=self.q_date_var.get() or None,
                category=self.q_category_var.get() or None,
                strategy_id=strategy_id,
                limit=200)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('查询失败', f'读取批次列表失败：\n{exc}')
            return
        self.q_run_ids_by_label = {}
        for run in runs:
            count = int(run['selected_count'] or 0)
            stamp = run['generated_at'].strftime('%H:%M:%S') if run['generated_at'] else ''
            label = f"#{run['id']} {stamp} {count}只 {run['strategy_id']}"
            self.q_run_ids_by_label[label] = run['id']
        values = list(self.q_run_ids_by_label)
        self.q_run_box.configure(values=values)
        if values:
            self.q_run_var.set(values[0])
            self._load_query_run(self.q_run_ids_by_label[values[0]])
            self.status_var.set(f'查询：找到 {len(runs)} 个批次，显示最新批次')
            print(f'查询：日期={self.q_date_var.get() or "全部"} '
                  f'类别={self.q_category_var.get() or "全部"} '
                  f'策略={self.q_strategy_var.get() or "全部"}，共 {len(runs)} 个批次')
        else:
            self.tree.delete(*self.tree.get_children())
            self.result_rows = []
            self.export_btn.configure(state='disabled')
            self.status_var.set('查询：无匹配批次')
            print('查询：无匹配批次')

    def _on_query_run_selected(self):
        label = self.q_run_var.get()
        run_id = self.q_run_ids_by_label.get(label)
        if run_id:
            self._load_query_run(run_id)

    def _load_query_run(self, run_id):
        try:
            run = self.db_store.get_run(run_id)
            rows = self.db_store.fetch_run_rows(run_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('查询失败', f'读取批次 #{run_id} 失败：\n{exc}')
            return
        self.tree.delete(*self.tree.get_children())
        self.result_rows = []
        for r in rows:
            display_row = {
                '代码': r.get('code'), '名称': r.get('name'), '行业/板块': r.get('sector', ''),
                '价格': r.get('price'), '涨跌幅%': r.get('change_pct'),
                '换手%': r.get('turnover'), '量比': r.get('volume_ratio'),
                '成交量': r.get('volume'), '成交额(亿)': r.get('amount'),
                '评分': r.get('score'), '日期': r.get('signal_date'),
                '说明': r.get('explanation'),
            }
            values = [self._cell(display_row.get(col)) for col in COLUMNS]
            self.tree.insert('', 'end', values=values)
            self.result_rows.append(display_row)
        self.last_export_columns = list(COLUMNS)
        self.export_btn.configure(state='normal' if self.result_rows else 'disabled')
        count = len(self.result_rows)
        if run:
            self.status_var.set(f'批次 #{run["id"]}：{run["strategy_name"]}（{run["strategy_id"]}），共 {count} 只')
            print(f'批次 #{run["id"]}: {run["trade_date"]} {run["generated_at"]} '
                  f'类别={run["category"]} 策略={run["strategy_id"]}（{run["strategy_name"]}），'
                  f'数据 {count} 只')
        else:
            self.status_var.set(f'批次 #{run_id}：共 {count} 只')

    def _preset_choices(self):
        from stock_selector.utils.config_loader import load_presets_file
        from stock_selector.utils.strategy_names import strategy_display_name
        data = load_presets_file().get('presets', {})
        # 跳过资金类策略（依赖收费接口，当前不可用）
        return [(name, strategy_display_name(name, cfg))
                for name, cfg in data.items() if not cfg.get('strategy_type')]

    def _v2_choices(self):
        import yaml
        from stock_selector.config import PROJECT_ROOT
        from stock_selector.utils.strategy_names import strategy_display_name
        path = PROJECT_ROOT / 'presets_v2.yaml'
        if not path.exists():
            return []
        with open(path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        return [(name, strategy_display_name(name, strategy, family='v2'))
                for name, strategy in cfg.get('strategies', {}).items()]

    def _tech_choices(self):
        from stock_selector.strategies.technical_selection import STRATEGIES
        return [(item['id'], item['name']) for item in STRATEGIES]

    def _refresh_strategies(self):
        category = self.category_var.get()
        if category == CATEGORY_PRESET:
            choices = self._preset_choices()
        elif category == CATEGORY_V2:
            choices = self._v2_choices()
        else:
            choices = self._tech_choices()

        self.strategy_ids_by_label = {}
        for strategy_id, display_name in choices:
            label = display_name
            if label in self.strategy_ids_by_label:
                label = f'{display_name}（{strategy_id}）'
            self.strategy_ids_by_label[label] = strategy_id
        values = list(self.strategy_ids_by_label)
        self.strategy_box.configure(values=values)
        self.strategy_var.set(values[0] if values else '')

    # ---------------- 运行 ----------------

    def _on_run(self):
        if self.running:
            return
        strategy_label = self.strategy_var.get()
        if not strategy_label:
            messagebox.showwarning('提示', '请先选择策略')
            return
        strategy_id = self.strategy_ids_by_label.get(strategy_label, strategy_label)

        try:
            limit = int(self.limit_var.get() or '0')
        except ValueError:
            messagebox.showwarning('提示', '处理上限必须是整数')
            return

        self.running = True
        self.run_btn.configure(state='disabled')
        self.export_btn.configure(state='disabled')
        self.tree.delete(*self.tree.get_children())
        self.result_rows = []
        self.status_var.set('正在运行...（获取行情可能需要 10-30 秒，请稍候）')
        print(f"▶ 已开始选股：数据源={self.source_var.get()} 策略={strategy_label} "
              f"上限={limit or '不限'} —— 正在连接数据源…")

        source_name = dict(SOURCE_CHOICES)[self.source_var.get()]
        params = dict(
            category=self.category_var.get(),
            strategy=strategy_id,
            strategy_label=strategy_label,
            source=source_name,
            limit=limit,
            exclude_st=self.exclude_st_var.get(),
            filter_cyb=self.filter_cyb_var.get(),
            filter_kcb=self.filter_kcb_var.get(),
        )
        threading.Thread(target=self._run_worker, args=(params,), daemon=True).start()

    def _run_worker(self, params):
        try:
            rows, columns = self._execute(params)
            db_message = self._save_selection_to_db(params, rows)
            self.log_queue.put(('done', rows, columns, db_message))
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.log_queue.put(('error', str(exc)))

    def _execute(self, params):
        import pandas as pd
        from stock_selector.data.smart_provider_manager import SmartProviderManager

        print(f"\n===== 开始选股 {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        print(f"数据源: {params['source'] or '智能'}  策略: {params['strategy_label']}（{params['strategy']}）")

        manager = SmartProviderManager(params['source'])
        provider = manager.get_provider()
        if provider is None:
            raise RuntimeError('所有数据源均不可用，请检查网络')
        print(f"已连接数据源: {manager.current_provider_name}")
        params['resolved_source'] = manager.current_provider_name

        stocks = provider.get_all_stocks()
        if stocks is None or stocks.empty:
            raise RuntimeError('无法获取股票行情列表')
        print(f"获取行情: {len(stocks)} 只")

        if params['exclude_st']:
            mask = ~stocks['name'].astype(str).str.contains('ST|退', case=False, na=False)
            stocks = stocks[mask]
            print(f"排除ST/退市后: {len(stocks)} 只")

        codes = stocks['code'].astype(str)
        if params.get('filter_cyb'):
            stocks = stocks[~codes.str.startswith(('300', '301'))]
            codes = stocks['code'].astype(str)
            print(f"排除创业板(3开头)后: {len(stocks)} 只")
        if params.get('filter_kcb'):
            stocks = stocks[~codes.str.startswith(('688', '689'))]
            print(f"排除科创板(688开头)后: {len(stocks)} 只")

        limit = params['limit']
        if limit and limit > 0:
            stocks = stocks.head(limit)
            print(f"按上限截取: {len(stocks)} 只")

        category = params['category']
        if category == CATEGORY_PRESET:
            rows, columns = self._run_preset(params['strategy'], stocks, provider,
                                             manager.current_provider_name)
        elif category == CATEGORY_TECH:
            rows, columns = self._run_tech(params['strategy'], stocks, provider,
                                            manager.current_provider_name)
        else:
            rows, columns = self._run_v2(params['strategy'], stocks, provider,
                                         manager.current_provider_name)

        print(f"选股完成: {len(rows)} 只")
        return rows, columns

    def _save_selection_to_db(self, params, rows):
        if not self.db_ready and not self.db_store.try_ensure_schema():
            return '数据库未连接，结果未入库'
        self.db_ready = True
        try:
            run_id = self.db_store.save_selection_run(
                trade_date=datetime.now().date(),
                category=params['category'],
                strategy_id=params['strategy'],
                strategy_name=params['strategy_label'],
                source=params.get('resolved_source') or params.get('source'),
                rows=rows,
                parameters={k: v for k, v in params.items() if k != 'strategy_label'},
            )
            return f'数据库已保存（批次 {run_id}）'
        except Exception as exc:  # noqa: BLE001
            return f'数据库保存失败：{exc}'

    def _run_preset(self, name, stocks, provider, source):
        from stock_selector.config import ScreenerConfig
        from stock_selector.data.cache import KlineCache
        from stock_selector.strategies.short_term_selector import ShortTermSelector
        from stock_selector.utils.config_loader import load_preset

        preset = load_preset(name)
        print(f"常规预设参数: {preset}")
        pool = stocks
        if preset.get('mainboard_only'):
            pool = pool[pool['sector'].isin(['上证主板', '深证主板'])]
            print(f"仅主板: {len(pool)} 只")

        cfg = ScreenerConfig(
            turnover_min=preset.get('turnover', 15.0),
            change_min=preset.get('change', [1, 3])[0],
            change_max=preset.get('change', [1, 3])[1],
            volume_ratio=preset.get('volume', 1.5),
            top_per_sector=preset.get('sector', 20),
            check_outer_inner=preset.get('check_outer_inner', True),
            check_kdj=preset.get('check_kdj', True),
            check_rsi=preset.get('check_rsi', True),
            filter_cyb=preset.get('filter_cyb', False),
            filter_kcb=preset.get('filter_kcb', False),
            request_sleep=0.05,
        )
        cache = KlineCache(ttl_hours=cfg.cache_ttl_hours, namespace=source)
        results = ShortTermSelector(cfg, client=provider, cache=cache).run(pool)

        rows = []
        for s in results:
            rows.append({
                '代码': s.get('code'), '名称': s.get('name'), '行业/板块': s.get('sector', ''),
                '价格': s.get('price'), '涨跌幅%': s.get('change_pct'),
                '换手%': s.get('turnover'), '量比': s.get('volume_ratio'),
                '成交量': s.get('volume'), '成交额(亿)': s.get('amount'),
                '评分': s.get('score'), '日期': '',
                '说明': ('炸板' if s.get('is_failed_limit') else ''),
            })
        return rows, list(COLUMNS)

    def _run_tech(self, strategy_id, stocks, provider, source):
        from stock_selector.strategies.technical_selection import STRATEGIES, TechnicalSelector
        from stock_selector.data.cache import KlineCache

        strategy_name = next((item['name'] for item in STRATEGIES if item['id'] == strategy_id), strategy_id)
        print(f"技术形态策略: {strategy_name}（{strategy_id}）")
        results = TechnicalSelector.screen_many(
            stock_list=stocks, provider=provider, strategy_ids=[strategy_id], days=150, limit=0,
            cache=KlineCache(ttl_hours=8, namespace=source), workers=6)
        rows = []
        for r in results[strategy_id]:
            metrics = r.get('metrics') or {}
            rows.append({
                '代码': r.get('code'), '名称': r.get('name'), '行业/板块': r.get('sector', ''),
                '价格': r.get('price'), '涨跌幅%': r.get('change_pct'),
                '换手%': r.get('turnover'), '量比': metrics.get('volume_ratio'),
                '成交量': r.get('volume'), '成交额(亿)': r.get('amount'),
                '评分': '',
                '日期': r.get('latest_date', ''),
                '说明': r.get('reason', ''),
            })
        return rows, list(COLUMNS)

    def _run_v2(self, name, stocks, provider, source):
        from stock_selector.config import PROJECT_ROOT
        from stock_selector.data.cache import KlineCache
        from stock_selector.strategies.strategy_adapter import StrategyAdapter

        class _NoIntraday:
            def get_today_high_distance(self, *a):
                return None

        adapter = StrategyAdapter(
            name, config_path=PROJECT_ROOT / 'presets_v2.yaml',
            cache=KlineCache(ttl_hours=8, namespace=source))
        # 资金/分时/板块接口不稳定，按降级模式运行（与批量 runner 一致）
        adapter.sector_client = None
        adapter.capital_client = None
        adapter.intraday_client = _NoIntraday()

        results = adapter.run(stocks, provider)
        rows = []
        for s in results:
            rows.append({
                '代码': s.get('code'), '名称': s.get('name'), '行业/板块': s.get('sector', ''),
                '价格': s.get('price'), '涨跌幅%': s.get('change_pct'),
                '换手%': s.get('turnover'), '量比': s.get('volume_ratio'),
                '成交量': s.get('volume'), '成交额(亿)': s.get('amount'),
                '评分': s.get('score'), '日期': '',
                '说明': s.get('reason', ''),
            })
        return rows, list(COLUMNS)

    # ---------------- 界面回调 ----------------

    def _show_results(self, rows, columns, db_message=''):
        self.result_rows = rows
        self.last_export_columns = columns
        for row in rows:
            values = [self._cell(row.get(col)) for col in columns]
            self.tree.insert('', 'end', values=values)
        self.running = False
        self.run_btn.configure(state='normal')
        if rows:
            self.export_btn.configure(state='normal')
        self.status_var.set(f'完成：选出 {len(rows)} 只；{db_message}' if db_message else f'完成：选出 {len(rows)} 只')
        print(f'✓ 完成，共 {len(rows)} 只')
        if db_message:
            print(db_message)

    def _finish_error(self, message):
        self.running = False
        self.run_btn.configure(state='normal')
        self.status_var.set('运行失败')
        messagebox.showerror('运行失败', message)

    def _cell(self, value):
        if isinstance(value, float):
            return _fmt(value)
        return '' if value is None else str(value)

    def _poll_log(self):
        try:
            chunks = []
            try:
                while True:
                    item = self.log_queue.get_nowait()
                    if isinstance(item, tuple):
                        kind = item[0]
                        if kind == 'done':
                            self._show_results(item[1], item[2], item[3] if len(item) > 3 else '')
                        elif kind == 'error':
                            self._finish_error(item[1])
                        elif kind == 'market':
                            self._render_market(item[1])
                        else:
                            chunks.append(str(item[1]))
                    else:
                        chunks.append(item)
            except queue.Empty:
                pass
            if chunks:
                # 折叠 tqdm 等用 '\r' 刷新的进度帧，只保留每行最后一段，避免日志刷屏
                text = re.sub(r'[^\n\r]*\r', '', ''.join(chunks))
                if text:
                    self.log_text.configure(state='normal')
                    self.log_text.insert('end', text)
                    self.log_text.see('end')
                    self.log_text.configure(state='disabled')
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
        finally:
            self.root.after(120, self._poll_log)

    def _on_export(self):
        if not self.result_rows:
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.csv', filetypes=[('CSV 文件', '*.csv')],
            initialfile=f"选股_{datetime.now():%Y%m%d_%H%M%S}.csv")
        if not path:
            return
        import pandas as pd
        pd.DataFrame(self.result_rows, columns=self.last_export_columns).to_csv(
            path, index=False, encoding='utf-8-sig')
        self.status_var.set(f'已导出: {path}')
        messagebox.showinfo('导出成功', f'已保存到:\n{path}')


def main():
    root = tk.Tk()
    try:
        root.call('tk', 'scaling', 1.2)
    except Exception:
        pass
    StockSelectorApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
