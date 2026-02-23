"""季节性/日历因子

A股市场已验证的季节性模式:
1. 春节效应: 节前一周通常上涨 (红包行情)
2. 两会效应: 3月初两会期间偏稳
3. 财报季压力: 4月/8月/10月财报披露期波动加大
4. 年末窗口粉饰: 12月基金年末调仓
5. 月末效应: 每月最后3天资金面偏紧
6. 周一效应: 周一下跌概率略高
"""

from datetime import datetime, timedelta


def get_seasonal_modifier() -> tuple[float, str]:
    """获取当前日期的季节性信心调节因子

    Returns:
        (modifier, reason)
        modifier: -0.2 ~ +0.2, 负值=减少买入信心, 正值=增加买入信心
        reason: 原因说明
    """
    now = datetime.now()
    month = now.month
    day = now.day
    weekday = now.weekday()  # 0=Monday

    modifier = 0.0
    reasons = []

    # ── 1. 春节红包行情 (农历春节前1-2周, 简化为公历1月下旬~2月初) ──
    if (month == 1 and day >= 20) or (month == 2 and day <= 10):
        modifier += 0.1
        reasons.append("春节红包行情")

    # ── 2. 两会维稳期 (3月1-15日) ──
    if month == 3 and day <= 15:
        modifier += 0.05
        reasons.append("两会维稳期")

    # ── 3. 财报季波动 (4月/8月/10月公布季报) ──
    if month in (4, 8, 10) and 10 <= day <= 30:
        modifier -= 0.1
        reasons.append("财报季波动")

    # ── 4. 年末窗口粉饰 (12月) ──
    if month == 12 and day >= 15:
        modifier += 0.05
        reasons.append("年末基金粉饰")

    # ── 5. 月末资金紧张 (每月最后3天) ──
    # 简化: 28-31号
    if day >= 28:
        modifier -= 0.05
        reasons.append("月末资金面紧张")

    # ── 6. 开门红 (每年第一个交易周) ──
    if month == 1 and day <= 7:
        modifier += 0.05
        reasons.append("开门红效应")

    # ── 7. 国庆后效应 (10月初回来常有反弹) ──
    if month == 10 and day <= 12:
        modifier += 0.05
        reasons.append("国庆后效应")

    # ── 8. 五穷六绝 (5-6月历史偏弱) ──
    if month in (5, 6):
        modifier -= 0.05
        reasons.append("五穷六绝")

    reason = "; ".join(reasons) if reasons else "无季节性因素"
    return round(max(-0.2, min(0.2, modifier)), 2), reason
