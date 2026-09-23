"""结构约束：模型门面导出与领域依赖边界。

这些测试不校验业务语义，只防止以下回退：
1. ``app.models`` 门面丢失或替换历史上的公开模型（请求/响应类型必须
   保持同一 class 对象，OpenAPI schema 名称与引用才不会变）；
2. 领域模型模块跨领域导入、或反向通过门面导入彼此，重新引入循环依赖。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import BaseModel

import app.models as facade
from app.models import base as base_models

MODELS_DIR = Path(__file__).resolve().parent.parent / "app" / "models"

# 拆分前 app/models.py 中的全部顶层公开名称。
# 门面必须逐项原样保留（同一个类对象，而非名称不同的替代品）。
EXPECTED_FACADE_NAMES = [
    # 公共基础
    "EPS",
    "BucketSpec",
    "SimRequest",
    "SimulateRequest",
    "BucketBalance",
    # 基础模拟响应
    "SimResult",
    "SimulateResponse",
    "PlanBucketResult",
    "PlanFailure",
    "PlanInitialBalancesResponse",
    # 分析（预测 / 规划 / 用量 / 公平性）
    "ForecastBucket",
    "ForecastRequest",
    "ForecastBucketResult",
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
    # 公共校验工具（拆分前即为可导入名称；下划线开头不进 __all__）
    "_is_finite_number",
    "_simulate_cross_validation_errors",
]

# 拆分前 app/models.py 没有 __all__；公开面即全部非下划线开头的名称。
EXPECTED_PUBLIC_NAMES = [name for name in EXPECTED_FACADE_NAMES if not name.startswith("_")]

# 领域模型模块（门面本身 __init__.py 除外）。
DOMAIN_MODULES = {
    path.stem
    for path in MODELS_DIR.glob("*.py")
    if path.name != "__init__.py"
}

# 每个领域允许依赖的 app.models 子模块白名单。
# base 是所有领域共享的公共基础；debt_diff 属于债务领域，允许复用 debt。
ALLOWED_MODEL_IMPORTS = {
    "base": set(),  # 公共基础不得依赖任何领域模块
    "simulation_models": {"base"},
    "analysis": {"base"},
    "reservation": {"base"},
    "routing": {"base"},
    "queueing": {"base"},
    "windowing": {"base"},
    "rollover": {"base"},
    "debt": {"base"},
    "debt_diff": {"base", "debt"},
}


def _imported_app_model_modules(path: Path) -> list[tuple[int, str]]:
    """返回 (行号, 被导入的 app.models 子模块名) 列表。

    对 ``import app.models.debt`` 与 ``from app.models.debt import X``
    两种形式都生效；裸 ``import app.models``（门面）也会被捕获为 "<facade>"。
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.models"):
            parts = node.module.split(".")
            found.append((node.lineno, parts[2] if len(parts) >= 3 else "<facade>"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.models":
                    found.append((node.lineno, "<facade>"))
                elif alias.name.startswith("app.models."):
                    found.append((node.lineno, alias.name.split(".")[2]))
    return found


def test_models_package_is_split_into_domains():
    assert (MODELS_DIR / "__init__.py").is_file(), "app.models 必须是包（门面 __init__.py）"
    assert not (MODELS_DIR.parent / "models.py").exists(), "旧的单文件 app/models.py 必须已移除"
    expected = set(ALLOWED_MODEL_IMPORTS)
    assert expected <= DOMAIN_MODULES, f"缺少领域模块: {sorted(expected - DOMAIN_MODULES)}"


def test_facade_exports_every_legacy_name():
    missing = [name for name in EXPECTED_FACADE_NAMES if not hasattr(facade, name)]
    assert not missing, f"门面缺少历史导出: {missing}"
    public_names = [name for name in EXPECTED_FACADE_NAMES if not name.startswith("_")]
    assert set(public_names) <= set(facade.__all__), "__all__ 未覆盖全部历史公开名称"


def test_facade_reexports_identical_model_objects():
    """门面必须透传领域模块中的同一个类对象。

    若门面重新定义了同名类，请求/响应 JSON 虽兼容，但 OpenAPI 的
    $ref 目标会被拆成两个 schema，因此这里比对类身份而非仅名称。
    """
    import importlib

    mismatches: list[str] = []
    for module_name in ALLOWED_MODEL_IMPORTS:
        module = importlib.import_module(f"app.models.{module_name}")
        for name in dir(module):
            obj = getattr(module, name)
            # 只比对“定义在本模块”的模型；从 base 等处导入再被本模块引用的
            # 类（如各领域用到的 BucketSpec）不属于本模块对外新增的定义。
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == f"app.models.{module_name}"
                and hasattr(facade, name)
                and getattr(facade, name) is not obj
            ):
                mismatches.append(f"{name}（定义于 {module_name}）")
    assert not mismatches, f"门面导出与领域定义不是同一对象: {mismatches}"


def test_facade_name_set_matches_legacy_surface_exactly():
    """门面 __all__ 不得静默增删（新增领域模型时需显式更新本测试）。"""
    assert sorted(facade.__all__) == sorted(EXPECTED_PUBLIC_NAMES)


@pytest.mark.parametrize("module_name", sorted(ALLOWED_MODEL_IMPORTS))
def test_domain_module_imports_stay_within_boundary(module_name):
    path = MODELS_DIR / f"{module_name}.py"
    allowed = ALLOWED_MODEL_IMPORTS[module_name]
    violations = [
        (lineno, target)
        for lineno, target in _imported_app_model_modules(path)
        if target != "<facade>" and target not in allowed
    ]
    assert not violations, (
        f"{module_name}.py 越界导入其他领域: {violations}；"
        f"允许的依赖: {sorted(allowed) or '无（公共基础层）'}"
    )


@pytest.mark.parametrize("module_name", sorted(ALLOWED_MODEL_IMPORTS))
def test_domain_modules_never_import_the_facade(module_name):
    """领域模块通过门面取名字会重新形成循环依赖，一律禁止。"""
    path = MODELS_DIR / f"{module_name}.py"
    facade_imports = [
        lineno for lineno, target in _imported_app_model_modules(path) if target == "<facade>"
    ]
    assert not facade_imports, f"{module_name}.py 不应从门面 app.models 导入: 行 {facade_imports}"


def test_domain_dependency_graph_has_no_cycles():
    """以白名单为准做一次显式环检测，防止白名单本身写成环。"""
    graph = {name: deps for name, deps in ALLOWED_MODEL_IMPORTS.items()}

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]):
        if node in visiting:
            cycle = stack[stack.index(node) :] + [node]
            pytest.fail(f"领域依赖存在环: {' -> '.join(cycle)}")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [])


def test_base_module_has_no_domain_and_no_app_dependencies():
    """公共基础层是最底层：除 app.errors（异常类型）外不得依赖 app 内任何模块。"""
    path = MODELS_DIR / "base.py"
    tree = ast.parse(path.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names if a.name.startswith("app."))
    assert set(imported) <= {"app.errors"}, f"base 只能依赖 app.errors，实际: {imported}"
    # EPS 等公共工具必须从基础层导出，供各领域与处理函数复用
    assert base_models.EPS > 0
    assert callable(base_models._is_finite_number)
    assert callable(base_models._simulate_cross_validation_errors)


def test_request_response_schema_names_preserved():
    """所有端点的请求/响应模型名称必须仍是历史名称集合。"""
    from app.main import app

    schema = app.openapi()
    component_names = set(schema["components"]["schemas"])

    legacy_model_names = {
        name
        for name in EXPECTED_FACADE_NAMES
        if isinstance(getattr(facade, name, None), type)
        and issubclass(getattr(facade, name), BaseModel)
    }
    missing = legacy_model_names - component_names
    assert not missing, f"OpenAPI components/schemas 缺少模型: {sorted(missing)}"
