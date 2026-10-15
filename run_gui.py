#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股器 GUI 启动入口（打包 exe 时使用）。

源码运行：
    py -3.11 run_gui.py
"""
import sys
from pathlib import Path

# 源码运行时的包路径（打包后由 PyInstaller 处理）
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

def crash_log_path():
    import os
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'gui_crash.log'
    return Path(__file__).resolve().parent / 'gui_crash.log'


if __name__ == '__main__':
    try:
        from stock_selector.gui_app import main
        main()
    except Exception:
        import traceback
        with open(crash_log_path(), 'w', encoding='utf-8') as fh:
            fh.write(traceback.format_exc())
        raise
