"""基础模拟领域 (/simulate) 的结果与响应模型。

只依赖公共基础模型 app.models.base；/plan-initial-balances 的请求体复用
base.SimulateRequest，其规划结果模型位于 analysis 领域模块。
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from app.models.base import BucketBalance


class SimResult(BaseModel):
    """单项请求的模拟结果。"""

    request_id: str
    index: Annotated[int, Field(description="该请求在原始 requests 数组中的下标")]
    timestamp: float
    allowed: bool
    rejected_by: Annotated[str | None, Field(default=None, description="导致拒绝的第一个余额不足的桶 ID")]
    balances: Annotated[dict[str, BucketBalance], Field(description="链上各桶扣减前后余额")]


class SimulateResponse(BaseModel):
    allowed_count: int
    rejected_count: int
    results: list[SimResult]
    final_balances: Annotated[dict[str, float], Field(description="模拟结束时所有桶的余额")]
