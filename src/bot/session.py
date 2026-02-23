"""多步会话状态机 — 交易录入等多步交互"""

import time
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TradeSession:
    """交易录入会话"""
    user_id: str
    step: int = 0  # 0=fund_code, 1=action, 2=amount, 3=nav, 4=date, 5=reason, 6=confirm
    data: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    STEPS = [
        ("fund_code", "请输入基金代码 (6位数字):"),
        ("action", "买入还是卖出? (buy/sell):"),
        ("amount", "金额 (RMB):"),
        ("nav", "成交净值:"),
        ("trade_date", "交易日期 (YYYY-MM-DD, 输入'今天'用今日):"),
        ("reason", "备注 (可选, 输入'跳过'):"),
        ("confirm", None),  # confirm step is special
    ]

    TIMEOUT = 300  # 5 分钟超时

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.TIMEOUT

    @property
    def current_field(self) -> str:
        if self.step < len(self.STEPS):
            return self.STEPS[self.step][0]
        return "done"

    @property
    def current_prompt(self) -> str | None:
        if self.step < len(self.STEPS):
            return self.STEPS[self.step][1]
        return None

    def process_input(self, text: str) -> tuple[str, dict | None]:
        """处理用户输入, 返回 (下一步提示/结果, 交易数据或None)

        Returns:
            ("prompt_text", None) — 需要继续输入
            ("success", trade_data) — 交易确认完成
            ("cancelled", None) — 用户取消
            ("error:xxx", None) — 输入校验失败
        """
        text = text.strip()

        if text in ("取消", "cancel"):
            return "cancelled", None

        field_name = self.current_field

        if field_name == "fund_code":
            if not text.isdigit() or len(text) != 6:
                return "error:请输入6位数字基金代码", None
            self.data["fund_code"] = text

        elif field_name == "action":
            text_lower = text.lower()
            if text_lower in ("buy", "买入", "买"):
                self.data["action"] = "buy"
            elif text_lower in ("sell", "卖出", "卖"):
                self.data["action"] = "sell"
            else:
                return "error:请输入 buy 或 sell", None

        elif field_name == "amount":
            try:
                amount = float(text)
                if amount <= 0:
                    return "error:金额必须大于0", None
                self.data["amount"] = amount
            except ValueError:
                return "error:请输入有效的数字金额", None

        elif field_name == "nav":
            try:
                nav = float(text)
                if nav <= 0:
                    return "error:净值必须大于0", None
                self.data["nav"] = nav
            except ValueError:
                return "error:请输入有效的净值", None

        elif field_name == "trade_date":
            if text in ("今天", "today", "t"):
                self.data["trade_date"] = datetime.now().strftime("%Y-%m-%d")
            else:
                try:
                    datetime.strptime(text, "%Y-%m-%d")
                    self.data["trade_date"] = text
                except ValueError:
                    return "error:日期格式须为 YYYY-MM-DD", None

        elif field_name == "reason":
            self.data["reason"] = "" if text in ("跳过", "skip", "s") else text

        elif field_name == "confirm":
            if text in ("确认", "confirm", "y", "yes"):
                return "success", self.data
            elif text in ("取消", "cancel", "n", "no"):
                return "cancelled", None
            else:
                return "error:请回复 确认 或 取消", None

        # 推进到下一步
        self.step += 1
        self.created_at = time.time()  # 重置超时

        if self.current_field == "confirm":
            return "confirm", self.data
        return self.current_prompt or "", None


class SessionManager:
    """会话管理器 — 管理所有用户的多步会话"""

    def __init__(self):
        self._sessions: dict[str, TradeSession] = {}

    def has_active_session(self, user_id: str) -> bool:
        session = self._sessions.get(user_id)
        if session and session.is_expired:
            del self._sessions[user_id]
            return False
        return user_id in self._sessions

    def start_trade_session(self, user_id: str) -> str:
        """启动交易录入会话, 返回第一步提示"""
        session = TradeSession(user_id=user_id)
        self._sessions[user_id] = session
        return session.current_prompt or ""

    def process(self, user_id: str, text: str) -> tuple[str, dict | None]:
        """处理会话输入"""
        session = self._sessions.get(user_id)
        if not session:
            return "error:无活跃会话", None

        if session.is_expired:
            del self._sessions[user_id]
            return "expired", None

        result, data = session.process_input(text)

        if result in ("success", "cancelled", "expired"):
            self._sessions.pop(user_id, None)

        return result, data

    def cancel(self, user_id: str):
        self._sessions.pop(user_id, None)
