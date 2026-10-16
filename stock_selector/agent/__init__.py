# -*- coding: utf-8 -*-
"""LLM 持续分析 Agent。

参考「致富研究员」的设计：盘中按固定节奏（默认每 5 分钟）以及每日若干
「学习时段」调用大模型，通过工具（tools）反复取证，最终产出结构化研判与
个股排序，并写入 PostgreSQL 供界面展示与后续学习。

对外主要入口：
    - :class:`stock_selector.agent.llm.LLMClient`
    - :class:`stock_selector.agent.loop.ReActAgent`
    - :class:`stock_selector.agent.scheduler.AgentScheduler`
    - :class:`stock_selector.agent.storage.AgentStore`
"""
from __future__ import annotations

__all__ = [
    'config',
    'llm',
    'tools',
    'loop',
    'storage',
    'scheduler',
]
