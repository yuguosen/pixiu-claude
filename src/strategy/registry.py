"""策略注册表 — 装饰器自动注册，插件化管理"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.strategy.base import Strategy

_REGISTRY: dict[str, tuple[type["Strategy"], float]] = {}


def register_strategy(weight: float = 0.20):
    """装饰器: @register_strategy(weight=0.30)

    Args:
        weight: 该策略的默认权重 (可被学习系统覆盖)
    """

    def decorator(cls):
        if not hasattr(cls, "name") or cls.name == "base":
            raise ValueError(f"{cls.__name__} must define a unique `name`")
        _REGISTRY[cls.name] = (cls, weight)
        return cls

    return decorator


def get_registered_strategies() -> dict[str, tuple[type["Strategy"], float]]:
    """返回所有已注册策略 {name: (cls, default_weight)}"""
    return dict(_REGISTRY)


def get_strategy_names() -> list[str]:
    """返回所有已注册策略名称"""
    return list(_REGISTRY.keys())


def discover_strategies():
    """强制导入所有策略模块以触发注册

    使用显式模块列表而非文件扫描，安全可控。
    """
    import importlib

    for mod in [
        "src.strategy.trend_following",
        "src.strategy.mean_reversion",
        "src.strategy.momentum",
        "src.strategy.valuation",
        "src.strategy.macro_cycle",
        "src.strategy.manager_alpha",
    ]:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass
