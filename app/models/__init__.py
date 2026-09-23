"""Pydantic 模型门面（稳定导出层）。

历史上所有模型都定义在 ``app.models`` 单文件中；现在按领域拆分到
``app/models/`` 下的独立模块，本文件保持 ``from app.models import X`` 的
既有导入路径与名称不变：

- base: 公共基础模型（BucketSpec/SimRequest/SimulateRequest/BucketBalance 等）
- simulation_models: 基础模拟结果（SimResult/SimulateResponse）
- analysis: 分析领域（/forecast、/plan-initial-balances、/usage-report、/fairness-report）
- reservation: 预留（/reservation-simulate）
- routing: 路由（/route-simulate）
- queueing: 排队（/queue-simulate）
- windowing: 滑动窗口（/window-simulate）
- rollover: 周期结转（/rollover-simulate）
- debt: 可借贷桶（/debt-simulate）
- debt_diff: 两情景债务对比（/debt-diff）

业务处理函数可以继续从本门面导入，也可以逐步迁移到所属领域模块；
领域模型模块之间不得通过本门面互相导入，以免重新引入跨领域循环。
"""
from __future__ import annotations

from app.models.base import (
    EPS,
    BucketBalance,
    BucketSpec,
    SimRequest,
    SimulateRequest,
    _is_finite_number,
    _simulate_cross_validation_errors,
)
from app.models.simulation_models import (
    SimResult,
    SimulateResponse,
)
from app.models.analysis import (
    BusiestWindow,
    FairnessPrincipalRow,
    FairnessReportRequest,
    FairnessReportResponse,
    FairnessScopeReport,
    FairnessSimRequest,
    FairnessWindowReport,
    FirstShortfall,
    ForecastBucket,
    ForecastBucketResult,
    ForecastRequest,
    ForecastResponse,
    PlanBucketResult,
    PlanFailure,
    PlanInitialBalancesResponse,
    UsageBucketReport,
    UsageReportRequest,
    UsageReportResponse,
    UsageWindowStats,
    WindowRange,
)
from app.models.reservation import (
    OccupancyInterval,
    ReservationBucket,
    ReservationBucketOccupancy,
    ReservationRequest,
    ReservationResult,
    ReservationSimulateRequest,
    ReservationSimulateResponse,
)
from app.models.routing import (
    RouteCandidateRejection,
    RouteSimRequest,
    RouteSimResult,
    RouteSimulateRequest,
    RouteSimulateResponse,
)
from app.models.queueing import (
    QueueSimRequest,
    QueueSimResult,
    QueueSimulateRequest,
    QueueSimulateResponse,
)
from app.models.windowing import (
    SlidingWindowRange,
    WindowPolicyFinalState,
    WindowPolicySpec,
    WindowPolicyView,
    WindowPrincipalOccupancy,
    WindowRejection,
    WindowSimRequest,
    WindowSimResult,
    WindowSimulateRequest,
    WindowSimulateResponse,
)
from app.models.rollover import (
    PeriodRange,
    RolloverBalances,
    RolloverPolicyFinalState,
    RolloverPolicySpec,
    RolloverPolicyView,
    RolloverRejection,
    RolloverSimRequest,
    RolloverSimResult,
    RolloverSimulateRequest,
    RolloverSimulateResponse,
)
from app.models.debt import (
    DebtBucketBalance,
    DebtBucketFinalState,
    DebtBucketSpec,
    DebtRejection,
    DebtSimResult,
    DebtSimulateRequest,
    DebtSimulateResponse,
)
from app.models.debt_diff import (
    DebtDiffBucketDelta,
    DebtDiffFinalSnapshot,
    DebtDiffFirstDivergence,
    DebtDiffOutcome,
    DebtDiffRequest,
    DebtDiffResponse,
    DebtDiffResult,
)

__all__ = [
    # 公共基础
    "EPS",
    "BucketBalance",
    "BucketSpec",
    "SimRequest",
    "SimulateRequest",
    # 基础模拟响应
    "SimResult",
    "SimulateResponse",
    "PlanBucketResult",
    "PlanFailure",
    "PlanInitialBalancesResponse",
    # 分析（预测/规划/用量/公平性）
    "ForecastBucket",
    "ForecastBucketResult",
    "ForecastRequest",
    "ForecastResponse",
    "UsageReportRequest",
    "WindowRange",
    "UsageWindowStats",
    "UsageBucketReport",
    "BusiestWindow",
    "UsageReportResponse",
    "FairnessSimRequest",
    "FairnessReportRequest",
    "FairnessPrincipalRow",
    "FirstShortfall",
    "FairnessScopeReport",
    "FairnessWindowReport",
    "FairnessReportResponse",
    # 预留
    "ReservationBucket",
    "ReservationRequest",
    "ReservationSimulateRequest",
    "OccupancyInterval",
    "ReservationResult",
    "ReservationBucketOccupancy",
    "ReservationSimulateResponse",
    # 路由
    "RouteSimRequest",
    "RouteSimulateRequest",
    "RouteCandidateRejection",
    "RouteSimResult",
    "RouteSimulateResponse",
    # 排队
    "QueueSimRequest",
    "QueueSimulateRequest",
    "QueueSimResult",
    "QueueSimulateResponse",
    # 滑动窗口
    "WindowPolicySpec",
    "WindowSimRequest",
    "WindowSimulateRequest",
    "SlidingWindowRange",
    "WindowPolicyView",
    "WindowRejection",
    "WindowSimResult",
    "WindowPrincipalOccupancy",
    "WindowPolicyFinalState",
    "WindowSimulateResponse",
    # 周期结转
    "RolloverPolicySpec",
    "RolloverSimRequest",
    "RolloverSimulateRequest",
    "PeriodRange",
    "RolloverBalances",
    "RolloverPolicyView",
    "RolloverRejection",
    "RolloverSimResult",
    "RolloverPolicyFinalState",
    "RolloverSimulateResponse",
    # 可借贷桶
    "DebtBucketSpec",
    "DebtSimulateRequest",
    "DebtBucketBalance",
    "DebtRejection",
    "DebtSimResult",
    "DebtBucketFinalState",
    "DebtSimulateResponse",
    # 两情景债务对比
    "DebtDiffRequest",
    "DebtDiffOutcome",
    "DebtDiffFirstDivergence",
    "DebtDiffBucketDelta",
    "DebtDiffResult",
    "DebtDiffFinalSnapshot",
    "DebtDiffResponse",
]
