"""
Transcription layer data structures.

TranscriptionDef explicitly declares how each raw problem item is handled:
  - Variable layout & global index assignment
  - Each processing operation with its export targets
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# ── Enums ────────────────────────────────────────────────────────────────────

class ExportTarget(Enum):
    """导出目标矩阵/向量"""
    A_b = "A_b"       # 等式约束 A*x = b
    G_h = "G_h"       # 不等式约束 G*x <= h
    G_h_q = "G_h_q"   # 锥约束 G*x + s = h, s ∈ K
    c = "c"           # 线性目标系数
    Q_c = "Q_c"       # 二次目标项


class VarOrdering(Enum):
    """决策变量排列方式"""
    BY_NODE = "by_node"          # [state@0, ctrl@0, ..., state@N, ctrl@N]
    BY_VARIABLE = "by_variable"  # [rx@0..N, ry@0..N, ..., alpha@0..N]


class VarSemantics(Enum):
    """决策变量的语义：是增量(扰动)还是全量(直接)"""
    PERTURBATION = "perturbation"  # dx, du: 相对参考轨迹的增量，x_ref += dx
    DIRECT = "direct"              # x, u: 直接优化状态量和控制量


class SCPParams:
    """SCP 迭代参数（从 YAML transcription.scp_params 解析）"""
    def __init__(self, raw: dict = None):
        raw = raw or {}
        self.max_iter = int(raw.get("max_iter", 50))
        self.eps_convergence = float(raw.get("eps_convergence", 0.002))
        mode = raw.get("variable_mode", "perturbation")
        self.variable_mode = VarSemantics(mode)
        self.verbose = bool(raw.get("verbose", True))

    @property
    def is_perturbation(self) -> bool:
        """变量=δx 增量模式"""
        return self.variable_mode == VarSemantics.PERTURBATION

    @property
    def is_direct(self) -> bool:
        """变量=x 直接模式"""
        return self.variable_mode == VarSemantics.DIRECT


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ExportDecl:
    """声明一个操作结果导出到哪个矩阵"""
    target: ExportTarget


@dataclass
class VarGroup:
    """一组变量在指定节点范围上的布局"""
    vars: List[str]
    nodes: List[Union[int, str]]  # [start, end], 如 [0, "N"]


@dataclass
class VariableLayout:
    """决策变量 x 向量的布局描述"""
    ordering: VarOrdering
    groups: List[VarGroup]


@dataclass
class OperationDecl:
    """
    一条处理操作的声明（从 YAML 直接映射）。
    具体语义由 operations/ 模块中对应的 ProcessingOp 子类解释。
    """
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    exports: List[ExportDecl] = field(default_factory=list)


@dataclass
class TranscriptionDef:
    """
    Transcription 层的完整描述。
    声明如何将 model 层的原始问题转化为 SOCP 矩阵填充代码。
    """
    variable_layout: VariableLayout
    operations: List[OperationDecl]
    scp_params: SCPParams = field(default_factory=SCPParams)
