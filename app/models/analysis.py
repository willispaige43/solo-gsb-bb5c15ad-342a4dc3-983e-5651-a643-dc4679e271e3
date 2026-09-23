"""分析领域模型：/forecast、/plan-initial-balances、/usage-report、/fairness-report。

只依赖公共基础模型 app.models.base；窗口区间 WindowRange 是本领域
usage/fairness 报告共享的内部类型。
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.errors import RequestValidationErrors
from app.models.base import (
    EPS,
    BucketSpec,
    SimulateRequest,
    _is_finite_number,
    _simulate_cross_validation_errors,
)


class ForecastBucket(BaseModel):
    """预测时刻的桶状态快照。

    capacity: 桶容量（令牌上限）
    refill_rate: 每秒连续补充的令牌数
    balance: 当前余额（now 时刻持有）
    """

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, description="桶唯一标识")]
    capacity: Annotated[float, Field(description="桶容量，必须为正数")]
    refill_rate: Annotated[float, Field(description="令牌补充速率（令牌/秒），必须非负")]
    balance: Annotated[float, Field(description="当前余额，要求 0 ≤ balance ≤ capacity")]

    @field_validator("capacity", "refill_rate", mode="after")
    @classmethod
    def _validate_rate_fields(cls, value, info):
        if info.field_name == "capacity" and value <= 0:
            raise ValueError("capacity 必须为正数")
        if info.field_name == "refill_rate" and value < 0:
            raise ValueError("refill_rate 必须为非负数")
        return value

    @field_validator("balance", mode="before")
    @classmethod
    def _validate_balance(cls, value):
        if not _is_finite_number(value) or value < 0:
            raise ValueError("balance 必须是非负有限数值")
        return value

    @model_validator(mode="after")
    def _check_balance_within_capacity(self):
        if self.balance > self.capacity + EPS:
            raise ValueError("balance 不能大于 capacity")
        return self


class ForecastRequest(BaseModel):
    """POST /forecast 请求体。"""

    model_config = ConfigDict(extra="forbid")

    now: Annotated[float, Field(description="当前时刻（秒，任意一致的时间原点）")]
    cost: Annotated[float, Field(gt=0, description="请求成本（链上每个桶都需持有的令牌数）")]
    chain: Annotated[list[str], Field(min_length=1, description="桶链：按顺序引用的桶 ID")]
    buckets: Annotated[list[ForecastBucket], Field(min_length=1, description="桶状态快照集合")]

    @field_validator("now", mode="before")
    @classmethod
    def _validate_now(cls, value):
        if not _is_finite_number(value):
            raise ValueError("now 必须是有限数值")
        return value

    @field_validator("cost", mode="before")
    @classmethod
    def _validate_cost(cls, value):
        if not _is_finite_number(value):
            raise ValueError("cost 必须是有限数值")
        if value <= 0:
            raise ValueError("cost 必须为正数")
        return value

    @field_validator("chain")
    @classmethod
    def _validate_chain_shape(cls, value: list[str]):
        if not value:
            raise ValueError("chain 至少需要引用一个桶")
        seen: set[str] = set()
        for bucket_id in value:
            if not isinstance(bucket_id, str) or not bucket_id:
                raise ValueError("chain 中的桶 ID 必须是非空字符串")
            if bucket_id in seen:
                raise ValueError(f"chain 中存在重复桶引用: {bucket_id}")
            seen.add(bucket_id)
        return value

    @model_validator(mode="after")
    def _cross_validate(self):
        errors: list[dict] = []

        # 重复桶 ID
        seen: set[str] = set()
        duplicates = False
        for index, bucket in enumerate(self.buckets):
            if bucket.id in seen:
                duplicates = True
                errors.append(
                    {
                        "type": "duplicate_bucket",
                        "loc": ("buckets", index, "id"),
                        "msg": f"重复的桶 ID: {bucket.id}",
                        "input": bucket.id,
                    }
                )
            seen.add(bucket.id)

        if duplicates:
            # 已存在重复定义，引用校验意义不大，直接返回
            raise RequestValidationErrors(errors)

        # 链中未知引用
        for c_index, bucket_id in enumerate(self.chain):
            if bucket_id not in seen:
                errors.append(
                    {
                        "type": "unknown_bucket_ref",
                        "loc": ("chain", c_index),
                        "msg": f"桶链引用了未定义的桶: {bucket_id}",
                        "input": bucket_id,
                    }
                )

        if errors:
            raise RequestValidationErrors(errors)
        return self


class ForecastBucketResult(BaseModel):
    """链上单个桶的可达性预测。"""

    id: str
    balance_now: Annotated[float, Field(description="now 时刻的余额")]
    reachable: Annotated[bool, Field(description="该桶单独是否可达成本")]
    reason: Annotated[
        str | None,
        Field(default=None, description="不可达原因：cost_exceeds_capacity / zero_refill_rate"),
    ] = None
    wait_seconds: Annotated[
        float | None, Field(default=None, description="该桶单独满足成本所需等待秒数；不可达为 null")
    ] = None
    projected_balance: Annotated[
        float | None,
        Field(default=None, description="预计可通过时刻的余额（不扣减）；链不可达时为 null"),
    ] = None


class ForecastResponse(BaseModel):
    reachable: Annotated[bool, Field(description="链上全部桶是否都能达到成本")]
    wait_seconds: Annotated[
        float | None, Field(description="全部桶首次同时满足成本所需等待秒数；不可达为 null")
    ]
    pass_at: Annotated[
        float | None, Field(description="预计可通过时刻 = now + wait_seconds；不可达为 null")
    ]
    limiting_bucket: Annotated[
        str | None,
        Field(description="等待最长的限制桶（并列取链上首个）；立即可通过或不可达时为 null"),
    ]
    buckets: Annotated[list[ForecastBucketResult], Field(description="链上各桶的预测，按链顺序")]


class PlanBucketResult(BaseModel):
    """单个桶的初始余额规划结果。"""

    id: str
    required_initial: Annotated[
        float, Field(description="满足该桶全部链上消耗所需的最低初始余额（[0, capacity] 内）")
    ]
    requested_initial: Annotated[
        float, Field(description="请求中给出的 initial；缺省按 capacity 计")
    ]
    delta: Annotated[
        float,
        Field(description="required_initial - requested_initial；为正表示请求初始余额不足"),
    ]


class PlanFailure(BaseModel):
    """满桶起步仍不可行时，按处理顺序首个无法满足的请求与桶。"""

    request_id: str
    index: Annotated[int, Field(description="该请求在原始 requests 数组中的下标")]
    timestamp: float
    bucket_id: Annotated[str, Field(description="链上首个余额不足的桶 ID")]
    cost: Annotated[float, Field(description="该请求的消耗量")]
    available: Annotated[
        float, Field(description="满桶起步回放中，该桶在判定时刻（补充之后、扣减之前）的余额")
    ]


class PlanInitialBalancesResponse(BaseModel):
    reachable: Annotated[bool, Field(description="满桶起步是否能让全部请求放行")]
    buckets: Annotated[
        list[PlanBucketResult] | None,
        Field(description="各桶规划结果，按 buckets 输入顺序；不可行为 null"),
    ]
    final_balances: Annotated[
        dict[str, float] | None,
        Field(description="用规划值完整回放得到的终态余额；不可行为 null"),
    ]
    first_failure: Annotated[
        PlanFailure | None,
        Field(description="不可行时按处理顺序首个无法满足的请求与桶；可行时为 null"),
    ]


class UsageReportRequest(SimulateRequest):
    """POST /usage-report 请求体：/simulate 请求体 + 统计窗口宽度。

    桶与请求的字段、跨字段校验（重复桶、未知引用、重复请求 ID）全部沿用
    SimulateRequest。
    """

    window_seconds: Annotated[float, Field(description="统计窗口宽度（秒），必须为正的有限数值")]

    @field_validator("window_seconds", mode="before")
    @classmethod
    def _validate_window_seconds(cls, value):
        if not _is_finite_number(value):
            raise ValueError("window_seconds 必须是有限数值")
        if value <= 0:
            raise ValueError("window_seconds 必须为正数")
        return value


class WindowRange(BaseModel):
    """半开窗口区间 [start, end)。"""

    index: Annotated[int, Field(description="窗口序号（从 0 开始）")]
    start: Annotated[float, Field(description="窗口起点（含）")]
    end: Annotated[float, Field(description="窗口终点（不含）")]


class UsageWindowStats(BaseModel):
    """单个桶在单个窗口内的使用统计。"""

    index: Annotated[int, Field(description="窗口序号")]
    allowed_consumption: Annotated[
        float, Field(description="窗口内放行请求对该桶的消耗合计")
    ]
    rejected_count: Annotated[
        int, Field(description="窗口内引用该桶且被原子拒绝的请求数（无论限制桶是否为该桶）")
    ]
    peak_occupancy: Annotated[
        float, Field(description="窗口内峰值占用 = capacity - 窗口内最低余额")
    ]


class UsageBucketReport(BaseModel):
    """单个桶的逐窗统计与峰值信息。"""

    id: str
    allowed_consumption: Annotated[float, Field(description="全部窗口放行消耗合计")]
    rejected_count: Annotated[int, Field(description="全部窗口拒绝次数合计")]
    peak_occupancy: Annotated[float, Field(description="全部窗口中的最高峰值占用")]
    peak_window: Annotated[
        WindowRange, Field(description="达到峰值占用的窗口起止时间（并列取最早窗口）")
    ]
    windows: Annotated[
        list[UsageWindowStats], Field(description="逐窗口统计，按窗口序号升序")
    ]


class BusiestWindow(WindowRange):
    """全局最忙窗口：跨桶放行消耗合计最大的窗口（并列取最早）。"""

    allowed_consumption: Annotated[float, Field(description="该窗口全部桶放行消耗之和")]
    allowed_count: Annotated[int, Field(description="该窗口放行的请求数")]
    rejected_count: Annotated[int, Field(description="该窗口被拒的请求数")]


class UsageReportResponse(BaseModel):
    window_seconds: Annotated[float, Field(description="统计窗口宽度（秒）")]
    window_count: Annotated[int, Field(description="覆盖请求时间跨度的窗口总数")]
    windows: Annotated[
        list[WindowRange], Field(description="全部窗口的起止时间，按窗口序号升序")
    ]
    buckets: Annotated[
        list[UsageBucketReport], Field(description="各桶统计，按 buckets 输入顺序")
    ]
    busiest_window: Annotated[BusiestWindow, Field(description="全局最忙窗口")]


class FairnessSimRequest(BaseModel):
    """公平性试算请求：在 /simulate 请求字段上增加 principal 与 weight。"""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, description="请求唯一标识")]
    timestamp: Annotated[float, Field(description="请求时间（秒，任意一致的时间原点）")]
    cost: Annotated[float, Field(gt=0, description="消耗量（从链上每个桶扣减的令牌数）")]
    chain: Annotated[list[str], Field(min_length=1, description="桶链：按顺序引用的桶 ID")]
    principal: Annotated[
        str, Field(min_length=1, description="请求归属主体（租户/用户/调用方 ID）")
    ]
    weight: Annotated[
        float,
        Field(default=1.0, description="主体权重，必须为正的有限数值；缺省为 1.0"),
    ] = 1.0

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value):
        if not _is_finite_number(value):
            raise ValueError("timestamp 必须是有限数值")
        return value

    @field_validator("cost", mode="before")
    @classmethod
    def _validate_cost(cls, value):
        if not _is_finite_number(value):
            raise ValueError("cost 必须是有限数值")
        if value <= 0:
            raise ValueError("cost 必须为正数")
        return value

    @field_validator("principal", mode="before")
    @classmethod
    def _validate_principal(cls, value):
        if not isinstance(value, str) or not value:
            raise ValueError("principal 必须是非空字符串")
        return value

    @field_validator("weight", mode="before")
    @classmethod
    def _validate_weight(cls, value):
        if not _is_finite_number(value):
            raise ValueError("weight 必须是有限数值")
        if value <= 0:
            raise ValueError("weight 必须为正数")
        return value

    @field_validator("chain")
    @classmethod
    def _validate_chain_shape(cls, value: list[str]):
        if not value:
            raise ValueError("chain 至少需要引用一个桶")
        seen: set[str] = set()
        for bucket_id in value:
            if not isinstance(bucket_id, str) or not bucket_id:
                raise ValueError("chain 中的桶 ID 必须是非空字符串")
            if bucket_id in seen:
                raise ValueError(f"chain 中存在重复桶引用: {bucket_id}")
            seen.add(bucket_id)
        return value


class FairnessReportRequest(BaseModel):
    """POST /fairness-report 请求体：带 principal/weight 的请求序列 + 统计窗口宽度。

    桶与请求的字段、跨字段校验（重复桶、未知引用、重复请求 ID）沿用
    SimulateRequest 的同一套规则。
    """

    model_config = ConfigDict(extra="forbid")

    buckets: Annotated[list[BucketSpec], Field(min_length=1, description="令牌桶集合")]
    requests: Annotated[
        list[FairnessSimRequest], Field(min_length=1, description="按时间戳模拟的请求序列")
    ]
    window_seconds: Annotated[float, Field(description="统计窗口宽度（秒），必须为正的有限数值")]

    @field_validator("window_seconds", mode="before")
    @classmethod
    def _validate_window_seconds(cls, value):
        if not _is_finite_number(value):
            raise ValueError("window_seconds 必须是有限数值")
        if value <= 0:
            raise ValueError("window_seconds 必须为正数")
        return value

    @model_validator(mode="after")
    def _cross_validate(self):
        errors = _simulate_cross_validation_errors(self.buckets, self.requests)

        # 同一 principal 的权重必须一致：加权 Jain 指数以主体为单位计算
        principal_weight: dict[str, float] = {}
        for r_index, request in enumerate(self.requests):
            previous = principal_weight.get(request.principal)
            if previous is None:
                principal_weight[request.principal] = float(request.weight)
            elif abs(previous - float(request.weight)) > EPS:
                errors.append(
                    {
                        "type": "inconsistent_principal_weight",
                        "loc": ("requests", r_index, "weight"),
                        "msg": (
                            f"principal {request.principal!r} 的权重不一致："
                            f"{previous} 与 {float(request.weight)}"
                        ),
                        "input": request.weight,
                    }
                )

        if errors:
            raise RequestValidationErrors(errors)
        return self


class FairnessPrincipalRow(BaseModel):
    """单个主体在某个统计范围（全局或单个窗口）内的公平性数据。"""

    principal: Annotated[str, Field(description="主体标识")]
    weight: Annotated[float, Field(description="主体权重")]
    request_count: Annotated[int, Field(description="该范围内该主体的请求总数")]
    allowed_count: Annotated[int, Field(description="放行请求数")]
    rejected_count: Annotated[int, Field(description="被原子拒绝的请求数")]
    allowed_consumption: Annotated[
        float, Field(description="放行请求的 cost 合计（该主体的实际获得量）")
    ]
    theoretical_share: Annotated[
        float,
        Field(description="理论权重份额 = 该范围全部放行消耗 × weight / 权重合计"),
    ]
    deficit: Annotated[
        float, Field(description="短缺量 = max(0, theoretical_share - allowed_consumption)")
    ]
    deficit_ratio: Annotated[
        float,
        Field(description="短缺比例 = deficit / theoretical_share；理论份额为 0 时为 0"),
    ]


class FirstShortfall(BaseModel):
    """最受限主体的短缺证据：按处理顺序首个造成其短缺的拒绝。"""

    request_id: Annotated[str, Field(description="被拒绝的请求 ID")]
    index: Annotated[int, Field(description="该请求在原始 requests 数组中的下标")]
    timestamp: Annotated[float, Field(description="该请求的时间戳")]
    bucket_id: Annotated[str, Field(description="导致原子拒绝的第一个余额不足的桶 ID")]
    cost: Annotated[float, Field(description="该请求的消耗量")]
    available: Annotated[
        float, Field(description="判定时刻（补充之后、扣减之前）限制桶的余额")
    ]


class FairnessScopeReport(BaseModel):
    """一个统计范围（全局或单个窗口）的公平性报告。"""

    principal_count: Annotated[int, Field(description="参与该范围统计的主体数")]
    request_count: Annotated[int, Field(description="该范围内的请求总数")]
    allowed_count: Annotated[int, Field(description="放行请求总数")]
    rejected_count: Annotated[int, Field(description="拒绝请求总数")]
    allowed_consumption: Annotated[
        float, Field(description="全部主体放行消耗（实际获得量）合计")
    ]
    weighted_jain_index: Annotated[
        float,
        Field(
            description=(
                "加权 Jain 公平指数 = (Σ x)² / (Σ w · Σ x²/w)，"
                "x 为主体实际获得量、w 为权重；取值 (0, 1]，越大越公平"
            )
        ),
    ]
    most_constrained_principal: Annotated[
        str | None,
        Field(
            description=(
                "短缺比例最高且有被拒请求的主体（并列取首次拒绝最早者）；"
                "不存在有短缺的被拒主体时为 null"
            )
        ),
    ]
    first_shortfall: Annotated[
        FirstShortfall | None,
        Field(
            description="最受限主体按处理顺序的首个短缺拒绝；无最受限主体时为 null"
        ),
    ]
    principals: Annotated[
        list[FairnessPrincipalRow],
        Field(description="各主体统计，按主体首次请求的处理顺序"),
    ]


class FairnessWindowReport(FairnessScopeReport):
    """单个窗口的公平性报告：范围数据 + 窗口起止。"""

    index: Annotated[int, Field(description="窗口序号")]
    start: Annotated[float, Field(description="窗口起点（含）")]
    end: Annotated[float, Field(description="窗口终点（不含）")]


class FairnessReportResponse(BaseModel):
    window_seconds: Annotated[float, Field(description="统计窗口宽度（秒）")]
    window_count: Annotated[int, Field(description="覆盖请求时间跨度的窗口总数")]
    windows: Annotated[
        list[WindowRange], Field(description="全部窗口的起止时间，按窗口序号升序")
    ]
    global_report: Annotated[FairnessScopeReport, Field(description="跨全部窗口的全局报告")]
    window_reports: Annotated[
        list[FairnessWindowReport], Field(description="逐窗口报告，按窗口序号升序")
    ]
