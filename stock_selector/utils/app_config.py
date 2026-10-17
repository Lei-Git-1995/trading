# -*- coding: utf-8 -*-
"""本地配置读写（config.local.json）。

参考「致富研究员」的配置做法：大模型参数放在项目/exe 根目录的 JSON 文件里，
而不是数据库。文件结构::

    {
      "llm": {
        "enabled": true,
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "model_trade": "",
        "model_learn": "",
        "timeout_sec": 180,
        "temperature": 0.2,
        "max_tokens": 4096
      },
      "agent": {
        "enabled": false,
        "interval_sec": 300
      }
    }

未出现的字段一律回落到 :data:`DEFAULT_CONFIG`。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

CONFIG_FILENAME = 'config.local.json'

DEFAULT_CONFIG: Dict[str, Any] = {
    'llm': {
        'enabled': True,
        'base_url': 'https://api.openai.com/v1',
        'api_key': '',
        'model': 'gpt-4o-mini',
        'model_trade': '',      # 空则回落 model
        'model_learn': '',      # 空则回落 model
        'timeout_sec': 180,
        'temperature': 0.2,
        'max_tokens': 4096,
        'json_mode': False,     # 结构化输出（部分接口支持）
    },
    'agent': {
        'enabled': False,
        'interval_sec': 300,
    },
}


def get_config_path() -> Path:
    """配置文件路径：项目根（打包后为 exe 同级目录）。"""
    from stock_selector.config import PROJECT_ROOT
    return PROJECT_ROOT / CONFIG_FILENAME


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> Dict[str, Any]:
    """读取 config.local.json 并与默认值合并；文件不存在或损坏时返回默认值。"""
    path = get_config_path()
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:  # noqa: BLE001
            data = {}
    return _deep_merge(DEFAULT_CONFIG, data)


def save_config(config: Dict[str, Any]) -> Path:
    """写入 config.local.json（与默认值合并后落盘）。"""
    merged = _deep_merge(DEFAULT_CONFIG, config or {})
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return path


def get_llm_config() -> Dict[str, Any]:
    """大模型配置（base_url / api_key / model / timeout_sec ...）。"""
    return load_config().get('llm') or {}


def get_agent_config() -> Dict[str, Any]:
    """Agent 行为配置（enabled / interval_sec）。"""
    return load_config().get('agent') or {}
