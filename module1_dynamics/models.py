"""
数据模型定义 — 模块1输入结构

所有字段来自上游 YAML 解析后的 dict，无硬编码。
支持变量名安全映射（Python 关键字如 lambda → lambda_）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import time
import sys

from scpgen.common.expression_utils import (
    preprocess_expression,
    python_safe_name,
    is_python_keyword,
    build_safe_symbol_table,
    replace_variable_names_in_expr,
)


@dataclass
class VariableDef:
    """单个状态/控制/参数变量定义"""
    name: str                    # 用户原始名称
    original_name: str = ""      # 如果被安全映射，保留原始名
    description: str = ""


@dataclass
class AuxiliaryDef:
    """辅助表达式定义"""
    name: str                        # 辅助变量名
    expr: str                        # 原始表达式字符串
    description: str = ""
    dependencies: List[str] = field(default_factory=list)


@dataclass
class DynamicsEntry:
    """单条动力学方程：state_dot = rhs"""
    state: str
    rhs: str


@dataclass
class VirtualControlConfig:
    """虚拟控制配置"""
    enabled: bool = False
    form: str = "signed"
    penalty_type: str = "quadratic"
    penalty_weight_symbol: str = "rho_vc"


@dataclass
class DynamicsTranscriptionConfig:
    """动力学转录配置"""
    time_mode: str = "fixed_time"
    discretization: str = "trapezoidal"
    variable_mode: str = "perturbation"
    midpoint_policy: str = "node_average"
    virtual_control: VirtualControlConfig = field(default_factory=VirtualControlConfig)
    simplify_level: str = "none"     # "none" | "basic" | "full"
    derive_jacobian_expressions: bool = True  # 是否实际计算 A_mat/B_mat


@dataclass
class MeshDef:
    """网格定义"""
    N: int = 10
    grid_type: str = "uniform"

    @property
    def N_minus_1(self) -> int:
        return self.N - 1

    @property
    def interval_count(self) -> int:
        return self.N_minus_1


@dataclass
class ProblemDef:
    """模块1输入：最优控制问题定义（已解析，含安全名称映射）"""
    problem_name: str = "unnamed_problem"
    input_yaml: str = ""

    states: List[VariableDef] = field(default_factory=list)
    controls: List[VariableDef] = field(default_factory=list)
    parameters: List[VariableDef] = field(default_factory=list)
    auxiliaries: List[AuxiliaryDef] = field(default_factory=list)
    dynamics: List[DynamicsEntry] = field(default_factory=list)

    mesh: MeshDef = field(default_factory=MeshDef)
    dynamics_transcription_config: DynamicsTranscriptionConfig = field(
        default_factory=DynamicsTranscriptionConfig
    )

    # 安全名称映射
    name_to_safe: Dict[str, str] = field(default_factory=dict)
    safe_to_original: Dict[str, str] = field(default_factory=dict)

    # 动力学依赖闭包（哪些 auxiliary 被动力学引用）
    dynamics_aux_closure: List[str] = field(default_factory=list)
    ignored_auxiliaries: List[str] = field(default_factory=list)

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
    def config(self) -> DynamicsTranscriptionConfig:
        return self.dynamics_transcription_config

    # ── factory ───────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: Dict[str, Any], simplify_level: str = "none") -> "ProblemDef":
        """从上游解析后的 dict 构造 ProblemDef，完成语法标准化和安全名称映射"""
        states_raw = d.get("states", [])
        controls_raw = d.get("controls", [])
        parameters_raw = d.get("parameters", [])
        auxiliaries_raw = d.get("auxiliaries", [])
        dynamics_raw = d.get("dynamics", [])

        # 构建安全名称映射（含所有类别，做全局重名检查）
        name_to_safe, safe_to_original = build_safe_symbol_table(
            states_raw, controls_raw, parameters_raw, auxiliaries_raw
        )

        # 预处理变量定义
        states = [
            VariableDef(
                name=name_to_safe.get(sv["name"], sv["name"]),
                original_name=sv["name"],
                description=sv.get("description", ""),
            )
            for sv in states_raw
        ]
        controls = [
            VariableDef(
                name=name_to_safe.get(cv["name"], cv["name"]),
                original_name=cv["name"],
                description=cv.get("description", ""),
            )
            for cv in controls_raw
        ]
        parameters = [
            VariableDef(
                name=name_to_safe.get(pv["name"], pv["name"]),
                original_name=pv["name"],
                description=pv.get("description", ""),
            )
            for pv in parameters_raw
        ]

        # 预处理 auxiliary 列表：语法标准化 + 变量名替换
        auxiliaries = []
        for a in auxiliaries_raw:
            safe_expr = preprocess_expression(a.get("expr", ""))
            safe_expr = replace_variable_names_in_expr(safe_expr, name_to_safe)
            safe_deps = [
                name_to_safe.get(d, d) for d in a.get("dependencies", [])
            ]
            auxiliaries.append(AuxiliaryDef(
                name=name_to_safe.get(a["name"], a["name"]),
                expr=safe_expr,
                description=a.get("description", ""),
                dependencies=safe_deps,
            ))

        # 预处理 dynamics：语法标准化 + 变量名替换
        dynamics = []
        for dyn in dynamics_raw:
            safe_rhs = preprocess_expression(dyn.get("rhs", ""))
            safe_rhs = replace_variable_names_in_expr(safe_rhs, name_to_safe)
            safe_state = name_to_safe.get(dyn["state"], dyn["state"])
            dynamics.append(DynamicsEntry(state=safe_state, rhs=safe_rhs))

        # mesh
        mesh_dict = d.get("mesh", {})
        mesh = MeshDef(**mesh_dict) if mesh_dict else MeshDef()

        # config（先 copy 避免修改输入 dict）
        config_dict = dict(d.get("dynamics_transcription_config", {}))
        vc_dict = dict(config_dict.pop("virtual_control", {}))
        vc_config = VirtualControlConfig(**vc_dict) if vc_dict else VirtualControlConfig()
        config = DynamicsTranscriptionConfig(
            virtual_control=vc_config,
            simplify_level=simplify_level,
            **config_dict,
        )

        pd = cls(
            problem_name=d.get("problem_name", "unnamed_problem"),
            input_yaml=d.get("input_yaml", ""),
            states=states,
            controls=controls,
            parameters=parameters,
            auxiliaries=auxiliaries,
            dynamics=dynamics,
            mesh=mesh,
            dynamics_transcription_config=config,
            name_to_safe=name_to_safe,
            safe_to_original=safe_to_original,
        )

        # 计算动力学依赖闭包
        pd._compute_dynamics_closure()

        return pd

    def _compute_dynamics_closure(self) -> None:
        """
        递归收集动力学 RHS 中引用的辅助表达式。

        对每个 auxiliary：
        - declared_deps: YAML 中显式写的 dependencies
        - inferred_deps: 从 expr 中自动提取的 auxiliary 引用
        - final_deps: 两者的并集

        用 final_deps 构建依赖闭包和拓扑排序。
        只保留被动力学直接或间接引用的 auxiliary，
        其余记录到 ignored_auxiliaries 中，不在模块1中展开。
        """
        if not self.auxiliaries or not self.dynamics:
            self.dynamics_aux_closure = []
            self.ignored_auxiliaries = [a.name for a in self.auxiliaries]
            self._declared_deps = {}
            self._inferred_deps = {}
            self._final_deps = {}
            return

        aux_map = {a.name: a for a in self.auxiliaries}
        aux_name_set = set(aux_map.keys())

        # Step 1: 对每个 auxiliary，合并 declared + inferred dependencies
        declared_deps: Dict[str, set] = {}
        inferred_deps: Dict[str, set] = {}
        final_deps: Dict[str, set] = {}

        for name, a in aux_map.items():
            declared = set(a.dependencies) & aux_name_set
            inferred = self._extract_identifiers(a.expr) & aux_name_set
            declared_deps[name] = declared
            inferred_deps[name] = inferred
            final_deps[name] = declared | inferred

        # Step 2: 收集所有 RHS 中引用的符号
        referenced: set = set()
        for dyn in self.dynamics:
            referenced.update(self._extract_identifiers(dyn.rhs))

        # Step 3: BFS 扩展，使用 final_deps
        closure: set = set()
        queue: list = [name for name in referenced if name in aux_name_set]
        while queue:
            name = queue.pop(0)
            if name in closure:
                continue
            closure.add(name)
            for dep in final_deps.get(name, set()):
                if dep in aux_name_set and dep not in closure:
                    queue.append(dep)

        self.dynamics_aux_closure = list(closure)
        self.ignored_auxiliaries = [
            a.name for a in self.auxiliaries if a.name not in closure
        ]
        self._declared_deps = {k: sorted(v) for k, v in declared_deps.items()}
        self._inferred_deps = {k: sorted(v - declared_deps[k]) for k, v in inferred_deps.items()}
        self._final_deps = {k: sorted(v) for k, v in final_deps.items()}

    @staticmethod
    def _extract_identifiers(expr_str: str) -> set:
        """从表达式字符串中提取标识符"""
        import re
        # 匹配字母或下划线开头、字母数字下划线组成的标识符
        # 排除数字和已知函数名
        known_funcs = {
            "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
            "exp", "log", "sqrt", "abs", "sign", "pow",
        }
        ids = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr_str))
        return ids - known_funcs

    def validate(self) -> List[str]:
        """基本校验"""
        errors: List[str] = []

        if self.nx == 0:
            errors.append("至少需要一个状态变量")
        if self.nu == 0:
            errors.append("至少需要一个控制变量")

        state_names = {s.name for s in self.states}
        for d in self.dynamics:
            if d.state not in state_names:
                errors.append(f"动力学方程引用了未定义的状态变量: {d.state}")

        # ── 动力学完整性校验 ──────────────────────────────────
        # 检查每个 state 有且只有一条动力学方程
        dynamics_states = [d.state for d in self.dynamics]

        # 缺失动力学
        missing = state_names - set(dynamics_states)
        if missing:
            errors.append(f"状态变量缺少动力学定义: {', '.join(sorted(missing))}")

        # 重复动力学
        from collections import Counter
        dupes = [s for s, c in Counter(dynamics_states).items() if c > 1]
        if dupes:
            errors.append(f"状态变量有重复的动力学定义: {', '.join(sorted(dupes))}")

        # 动力学数量应等于 nx
        if len(self.dynamics) != self.nx:
            errors.append(
                f"动力学方程数量 ({len(self.dynamics)}) 与状态变量数量 ({self.nx}) 不匹配"
            )

        if self.mesh.N < 2:
            errors.append("节点数 N 必须 >= 2")

        cfg = self.config
        if cfg.time_mode not in ("fixed_time", "free_final_time"):
            errors.append(f"未知 time_mode: {cfg.time_mode}")
        if cfg.discretization not in ("trapezoidal", "midpoint"):
            errors.append(f"未知 discretization: {cfg.discretization}")
        if cfg.variable_mode not in ("perturbation", "direct"):
            errors.append(f"未知 variable_mode: {cfg.variable_mode}")
        if cfg.virtual_control.enabled and cfg.virtual_control.form not in ("signed", "split_nonnegative", "disabled"):
            errors.append(f"未知 virtual_control form: {cfg.virtual_control.form}")

        return errors
