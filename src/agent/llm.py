"""统一 LLM 调用入口 — 重试 + Provider 回退 + 公共 API

所有 LLM 调用应通过此模块，而非直接调用 Gemini/Anthropic SDK。
"""

import json
import os
import time
from pathlib import Path

from rich.console import Console

from src.agent.errors import ErrorCategory, LLMError
from src.config import CONFIG

console = Console()


# ═══════════════════ 配置查询 ═══════════════════


def load_env() -> None:
    """从 .env 文件加载环境变量"""
    env_path = Path(CONFIG.get("project_root", Path(__file__).parent.parent.parent)) / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def get_provider() -> str:
    """获取当前 LLM 后端 ('gemini' 或 'anthropic')"""
    load_env()
    return os.environ.get("LLM_PROVIDER", CONFIG.get("llm", {}).get("provider", "gemini"))


def get_provider_config(provider: str | None = None) -> dict:
    """获取指定后端的模型配置"""
    llm_config = CONFIG.get("llm", {})
    provider = provider or get_provider()
    return llm_config.get(provider, {})


def get_analysis_model(provider: str | None = None) -> str:
    return get_provider_config(provider).get("analysis_model", "gemini-2.0-flash")


def get_decision_model(provider: str | None = None) -> str:
    return get_provider_config(provider).get("decision_model", "gemini-2.5-pro")


def get_critical_model(provider: str | None = None) -> str:
    """关键决策模型 — 用于核心投资决策和辩论裁判"""
    return get_provider_config(provider).get("critical_model", get_decision_model(provider))


# ═══════════════════ Provider 后端实现 ═══════════════════


def _call_gemini(
    system: str,
    user_message: str,
    model: str,
    max_tokens: int,
) -> tuple[str, int]:
    """调用 Google Gemini API (新 SDK: google-genai)"""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise LLMError(
            category=ErrorCategory.AUTH,
            provider="gemini",
            model=model,
            message="GEMINI_API_KEY 未设置",
        )

    client = genai.Client(api_key=api_key)

    llm_config = CONFIG.get("llm", {})
    config_kwargs = {
        "system_instruction": system,
        "max_output_tokens": max_tokens,
        "temperature": 0.7,
    }

    # Gemini 2.5 Pro 支持 thinking
    if llm_config.get("enable_thinking") and "2.5" in model:
        thinking_budget = get_provider_config("gemini").get("thinking_budget", 4096)
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget,
        )

    response = client.models.generate_content(
        model=model,
        contents=user_message,
        config=types.GenerateContentConfig(**config_kwargs),
    )

    text = response.text or ""

    usage = getattr(response, "usage_metadata", None)
    total_tokens = getattr(usage, "total_token_count", 0) if usage else 0

    return text, total_tokens


def _call_anthropic(
    system: str,
    user_message: str,
    model: str,
    max_tokens: int,
) -> tuple[str, int]:
    """调用 Anthropic Claude API (支持代理 base_url)"""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMError(
            category=ErrorCategory.AUTH,
            provider="anthropic",
            model=model,
            message="ANTHROPIC_API_KEY 未设置",
        )

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = anthropic.Anthropic(**client_kwargs)

    llm_config = CONFIG.get("llm", {})
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }

    # 扩展思考 (Sonnet / Opus)
    if llm_config.get("enable_thinking") and ("sonnet" in model or "opus" in model):
        if "opus" in model:
            thinking_budget = get_provider_config("anthropic").get("critical_thinking_budget", 5000)
            kwargs["thinking"] = {
                "type": "adaptive",
                "budget_tokens": thinking_budget,
            }
        else:
            thinking_budget = get_provider_config("anthropic").get("thinking_budget", 3000)
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
        kwargs["max_tokens"] = max_tokens + thinking_budget

    response = client.messages.create(**kwargs)

    text = ""
    for block in response.content:
        if block.type == "text":
            text = block.text
            break

    total_tokens = response.usage.input_tokens + response.usage.output_tokens
    return text, total_tokens


def _dispatch(
    provider: str,
    system: str,
    user_message: str,
    model: str,
    max_tokens: int,
) -> tuple[str, int]:
    """分发到指定 Provider"""
    if provider == "anthropic":
        return _call_anthropic(system, user_message, model, max_tokens)
    else:
        return _call_gemini(system, user_message, model, max_tokens)


# ═══════════════════ 重试 + Provider 回退 ═══════════════════


