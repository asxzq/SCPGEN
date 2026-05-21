"""
数据模型定义 — Module 5: ECOS Canonicalizer

定义 EcosVariableBlock, EcosEqualityBlock, EcosInequalityBlock,
EcosConeBlock, ObjectivePlanEntry, EcosCanonicalIR, Module5Input 等 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class EcosVariableBlock:
    """ECOS 优化变量 y 中的单个变量块"""
    name: str
    role: str                            # state_perturbation, control_perturbation, time,
                                          # dynamics_virtual_control, inequality_slack,
                                          # quadratic_cost_epigraph
    source_module: str                   # module1_dynamics, module3_inequalities, module5_ecos
    domain: str = "free"                 # "free" | "nonnegative"
    dimension_concrete: int = 0
    dimension_symbolic: str = ""
    column_start_concrete: int = 0
    column_end_concrete: int = 0
    in_original_z: bool = True           # 是否来自 Module 4 的原始 z（False = epigraph）


@dataclass
class EcosEqualityBlock:
    """A y = b 中的单个等式约束块"""
    name: str
    source_module: str
    type: str                            # "dynamics" | "original_equality"
    rows_symbolic: str = ""
    rows_concrete: int = 0
    row_start_concrete: int = 0
    row_end_concrete: int = 0
    # 从 Module 4 保留的结构信息
    variable_stencil: List[str] = field(default_factory=list)
    matrix_blocks: List[Dict[str, Any]] = field(default_factory=list)
    rhs_block: Dict[str, Any] = field(default_factory=dict)
    row_layout: Dict[str, Any] = field(default_factory=dict)
    template_reference: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EcosInequalityBlock:
    """G y + s = h 中的单个不等式约束块"""
    name: str
    source_module: str
    type: str                            # "original_inequality" | "variable_domain"
    rows_symbolic: str = ""
    rows_concrete: int = 0
    row_start_concrete: int = 0
    row_end_concrete: int = 0
    cone_type: str = "linear"            # "linear" | "second_order"
    # 从 Module 4 保留的结构信息（linear cone blocks）
    variable_stencil: List[str] = field(default_factory=list)
    matrix_blocks: List[Dict[str, Any]] = field(default_factory=list)
    rhs_block: Dict[str, Any] = field(default_factory=dict)
    row_layout: Dict[str, Any] = field(default_factory=dict)
    template_reference: Dict[str, Any] = field(default_factory=dict)
    # variable_domain 专用
    variable: str = ""
    domain: str = ""
    canonical_inequality: str = ""


@dataclass
class EcosConeBlock:
    """单个锥约束块（线性或二阶锥）"""
    name: str
    type: str                            # "linear" | "second_order"
    dim: int = 0                         # 锥维度
    row_start_concrete: int = 0          # 在 G/h 中的行偏移
    row_end_concrete: int = 0
    # SOC 专用
    source_cost_term: str = ""
    epigraph_variable: str = ""
    vector_variable: str = ""
    rho_symbol: str = ""
    # SOC G/h 构造规则
    soc_assembly: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ObjectivePlanEntry:
    """c 向量中的单个目标条目"""
    source_cost_term: str
    variable_block: str
    coefficient_symbolic: str
    applies_to: str = "all_elements"     # "all_elements" | "single"


@dataclass
class EcosCanonicalIR:
    """Module 5 输出：完整的 ECOS canonical IR"""
    problem_name: str = ""
    variable_mode: str = "perturbation"
    source_module4_path: str = ""

    # 符号表（从 Module 4 透传）
    symbol_table: Dict[str, Any] = field(default_factory=dict)

    # 变量注册
    original_variables: List[EcosVariableBlock] = field(default_factory=list)
    epigraph_variables: List[EcosVariableBlock] = field(default_factory=list)
    ecos_variables: List[EcosVariableBlock] = field(default_factory=list)
    dim_z: int = 0
    dim_y: int = 0

    # 目标
    linear_objective_plan: List[ObjectivePlanEntry] = field(default_factory=list)
    quadratic_objective_info: List[Dict[str, Any]] = field(default_factory=list)

    # 等式
    equality_blocks: List[EcosEqualityBlock] = field(default_factory=list)

    # 不等式
    inequality_blocks: List[EcosInequalityBlock] = field(default_factory=list)

    # 锥体
    cone_blocks: List[EcosConeBlock] = field(default_factory=list)

    # ECOS 维度
    ecos_dims: Dict[str, Any] = field(default_factory=dict)

    # 调试
    debug_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Module5Input:
    """Module 5 的输入配置"""
    module4_path: str = ""
    output_path: str = "ecos_canonical_module5_output.yaml"
    write_report: bool = False
    report_path: str = ""
