"""
数据模型定义 — Module 2 输入结构

镜像 Module 1 的 models.py 模式。
所有字段来自上游 YAML 解析后的 dict，无硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from scpgen.common.apply_to import normalize_apply_to, get_apply_to_summary


@dataclass
class EqualityConstraintDef:
    """单条等式约束定义（已归一化）"""
    name: str                          # 约束名称
    apply_to_raw: Any = None           # 原始 apply_to（用于 traceability）
    apply_to_normalized: Dict[str, Any] = field(default_factory=dict)  # 归一化后
    scalar_expressions: List[str] = field(default_factory=list)         # 预处理后的标量表达式
    original_form: str = ""            # "expression" | "expressions" | "equations"
    equations_dict: Optional[Dict[str, str]] = None  # 仅 equations 形式：原始 {lhs: rhs} 映射

    @property
    def scalar_count(self) -> int:
        return len(self.scalar_expressions)


@dataclass
class EqualityTranscriptionConfig:
    """等式约束转录配置"""
    variable_mode: Optional[str] = None   # None 表示继承 dynamics 的 variable_mode


@dataclass
class Module2InputDef:
    """Module 2 完整输入（已解析）"""
    problem_name: str = "unnamed_problem"
    input_yaml: str = ""

    # 共享变量定义（从 input_dict 透传）
    states: List[Dict[str, Any]] = field(default_factory=list)
    controls: List[Dict[str, Any]] = field(default_factory=list)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    auxiliaries: List[Dict[str, Any]] = field(default_factory=list)

    # 安全名称映射
    name_to_safe: Dict[str, str] = field(default_factory=dict)
    safe_to_original: Dict[str, str] = field(default_factory=dict)

    # 网格
    mesh_N: int = 10

    # 等式约束
    constraints: List[EqualityConstraintDef] = field(default_factory=list)

    # 配置
    dynamics_variable_mode: str = "perturbation"
    config: EqualityTranscriptionConfig = field(default_factory=EqualityTranscriptionConfig)

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
        """解析后的 variable_mode"""
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

    def validate(self) -> List[str]:
        """基本校验"""
        errors: List[str] = []
        if self.mesh_N < 2:
            errors.append("节点数 N 必须 >= 2")
        if self.variable_mode not in ("perturbation", "direct"):
            errors.append(f"不支持的 variable_mode: {self.variable_mode}")
        for c in self.constraints:
            if not c.scalar_expressions:
                errors.append(f"等式约束 '{c.name}' 没有表达式")
            if not c.apply_to_normalized:
                errors.append(f"等式约束 '{c.name}' 的 apply_to 未归一化")
        return errors
