"""
LLM 调用抽象层
支持 Anthropic Claude（默认）和 OpenAI 兼容接口（通过 LLM_API_STYLE 切换）

环境变量：
    LLM_API_KEY     : 必填
    LLM_MODEL       : 模型名
    LLM_API_URL     : 接口地址
    LLM_API_STYLE   : "anthropic"（默认）| "openai"
    API_TIMEOUT     : 超时秒数（默认 60）
    LLM_MAX_TOKENS  : 最大输出 token（默认 1500）
"""
import os
from typing import Optional

import requests

_TIMEOUT   = int(os.environ.get("API_TIMEOUT",    "60"))
_MAX_TOK   = int(os.environ.get("LLM_MAX_TOKENS", "1500"))
_MODEL     = os.environ.get("LLM_MODEL",    "claude-3-5-sonnet-20241022")
_API_URL   = os.environ.get("LLM_API_URL",  "https://api.anthropic.com/v1/messages")
_API_STYLE = os.environ.get("LLM_API_STYLE","anthropic").lower()


def call(system: str, user: str, api_key: Optional[str] = None) -> str:
    """
    向 LLM 发送一条 system + user 消息，返回纯文本回复。
    失败时抛出 RuntimeError。
    """
    key = api_key or os.environ.get("LLM_API_KEY")
    if not key:
        raise RuntimeError("LLM_API_KEY 未设置")

    if _API_STYLE == "openai":
        return _call_openai(system, user, key)
    return _call_anthropic(system, user, key)


def _call_anthropic(system: str, user: str, key: str) -> str:
    headers = {
        "x-api-key":         key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    payload = {
        "model":      _MODEL,
        "max_tokens": _MAX_TOK,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
    }
    resp = requests.post(_API_URL, headers=headers, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_openai(system: str, user: str, key: str) -> str:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":      _MODEL,
        "max_tokens": _MAX_TOK,
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": user},
        ],
    }
    resp = requests.post(_API_URL, headers=headers, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