def _get_fallback_provider(primary: str) -> str | None:
    """获取备用 Provider (需有 API Key)"""
    load_env()
    fallback = "anthropic" if primary == "gemini" else "gemini"
    key_env = "ANTHROPIC_API_KEY" if fallback == "anthropic" else "GEMINI_API_KEY"
    if os.environ.get(key_env, ""):
        return fallback
    return None


def _resolve_model_for_provider(model: str, target_provider: str, original_provider: str) -> str:
    """当回退到备用 Provider 时，映射模型名称

    例: gemini-2.0-flash → claude-haiku-4-5-20251001
    """
    if target_provider == original_provider:
        return model

    target_config = get_provider_config(target_provider)

    # 按模型角色映射: 分析模型 / 决策模型 / 关键模型
    original_config = get_provider_config(original_provider)
    if model == original_config.get("analysis_model"):
        return target_config.get("analysis_model", model)
    if model == original_config.get("critical_model"):
        return target_config.get("critical_model", model)
    if model == original_config.get("decision_model"):
        return target_config.get("decision_model", model)

    # 无法映射，使用目标的决策模型作为兜底
    return target_config.get("decision_model", model)


def call_llm(
    system: str,
    user_message: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, int]:
    """统一 LLM 调用入口 — 自动重试 + Provider 回退

    Args:
        system: 系统提示词
        user_message: 用户消息
        model: 模型名称 (None = 使用当前 Provider 的决策模型)
        max_tokens: 最大输出 token (None = 使用配置默认值)

    Returns:
        (response_text, tokens_used)

    Raises:
        LLMError: 所有重试耗尽后抛出
    """
    load_env()
    llm_config = CONFIG.get("llm", {})
    primary_provider = get_provider()
    model = model or get_decision_model()
    max_tokens = max_tokens or llm_config.get("max_tokens", 4096)

    max_retries = llm_config.get("max_retries", 3)
    backoff_base = llm_config.get("retry_backoff_base", 2)
    backoff_max = llm_config.get("retry_backoff_max", 8)
    enable_fallback = llm_config.get("enable_provider_fallback", True)

    # 构建 Provider 链
    provider_chain = [primary_provider]
    if enable_fallback:
        fallback = _get_fallback_provider(primary_provider)
        if fallback:
            provider_chain.append(fallback)

    last_error: LLMError | None = None

    for provider in provider_chain:
        current_model = _resolve_model_for_provider(model, provider, primary_provider)

        for attempt in range(max_retries):
            try:
                return _dispatch(provider, system, user_message, current_model, max_tokens)
            except LLMError:
                raise  # 已分类的错误 (如 API Key 未设置) 直接抛出
            except Exception as exc:
                error = LLMError.classify(exc, provider, current_model)
                last_error = error

                if not error.is_retryable:
                    console.print(f"  [red]LLM 不可重试错误: {error}[/]")
                    raise error from exc

                if error.category == ErrorCategory.RATE_LIMIT:
                    console.print(
                        f"  [yellow]LLM 限流 ({provider}/{current_model}), "
                        f"切换到下一个 Provider...[/]"
                    )
                    break  # 跳到下一个 provider

                # 指数退避
                delay = min(backoff_base ** attempt, backoff_max)
                console.print(
                    f"  [yellow]LLM 调用失败 ({error.category.value}), "
                    f"第 {attempt + 1}/{max_retries} 次重试, "
                    f"等待 {delay}s...[/]"
                )
                time.sleep(delay)

    # 所有尝试耗尽
    if last_error:
        raise last_error
    raise LLMError(
        category=ErrorCategory.UNKNOWN,
        provider=primary_provider,
        model=model,
        message="所有 LLM Provider 均不可用",
    )


# ═══════════════════ JSON 解析 ═══════════════════


def parse_json_response(text: str) -> dict:
    """从 LLM 响应中解析 JSON

    Raises:
        LLMError(FORMAT): JSON 解析失败
    """
    text = text.strip()

    # 处理 markdown 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1
        if end >= 0 and lines[end].strip() == "```":
            text = "\n".join(lines[start:end])
        else:
            text = "\n".join(lines[start:])
        text = text.strip()

    # 有时 LLM 在 JSON 前后加了其他文本，提取 {} 块
    if not text.startswith("{"):
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            text = text[brace_start : brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(
            category=ErrorCategory.FORMAT,
            provider="unknown",
            model="unknown",
            message=f"JSON 解析失败: {exc}. 原文前200字: {text[:200]}",
        ) from exc
