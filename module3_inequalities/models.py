"""
数据模型定义 — Module 3 输入结构

镜像 Module 1/2 的 models.py 模式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class SlackConfig:
    """Slack 变量配置"""
    enabled: bool = False
    penalty_type: str = "l1"               # 首版仅 l1
    penalty_weight_symbol: str = "rho_slack"


@dataclass
class InequalityConstraintDef:
    """单条不等式约束定义（已归一化为 g <= 0）"""
    name: str                                   # 约束名称
    apply_to_raw: Any = None                    # 原始 apply_to
    apply_to_normalized: Dict[str, Any] = field(default_factory=dict)  # 归一化后
    normalized_expressions: List[str] = field(default_factory=list)    # g <= 0 的表达式
    sub_names: List[str] = field(default_factory=list)                 # 链式拆分的子名称
    original_expression: str = ""               # 原始表达式（用于 traceability）
    slack_config: SlackConfig = field(default_factory=SlackConfig)

    @property
    def scalar_count(self) -> int:
        return len(self.normalized_expressions)

    @property
    def slack_enabled(self) -> bool:
        return self.slack_config.enabled


@dataclass
class InequalityTranscriptionConfig:
    """不等式约束转录配置"""
    variable_mode: Optional[str] = None    # None 表示继承 dynamics
    slack: SlackConfig = field(default_factory=SlackConfig)


@dataclass
class Module3InputDef:
    """Module 3 完整输入（已解析）"""
    problem_name: str = "unnamed_problem"
    input_yaml: str = ""

    # 共享变量定义
    states: List[Dict[str, Any]] = field(default_factory=list)
    controls: List[Dict[str, Any]] = field(default_factory=list)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    auxiliaries: List[Dict[str, Any]] = field(default_factory=list)

    # 安全名称映射
    name_to_safe: Dict[str, str] = field(default_factory=dict)
    safe_to_original: Dict[str, str] = field(default_factory=dict)

    # 网格
    mesh_N: int = 10

    # 不等式约束
    constraints: List[InequalityConstraintDef] = field(default_factory=list)

    # 配置
    dynamics_variable_mode: str = "perturbation"
    config: InequalityTranscriptionConfig = field(
        default_factory=InequalityTranscriptionConfig
    )

    # ── computed helpers ──────────────────────────────────────────

    @property
    def nx(self) -> int:
        return len(self.states)

    @property
    def nu(self) -> int:
        return len(self.controls)

    @property
    def np(self) -> int:
        return len(self.parameters)

    @property
    def variable_mode(self) -> str:
        if self.config.variable_mode is not None:
            return self.config.variable_mode
        return self.dynamics_variable_mode

    @property
    def is_perturbation(self) -> bool:
        return self.variable_mode == "perturbation"

    @property
    def is_direct(self) -> bool:
        return self.variable_mode == "direct"

    @property
    def constraint_count(self) -> int:
        return len(self.constraints)

    @property
    def total_scalar_count(self) -> int:
        return sum(c.scalar_count for c in self.constraints)

    @property
    def global_slack_config(self) -> SlackConfig:
        return self.config.slack

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.mesh_N < 2:
            errors.append("节点数 N 必须 >= 2")
        if self.variable_mode not in ("perturbation", "direct"):
            errors.append(f"不支持的 variable_mode: {self.variable_mode}")
        for c in self.constraints:
            if not c.normalized_expressions:
                errors.append(f"不等式约束 '{c.name}' 没有表达式")
            if not c.apply_to_normalized:
                errors.append(f"不等式约束 '{c.name}' 的 apply_to 未归一化")
            if c.slack_config.penalty_type not in ("l1",):
                errors.append(
                    f"不等式约束 '{c.name}' 的 penalty_type 不支持: "
                    f"{c.slack_config.penalty_type}（首版仅支持 l1）"
                )
        return errors
