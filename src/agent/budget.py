"""LLM 上下文预算管理 — 按优先级裁剪 prompt，确保不超 token 预算"""

from dataclasses import dataclass


@dataclass
class PromptSection:
    name: str
    content: str
    priority: int  # 1=必须 2=重要 3=可选


def estimate_tokens(text: str) -> int:
    """CJK + 英文混合估算 token 数

    中文约 1.5 token/字，英文约 1.3 token/word。
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    non_cjk_chars = len(text) - cjk
    words = max(non_cjk_chars / 4, 0)  # 粗略按4字符1词估算
    return int(cjk * 1.5 + words * 1.3)


def build_prompt(sections: list[PromptSection], max_tokens: int = 8000) -> str:
    """按优先级裁剪 sections，确保不超 token 预算

    Args:
        sections: 各段内容 (按 priority 排序后裁剪)
        max_tokens: 最大 token 预算

    Returns:
        拼接后的 prompt 文本
    """
    sorted_s = sorted(sections, key=lambda s: s.priority)
    parts: list[str] = []
    used = 0
    dropped: list[str] = []

    for s in sorted_s:
        if not s.content:
            continue
        tokens = estimate_tokens(s.content)
        remaining = max_tokens - used

        if tokens <= remaining:
            parts.append(s.content)
            used += tokens
        elif s.priority == 1:
            # 必须项: 截断后强制加入
            ratio = remaining / max(tokens, 1)
            cut_len = int(len(s.content) * ratio)
            cut = s.content[:cut_len]
            # 尽量在换行处截断
            last_nl = cut.rfind("\n")
            if last_nl > len(cut) * 0.5:
                cut = cut[:last_nl]
            parts.append(cut + "\n[...已截断]")
            used = max_tokens
        else:
            dropped.append(s.name)

    if dropped:
        parts.append(f"\n[预算限制，已省略: {', '.join(dropped)}]")

    return "\n\n".join(parts)
