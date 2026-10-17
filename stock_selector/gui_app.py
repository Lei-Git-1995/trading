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
from datetime import datetime, date
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from stock_selector.data.postgres_store import PostgresStore
from stock_selector.data.market_board import fetch_market_snapshot
from stock_selector.data.limit_up import fetch_limit_up_emotion
from stock_selector.utils import app_config


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
NUMERIC_COLUMNS = frozenset({'价格', '涨跌幅%', '换手%', '量比', '成交量', '成交额(亿)', '评分'})
COLUMNS = ('代码', '名称', '行业/板块', '价格', '涨跌幅%', '换手%', '量比',
           '成交量', '成交额(亿)', '评分', '日期', '说明')
COL_WIDTHS = {'代码': 70, '名称': 100, '行业/板块': 110, '价格': 70, '涨跌幅%': 70,
              '换手%': 70, '量比': 60, '成交量': 85, '成交额(亿)': 90,
              '评分': 60, '日期': 90, '说明': 420}
# 数值列右对齐，其余左对齐；表头与单元格用同一对齐方式，避免表头/数据错位
COL_RIGHT = {'价格', '涨跌幅%', '换手%', '量比', '成交量', '成交额(亿)', '评分'}

# ---------------------------------------------------------------
# 视觉风格（参考「致富研究员」：微软雅黑 + 红涨绿跌 + 分区卡片）
# ---------------------------------------------------------------
COLOR_UP = '#d0021b'      # 涨/净流入
COLOR_DOWN = '#009900'    # 跌/净流出
COLOR_FLAT = '#333333'
COLOR_HINT = '#888888'
COLOR_PRIMARY = '#1f4e79'

FONT = ('Microsoft YaHei UI', 10)
FONT_SMALL = ('Microsoft YaHei UI', 9)
FONT_BOLD = ('Microsoft YaHei UI', 10, 'bold')
FONT_TITLE = ('Microsoft YaHei UI', 15, 'bold')
FONT_MONO = ('Consolas', 9)

INDEX_NAMES = ('上证指数', '深证成指', '创业板指', '科创50', '沪深300', '上证50')


