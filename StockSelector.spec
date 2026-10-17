# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'psycopg2', 'psycopg2._psycopg',
    'stock_selector.agent', 'stock_selector.agent.config',
    'stock_selector.agent.llm', 'stock_selector.agent.tools',
    'stock_selector.agent.loop', 'stock_selector.agent.storage',
    'stock_selector.agent.scheduler', 'stock_selector.utils.app_config',
    'stock_selector.data.limit_up', 'stock_selector.data.market_board',
]
tmp_ret = collect_all('akshare')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ['E:/trading/run_gui.py'],
    pathex=['E:/trading'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='StockSelector',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[],
    name='StockSelector',
)
