"""K线本地缓存：避免同一天重复请求逐股K线"""
import os
import pickle
import time
from pathlib import Path

from stock_selector.config import CACHE_DIR


class KlineCache:
    """进程内字典 + pickle 磁盘持久化，带有效期"""

    def __init__(self, ttl_hours=8.0, cache_dir: Path = None, namespace: str = ''):
        self.ttl_seconds = ttl_hours * 3600
        base = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir = base / namespace if namespace else base
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem = {}

    def _path(self, code: str) -> Path:
        return self.cache_dir / f'{code}.pkl'

    def get(self, code: str):
        """命中且未过期则返回 DataFrame，否则 None"""
        if code in self._mem:
            df, ts = self._mem[code]
            if time.time() - ts < self.ttl_seconds:
                return df
            del self._mem[code]

        p = self._path(code)
        if not p.exists():
            return None
        try:
            with open(p, 'rb') as f:
                df, ts = pickle.load(f)
            if time.time() - ts < self.ttl_seconds:
                self._mem[code] = (df, ts)
                return df
        except Exception:
            pass
        return None

    def set(self, code: str, df) -> None:
        if df is None:
            return
        ts = time.time()
        self._mem[code] = (df, ts)
        try:
            with open(self._path(code), 'wb') as f:
                pickle.dump((df, ts), f)
        except Exception:
            pass

    def clear(self) -> None:
        self._mem.clear()
        for p in self.cache_dir.glob('*.pkl'):
            try:
                os.remove(p)
            except OSError:
                pass