def _chg_tag(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 'flat'
    if f > 0.005:
        return 'up'
    if f < -0.005:
        return 'down'
    return 'flat'


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
        self.root.geometry('1280x840')
        self.root.minsize(1040, 680)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.result_rows: list[dict] = []
        self.last_export_columns: list[str] = []
        self.strategy_ids_by_label: dict[str, str] = {}
        self.db_store = PostgresStore()
        self.db_ready = False
        self.auto_refresh_job = None
        self.running = False
        self.market_refreshing = False
        self.board_refreshing = False
        self._last_emotion = None
        self.q_page = 0
        self.q_page_size = 100
        self.risk_queue = queue.Queue()
        self.risk_busy = False
        self.risk_enabled = threading.Event()
        self.risk_last_blocked = None
        self._sort_states = {}

        # LLM 持续分析 Agent
        self.agent_store = None
        self.agent_scheduler = None
        self.agent_running = False

        self._install_stdout_redirect()
        self._init_logging()
        self._apply_theme()
        self._build_ui()
        self._refresh_strategies()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        self.root.after(120, self._poll_log)
        self.root.after(300, self._init_database)
        self.root.after(600, self._market_timer)
        self.root.after(900, self._board_timer)
        self.root.after(800, self._toggle_auto_refresh)
        self.root.after(1500, self._risk_timer)

    # ---------------- 基础 ----------------

    def _install_stdout_redirect(self):
        writer = _QueueWriter(self.log_queue)
        sys.stdout = writer
        sys.stderr = writer

    def _init_logging(self):
        try:
            from stock_selector.utils.logger import setup_logger, get_default_log_file
            setup_logger(level=20, log_file=get_default_log_file(),
                         enable_color=False, force=True)
        except Exception:
            pass

    def _apply_theme(self):
        style = ttk.Style(self.root)
        for theme in ('vista', 'clam'):
            try:
                if theme in style.theme_names():
                    style.theme_use(theme)
                    break
            except Exception:
                pass
        # 全局默认字体（含未显式设置的控件）
        try:
            default_font = tkfont.nametofont('TkDefaultFont')
            default_font.configure(family='Microsoft YaHei UI', size=10)
            tkfont.nametofont('TkTextFont').configure(family='Microsoft YaHei UI', size=10)
            tkfont.nametofont('TkMenuFont').configure(family='Microsoft YaHei UI', size=10)
        except Exception:
            pass
        style.configure('.', font=FONT)
        style.configure('Treeview', font=FONT, rowheight=28)
        style.configure('Treeview.Heading', font=FONT_BOLD)
        style.map('Treeview', background=[('selected', '#d6e4f5')],
                  foreground=[('selected', COLOR_FLAT)])
        style.configure('TLabelframe.Label', font=FONT_BOLD, foreground=COLOR_PRIMARY)
        style.configure('TNotebook.Tab', font=FONT, padding=(16, 6))
        style.configure('TButton', font=FONT, padding=(8, 3))
        style.configure('Title.TLabel', font=FONT_TITLE, foreground=COLOR_PRIMARY)
        style.configure('Hint.TLabel', font=FONT_SMALL, foreground=COLOR_HINT)
        style.configure('Field.TLabel', font=FONT)

    def _build_ui(self):
        # ---- 顶部标题 + A股指数条 ----
        header = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        header.pack(fill='x')
        ttk.Label(header, text='A股选股器', style='Title.TLabel').pack(side='left')
        idx_wrap = ttk.Frame(header)
        idx_wrap.pack(side='left', padx=(18, 0))
        self.idx_vars = {}
        self.idx_labels = {}
        for i, name in enumerate(INDEX_NAMES):
            var = tk.StringVar(value=f'{name}: -')
            lbl = ttk.Label(idx_wrap, textvariable=var, font=FONT,
                            foreground=COLOR_HINT)
            lbl.grid(row=0, column=i, sticky='w', padx=(0, 16))
            self.idx_vars[name] = var
            self.idx_labels[name] = lbl

        # ---- 选股设置（分区卡片）----
        toolbar = ttk.LabelFrame(self.root, text='选股设置', padding=(12, 8))
        toolbar.pack(fill='x', padx=10, pady=(4, 0))

        ttk.Label(toolbar, text='数据源:', style='Field.TLabel').grid(
            row=0, column=0, sticky='w', pady=3)
        self.source_var = tk.StringVar(value=SOURCE_CHOICES[0][0])
        self.source_box = ttk.Combobox(
            toolbar, textvariable=self.source_var, width=14, state='readonly',
            values=[name for name, _ in SOURCE_CHOICES])
        self.source_box.grid(row=0, column=1, sticky='w', padx=(4, 18))

        ttk.Label(toolbar, text='策略类别:', style='Field.TLabel').grid(row=0, column=2, sticky='w')
        self.category_var = tk.StringVar(value=CATEGORY_PRESET)
        self.category_box = ttk.Combobox(
            toolbar, textvariable=self.category_var, width=12, state='readonly',
            values=CATEGORY_CHOICES)
        self.category_box.grid(row=0, column=3, sticky='w', padx=(4, 18))
        self.category_box.bind('<<ComboboxSelected>>', lambda e: self._refresh_strategies())

        ttk.Label(toolbar, text='策略:', style='Field.TLabel').grid(row=0, column=4, sticky='w')
        self.strategy_var = tk.StringVar(value='')
        self.strategy_box = ttk.Combobox(
            toolbar, textvariable=self.strategy_var, width=30, state='readonly', values=[])
        self.strategy_box.grid(row=0, column=5, sticky='w', padx=(4, 18))

        ttk.Label(toolbar, text='处理上限(0=全部):', style='Field.TLabel').grid(
            row=0, column=6, sticky='w')
        self.limit_var = tk.StringVar(value='500')
        ttk.Entry(toolbar, textvariable=self.limit_var, width=8).grid(
            row=0, column=7, sticky='w', padx=(4, 18))

        ttk.Label(toolbar, text='历史日期(可空):', style='Field.TLabel').grid(
            row=1, column=10, sticky='w', pady=(6, 0))
        self.history_date_var = tk.StringVar(value='')
        ttk.Entry(toolbar, textvariable=self.history_date_var, width=12).grid(
            row=1, column=11, sticky='w', padx=(4, 18), pady=(6, 0))

        self.exclude_st_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='排除ST/退市', variable=self.exclude_st_var).grid(
            row=0, column=8, sticky='w', padx=(0, 14))
        self.filter_cyb_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='排除创业板(3开头)', variable=self.filter_cyb_var).grid(
            row=0, column=9, sticky='w', padx=(0, 14))
        self.filter_kcb_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='排除科创板(688开头)', variable=self.filter_kcb_var).grid(
            row=0, column=10, sticky='w')

        self.run_btn = ttk.Button(toolbar, text='▶ 开始选股', command=self._on_run)
        self.run_btn.grid(row=0, column=11, sticky='e', padx=(18, 6))
        self.export_btn = ttk.Button(toolbar, text='导出CSV', command=self._on_export,
                                     state='disabled')
        self.export_btn.grid(row=0, column=12, sticky='e')

        self.auto_refresh_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='自动刷新', variable=self.auto_refresh_var,
                        command=self._toggle_auto_refresh).grid(row=1, column=0,
                                                                columnspan=2, sticky='w', pady=(6, 0))
        ttk.Label(toolbar, text='间隔(秒):', style='Field.TLabel').grid(
            row=1, column=2, sticky='w', pady=(6, 0))
        self.refresh_interval_var = tk.StringVar(value='300')
        ttk.Combobox(toolbar, textvariable=self.refresh_interval_var, width=6,
                     state='readonly', values=('30', '60', '120', '300')).grid(
            row=1, column=3, sticky='w', padx=(4, 18), pady=(6, 0))
        ttk.Label(toolbar, text='首次运行会建立 K 线缓存，后续刷新会复用缓存；'
                                '选中一行可「加入自选」。',
                  style='Hint.TLabel').grid(row=1, column=4, columnspan=6,
                                            sticky='w', pady=(6, 0))

        # ---- 统一标签栏：选股结果与各功能页同级（顺序参照「致富研究员」）----
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=(8, 0))
        self.notebook = notebook
        notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # 大盘板块
        market_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(market_frame, text='大盘板块')
        self._build_market_panel(market_frame)

        # 选股结果
        result_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(result_frame, text='选股结果')
        result_top = ttk.Frame(result_frame)
        result_top.pack(fill='x', pady=(0, 4))
        self.paper_overview_var = tk.StringVar(value='模拟盘：加载中...')
        ttk.Label(result_top, textvariable=self.paper_overview_var, style='Hint.TLabel').pack(side='left')
        result_actions = ttk.Frame(result_frame)
        result_actions.pack(fill='x', pady=(0, 4))
        result_top = result_actions
        ttk.Label(result_top, text='数量:').pack(side='left', padx=(12, 2))
        self.paper_qty_var = tk.StringVar(value='100')
        ttk.Entry(result_top, textvariable=self.paper_qty_var, width=7).pack(side='left')
        ttk.Label(result_top, text='止盈价:').pack(side='left', padx=(8, 2))
        self.paper_target_price_var = tk.StringVar(value='')
        ttk.Entry(result_top, textvariable=self.paper_target_price_var, width=8).pack(side='left')
        ttk.Label(result_top, text='止损价:').pack(side='left', padx=(6, 2))
        self.paper_stop_loss_var = tk.StringVar(value='')
        ttk.Entry(result_top, textvariable=self.paper_stop_loss_var, width=8).pack(side='left')
        ttk.Button(result_top, text='模拟买入(选中)', command=self._on_paper_buy).pack(side='left', padx=4)
        ttk.Button(result_top, text='模拟卖出(选中持仓)', command=self._on_paper_sell_result).pack(side='left', padx=2)
        ttk.Button(result_top, text='刷新持仓', command=self._refresh_positions).pack(side='left', padx=2)
        risk_bar = ttk.Frame(result_frame)
        risk_bar.pack(fill='x', pady=(0, 4))
        self.risk_auto_var = tk.BooleanVar(value=True)
        self.risk_enabled.set()
        ttk.Checkbutton(risk_bar, text='自动止盈止损（模拟盘）', variable=self.risk_auto_var,
                        command=self._toggle_risk).pack(side='left')
        self.risk_status_var = tk.StringVar(value='每30秒检查；仅程序运行时生效；未成交原因见日志')
        ttk.Label(risk_bar, textvariable=self.risk_status_var, style='Hint.TLabel').pack(side='left', padx=8)
        ttk.Label(result_frame, text='风控价留空不设置；持仓页留空保存可清除',
                  style='Hint.TLabel').pack(anchor='w')
        self.tree = ttk.Treeview(result_frame, columns=COLUMNS, show='headings', height=16)
        for col in COLUMNS:
            anchor = 'e' if col in COL_RIGHT else 'w'
            heading_options = {'text': col, 'anchor': anchor}
            if col in NUMERIC_COLUMNS:
                heading_options['command'] = lambda c=col: self._sort_tree(self.tree, c)
            self.tree.heading(col, **heading_options)
            self.tree.column(col, width=COL_WIDTHS.get(col, 90), anchor=anchor,
                             stretch=(col == '说明'))
        self.tree.tag_configure('up', foreground=COLOR_UP)
        self.tree.tag_configure('down', foreground=COLOR_DOWN)
        self.tree.tag_configure('flat', foreground=COLOR_FLAT)
        vsb = ttk.Scrollbar(result_frame, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(result_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)

        # 自选/持仓
        watch_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(watch_frame, text='自选/持仓')

        # 历史选股结果
        query_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(query_frame, text='历史选股结果')

        # 连板/阶梯（参照致富研究员）
        board_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(board_frame, text='连板/阶梯')
        bf_meta = ttk.Frame(board_frame)
        bf_meta.pack(fill='x', pady=(0, 4))
        self.var_board_tab_meta = tk.StringVar(value='猎板/阶梯: 加载中...')
        ttk.Label(bf_meta, textvariable=self.var_board_tab_meta, font=FONT).pack(side='left')
        ttk.Label(board_frame, text='左：涨停/炸板猎板池 · 右：连板高度梯队 · 随盯盘刷新（东财涨停池）',
                   style='Hint.TLabel').pack(anchor='w', pady=(0, 4))
        bf_panes = ttk.Frame(board_frame)
        bf_panes.pack(fill='both', expand=True)
        bf_panes.columnconfigure(0, weight=1)
        bf_panes.columnconfigure(1, weight=1)
        bf_panes.rowconfigure(0, weight=1)
        hunt_box = ttk.LabelFrame(bf_panes, text='猎板池（涨停/炸板）', padding=4)
        hunt_box.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        lad_box = ttk.LabelFrame(bf_panes, text='连板梯队', padding=4)
        lad_box.grid(row=0, column=1, sticky='nsew', padx=(4, 0))
        hcols = ('rank', 'code', 'name', 'bn', 'kind', 'seal', 'pct', 'broken', 'fund')
        self.hunt_tree = ttk.Treeview(hunt_box, columns=hcols, show='headings', height=14)
        hheaders = {'rank':('#',28),'code':('代码',58),'name':('名称',72),'bn':('板',36),'kind':('类型',70),'seal':('封板',56),'pct':('涨幅',56),'broken':('炸板',44),'fund':('封单亿',60)}
        for c,(t,w) in hheaders.items():
            self.hunt_tree.heading(c,text=t); self.hunt_tree.column(c,width=w,anchor='center')
        self.hunt_tree.tag_configure('sealed',foreground=COLOR_UP); self.hunt_tree.tag_configure('broken',foreground=COLOR_DOWN); self.hunt_tree.tag_configure('flat',foreground=COLOR_FLAT)
        hscroll = ttk.Scrollbar(hunt_box, orient='vertical', command=self.hunt_tree.yview); self.hunt_tree.configure(yscrollcommand=hscroll.set)
        self.hunt_tree.pack(side='left', fill='both', expand=True); hscroll.pack(side='right', fill='y')
        lcols = ('h','code','name','industry','seal','pct')
        self.ladder_tree = ttk.Treeview(lad_box, columns=lcols, show='headings', height=14)
        lheaders = {'h':('高度',50),'code':('代码',58),'name':('名称',72),'industry':('行业',90),'seal':('封板',56),'pct':('涨幅',56)}
        for c,(t,w) in lheaders.items():
            self.ladder_tree.heading(c,text=t); self.ladder_tree.column(c,width=w,anchor='w' if c=='industry' else 'center')
        self.ladder_tree.tag_configure('high',foreground=COLOR_UP); self.ladder_tree.tag_configure('low',foreground=COLOR_FLAT)
        lscroll = ttk.Scrollbar(lad_box, orient='vertical', command=self.ladder_tree.yview); self.ladder_tree.configure(yscrollcommand=lscroll.set)
        self.ladder_tree.pack(side='left', fill='both', expand=True); lscroll.pack(side='right', fill='y')
        pend_box = ttk.LabelFrame(board_frame, text='情绪研判 / 操作偏向', padding=4)
        pend_box.pack(fill='x', pady=(6,0))
        self.var_ladder_pending = tk.StringVar(value='待办: -')
        ttk.Label(pend_box, textvariable=self.var_ladder_pending, font=FONT, wraplength=1200, justify='left').pack(anchor='w')


        # 最近交易
        trade_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(trade_frame, text='最近交易')
        trade_top = ttk.Frame(trade_frame)
        trade_top.pack(fill='x', pady=(0, 4))
        ttk.Label(trade_top, text='模拟盘成交明细（来源：PostgreSQL trade_orders）',
                  style='Hint.TLabel').pack(side='left')
        ttk.Button(trade_top, text='刷新交易', command=self._refresh_trades).pack(side='right')
        tcols = ('time','side','code','name','qty','price','amount','pnl','reason')
        self.trade_tree = ttk.Treeview(trade_frame, columns=tcols, show='headings')
        theaders = {'time':('时间',130),'side':('方向',50),'code':('代码',70),'name':('名称',80),'qty':('数量',60),'price':('价格',70),'amount':('金额',80),'pnl':('本次盈亏',80),'reason':('原因',200)}
        for c,(t,w) in theaders.items():
            self.trade_tree.heading(c,text=t); self.trade_tree.column(c,width=w,anchor='w' if c=='reason' else 'center')
        self.trade_tree.tag_configure('profit',foreground=COLOR_UP); self.trade_tree.tag_configure('loss',foreground=COLOR_DOWN); self.trade_tree.tag_configure('flat',foreground=COLOR_FLAT)
        tscroll = ttk.Scrollbar(trade_frame, orient='vertical', command=self.trade_tree.yview); self.trade_tree.configure(yscrollcommand=tscroll.set)
        self.trade_tree.pack(side='left', fill='both', expand=True); tscroll.pack(side='right', fill='y')


        # 自动交易记录
        trade_log_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(trade_log_frame, text='自动交易记录')
        tlog_top = ttk.Frame(trade_log_frame)
        tlog_top.pack(fill='x', pady=(0, 4))
        ttk.Label(tlog_top, text='成交流水（含状态 / 余额 / 原因）', style='Hint.TLabel').pack(side='left')
        ttk.Button(tlog_top, text='刷新记录', command=self._refresh_trades).pack(side='right')
        self.trade_log_text = tk.Text(trade_log_frame, wrap='word', font=FONT_MONO, height=10, state='disabled',
                                       relief='flat', background='#fbfbfb', padx=6, pady=4)
        lscroll = ttk.Scrollbar(trade_log_frame, orient='vertical', command=self.trade_log_text.yview)
        self.trade_log_text.configure(yscrollcommand=lscroll.set)
        self.trade_log_text.pack(side='left', fill='both', expand=True)
        lscroll.pack(side='right', fill='y')


        # 今日复盘
        review_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(review_frame, text='今日复盘')
        rev_top = ttk.Frame(review_frame)
        rev_top.pack(fill='x', pady=(0,4))
        self.var_review_meta = tk.StringVar(value='复盘: 加载中...')
        ttk.Label(rev_top, textvariable=self.var_review_meta, font=FONT).pack(side='left')
        ttk.Button(rev_top, text='刷新复盘', command=self._refresh_review).pack(side='right')
        rev_body = ttk.Frame(review_frame)
        rev_body.pack(fill='both', expand=True)
        self.review_text = tk.Text(rev_body, wrap='word', font=FONT, spacing1=2, spacing3=4, padx=8, pady=8)
        rscroll = ttk.Scrollbar(rev_body, orient='vertical', command=self.review_text.yview)
        self.review_text.configure(yscrollcommand=rscroll.set)
        self.review_text.pack(side='left', fill='both', expand=True)
        rscroll.pack(side='right', fill='y')


        # 配置（AI 大模型）
        config_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(config_frame, text='配置')
        self._build_config_tab(config_frame)

        # LLM 持续分析（Agent）
        agent_frame = ttk.Frame(notebook, padding=(6, 6))
        notebook.add(agent_frame, text='LLM 分析')
        self._build_agent_tab(agent_frame)

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

        pos_box = ttk.LabelFrame(watch_frame, text='模拟盘持仓', padding=4)
        pos_box.pack(fill='both', expand=True, pady=(6, 0))
        pos_top = ttk.Frame(pos_box)
        pos_top.pack(fill='x')
        ttk.Label(pos_top, text='数量:').pack(side='left')
        self.pos_qty_var = tk.StringVar(value='100')
        ttk.Entry(pos_top, textvariable=self.pos_qty_var, width=7).pack(side='left', padx=2)
        ttk.Button(pos_top, text='模拟卖出(选中)', command=self._on_paper_sell).pack(side='left', padx=4)
        ttk.Button(pos_top, text='全部卖出', command=lambda: self._on_paper_sell(all_out=True)).pack(side='left', padx=2)
        ttk.Button(pos_top, text='刷新持仓', command=self._refresh_positions).pack(side='left', padx=2)
        risk_editor = ttk.Frame(pos_box)
        risk_editor.pack(fill='x', pady=3)
        pos_top = risk_editor
        ttk.Label(pos_top, text='止盈价:').pack(side='left', padx=(10, 2))
        self.pos_target_price_var = tk.StringVar(value='')
        ttk.Entry(pos_top, textvariable=self.pos_target_price_var, width=8).pack(side='left')
        ttk.Label(pos_top, text='止损价:').pack(side='left', padx=(6, 2))
        self.pos_stop_loss_var = tk.StringVar(value='')
        ttk.Entry(pos_top, textvariable=self.pos_stop_loss_var, width=8).pack(side='left')
        ttk.Button(pos_top, text='设置风控价', command=self._on_set_position_risk).pack(side='left', padx=4)
        self.var_pos_meta = tk.StringVar(value='')
        ttk.Label(pos_box, textvariable=self.var_pos_meta, style='Hint.TLabel').pack(anchor='w')
        pcols = ('code', 'name', 'volume', 'avg_cost', 'last_price', 'profit_pct', 'profit', 'value', 'target', 'stop', 'opened')
        self.pos_tree = ttk.Treeview(pos_box, columns=pcols, show='headings', height=8)
        self.pos_tree.bind('<<TreeviewSelect>>', self._on_position_selected)
        pheaders = {'code': ('代码', 70), 'name': ('名称', 90), 'volume': ('持股', 60),
                    'avg_cost': ('成本', 70), 'last_price': ('现价', 70), 'profit_pct': ('盈亏%', 70),
                    'profit': ('盈亏额', 80), 'value': ('市值', 90), 'target': ('止盈价', 75),
                    'stop': ('止损价', 75), 'opened': ('建仓日', 90)}
        for c, (t, w) in pheaders.items():
            self.pos_tree.heading(c, text=t)
            self.pos_tree.column(c, width=w, anchor='w' if c in ('name', 'opened') else 'center')
        self.pos_tree.tag_configure('profit', foreground=COLOR_UP)
        self.pos_tree.tag_configure('loss', foreground=COLOR_DOWN)
        pscroll = ttk.Scrollbar(pos_box, orient='vertical', command=self.pos_tree.yview)
        self.pos_tree.configure(yscrollcommand=pscroll.set)
        self.pos_tree.pack(side='left', fill='both', expand=True, pady=(4, 0))
        pscroll.pack(side='right', fill='y')

        # 历史选股查询（PostgreSQL 后端，日期范围 + 分页）
        q_controls = ttk.Frame(query_frame)
        q_controls.pack(fill='x')
        ttk.Label(q_controls, text='起始日期:').pack(side='left')
        self.q_from_var = tk.StringVar(value='')
        self.q_from_box = ttk.Combobox(
            q_controls, textvariable=self.q_from_var, width=12, values=[])
        self.q_from_box.pack(side='left', padx=(4, 8))
        ttk.Label(q_controls, text='结束日期:').pack(side='left')
        self.q_to_var = tk.StringVar(value='')
        self.q_to_box = ttk.Combobox(
            q_controls, textvariable=self.q_to_var, width=12, values=[])
        self.q_to_box.pack(side='left', padx=(4, 8))
        ttk.Label(q_controls, text='类别:').pack(side='left')
        self.q_category_var = tk.StringVar(value='全部')
        self.q_category_box = ttk.Combobox(
            q_controls, textvariable=self.q_category_var, width=10, state='readonly', values=['全部'])
        self.q_category_box.pack(side='left', padx=(4, 8))
        self.q_category_box.bind('<<ComboboxSelected>>', lambda e: self._refresh_query_strategies())
        ttk.Label(q_controls, text='策略:').pack(side='left')
        self.q_strategy_var = tk.StringVar(value='全部')
        self.q_strategy_box = ttk.Combobox(
            q_controls, textvariable=self.q_strategy_var, width=22, state='readonly', values=['全部'])
        self.q_strategy_box.pack(side='left', padx=(4, 8))
        ttk.Button(q_controls, text='查询', command=lambda: self._on_query_page(reset=True)).pack(side='left', padx=2)

        q_quick = ttk.Frame(query_frame)
        q_quick.pack(fill='x', pady=(6, 0))
        ttk.Label(q_quick, text='快捷:').pack(side='left')
        ttk.Button(q_quick, text='近3天', command=lambda: self._set_query_range(3)).pack(side='left', padx=2)
        ttk.Button(q_quick, text='近5天', command=lambda: self._set_query_range(5)).pack(side='left', padx=2)
        ttk.Button(q_quick, text='近10天', command=lambda: self._set_query_range(10)).pack(side='left', padx=2)
        ttk.Button(q_quick, text='近30天', command=lambda: self._set_query_range(30)).pack(side='left', padx=2)
        ttk.Button(q_quick, text='全部', command=lambda: self._set_query_range(0)).pack(side='left', padx=2)

        q_row2 = ttk.Frame(query_frame)
        q_row2.pack(fill='x', pady=(6, 0))
        ttk.Button(q_row2, text='上一页', command=lambda: self._on_query_page(delta=-1)).pack(side='left', padx=2)
        ttk.Button(q_row2, text='下一页', command=lambda: self._on_query_page(delta=1)).pack(side='left', padx=2)
        self.q_page_var = tk.StringVar(value='第 1/1 页 · 共 0 条 · 每页 100')
        ttk.Label(q_row2, textvariable=self.q_page_var).pack(side='left', padx=10)
        ttk.Button(q_row2, text='导出CSV', command=self._on_export_query).pack(side='left', padx=2)

        q_tree_wrap = ttk.Frame(query_frame)
        q_tree_wrap.pack(fill='both', expand=True, pady=(6, 0))
        self.q_tree = ttk.Treeview(q_tree_wrap, columns=COLUMNS, show='headings', height=14)
        for col in COLUMNS:
            anchor = 'e' if col in COL_RIGHT else 'w'
            heading_options = {'text': col, 'anchor': anchor}
            if col in NUMERIC_COLUMNS:
                heading_options['command'] = lambda c=col: self._sort_tree(self.q_tree, c)
            self.q_tree.heading(col, **heading_options)
            self.q_tree.column(col, width=COL_WIDTHS.get(col, 90), anchor=anchor,
                               stretch=(col == '说明'))
        self.q_tree.tag_configure('up', foreground=COLOR_UP)
        self.q_tree.tag_configure('down', foreground=COLOR_DOWN)
        self.q_tree.tag_configure('flat', foreground=COLOR_FLAT)
        q_vsb = ttk.Scrollbar(q_tree_wrap, orient='vertical', command=self.q_tree.yview)
        q_hsb = ttk.Scrollbar(q_tree_wrap, orient='horizontal', command=self.q_tree.xview)
        self.q_tree.configure(yscrollcommand=q_vsb.set, xscrollcommand=q_hsb.set)
        q_vsb.pack(side='right', fill='y')
        q_hsb.pack(side='bottom', fill='x')
        self.q_tree.pack(side='left', fill='both', expand=True)

        # 日志区
        log_frame = ttk.LabelFrame(self.root, text='运行日志', padding=(6, 4))
        log_frame.pack(fill='both', expand=False, padx=10, pady=(8, 4))
        self.log_text = tk.Text(log_frame, height=8, wrap='word', state='disabled',
                                font=FONT_MONO, relief='flat', background='#fbfbfb',
                                padx=6, pady=4)
        log_scroll = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        log_scroll.pack(side='right', fill='y')

        self.status_var = tk.StringVar(value='就绪')
        ttk.Label(self.root, textvariable=self.status_var, anchor='w',
                  style='Hint.TLabel', padding=(12, 3)).pack(fill='x', side='bottom')

    # ---------------- 大盘 / 板块面板 ----------------

    def _build_market_panel(self, parent):
        self.market_state_var = tk.StringVar(value='加载中…')
        ttk.Label(parent, textvariable=self.market_state_var, anchor='w',
                  style='Hint.TLabel').pack(fill='x')
        self.board_sort_var = tk.StringVar(value='')
        ttk.Label(parent, textvariable=self.board_sort_var, anchor='w',
                  style='Hint.TLabel').pack(fill='x')
        ttk.Label(parent, text='主力净流入榜', anchor='w', font=FONT_BOLD,
                  foreground=COLOR_UP).pack(fill='x', pady=(4, 0))
        self.board_up_tree = self._mk_board_tree(parent, 7)
        ttk.Label(parent, text='主力净流出榜', anchor='w', font=FONT_BOLD,
                  foreground=COLOR_DOWN).pack(fill='x', pady=(4, 0))
        self.board_down_tree = self._mk_board_tree(parent, 7)

        ttk.Button(parent, text='刷新大盘/板块', command=self._on_refresh_market).pack(
            fill='x', pady=(6, 0))

    @staticmethod
    def _mk_board_tree(parent, height):
        tree = ttk.Treeview(
            parent, columns=('板块', '净流入(亿)', '涨幅', '上涨家数', '涨停数', '上涨比'),
            show='headings', height=height)
        for col, width, anchor in (('板块', 92, 'w'), ('净流入(亿)', 80, 'e'),
                                   ('涨幅', 58, 'e'), ('上涨家数', 62, 'e'),
                                   ('涨停数', 54, 'e'), ('上涨比', 58, 'e')):
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
        for idx in data.get('indices', []):
            name = idx.get('name', '')
            var = self.idx_vars.get(name)
            lbl = self.idx_labels.get(name)
            if var is None:
                continue
            pct = idx.get('pct_chg', 0.0)
            var.set(f"{name}: {idx.get('close', 0):.2f}  {pct:+.2f}%")
            if lbl is not None:
                if pct > 0.005:
                    lbl.configure(foreground=COLOR_UP)
                elif pct < -0.005:
                    lbl.configure(foreground=COLOR_DOWN)
                else:
                    lbl.configure(foreground=COLOR_FLAT)
        self._fill_board_tree(self.board_up_tree, data.get('gainers', []))
        self._fill_board_tree(self.board_down_tree, data.get('losers', []))
        label = {
            'main_net_yi': '主力净流入',
            'pct_chg_5d': '5日涨跌幅',
            'pct_chg': '今日涨跌幅',
        }.get(data.get('sort_key'), '主力净流入')
        source = data.get('board_source')
        self.board_sort_var.set(f'按{label}排序 · {source}' if source else f'按{label}排序')
        self.market_state_var.set(
            f"更新 {data.get('time', '')}" + ('（缓存）' if data.get('stale') else ''))

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
                values=(b.get('name', ''), self._fmt_signed(b.get('main_net_yi')),
                        self._fmt_signed(pct), self._fmt_count(b.get('up')),
                        self._fmt_count(b.get('limit_up')),
                        '—' if up_ratio is None else f'{up_ratio * 100:.1f}%'))

    @staticmethod
    def _fmt_count(value):
        return '—' if value is None else f'{int(value):,}'

    @staticmethod
    def _fmt_signed(value):
        return '—' if value is None else f'{value:+.2f}'

    # ---------------- 连板/阶梯 ----------------

    def _board_timer(self):
        self._refresh_board_async()
        self.root.after(60000, self._board_timer)

    def _refresh_board_async(self):
        if self.board_refreshing:
            return
        self.board_refreshing = True
        threading.Thread(target=self._fetch_board_worker, daemon=True).start()

    def _fetch_board_worker(self):
        try:
            data = fetch_limit_up_emotion(force=True)
        except Exception:
            data = None
        self.log_queue.put(('ladder', data))

    @staticmethod
    def _fmt_seal(value):
        s = str(value or '').strip()
        if len(s) == 6 and s.isdigit():
            return f'{s[0:2]}:{s[2:4]}'
        return s or '—'

    def _render_ladder(self, data):
        self.board_refreshing = False
        if not data:
            self.var_board_tab_meta.set('猎板/阶梯: 数据获取失败')
            return
        self._last_emotion = data
        day = data.get('day', '')
        stale = ' · 沿用缓存' if data.get('stale') else ''
        promo = data.get('promotion_rate')
        self.var_board_tab_meta.set(
            f"猎板/阶梯 · {day} · 涨停 {data.get('limit_up_n', 0)} · "
            f"炸板 {data.get('broken_seal_n', 0)} · 高度 {data.get('max_board_height', 0)} · "
            f"晋级 {('—' if promo is None else f'{promo * 100:.0f}%')} · "
            f"{data.get('phase_label', '')}{stale}")

        self.hunt_tree.delete(*self.hunt_tree.get_children())
        roster = []
        for row in data.get('zt_items', []):
            roster.append((row, '涨停', 'sealed'))
        for row in data.get('broken_all', []):
            roster.append((row, '炸板', 'broken'))
        for i, (row, kind, tag) in enumerate(roster, 1):
            fund = row.get('fund')
            fund_text = '—' if fund in (None, '') else f'{float(fund) / 1e8:.2f}'
            self.hunt_tree.insert(
                '', 'end', tags=(tag,),
                values=(i, row.get('code', ''), row.get('name', ''),
                        row.get('board_n', '') if kind == '涨停' else '',
                        kind, self._fmt_seal(row.get('first_seal')),
                        f"{float(row.get('pct_chg') or 0):+.2f}",
                        row.get('broken_n', 0), fund_text))

        self.ladder_tree.delete(*self.ladder_tree.get_children())
        zt = sorted(data.get('zt_items', []),
                    key=lambda x: (-int(x.get('board_n') or 0), -float(x.get('pct_chg') or 0)))
        for row in zt:
            h = int(row.get('board_n') or 0)
            self.ladder_tree.insert(
                '', 'end', tags=('high',) if h >= 3 else ('low',),
                values=(h, row.get('code', ''), row.get('name', ''),
                        row.get('industry', ''), self._fmt_seal(row.get('first_seal')),
                        f"{float(row.get('pct_chg') or 0):+.2f}"))

        bias = data.get('buy_bias') or {}
        hist = data.get('height_hist') or {}
        hist_text = ' '.join(f'{k}板×{v}' for k, v in sorted(
            hist.items(), key=lambda kv: -int(kv[0]))) if hist else '—'
        err = data.get('error')
        self.var_ladder_pending.set(
            f"高度分布：{hist_text}    "
            f"偏向：{bias.get('note', '—')}"
            + (f"    [提示] {err}" if err else ''))
        if self.db_ready:
            self._refresh_review()

    # ---------------- 策略列表 ----------------

    def _init_database(self):
        if self.db_store.try_ensure_schema():
            self.db_ready = True
            print('数据库：PostgreSQL 已连接，选股结果会自动保存。')
            self._sync_paper_account()
            self._refresh_paper_overview()
            self._refresh_trades()
            self._refresh_review()
            self._refresh_positions()
            self._refresh_watch_groups()
            self._refresh_query_sources()
            try:
                self._ensure_agent_store()
                self._refresh_agent_analyses()
            except Exception as exc:  # noqa: BLE001
                print(f'Agent 初始化失败：{exc}')
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
            self._refresh_positions()
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

    # ---------------- LLM 持续分析 Agent ----------------

    def _on_close(self):
        self.risk_enabled.clear()
        try:
            if self.agent_scheduler is not None:
                self.agent_scheduler.stop()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()

    def _build_config_tab(self, parent):
        cfg = app_config.load_config()
        llm = cfg.get('llm', {})
        agent = cfg.get('agent', {})

        self.llm_enabled_var = tk.BooleanVar(value=bool(llm.get('enabled', True)))
        self.llm_key_var = tk.StringVar(value=str(llm.get('api_key') or ''))
        self.llm_model_var = tk.StringVar(value=str(llm.get('model') or 'gpt-4o-mini'))
        self.llm_base_url_var = tk.StringVar(
            value=str(llm.get('base_url') or 'https://api.openai.com/v1'))
        self.llm_timeout_var = tk.StringVar(value=str(llm.get('timeout_sec') or 180))
        temperature = llm.get('temperature')
        self.llm_temp_var = tk.StringVar(value=str(temperature if temperature is not None else 0.2))
        self.llm_max_tokens_var = tk.StringVar(value=str(llm.get('max_tokens') or 4096))
        self.agent_interval_var = tk.StringVar(value=str(agent.get('interval_sec') or 300))
        paper = cfg.get('paper_trade', {})
        self.paper_auto_var = tk.BooleanVar(value=bool(paper.get('auto_enabled', False)))
        self.paper_initial_cash_var = tk.StringVar(value=str(paper.get('initial_cash') or 100000))
        self.paper_max_position_var = tk.StringVar(value=str(paper.get('max_position_pct') or 10))
        self.paper_stop_var = tk.StringVar(value=str(paper.get('hard_stop_pct') or 7))
        self.paper_take_var = tk.StringVar(value=str(paper.get('take_profit_pct') or 15))

        row0 = ttk.Frame(parent)
        row0.pack(fill='x')
        ttk.Checkbutton(row0, text='启用大模型', variable=self.llm_enabled_var).pack(side='left')
        ttk.Label(row0, text='API 地址:').pack(side='left', padx=(12, 2))
        ttk.Entry(row0, textvariable=self.llm_base_url_var, width=46).pack(side='left')

        row1 = ttk.Frame(parent)
        row1.pack(fill='x', pady=(6, 0))
        ttk.Label(row1, text='API Key:').pack(side='left')
        ttk.Entry(row1, textvariable=self.llm_key_var, width=46, show='*').pack(side='left')

        row2 = ttk.Frame(parent)
        row2.pack(fill='x', pady=(6, 0))
        ttk.Label(row2, text='模型:').pack(side='left')
        ttk.Entry(row2, textvariable=self.llm_model_var, width=18).pack(side='left', padx=(2, 12))
        ttk.Label(row2, text='超时(秒):').pack(side='left')
        ttk.Entry(row2, textvariable=self.llm_timeout_var, width=6).pack(side='left', padx=(2, 12))
        ttk.Label(row2, text='温度:').pack(side='left')
        ttk.Entry(row2, textvariable=self.llm_temp_var, width=6).pack(side='left', padx=(2, 12))
        ttk.Label(row2, text='max_tokens:').pack(side='left')
        ttk.Entry(row2, textvariable=self.llm_max_tokens_var, width=8).pack(side='left', padx=(2, 12))

        row3 = ttk.Frame(parent)
        row3.pack(fill='x', pady=(6, 0))
        ttk.Label(row3, text='Agent 盘中间隔(秒):').pack(side='left')
        ttk.Combobox(row3, textvariable=self.agent_interval_var, width=7, state='readonly',
                     values=('60', '120', '300', '600')).pack(side='left', padx=(4, 12))
        ttk.Button(row3, text='保存配置', command=self._save_config).pack(side='left')

        row4 = ttk.Frame(parent)
        row4.pack(fill='x', pady=(8, 0))
        ttk.Label(row4, text='内置模拟盘:').pack(side='left')
        ttk.Entry(row4, textvariable=self.paper_initial_cash_var, width=10).pack(side='left', padx=(4, 2))
        ttk.Label(row4, text='初始资金').pack(side='left', padx=(0, 12))
        ttk.Entry(row4, textvariable=self.paper_max_position_var, width=5).pack(side='left', padx=(0, 2))
        ttk.Label(row4, text='单票仓位%').pack(side='left', padx=(0, 12))
        ttk.Entry(row4, textvariable=self.paper_stop_var, width=5).pack(side='left', padx=(0, 2))
        ttk.Label(row4, text='硬止损%').pack(side='left', padx=(0, 12))
        ttk.Entry(row4, textvariable=self.paper_take_var, width=5).pack(side='left', padx=(0, 2))
        ttk.Label(row4, text='止盈%').pack(side='left', padx=(0, 12))
        ttk.Checkbutton(row4, text='启用 Agent 自动模拟买卖', variable=self.paper_auto_var).pack(side='left')
        ttk.Label(parent, text='自动交易默认关闭；开启后仅模拟成交，盘中按 Agent 间隔检查。硬止盈止损按持仓成本比例执行，受 A 股 T+1 限制。',
                  style='Hint.TLabel').pack(anchor='w', pady=(5, 0))

        self.config_status_var = tk.StringVar(value='')
        ttk.Label(parent, textvariable=self.config_status_var,
                  style='Hint.TLabel').pack(anchor='w', pady=(8, 0))
        ttk.Label(parent, text=f'配置保存在 {app_config.get_config_path()}。'
                               'API Key 等仅写入本地文件，不入数据库。',
                  style='Hint.TLabel').pack(anchor='w', pady=(6, 0))

    def _save_config(self):
        try:
            timeout = float(self.llm_timeout_var.get() or 180)
            temperature = float(self.llm_temp_var.get() or 0.2)
            max_tokens = int(float(self.llm_max_tokens_var.get() or 4096))
            interval = int(self.agent_interval_var.get() or 300)
            initial_cash = float(self.paper_initial_cash_var.get() or 100000)
            max_position_pct = float(self.paper_max_position_var.get() or 10)
            hard_stop_pct = float(self.paper_stop_var.get() or 7)
            take_profit_pct = float(self.paper_take_var.get() or 15)
        except ValueError:
            messagebox.showwarning('提示', '超时 / 温度 / max_tokens / 间隔必须是数字')
            return
        cfg = app_config.load_config()
        cfg.setdefault('llm', {})
        cfg['llm'].update({
            'enabled': bool(self.llm_enabled_var.get()),
            'base_url': self.llm_base_url_var.get().strip() or 'https://api.openai.com/v1',
            'api_key': self.llm_key_var.get().strip(),
            'model': self.llm_model_var.get().strip() or 'gpt-4o-mini',
            'timeout_sec': timeout,
            'temperature': temperature,
            'max_tokens': max_tokens,
        })
        cfg.setdefault('agent', {})
        cfg['agent']['interval_sec'] = interval
        cfg['paper_trade'] = {
            'auto_enabled': bool(self.paper_auto_var.get()),
            'initial_cash': max(0.0, initial_cash),
            'max_position_pct': min(100.0, max(0.1, max_position_pct)),
            'hard_stop_pct': min(50.0, max(0.1, hard_stop_pct)),
            'take_profit_pct': min(200.0, max(0.1, take_profit_pct)),
            'min_ai_confidence': 60.0,
            'trade_lots': 1,
            'no_buy_after': '14:45',
        }
        try:
            path = app_config.save_config(cfg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('保存失败', str(exc))
            return
        self.config_status_var.set(f'已保存：{datetime.now():%H:%M:%S}')
        self._sync_paper_account(cfg['paper_trade'])
        self._refresh_paper_overview()
        print(f'配置已保存：{path}')

    def _sync_paper_account(self, settings=None):
        if not self._ensure_db_ready():
            return
        cfg = app_config.load_config()
        paper = settings or cfg.get('paper_trade', {})
        values = dict(paper)
        values['auto_paper_enabled'] = bool(values.pop('auto_enabled', False))
        self.db_store.upsert_account('模拟盘', 'paper', values,
                                     initial_cash=float(paper.get('initial_cash') or 100000))

    def _build_agent_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill='x')
        self.agent_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='启用连续分析', variable=self.agent_enabled_var,
                        command=self._on_agent_toggle).pack(side='left')
        ttk.Label(top, text='盘中间隔(秒):').pack(side='left', padx=(12, 2))
        ttk.Combobox(top, textvariable=self.agent_interval_var, width=7, state='readonly',
                     values=('60', '120', '300', '600')).pack(side='left')
        ttk.Button(top, text='立即分析', command=self._on_agent_once).pack(side='left', padx=(12, 2))
        ttk.Button(top, text='刷新记录', command=self._refresh_agent_analyses).pack(side='left', padx=2)
        if not hasattr(self, 'paper_overview_var'):
            self.paper_overview_var = tk.StringVar(value='模拟盘：读取中')
        ttk.Label(top, textvariable=self.paper_overview_var,
                  style='Hint.TLabel').pack(side='left', padx=(12, 0))
        ttk.Button(top, text='刷新模拟盘', command=self._refresh_paper_overview).pack(side='left', padx=4)
        self.agent_status_var = tk.StringVar(value='未启动（请在「配置」页填写并保存 API Key）')
        ttk.Label(top, textvariable=self.agent_status_var,
                  style='Hint.TLabel').pack(side='left', padx=(12, 0))

        hist = ttk.Frame(parent)
        hist.pack(fill='x', pady=(6, 0))
        ttk.Label(hist, text='历史批次:').pack(side='left')
        self.agent_hist_var = tk.StringVar(value='')
        self.agent_hist_box = ttk.Combobox(
            hist, textvariable=self.agent_hist_var, width=72, state='readonly', values=[])
        self.agent_hist_box.pack(side='left', padx=(4, 8))
        self.agent_hist_box.bind('<<ComboboxSelected>>', lambda e: self._on_agent_hist_selected())
        self.agent_picks_tree = ttk.Treeview(
            parent, columns=('排名', '代码', '名称', '动作', '置信', '价格', '目标', '止损', '行业', '理由'),
            show='headings', height=6)
        for col, width, anchor in (('排名', 46, 'e'), ('代码', 72, 'w'), ('名称', 100, 'w'),
                                   ('动作', 60, 'w'), ('置信', 56, 'e'), ('价格', 66, 'e'),
                                   ('目标', 66, 'e'), ('止损', 66, 'e'), ('行业', 90, 'w'),
                                   ('理由', 360, 'w')):
            self.agent_picks_tree.heading(col, text=col, anchor=anchor)
            self.agent_picks_tree.column(col, width=width, anchor=anchor,
                                         stretch=(col == '理由'))
        self.agent_picks_tree.pack(fill='both', expand=True, pady=(6, 0))

        ttk.Label(parent, text='研判摘要:', style='Field.TLabel').pack(anchor='w', pady=(6, 0))
        self.agent_summary_text = tk.Text(parent, height=4, wrap='word', state='disabled',
                                          font=FONT, relief='flat', background='#fbfbfb',
                                          padx=6, pady=4)
        self.agent_summary_text.pack(fill='x')
        ttk.Label(parent, text='盘中每 5 分钟自动研判候选股票；开盘前/午间/收盘三个学习时段各沉淀一次经验。'
                               '结果写入 PostgreSQL（agent_analyses / agent_picks），供本页回看。',
                  style='Hint.TLabel').pack(anchor='w', pady=(6, 0))

    def _ensure_agent_store(self):
        from stock_selector.agent.storage import AgentStore
        if not self._ensure_db_ready():
            return None
        if self.agent_store is None:
            self.agent_store = AgentStore(self.db_store)
        if not self.agent_store.try_ensure_schema():
            print(f'Agent 表初始化失败：{self.db_store.last_error}')
            return None
        return self.agent_store

    def _refresh_paper_overview(self):
        if not self._ensure_db_ready():
            return
        try:
            account = self.db_store.get_account('模拟盘')
            if not account:
                self._sync_paper_account()
                account = self.db_store.get_account('模拟盘')
            if not account:
                self.paper_overview_var.set('模拟盘：未配置')
                return
            positions = self.db_store.get_paper_positions(account['id'])
            market_value = sum(p['market_value'] for p in positions)
            equity = account['cash_balance'] + market_value
            pnl = equity - account['initial_cash']
            self.paper_overview_var.set(
                f"模拟盘：现金 {account['cash_balance']:,.2f}｜持仓 {len(positions)} 只｜"
                f"市值 {market_value:,.2f}｜盈亏 {pnl:+,.2f}")
        except Exception as exc:  # noqa: BLE001
            self.paper_overview_var.set(f'模拟盘读取失败：{exc}')

    def _paper_account(self):
        account = self.db_store.get_account('模拟盘')
        if not account:
            self._sync_paper_account()
            account = self.db_store.get_account('模拟盘')
        return account

    @staticmethod
    def _trade_pnl(result):
        if isinstance(result, dict):
            pnl = result.get('realized_pnl')
            try:
                return float(pnl) if pnl is not None else None
            except (TypeError, ValueError):
                return None
        return None

    def _refresh_trades(self):
        if not hasattr(self, 'trade_tree'):
            return
        if not self._ensure_db_ready():
            return
        try:
            account = self._paper_account()
            if not account:
                return
            trades = self.db_store.list_paper_trades(account['id'], limit=200)
        except Exception as exc:  # noqa: BLE001
            print(f'读取交易记录失败: {exc}')
            return

        self.trade_tree.delete(*self.trade_tree.get_children())
        log_lines = []
        for t in trades:
            price = t.get('price') or 0.0
            vol = t.get('volume') or 0
            amount = float(price) * float(vol)
            pnl = self._trade_pnl(t.get('result'))
            side = '买入' if t.get('action') == 'buy' else '卖出'
            ttag = 'flat'
            if pnl is not None:
                ttag = 'profit' if pnl > 0 else ('loss' if pnl < 0 else 'flat')
            self.trade_tree.insert('', 'end', tags=(ttag,), values=(
                t.get('created_at', ''), side, t.get('code', ''), t.get('name', ''),
                vol, f'{float(price):.2f}', f'{amount:,.0f}',
                '—' if pnl is None else f'{pnl:+,.2f}', t.get('reason', '')))
            result = t.get('result') or {}
            cash = result.get('cash_balance') if isinstance(result, dict) else None
            log_lines.append(
                f"{t.get('created_at', '')}  {side}  {t.get('code', '')} {t.get('name', '')}  "
                f"{vol}股 @{float(price):.2f}  金额{amount:,.0f}  [{t.get('status', '')}]  "
                + (f"盈亏{pnl:+,.2f}  " if pnl is not None else '')
                + (f"余额{cash:,.2f}  " if cash is not None else '')
                + f"原因：{t.get('reason', '')}")

        self.trade_log_text.configure(state='normal')
        self.trade_log_text.delete('1.0', 'end')
        if log_lines:
            self.trade_log_text.insert('end', '\n'.join(log_lines))
        else:
            self.trade_log_text.insert('end', '暂无交易记录。启用自动交易或经 Agent 下单后，此处显示成交日志。')
        self.trade_log_text.configure(state='disabled')

    def _refresh_positions(self):
        if not hasattr(self, 'pos_tree'):
            return
        if not self._ensure_db_ready():
            return
        try:
            account = self._paper_account()
            positions = self.db_store.get_paper_positions(account['id']) if account else []
        except Exception as exc:  # noqa: BLE001
            self.var_pos_meta.set(f'读取失败：{exc}')
            return
        self.pos_tree.delete(*self.pos_tree.get_children())
        total_value = 0.0
        total_pnl = 0.0
        for p in positions:
            cost_value = p.get('cost_value') or 0.0
            market_value = p.get('market_value') or 0.0
            profit = market_value - cost_value
            profit_pct = (profit / cost_value * 100) if cost_value else 0.0
            total_value += market_value
            total_pnl += profit
            tag = 'profit' if profit > 0 else ('loss' if profit < 0 else '')
            self.pos_tree.insert('', 'end', tags=(tag,), values=(
                p.get('code', ''), p.get('name', ''), p.get('volume', 0),
                f"{p.get('avg_cost', 0):.3f}", f"{p.get('last_price', 0):.2f}",
                f"{profit_pct:+.2f}", f"{profit:+,.0f}", f"{market_value:,.0f}",
                _fmt(p.get('target_price'), 3), _fmt(p.get('stop_loss'), 3), p.get('opened_on', '')))
        if account:
            equity = account['cash_balance'] + total_value
            pnl = equity - account['initial_cash']
            self.var_pos_meta.set(
                f"持仓 {len(positions)} 只｜市值 {total_value:,.0f}｜持仓盈亏 {total_pnl:+,.0f}｜"
                f"总权益 {equity:,.0f}（{pnl:+,.0f}）")
        else:
            self.var_pos_meta.set('未配置模拟盘')

    def _selected_result(self):
        sel = self.tree.selection()
        if not sel:
            return None
        index = self.tree.index(sel[0])
        if 0 <= index < len(self.result_rows):
            return self.result_rows[index]
        return None

    def _on_paper_buy(self):
        if not self._ensure_db_ready():
            messagebox.showwarning('模拟买入', '数据库未连接')
            return
        row = self._selected_result()
        if not row:
            messagebox.showinfo('模拟买入', '请先在选股结果中选中一只股票')
            return
        code = str(row.get('代码') or '').strip()
        name = str(row.get('名称') or '').strip()
        try:
            price = float(row.get('价格') or 0)
        except (TypeError, ValueError):
            price = 0.0
        if not code or price <= 0:
            messagebox.showwarning('模拟买入', '选中的股票缺少有效价格，无法下单')
            return
        try:
            volume = int(self.paper_qty_var.get())
        except (TypeError, ValueError):
            messagebox.showwarning('模拟买入', '数量必须是100股的整数倍')
            return
        if volume <= 0 or volume % 100:
            messagebox.showwarning('模拟买入', '数量必须是正的100股整数倍')
            return
        try:
            from stock_selector.trading.risk import risk_prices
            target_price, stop_loss = risk_prices(
                self.paper_target_price_var.get(), self.paper_stop_loss_var.get(), price)
        except (TypeError, ValueError):
            messagebox.showwarning('模拟买入', '风控价须大于0，止盈价高于买入价，止损价低于买入价')
            return
        if ((target_price is not None and target_price <= price) or
                (stop_loss is not None and stop_loss >= price) or
                (target_price is not None and stop_loss is not None and stop_loss >= target_price)):
            messagebox.showwarning('模拟买入', '止盈价应高于买入价，止损价应低于买入价')
            return
        account = self._paper_account()
        if not account:
            messagebox.showerror('模拟买入', '模拟盘账户不可用')
            return
        try:
            order_id = self.db_store.execute_paper_order(
                account['id'], code=code, name=name, action='buy',
                price=price, volume=volume, reason='手动模拟买入',
                target_price=target_price, stop_loss=stop_loss)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('模拟买入失败', str(exc))
            return
        print(f'模拟买入 #{order_id}: {code} {name} {volume}股 @{price:.2f}')
        self.status_var.set(f'模拟买入成功：{code} {name} {volume}股 @{price:.2f}')
        self._after_paper_trade()

    def _on_paper_sell_result(self):
        if not self._ensure_db_ready():
            messagebox.showwarning('模拟卖出', '数据库未连接')
            return
        row = self._selected_result()
        if not row:
            messagebox.showinfo('模拟卖出', '请先在选股结果中选中一只股票')
            return
        code = str(row.get('代码') or '').strip().zfill(6)
        name = str(row.get('名称') or '').strip()
        try:
            price = float(row.get('价格') or 0)
        except (TypeError, ValueError):
            price = 0
        try:
            volume = int(self.paper_qty_var.get())
        except (TypeError, ValueError):
            volume = 0
        import math
        if not math.isfinite(price):
            price = 0
        if price <= 0 or volume <= 0 or volume % 100:
            messagebox.showwarning('模拟卖出', '请检查选中股票的价格和卖出数量（100股整数倍）')
            return
        account = self._paper_account()
        try:
            position = next((p for p in self.db_store.get_paper_positions(account['id'])
                             if p['code'] == code), None) if account else None
        except Exception as exc:
            messagebox.showerror('模拟卖出失败', str(exc))
            return
        if not position:
            messagebox.showinfo('模拟卖出', f'{code} 当前没有模拟盘持仓')
            return
        if volume > position['volume']:
            messagebox.showwarning('模拟卖出', f"持仓不足：持有 {position['volume']} 股")
            return
        try:
            order_id = self.db_store.execute_paper_order(
                account['id'], code=code, name=name or position['name'], action='sell',
                price=price, volume=volume, reason='选股结果页手动模拟卖出')
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('模拟卖出失败', str(exc))
            return
        print(f'模拟卖出 #{order_id}: {code} {name} {volume}股 @{price:.2f}')
        self.status_var.set(f'模拟卖出成功：{code} {name} {volume}股 @{price:.2f}')
        self._after_paper_trade()

    def _on_set_position_risk(self):
        if not self._ensure_db_ready():
            messagebox.showwarning('设置风控价', '数据库未连接')
            return
        sel = self.pos_tree.selection()
        if not sel:
            messagebox.showinfo('设置风控价', '请先在模拟盘持仓中选中一只股票')
            return
        values = self.pos_tree.item(sel[0], 'values')
        try:
            from stock_selector.trading.risk import risk_prices
            target, stop = risk_prices(self.pos_target_price_var.get(), self.pos_stop_loss_var.get())
            self.db_store.set_paper_position_risk(
                self._paper_account()['id'], values[0], target_price=target, stop_loss=stop)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('设置风控价失败', str(exc))
            return
        self.status_var.set(f'已更新 {values[0]} 的止盈止损价')
        self._after_paper_trade()

    def _on_position_selected(self, _event=None):
        sel = self.pos_tree.selection()
        if not sel:
            return
        values = self.pos_tree.item(sel[0], 'values')
        self.pos_target_price_var.set(values[8] if len(values) > 8 else '')
        self.pos_stop_loss_var.set(values[9] if len(values) > 9 else '')

    def _on_paper_sell(self, all_out: bool = False):
        if not self._ensure_db_ready():
            messagebox.showwarning('模拟卖出', '数据库未连接')
            return
        sel = self.pos_tree.selection()
        if not sel:
            messagebox.showinfo('模拟卖出', '请先在模拟盘持仓中选中一只股票')
            return
        values = self.pos_tree.item(sel[0], 'values')
        code, name = values[0], values[1]
        held = int(float(values[2]))
        try:
            price = float(values[4])
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            messagebox.showwarning('模拟卖出', '持仓缺少有效现价，无法下单')
            return
        if all_out:
            volume = held
        else:
            try:
                volume = int(self.pos_qty_var.get())
            except (TypeError, ValueError):
                messagebox.showwarning('模拟卖出', '数量必须是100股的整数倍')
                return
            if volume <= 0 or volume % 100:
                messagebox.showwarning('模拟卖出', '数量必须是正的100股整数倍')
                return
        if volume > held:
            messagebox.showwarning('模拟卖出', f'持仓不足：持有 {held} 股')
            return
        account = self._paper_account()
        if not account:
            messagebox.showerror('模拟卖出', '模拟盘账户不可用')
            return
        try:
            order_id = self.db_store.execute_paper_order(
                account['id'], code=code, name=name, action='sell',
                price=price, volume=volume, reason='手动模拟卖出')
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('模拟卖出失败', str(exc))
            return
        print(f'模拟卖出 #{order_id}: {code} {name} {volume}股 @{price:.2f}')
        self.status_var.set(f'模拟卖出成功：{code} {name} {volume}股 @{price:.2f}')
        self._after_paper_trade()

    def _after_paper_trade(self):
        self._refresh_paper_overview()
        self._refresh_positions()
        self._refresh_trades()
        self._refresh_review()

    def _toggle_risk(self):
        if self.risk_auto_var.get():
            self.risk_enabled.set()
            self.risk_status_var.set('已开启，每30秒检查持仓风控价；仅程序运行时生效')
        else:
            self.risk_enabled.clear()
            self.risk_status_var.set('自动止盈止损已暂停')

    def _risk_timer(self):
        if self.risk_enabled.is_set() and self.db_ready and not self.risk_busy:
            self.risk_busy = True
            threading.Thread(target=self._risk_worker, daemon=True).start()
            self.root.after(250, self._poll_risk)
        self.root.after(30000, self._risk_timer)

    def _risk_worker(self):
        try:
            from stock_selector.trading.risk import check_position_risk
            from stock_selector.agent.tools import fetch_quotes
            account = self.db_store.get_account('模拟盘')
            outcome = check_position_risk(
                self.db_store, account['id'], fetch_quotes, enabled=self.risk_enabled.is_set
            ) if account else {'executed': [], 'blocked': [], 'status': '模拟盘未配置'}
        except Exception as exc:
            outcome = {'executed': [], 'blocked': [str(exc)], 'status': '检查失败，稍后重试'}
        self.risk_queue.put(outcome)

    def _poll_risk(self):
        try:
            outcome = self.risk_queue.get_nowait()
        except queue.Empty:
            self.root.after(250, self._poll_risk)
            return
        self.risk_busy = False
        if self.risk_enabled.is_set():
            blocked = outcome['blocked']
            detail = f'；{blocked[0]}' if blocked else ''
            self.risk_status_var.set(f"{datetime.now():%H:%M:%S} {outcome['status']}{detail}；仅程序运行时生效")
        if outcome['blocked'] != self.risk_last_blocked:
            for line in outcome['blocked']:
                print(f'[模拟盘风控] {line}')
            self.risk_last_blocked = outcome['blocked']
        for line in outcome['executed']:
            print(f'[模拟盘风控] {line}')
        if outcome['executed']:
            self._after_paper_trade()
        else:
            self._refresh_positions()
            self._refresh_paper_overview()

    def _refresh_review(self):
        if not hasattr(self, 'review_text'):
            return
        if not self._ensure_db_ready():
            self.var_review_meta.set('复盘：数据库未连接')
            return
        try:
            account = self._paper_account()
            positions = self.db_store.get_paper_positions(account['id']) if account else []
            trades = self.db_store.list_paper_trades(account['id'], limit=50) if account else []
        except Exception as exc:  # noqa: BLE001
            self.var_review_meta.set(f'复盘读取失败：{exc}')
            return

        lines = []
        lines.append(f"复盘时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
        if account:
            market_value = sum(p.get('market_value') or 0 for p in positions)
            equity = account['cash_balance'] + market_value
            pnl = equity - account['initial_cash']
            lines.append(
                f"模拟盘权益 {equity:,.2f}（现金 {account['cash_balance']:,.2f} / 市值 {market_value:,.2f}），"
                f"累计盈亏 {pnl:+,.2f}（{pnl / account['initial_cash'] * 100:+.2f}%）")
            lines.append('')
            lines.append(f"持仓（{len(positions)} 只）：")
            if positions:
                for p in positions:
                    lines.append(
                        f"  {p.get('code', '')} {p.get('name', '')}  "
                        f"{p.get('volume', 0)}股  成本{p.get('avg_cost', 0):.2f}  "
                        f"现价{p.get('last_price', 0):.2f}  市值{p.get('market_value', 0):,.0f}")
            else:
                lines.append('  （空仓）')
            lines.append('')
        trades = [t for t in trades if str(t.get('created_at', '')).startswith(str(datetime.now().date()))]
        lines.append(f"今日成交（{len(trades)} 笔）：")
        if trades:
            for t in trades:
                side = '买入' if t.get('action') == 'buy' else '卖出'
                lines.append(f"  {t.get('created_at', '')}  {side} {t.get('code', '')} {t.get('name', '')}"
                             f"  {t.get('volume', 0)}股 @{t.get('price', 0):.2f}  {t.get('reason', '')}")
        else:
            lines.append('  （无）')

        try:
            today = str(datetime.now().date())
            runs = self.db_store.list_runs(trade_date=today, limit=20)
            if runs:
                total_picks = sum(int(r.get('selected_count') or 0) for r in runs)
                lines.append('')
                lines.append(f"今日选股（{len(runs)} 批 / 共 {total_picks} 只）：")
                for r in runs[:8]:
                    lines.append(f"  [{r.get('category')}] {r.get('strategy_name')} "
                                 f"· {r.get('selected_count')} 只 · {r.get('generated_at')}")
                top_run = runs[0]
                picks = self.db_store.fetch_run_rows(top_run['id'])[:10]
                if picks:
                    lines.append(f"  最近一批（{top_run.get('strategy_name')}）前 {len(picks)} 只：")
                    for p in picks:
                        lines.append(f"    {p.get('code')} {p.get('name')}  "
                                     f"评分{_fmt(p.get('score'))} 涨跌{_fmt(p.get('change_pct'))}%  {p.get('sector') or ''}")
        except Exception as exc:  # noqa: BLE001
            lines.append('')
            lines.append(f"（选股复盘读取失败：{exc}）")

        emo = getattr(self, '_last_emotion', None)
        if emo:
            lines.append('')
            lines.append(f"涨停情绪：{emo.get('phase_label', '')} · 涨停 {emo.get('limit_up_n', 0)} / "
                         f"炸板 {emo.get('broken_seal_n', 0)} · 高度 {emo.get('max_board_height', 0)}")
            bias = emo.get('buy_bias') or {}
            if bias.get('note'):
                lines.append(f"操作偏向：{bias['note']}")

        self.var_review_meta.set(f"复盘 · {datetime.now():%Y-%m-%d} · 持仓 {len(positions)} 只")
        self.review_text.delete('1.0', 'end')
        self.review_text.insert('end', '\n'.join(lines))

    def _on_tab_changed(self, _event=None):
        try:
            tab = self.notebook.tab(self.notebook.select(), 'text')
        except Exception:  # noqa: BLE001
            return
        try:
            if tab in ('最近交易', '自动交易记录'):
                self._refresh_trades()
            elif tab == '今日复盘':
                self._refresh_review()
            elif tab == '自选/持仓':
                self._refresh_watch_groups()
                self._refresh_positions()
            elif tab == '历史选股结果':
                self._refresh_query_sources()
                if not getattr(self, 'q_rows', None):
                    self._on_query_page(reset=True)
        except Exception:  # noqa: BLE001
            pass

    def _agent_config(self):
        from stock_selector.agent import config as agent_config
        return agent_config.merge_config({
            'enabled': self.agent_enabled_var.get(),
            'interval_sec': int(self.agent_interval_var.get() or 300),
        })

    def _on_agent_toggle(self):
        if self.agent_enabled_var.get():
            self._start_agent_scheduler()
        else:
            self._stop_agent_scheduler()

    def _start_agent_scheduler(self):
        agent_store = self._ensure_agent_store()
        if agent_store is None:
            self.agent_enabled_var.set(False)
            messagebox.showwarning('数据库未连接', '连续分析需要 PostgreSQL，请先启动并配置数据库。')
            return
        from stock_selector.agent.scheduler import AgentScheduler
        self.agent_scheduler = AgentScheduler(
            store=self.db_store, agent_store=agent_store,
            llm_settings=app_config.get_llm_config(),
            agent_cfg=self._agent_config(),
            log=lambda m: self.log_queue.put(m if m.endswith('\n') else m + '\n'),
            on_result=lambda r: self.log_queue.put(('agent', r)))
        self.agent_scheduler.start()
        self.agent_status_var.set(f'连续分析已启动 · 盘中每 {self.agent_interval_var.get()} 秒')
        print('[agent] 连续分析已启动（盘中按间隔运行，学习时段各一次）')

    def _stop_agent_scheduler(self):
        if self.agent_scheduler is not None:
            self.agent_scheduler.stop()
            self.agent_scheduler = None
        self.agent_status_var.set('连续分析已停止')
        print('[agent] 连续分析已停止')

    def _on_agent_once(self):
        if self.agent_running:
            messagebox.showinfo('提示', '已有分析任务在运行，请稍候。')
            return
        agent_store = self._ensure_agent_store()
        if agent_store is None:
            messagebox.showwarning('数据库未连接', '分析结果需要写入 PostgreSQL。')
            return
        cfg = self._agent_config()
        cfg['enabled'] = True
        self.agent_running = True
        self.agent_status_var.set('正在分析…')

        def worker():
            from stock_selector.agent.scheduler import run_analysis_once
            try:
                result = run_analysis_once(
                    store=self.db_store, agent_store=agent_store,
                    llm_settings=app_config.get_llm_config(),
                    agent_cfg=cfg, trigger='manual', session='intraday',
                    log=lambda m: self.log_queue.put(m if m.endswith('\n') else m + '\n'),
                    persist=True)
            except Exception as exc:  # noqa: BLE001
                result = {'status': 'error', 'error': str(exc), 'picks': []}
            self.log_queue.put(('agent', result))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_agent_analyses(self):
        agent_store = self._ensure_agent_store()
        if agent_store is None:
            return
        try:
            rows = agent_store.list_analyses(limit=30)
        except Exception as exc:  # noqa: BLE001
            print(f'读取分析记录失败: {exc}')
            return
        self._agent_analyses = rows
        labels = [f"#{r['id']} {r['created_at']} {r['session']}/{r['trigger']} "
                  f"[{r['status']}] {r['picks_count']}只" for r in rows]
        self.agent_hist_box.configure(values=labels)
        if labels:
            self.agent_hist_var.set(labels[0])
            self._on_agent_hist_selected()

    def _on_agent_hist_selected(self):
        label = self.agent_hist_var.get()
        match = re.match(r'#(\d+)', label or '')
        if not match or self.agent_store is None:
            return
        self._show_agent_analysis(int(match.group(1)))

    def _show_agent_analysis(self, analysis_id):
        try:
            info = self.agent_store.get_analysis(analysis_id)
            picks = self.agent_store.get_picks(analysis_id)
        except Exception as exc:  # noqa: BLE001
            print(f'读取分析明细失败: {exc}')
            return
        if not info:
            return
        lines = [f"批次 #{info['id']}  {info['created_at']}  {info['session']}/{info['trigger']} "
                 f"[{info['status']}]  模型={info['model']}"]
        if info.get('summary'):
            lines.append(f"摘要：{info['summary']}")
        if info.get('market_view'):
            lines.append(f"研判：{info['market_view']}")
        if info.get('error'):
            lines.append(f"错误：{info['error']}")
        self._set_agent_summary('\n'.join(lines))
        self.agent_picks_tree.delete(*self.agent_picks_tree.get_children())
        for p in picks:
            tag = _chg_tag(p.get('confidence') if p.get('confidence') is not None
                           else p.get('score'))
            self.agent_picks_tree.insert('', 'end', tags=(tag,), values=(
                p.get('rank'), p.get('code'), p.get('name'), p.get('action'),
                _fmt(p.get('confidence'), 0), _fmt(p.get('price')),
                _fmt(p.get('target_price')), _fmt(p.get('stop_loss')),
                p.get('sector'), p.get('reason')))

    def _set_agent_summary(self, text):
        self.agent_summary_text.configure(state='normal')
        self.agent_summary_text.delete('1.0', 'end')
        self.agent_summary_text.insert('end', text)
        self.agent_summary_text.configure(state='disabled')

    def _render_agent_result(self, result):
        self.agent_running = False
        status = result.get('status')
        self.agent_status_var.set(
            f"最近一次：{status} · {len(result.get('picks') or [])} 只 · "
            f"{result.get('tool_calls', 0)} 次工具调用")
        if status == 'error' and result.get('error'):
            print(f"[agent] 分析失败：{result['error']}")
        self._refresh_paper_overview()
        self._refresh_trades()
        self._refresh_review()
        self._refresh_agent_analyses()

    def _toggle_auto_refresh(self):
        if self.auto_refresh_job is not None:
            self.root.after_cancel(self.auto_refresh_job)
            self.auto_refresh_job = None
        if self.auto_refresh_var.get():
            self._schedule_auto_refresh()

    def _schedule_auto_refresh(self):
        try:
            seconds = max(10, int(self.refresh_interval_var.get() or '300'))
        except ValueError:
            seconds = 300
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
        if not hasattr(self, 'q_from_box'):
            return
        try:
            dates = self.db_store.list_run_dates()
            self.q_from_box.configure(values=dates)
            self.q_to_box.configure(values=dates)
            categories = ['全部'] + self.db_store.list_run_categories()
            self.q_category_box.configure(values=categories)
            if self.q_category_var.get() not in categories:
                self.q_category_var.set('全部')
            self._refresh_query_strategies()
        except Exception as exc:  # noqa: BLE001
            print(f'查询：读取日期/类别失败：{exc}')

    def _refresh_query_strategies(self):
        try:
            category = self.q_category_var.get()
            items = self.db_store.list_run_strategies(None if category in ('', '全部') else category)
            self.q_strategy_ids_by_label = {'全部': None}
            for item in items:
                label = item['strategy_name'] or item['strategy_id']
                if label in self.q_strategy_ids_by_label:
                    label = f'{label}（{item["strategy_id"]}）'
                self.q_strategy_ids_by_label[label] = item['strategy_id']
            values = list(self.q_strategy_ids_by_label)
            self.q_strategy_box.configure(values=values)
            if self.q_strategy_var.get() not in values:
                self.q_strategy_var.set('全部')
        except Exception as exc:  # noqa: BLE001
            print(f'查询：读取策略列表失败：{exc}')

    def _set_query_range(self, days):
        from datetime import timedelta
        if days <= 0:
            self.q_from_var.set('')
            self.q_to_var.set('')
            return
        today = datetime.now().date()
        self.q_to_var.set(str(today))
        self.q_from_var.set(str(today - timedelta(days=days - 1)))

    def _on_query_page(self, reset=False, delta=0):
        if not self._ensure_db_ready():
            messagebox.showwarning('数据库未连接', '请先启动本地 PostgreSQL 并配置数据库连接。')
            return
        page_size = getattr(self, 'q_page_size', 100)
        if reset:
            self.q_page = 0
        else:
            self.q_page = max(0, getattr(self, 'q_page', 0) + delta)
        category = self.q_category_var.get()
        strategy_label = self.q_strategy_var.get()
        strategy_id = (self.q_strategy_ids_by_label.get(strategy_label)
                       if hasattr(self, 'q_strategy_ids_by_label') else None)
        date_from = self.q_from_var.get().strip() or None
        date_to = self.q_to_var.get().strip() or None
        offset = self.q_page * page_size
        try:
            rows, total = self.db_store.query_selections(
                date_from=date_from, date_to=date_to,
                category=None if category in ('', '全部') else category,
                strategy_id=strategy_id, limit=page_size, offset=offset)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('查询失败', f'读取选股结果失败：\n{exc}')
            return
        max_page = max(0, (total - 1) // page_size)
        if self.q_page > max_page:
            self.q_page = max_page
            offset = self.q_page * page_size
            rows, total = self.db_store.query_selections(
                date_from=date_from, date_to=date_to,
                category=None if category in ('', '全部') else category,
                strategy_id=strategy_id, limit=page_size, offset=offset)
        self._render_query_rows(rows)
        total_pages = (total + page_size - 1) // page_size if total else 0
        self.q_page_var.set(f'第 {self.q_page + 1}/{total_pages or 1} 页 · 共 {total} 条 · 每页 {page_size}')
        self.status_var.set(
            f'查询：{date_from or "起始不限"} ~ {date_to or "结束不限"} · '
            f'类别={category} · 策略={strategy_label} · 命中 {total} 条')
        print(f'查询：日期={date_from or "不限"}~{date_to or "不限"} 类别={category} '
              f'策略={strategy_label} 共 {total} 条，显示第 {self.q_page + 1} 页（{len(rows)} 条）')

    def _render_query_rows(self, rows):
        self.q_tree.delete(*self.q_tree.get_children())
        self.q_rows = []
        for r in rows:
            display_row = {
                '代码': r.get('code'), '名称': r.get('name'), '行业/板块': r.get('sector', ''),
                '价格': r.get('price'), '涨跌幅%': r.get('change_pct'),
                '换手%': r.get('turnover'), '量比': r.get('volume_ratio'),
                '成交量': r.get('volume'), '成交额(亿)': r.get('amount'),
                '评分': r.get('score'), '日期': r.get('trade_date') or r.get('signal_date'),
                '说明': r.get('explanation'),
            }
            values = [self._cell(display_row.get(col)) for col in COLUMNS]
            self.q_tree.insert('', 'end', values=values,
                               tags=(_chg_tag(display_row.get('涨跌幅%')),))
            self.q_rows.append(display_row)

    def _on_export_query(self):
        rows = getattr(self, 'q_rows', [])
        if not rows:
            messagebox.showinfo('导出CSV', '当前没有查询结果可导出。')
            return
        default = f"history_selections_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path = filedialog.asksaveasfilename(
            title='导出历史选股结果', defaultextension='.csv',
            initialfile=default, filetypes=[('CSV 文件', '*.csv'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            import pandas as pd
            pd.DataFrame(rows, columns=list(COLUMNS)).to_csv(path, index=False, encoding='utf-8-sig')
            self.status_var.set(f'已导出 {len(rows)} 条到 {path}')
            print(f'历史选股结果已导出：{path}（{len(rows)} 条）')
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('导出失败', str(exc))

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

        history_date = self.history_date_var.get().strip()
        if history_date:
            try:
                parsed_history_date = datetime.strptime(history_date, '%Y-%m-%d').date()
                if parsed_history_date > date.today():
                    raise ValueError('不能选择未来日期')
            except ValueError as exc:
                messagebox.showwarning('日期格式', f'请输入 YYYY-MM-DD 格式的有效历史日期。\n{exc}')
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
            history_date=history_date or None,
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
        from stock_selector.data.providers import create_provider

        print(f"\n===== 开始选股 {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        print(f"数据源: {params['source'] or '智能'}  策略: {params['strategy_label']}（{params['strategy']}）")

        historical_date = params.get('history_date')
        if historical_date:
            provider_name = params['source'] or 'tencent'
            provider = create_provider(provider_name)
            manager = None
        else:
            manager = SmartProviderManager(params['source'])
            provider = manager.get_provider()
        if provider is None:
            raise RuntimeError('所有数据源均不可用，请检查网络')
        resolved_source = provider_name if historical_date else manager.current_provider_name
        print(f"已连接数据源: {resolved_source}")
        params['resolved_source'] = resolved_source

        stocks = provider.get_all_stocks()
        if stocks is None or stocks.empty:
            raise RuntimeError('无法获取股票行情列表')
        print(f"获取股票列表: {len(stocks)} 只")

        if historical_date:
            stocks = self._historical_stock_snapshot(
                stocks, provider, historical_date, resolved_source)
            if stocks.empty:
                raise RuntimeError(f'没有找到 {historical_date} 的有效历史日 K 数据')
            provider = self._active_historical_provider
            print(f"历史日 K {historical_date}: {len(stocks)} 只；内外盘等分时字段不可用")

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
                                             resolved_source)
        elif category == CATEGORY_TECH:
            rows, columns = self._run_tech(params['strategy'], stocks, provider,
                                            resolved_source)
        else:
            rows, columns = self._run_v2(params['strategy'], stocks, provider,
                                         resolved_source)

        if historical_date:
            for row in rows:
                row['日期'] = historical_date
                reason = str(row.get('说明') or '').strip()
                row['说明'] = (reason + '；历史日K筛选，无盘中内外盘数据').strip('；')

        print(f"选股完成: {len(rows)} 只")
        return rows, columns

    def _historical_stock_snapshot(self, universe, provider, target_date, source):
        import pandas as pd
        from concurrent.futures import ThreadPoolExecutor
        from stock_selector.data.cache import KlineCache

        target = datetime.strptime(target_date, '%Y-%m-%d').date()
        cache = KlineCache(ttl_hours=72, namespace=f'{source}-history-{target_date}')
        histories = {}

        def load(item):
            _, stock = item
            code = str(stock['code']).zfill(6)
            hist = cache.get(code)
            if hist is None:
                try:
                    hist = provider.get_stock_history(code, days=180, end_date=target_date)
                except TypeError:
                    hist = provider.get_stock_history(code, days=180)
                if hist is None or hist.empty or '日期' not in hist:
                    return None
                hist = hist.copy()
                hist['日期'] = pd.to_datetime(hist['日期'], errors='coerce').dt.date
                hist = hist[hist['日期'] <= target].dropna(subset=['日期'])
                if hist.empty or hist.iloc[-1]['日期'] != target:
                    return None
                cache.set(code, hist)
            histories[code] = hist
            last = hist.iloc[-1]
            close = float(last['收盘'])
            volume = float(last['成交量'])
            previous_volumes = pd.to_numeric(hist['成交量'].iloc[-6:-1], errors='coerce').dropna()
            volume_ratio = (volume / previous_volumes.mean()) if len(previous_volumes) and previous_volumes.mean() else 0.0
            change_pct = float(last.get('涨跌幅', 0) or 0)
            turnover = last.get('换手率')
            try:
                turnover = float(turnover)
                if pd.isna(turnover):
                    turnover = float('nan')
            except (TypeError, ValueError):
                turnover = float('nan')
            return {
                'code': code, 'name': stock.get('name', code), 'price': close,
                'change_pct': change_pct, 'turnover': turnover, 'volume': volume,
                'inner_vol': float('nan'), 'outer_vol': float('nan'),
                'outer_ratio': float('nan'), 'inner_ratio': float('nan'),
                'sector': stock.get('sector', ''), 'volume_ratio': volume_ratio,
            }

        workers = min(12, max(1, len(universe)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='historical-kline') as pool:
            rows = [row for row in pool.map(load, universe.iterrows()) if row]
        self._historical_histories = histories

        class HistoricalProvider:
            def get_stock_history(self, code, days=10, end_date=None):
                hist = histories.get(str(code).zfill(6))
                return hist.tail(days).copy() if hist is not None else None

        self._active_historical_provider = HistoricalProvider()
        return pd.DataFrame(rows)

    def _save_selection_to_db(self, params, rows):
        if not self.db_ready and not self.db_store.try_ensure_schema():
            return '数据库未连接，结果未入库'
        self.db_ready = True
        try:
            run_id = self.db_store.save_selection_run(
                trade_date=(date.fromisoformat(params['history_date'])
                            if params.get('history_date') else datetime.now().date()),
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
            self.tree.insert('', 'end', values=values,
                             tags=(_chg_tag(row.get('涨跌幅%')),))
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

    def _sort_tree(self, tree, column):
        state_key = (tree, column)
        descending = self._sort_states.get(state_key, False)
        sortable = []
        missing = []
        for item in tree.get_children(''):
            raw = str(tree.set(item, column)).strip()
            try:
                number = float(raw.replace(',', '').replace('%', ''))
            except (TypeError, ValueError):
                missing.append(item)
            else:
                sortable.append((number, item))
        sortable.sort(key=lambda pair: pair[0], reverse=descending)
        for index, item in enumerate([item for _, item in sortable] + missing):
            tree.move(item, '', index)
        for col in NUMERIC_COLUMNS:
            indicator = ' ↑' if col == column and not descending else ' ↓' if col == column else ''
            tree.heading(col, text=col + indicator)
        self._sort_states[state_key] = not descending

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
                        elif kind == 'ladder':
                            self._render_ladder(item[1])
                        elif kind == 'agent':
                            self._render_agent_result(item[1])
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
