"""交易费用计算"""

from src.config import CONFIG


def calculate_subscription_fee(
    amount: float, fee_rate: float = 0.015, discount: float = None
) -> dict:
    """计算申购费用

    Args:
        amount: 申购金额 (RMB)
        fee_rate: 原始申购费率 (默认 1.5%)
        discount: 折扣 (默认用支付宝1折)

    Returns:
        dict: {fee, net_amount, fee_rate_actual}
    """
    if discount is None:
        discount = CONFIG["subscription_fee_discount"]

    actual_rate = fee_rate * discount
    fee = amount * actual_rate
    net_amount = amount - fee

    return {
        "fee": round(fee, 2),
        "net_amount": round(net_amount, 2),
        "fee_rate_original": fee_rate,
        "fee_rate_actual": round(actual_rate, 4),
        "discount": discount,
    }


def calculate_redemption_fee(
    amount: float, holding_days: int, fee_schedule: dict = None
) -> dict:
    """计算赎回费用

    Args:
        amount: 赎回金额 (RMB)
        holding_days: 持有天数
        fee_schedule: 费率表 {天数阈值: 费率}

    Returns:
        dict: {fee, net_amount, fee_rate}
    """
    if fee_schedule is None:
        fee_schedule = {
            7: 0.015,    # 7天内 1.5%
            30: 0.0075,  # 30天内 0.75%
            365: 0.005,  # 1年内 0.5%
            730: 0.0025, # 2年内 0.25%
            99999: 0.0,  # 2年以上 0%
        }

    fee_rate = 0
    for days_threshold, rate in sorted(fee_schedule.items()):
        if holding_days < days_threshold:
            fee_rate = rate
            break

    fee = amount * fee_rate
    net_amount = amount - fee

    return {
        "fee": round(fee, 2),
        "net_amount": round(net_amount, 2),
        "fee_rate": fee_rate,
        "holding_days": holding_days,
    }


def estimate_round_trip_cost(
    amount: float,
    holding_days: int = 30,
    subscription_rate: float = 0.015,
) -> dict:
    """估算一次完整买卖的总费用

    Args:
        amount: 交易金额
        holding_days: 预计持有天数
        subscription_rate: 申购费率

    Returns:
        dict: 总费用明细
    """
    buy_cost = calculate_subscription_fee(amount, subscription_rate)
    sell_cost = calculate_redemption_fee(amount, holding_days)

    total_fee = buy_cost["fee"] + sell_cost["fee"]
    total_fee_pct = total_fee / amount * 100 if amount > 0 else 0

    return {
        "subscription_fee": buy_cost["fee"],
        "redemption_fee": sell_cost["fee"],
        "total_fee": round(total_fee, 2),
        "total_fee_pct": round(total_fee_pct, 3),
        "breakeven_return_pct": round(total_fee_pct, 3),
        "net_investment": round(buy_cost["net_amount"], 2),
    }
