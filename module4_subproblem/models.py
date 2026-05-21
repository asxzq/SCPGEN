"""
数据模型定义 — Module 4 核心结构

定义 VariableBlock, EqualityBlock, InequalityBlock, CostTerm, SubproblemIR 等 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class VariableBlock:
    """单个优化变量块"""
    name: str                            # 变量块名称，如 "delta_x", "vc_plus", "s_heat_rate"
    role: str                            # 语义角色：state_perturbation, control_perturbation, time, dynamics_virtual_control, inequality_slack
    source_module: str                   # "module1_dynamics" | "module2_equalities" | "module3_inequalities"
    domain: str = "free"                 # "free" | "nonnegative"
    shape_symbolic: List[Any] = field(default_factory=list)   # [N, nx] 等符号形状
    shape_concrete: List[int] = field(default_factory=list)   # [30, 8] 等具体形状
    dimension_symbolic: str = ""         # "N * nx" 等符号维度
    dimension_concrete: int = 0          # 具体维度（整数）
    column_start_concrete: int = 0       # 在决策向量 z 中的起始列（0-based）
    column_end_concrete: int = 0         # 在决策向量 z 中的结束列（inclusive）
    indexing_rule: Dict[str, str] = field(default_factory=dict)  # {"element": "delta_x[k,i]", "flat_index": "..."}


@dataclass
class EqualityBlock:
    """单个等式约束块"""
    name: str                            # 块名称
    source_module: str                   # "module1_dynamics" | "module2_equalities"
    type: str                            # "dynamics" | "original_equality"
    rows_symbolic: str = ""              # 符号行数，如 "(N-1) * nx"
    rows_concrete: int = 0               # 具体行数
    row_start_concrete: int = 0          # 在等式矩阵中的起始行
    row_end_concrete: int = 0            # 在等式矩阵中的结束行（inclusive）
    variable_stencil: List[str] = field(default_factory=list)  # ["delta_x[k]", "delta_u[k]", ...]
    matrix_blocks: List[Dict[str, Any]] = field(default_factory=list)  # [{"name": "C_xL", "variable_block": "delta_x", ...}]
    rhs_block: Dict[str, Any] = field(default_factory=dict)    # {"name": "rhs", ...}
    row_layout: Dict[str, Any] = field(default_factory=dict)   # {"loop_order": [...], "rows_per_node": ...}
    template_reference: Dict[str, Any] = field(default_factory=dict)  # 引用原始模板的元信息


@dataclass
class InequalityBlock:
    """单个不等式约束块"""
    name: str                            # 块名称
    source_module: str                   # "module3_inequalities" | "module1_dynamics"
    type: str                            # "original_inequality" | "variable_domain"
    rows_symbolic: str = ""
    rows_concrete: int = 0
    row_start_concrete: int = 0
    row_end_concrete: int = 0
    # 仅 original_inequality
    variable_stencil: List[str] = field(default_factory=list)
    matrix_blocks: List[Dict[str, Any]] = field(default_factory=list)
    rhs_block: Dict[str, Any] = field(default_factory=dict)
    row_layout: Dict[str, Any] = field(default_factory=dict)
    template_reference: Dict[str, Any] = field(default_factory=dict)
    # 仅 variable_domain
    variable: str = ""                   # 被约束的变量名
    domain: str = ""                     # "nonnegative"
    canonical_inequality: str = ""       # "-vc_plus <= 0"


@dataclass
class CostTerm:
    """单个成本项"""
    name: str                            # 如 "virtual_control_l1_penalty"
    source_module: str                   # "module1_dynamics" | "module3_inequalities"
    type: str                            # "linear" | "quadratic"
    expression_template: str = ""        # 如 "rho_vc * sum(vc_plus + vc_minus)"
    variables: List[str] = field(default_factory=list)  # 涉及的变量名
    role: str = ""                       # "virtual_control_penalty" | "slack_penalty"


@dataclass
class Module4Input:
    """Module 4 的聚合输入"""
    problem_name: str = "unnamed"
    # 三个模块的原始输出 dict
    m1_output: Dict[str, Any] = field(default_factory=dict)
    m2_output: Dict[str, Any] = field(default_factory=dict)
    m3_output: Dict[str, Any] = field(default_factory=dict)
    # 启用标志
    m2_enabled: bool = True
    m3_enabled: bool = True
    # 路径信息（用于 source_modules）
    m1_path: str = ""
    m2_path: str = ""
    m3_path: str = ""
    # 输出路径
    output_path: str = "subproblem_ir_module4_output.yaml"


@dataclass
class SubproblemIR:
    """Module 4 输出：完整的子问题 IR"""
    problem_name: str = ""
    variable_mode: str = "perturbation"
    mesh: Dict[str, Any] = field(default_factory=dict)

    symbol_table: Dict[str, Any] = field(default_factory=dict)

    variable_blocks: List[VariableBlock] = field(default_factory=list)
    equality_blocks: List[EqualityBlock] = field(default_factory=list)
    inequality_blocks: List[InequalityBlock] = field(default_factory=list)

    introduced_variables: Dict[str, Any] = field(default_factory=dict)  # by_module1/2/3 + merged
    cost_terms: Dict[str, Any] = field(default_factory=dict)            # by_module1/2/3 + merged

    source_modules: Dict[str, Any] = field(default_factory=dict)
    debug_summary: Dict[str, Any] = field(default_factory=dict)
