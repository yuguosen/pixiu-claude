"""LLM 错误分类体系 — 区分可重试/不可重试，驱动重试与 Provider 回退"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ErrorCategory(Enum):
    """LLM 调用错误分类"""

    RATE_LIMIT = "rate_limit"  # 429, 限流 → 可重试, 触发 Provider 切换
    AUTH = "auth"  # 401/403, 认证失败 → 不可重试
    BILLING = "billing"  # 402, 余额不足 → 不可重试
    TIMEOUT = "timeout"  # 超时 → 可重试
    FORMAT = "format"  # JSON 解析失败 → 可重试 (LLM 输出不稳定)
    CONTEXT_OVERFLOW = "context_overflow"  # 上下文过长 → 可重试 (需压缩)
    NETWORK = "network"  # 网络异常 → 可重试
    UNKNOWN = "unknown"  # 未知 → 可重试


# 不可重试的错误类别
_NON_RETRYABLE = {ErrorCategory.AUTH, ErrorCategory.BILLING}


@dataclass
class LLMError(Exception):
    """结构化 LLM 错误"""

    category: ErrorCategory
    provider: str
    model: str
    message: str
    status_code: int | None = None

    @property
    def is_retryable(self) -> bool:
        return self.category not in _NON_RETRYABLE

    def __str__(self) -> str:
        code = f" [{self.status_code}]" if self.status_code else ""
        return f"[{self.provider}/{self.model}] {self.category.value}{code}: {self.message}"

    @classmethod
    def classify(cls, exc: Exception, provider: str, model: str) -> LLMError:
        """从原始异常中推断错误分类"""
        status_code = _extract_status_code(exc, provider)
        category = _categorize(exc, status_code, provider)
        message = str(exc)[:500]
        return cls(
            category=category,
            provider=provider,
            model=model,
            message=message,
            status_code=status_code,
        )


def _extract_status_code(exc: Exception, provider: str) -> int | None:
    """从异常中提取 HTTP 状态码"""
    # Anthropic: APIStatusError 有 .status_code
    if hasattr(exc, "status_code"):
        return getattr(exc, "status_code")

    # Gemini / 通用: 从错误信息中匹配状态码
    msg = str(exc)
    match = re.search(r"\b(4\d{2}|5\d{2})\b", msg)
    if match:
        return int(match.group(1))

    return None


def _categorize(exc: Exception, status_code: int | None, provider: str) -> ErrorCategory:
    """根据状态码 + 异常类型推断分类"""
    msg = str(exc).lower()

    # 按状态码分类
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if status_code == 401 or status_code == 403:
        return ErrorCategory.AUTH
    if status_code == 402:
        return ErrorCategory.BILLING

    # 按异常类型分类
    exc_type = type(exc).__name__

    if "timeout" in exc_type.lower() or "timeout" in msg:
        return ErrorCategory.TIMEOUT

    if "json" in exc_type.lower() or "json" in msg:
        return ErrorCategory.FORMAT

    # Anthropic 特定
    if exc_type == "AuthenticationError":
        return ErrorCategory.AUTH
    if exc_type == "RateLimitError":
        return ErrorCategory.RATE_LIMIT

    # Gemini 特定 (错误信息关键词)
    if "rate" in msg and "limit" in msg:
        return ErrorCategory.RATE_LIMIT
    if "quota" in msg or "resource_exhausted" in msg:
        return ErrorCategory.RATE_LIMIT
    if "api key" in msg or "permission" in msg or "unauthorized" in msg:
        return ErrorCategory.AUTH
    if "context" in msg and ("length" in msg or "overflow" in msg or "too long" in msg):
        return ErrorCategory.CONTEXT_OVERFLOW

    # 网络类
    if any(kw in msg for kw in ("connection", "network", "dns", "refused", "reset")):
        return ErrorCategory.NETWORK

    # 状态码 5xx
    if status_code and 500 <= status_code < 600:
        return ErrorCategory.NETWORK

    return ErrorCategory.UNKNOWN
