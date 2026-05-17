"""
Immutable data structures for the model layer.

ModelDef captures the original optimal control problem:
  - Dimensional normalization scales (length, velocity, mass, ...)
  - Scalarized 1D variables (state, control, auxiliary) with dimension tags
  - Named expression aliases (L=..., D=..., overload=...) for reuse
  - Parameters & external function declarations
  - Continuous-time dynamics (may reference aliases)
  - Original equality / inequality constraints
  - Original objective
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# ── Enums ────────────────────────────────────────────────────────────────────

class VarRole(Enum):
    STATE = "state"
    CONTROL = "control"
    AUXILIARY = "auxiliary"


class ConstraintType(Enum):
    BOUNDARY = "boundary"    # 端点约束: var@node = value
    BOX = "box"              # 盒约束: lower <= var@nodes <= upper
    PATH = "path"            # 路径约束: lower <= expr(x,u) <= upper
    WAYPOINT = "waypoint"    # 航路点约束
    CUSTOM = "custom"        # 自定义


class ObjSense(Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class DiscreteMethod(Enum):
    TRAPEZOIDAL = "trapezoidal"
    HERMITE_SIMPSON = "hermite_simpson"


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScaleDef:
    """量纲级归一化尺度定义: 物理量 = scale_value * 归一化量"""
    name: str                      # e.g. "length", "velocity", "mass"
    value: float                   # scale factor (物理单位/归一化)
    unit: str = ""                 # physical unit, e.g. "m", "m/s"
    derive: str = ""               # derivation expression, e.g. "length / velocity"


@dataclass(frozen=True)
class VariableDef:
    """标量变量定义（始终 dim=1），通过 dimension 引用 scales 中的量纲"""
    name: str
    role: VarRole
    dimension: str = ""            # 量纲名, e.g. "length", "velocity", "angle", ""
    description: str = ""
    alias_expr: Optional[str] = None   # auxiliary 变量的定义表达式

    @property
    def scale(self) -> float:
        """Backward-compat: return 1.0 (scale resolved externally)"""
        return 1.0


@dataclass(frozen=True)
class ParameterDef:
    """参数定义"""
    name: str
    value: Any = None       # 可为数字或字符串（引用）
    description: str = ""


@dataclass(frozen=True)
class ExternalFuncDef:
    """外部函数声明（用户自行实现）"""
    name: str
    signature: str           # C 函数签名
    description: str = ""


@dataclass(frozen=True)
class ExpressionDef:
    """命名表达式别名: L = ...，可引用其他表达式和外部函数"""
    name: str
    expr: str                # SymPy 兼容表达式字符串
    description: str = ""


@dataclass(frozen=True)
class DynamicsEntry:
    """单条动力学: d(state)/dt = rhs"""
    state: str
    rhs: str                 # 可引用 expression 别名、外部函数、变量


@dataclass(frozen=True)
class NodeBinding:
    """单点绑定: variable@node = value_expression (boundary) 或 lower <= var <= upper (box)"""
    var: str
    node: Union[int, str, None] = None
    value: str = ""
    lower: str = ""
    upper: str = ""


@dataclass(frozen=True)
class ConstraintDef:
    """原始约束定义"""
    name: str
    ctype: ConstraintType
    bindings: List[NodeBinding] = field(default_factory=list)
    expr: str = ""
    lower: str = ""
    upper: str = ""
    nodes: List[Union[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ObjectiveDef:
    """原始目标函数"""
    sense: ObjSense
    expr: str


@dataclass(frozen=True)
class DiscreteConfig:
    """离散化配置
    
    node_count: 区间数 N_INTERVALS（而非节点数）。
                 节点数 N_NODES = N_INTERVALS + 1。
                 终端索引 FINAL_NODE = N_INTERVALS。
    """
    node_count: int
    node_count_param: str
    method: DiscreteMethod = DiscreteMethod.TRAPEZOIDAL
    
    @property
    def N_INTERVALS(self) -> int:
        """区间数"""
        return self.node_count
    
    @property
    def N_NODES(self) -> int:
        """节点数 = 区间数 + 1"""
        return self.node_count + 1
    
    @property
    def FINAL_NODE(self) -> int:
        """终端节点索引 = 区间数"""
        return self.node_count


@dataclass(frozen=True)
class ModelDef:
    """原始最优控制问题的完整描述（不可变）"""
    name: str
    discretization: DiscreteConfig
    scales: Dict[str, ScaleDef] = field(default_factory=dict)
    states: List[VariableDef] = field(default_factory=list)
    controls: List[VariableDef] = field(default_factory=list)
    auxiliaries: List[VariableDef] = field(default_factory=list)
    expressions: List[ExpressionDef] = field(default_factory=list)
    parameters: List[ParameterDef] = field(default_factory=list)
    external_funcs: List[ExternalFuncDef] = field(default_factory=list)
    dynamics: List[DynamicsEntry] = field(default_factory=list)
    eq_constraints: List[ConstraintDef] = field(default_factory=list)
    ineq_constraints: List[ConstraintDef] = field(default_factory=list)
    objective: Optional[ObjectiveDef] = None

    @property
    def N_INTERVALS(self) -> int:
        """区间数"""
        return self.discretization.N_INTERVALS
    
    @property
    def N_NODES(self) -> int:
        """节点数 = 区间数 + 1"""
        return self.discretization.N_NODES
    
    @property
    def FINAL_NODE(self) -> int:
        """终端节点索引 = 区间数"""
        return self.discretization.FINAL_NODE
    
    @property
    def N(self) -> int:
        """[Deprecated] 节点数。请使用 N_NODES。"""
        return self.N_NODES

    @property
    def all_variables(self) -> List[VariableDef]:
        return list(self.states) + list(self.controls) + list(self.auxiliaries)

    @property
    def state_names(self) -> List[str]:
        return [v.name for v in self.states]

    @property
    def control_names(self) -> List[str]:
        return [v.name for v in self.controls]

    @property
    def auxiliary_names(self) -> List[str]:
        return [v.name for v in self.auxiliaries]

    def var_dimension(self, name: str) -> str:
        """Get the dimension tag for a variable."""
        for v in self.all_variables:
            if v.name == name:
                return v.dimension
        return ""

    def scale_of(self, dim_or_var: str) -> float:
        """Get scale for a dimension name or variable name."""
        # Try as dimension name first
        if dim_or_var in self.scales:
            return self.scales[dim_or_var].value
        # Try as variable name → look up its dimension
        for v in self.all_variables:
            if v.name == dim_or_var and v.dimension in self.scales:
                return self.scales[v.dimension].value
        return 1.0

    def get_variable(self, name: str) -> VariableDef:
        for v in self.all_variables:
            if v.name == name:
                return v
        raise KeyError(f"Variable '{name}' not found in model")

    def get_scale(self, name: str) -> float:
        return self.scale_of(name)

    def get_expression(self, name: str) -> ExpressionDef:
        for e in self.expressions:
            if e.name == name:
                return e
        raise KeyError(f"Expression '{name}' not found")

    def get_parameter(self, name: str) -> ParameterDef:
        for p in self.parameters:
            if p.name == name:
                return p
        raise KeyError(f"Parameter '{name}' not found in model")
