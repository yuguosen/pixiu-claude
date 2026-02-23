"""LLM 结构化输出模型 — Pydantic 验证"""

from pydantic import BaseModel, Field, field_validator


class MarketAssessment(BaseModel):
    """市场评估"""
    regime_agreement: bool = True
    regime_override: str | None = None
    key_risks: list[str] = Field(default_factory=list)
    key_opportunities: list[str] = Field(default_factory=list)
    sentiment: str = "neutral"
    narrative: str = ""

    @field_validator("sentiment")
    @classmethod
    def validate_sentiment(cls, v: str) -> str:
        valid = {"bullish", "bearish", "cautious", "neutral"}
        if v not in valid:
            return "neutral"
        return v


class FundRecommendation(BaseModel):
    """单只基金建议"""
    fund_code: str
    action: str = "hold"
    confidence: float = Field(default=0.5, ge=0, le=1)
    amount: float = 0
    reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    stop_loss_trigger: str = ""

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        valid = {"buy", "sell", "hold", "watch"}
        if v not in valid:
            return "hold"
        return v


class AgentDecision(BaseModel):
    """完整决策"""
    date: str
    market_assessment: MarketAssessment
    recommendations: list[FundRecommendation]
    portfolio_advice: str = ""
    watchlist_changes: list[str] = Field(default_factory=list)
    confidence_summary: str = ""


class ReflectionResult(BaseModel):
    """反思结果"""
    was_correct: bool = False
    accuracy_analysis: str = ""
    missed_factors: list[str] = Field(default_factory=list)
    overweighted_factors: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    strategy_suggestions: list[str] = Field(default_factory=list)


class ScenarioResult(BaseModel):
    """场景推演结果"""
    analysis_horizon: str = "1-3个月"
    scenarios: dict = Field(default_factory=dict)
    expected_value: float = 0.0
    recommendation: str = ""
    risk_reward_ratio: str = ""
    tokens_used: int = 0


class DebateVerdict(BaseModel):
    """辩论裁判判决"""
    verdict: str = ""
    side_taken: str = "neutral"
    reasoning: str = ""
    winning_arguments: list[str] = Field(default_factory=list)
    dismissed_arguments: list[str] = Field(default_factory=list)
    action: str = "hold"
    confidence: float = Field(default=0.5, ge=0, le=1)
    position_advice: str = ""

    @field_validator("side_taken")
    @classmethod
    def validate_side(cls, v: str) -> str:
        valid = {"bullish", "bearish", "neutral"}
        if v not in valid:
            return "neutral"
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        valid = {"buy", "sell", "hold", "watch"}
        if v not in valid:
            return "hold"
        return v
