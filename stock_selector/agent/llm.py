# -*- coding: utf-8 -*-
"""OpenAI 兼容大模型客户端与设置解析。

密钥/地址/模型来自本地配置文件 ``config.local.json`` 的 ``llm`` 段
（见 :mod:`stock_selector.utils.app_config`）：``enabled`` / ``base_url`` /
``api_key`` / ``model`` / ``timeout_sec`` / ``temperature`` / ``max_tokens``。
``model_trade`` / ``model_learn`` 为空则回落到 ``model``。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE_URL = 'https://api.hcnsec.cn/v1/'
DEFAULT_MODEL = 'auto'


def resolve_llm_settings(settings: Optional[Dict[str, Any]] = None,
                         agent_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把 llm 配置 + agent 配置合并成 LLM 调用参数（settings 优先）。"""
    settings = settings or {}
    agent_cfg = agent_cfg or {}
    model = str(settings.get('model') or agent_cfg.get('model') or DEFAULT_MODEL)
    temperature = settings.get('temperature')
    if temperature is None:
        temperature = agent_cfg.get('temperature', 0.25)
    max_tokens = settings.get('max_tokens')
    if max_tokens is None:
        max_tokens = agent_cfg.get('max_tokens', 2000)
    timeout = settings.get('timeout_sec')
    if timeout is None:
        timeout = agent_cfg.get('timeout_sec', 90)
    json_mode = settings.get('json_mode')
    if json_mode is None:
        json_mode = agent_cfg.get('json_mode', False)
    return {
        'base_url': str(settings.get('base_url') or agent_cfg.get('base_url')
                        or DEFAULT_BASE_URL).rstrip('/'),
        'api_key': str(settings.get('api_key') or agent_cfg.get('api_key') or ''),
        'model': model,
        'model_trade': str(settings.get('model_trade') or agent_cfg.get('model_trade') or model),
        'model_learn': str(settings.get('model_learn') or agent_cfg.get('model_learn') or model),
        'enabled': bool(settings.get('enabled', agent_cfg.get('enabled', True))),
        'temperature': float(temperature if temperature is not None else 0.25),
        'max_tokens': int(max_tokens if max_tokens is not None else 2000),
        'timeout': float(timeout if timeout is not None else 90),
        'json_mode': bool(json_mode),
    }


def chat_completions(*, base_url: str, api_key: str, model: str,
                     messages: List[Dict[str, Any]],
                     temperature: float = 0.25, max_tokens: int = 2000,
                     timeout: float = 90,
                     response_format: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """调用 ``/chat/completions``，返回 ``{ok, text, raw, error, usage}``。"""
    if not api_key:
        return {'ok': False, 'text': '', 'raw': None, 'error': '未配置 API Key', 'usage': {}}
    url = str(base_url or DEFAULT_BASE_URL).rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json',
               'Authorization': f'Bearer {api_key}'}
    body = {'model': model, 'messages': messages,
            'temperature': temperature, 'max_tokens': max_tokens}
    if response_format:
        body['response_format'] = response_format
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'text': '', 'raw': None, 'error': f'网络异常: {exc}', 'usage': {}}
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return {'ok': False, 'text': '', 'raw': resp.text[:500],
                'error': f'HTTP {resp.status_code} 非 JSON', 'usage': {}}
    if resp.status_code >= 400:
        err = (data.get('error') or {}) if isinstance(data, dict) else {}
        msg = err.get('message') or (data.get('message') if isinstance(data, dict) else '') \
            or resp.text[:300]
        return {'ok': False, 'text': '', 'raw': data,
                'error': f'HTTP {resp.status_code}: {msg}', 'usage': {}}
    try:
        msg = ((data.get('choices') or [{}])[0].get('message') or {})
        text = (msg.get('content') or '').strip()
        if not text:
            text = (msg.get('reasoning_content') or msg.get('reasoning') or '').strip()
    except Exception:  # noqa: BLE001
        text = ''
    usage = data.get('usage') if isinstance(data, dict) else {}
    if not text:
        return {'ok': False, 'text': '', 'raw': data, 'error': '空回复', 'usage': usage or {}}
    return {'ok': True, 'text': text, 'raw': data, 'error': '', 'usage': usage or {}}


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型回复中尽力提取 JSON 对象。"""
    text = (text or '').strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S | re.I)
    if match:
        try:
            obj = json.loads(match.group(1))
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            pass
    start = text.find('{')
    if start < 0:
        return None
    chunk = text[start:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(chunk)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    repaired = repair_truncated_json(chunk)
    if repaired is not None:
        return repaired
    for fix in ('}', ']}', '"]}', '"}]}'):
        try:
            obj = json.loads(chunk + fix)
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            continue
    return None


def repair_truncated_json(chunk: str) -> Optional[Dict[str, Any]]:
    """尽力闭合因 max_tokens 截断的 JSON。"""
    s = (chunk or '').rstrip()
    if not s.startswith('{'):
        return None
    in_str = esc = False
    last_safe = 0
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
                last_safe = i + 1
            continue
        if ch == '"':
            in_str = True
            continue
        if ch in '{[]},:':
            last_safe = i + 1
        elif ch not in ' \t\r\n':
            last_safe = i + 1
    if in_str:
        s = s[:last_safe if last_safe else len(s)] + '"'
    s = re.sub(r'[,:\s]+$', '', s)
    stack: List[str] = []
    in_str = esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in '}]':
            if stack and stack[-1] == ch:
                stack.pop()
    try:
        obj = json.loads(s + ''.join(reversed(stack)))
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


class LLMClient:
    """轻量封装：一次构造，多次调用。"""

    def __init__(self, settings: Optional[Dict[str, Any]] = None,
                 agent_cfg: Optional[Dict[str, Any]] = None):
        spec = resolve_llm_settings(settings, agent_cfg)
        self.base_url = spec['base_url']
        self.api_key = spec['api_key']
        self.model = spec['model']
        self.model_trade = spec['model_trade']
        self.model_learn = spec['model_learn']
        self.enabled = spec['enabled']
        self.temperature = spec['temperature']
        self.max_tokens = spec['max_tokens']
        self.timeout = spec['timeout']
        self.json_mode = spec['json_mode']
        self.last_usage: Dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict[str, Any]], *, kind: str = 'trade',
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> Dict[str, Any]:
        model = self.model_learn if kind == 'learn' else self.model_trade
        response_format = {'type': 'json_object'} if self.json_mode else None
        result = chat_completions(
            base_url=self.base_url, api_key=self.api_key, model=model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            timeout=self.timeout, response_format=response_format)
        self.last_usage = result.get('usage') or {}
        return result
