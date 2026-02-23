"""渐进降级: API 实时 → DB 缓存 → 中性默认"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any, Callable

from rich.console import Console

console = Console()


class DataQuality(IntEnum):
    DEFAULT = 0  # 中性默认值
    STALE = 1  # DB 过期缓存
    CACHED = 2  # DB 有效缓存
    REALTIME = 3  # API 实时数据


@dataclass
class DataResult:
    data: Any
    quality: DataQuality
    source: str  # "api" / "db" / "default"


def fetch_with_fallback(
    name: str,
    api_fn: Callable[[], Any],
    db_fn: Callable[[], tuple[Any, str] | None],
    default_fn: Callable[[], Any],
    ttl_hours: int = 24,
) -> DataResult:
    """三级降级获取数据

    Args:
        name: 数据源名称 (用于日志)
        api_fn: API 实时获取函数，返回数据或 None
        db_fn: DB 缓存查询函数，返回 (data, updated_date_str) 或 None
        default_fn: 中性默认值工厂
        ttl_hours: 缓存有效期 (小时)
    """
    # Tier 1: API 实时
    try:
        data = api_fn()
        if data is not None:
            return DataResult(data=data, quality=DataQuality.REALTIME, source="api")
    except Exception as e:
        console.print(f"  [dim]{name} API: {e}[/]")

    # Tier 2: DB 缓存
    try:
        cached = db_fn()
        if cached is not None:
            data, updated_at = cached
            try:
                age = datetime.now() - datetime.strptime(updated_at, "%Y-%m-%d")
            except (ValueError, TypeError):
                age = timedelta(hours=ttl_hours + 1)
            quality = (
                DataQuality.CACHED
                if age < timedelta(hours=ttl_hours)
                else DataQuality.STALE
            )
            return DataResult(data=data, quality=quality, source="db")
    except Exception as e:
        console.print(f"  [dim]{name} DB: {e}[/]")

    # Tier 3: 中性默认
    return DataResult(data=default_fn(), quality=DataQuality.DEFAULT, source="default")
