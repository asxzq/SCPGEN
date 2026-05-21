"""
符号引擎 — 基于 SymPy 的符号表达式构建与微分

性能优化版本:
- 默认不做 simplify，简化级别可配置
- 只解析动力学依赖闭包中的 auxiliary（减少不必要计算）
- 分阶段计时日志
- 变量名安全映射（处理 Python 关键字如 lambda）
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional, Callable
from collections import deque
import time
import sys

import sympy as sp
from sympy import Symbol, Matrix, diff, latex, ccode

from .models import ProblemDef, AuxiliaryDef


# ── 空日志 ────────────────────────────────────────────────────────

def _null_logger(msg: str) -> None:
    pass


# ── 结构化表达式节点 ──────────────────────────────────────────────

def _expr_to_structured(expr: sp.Expr) -> Dict[str, Any]:
    """将 SymPy 表达式树转为结构化 dict"""
    if expr.is_Symbol:
        return {"type": "symbol", "name": str(expr)}
    if expr.is_Integer:
        return {"type": "number", "value": int(expr)}
    if expr.is_Float or expr.is_Rational:
        return {"type": "number", "value": float(expr)}
    if expr.is_Add:
        return {"type": "add", "operands": [_expr_to_structured(a) for a in expr.args]}
    if expr.is_Mul:
        factors = [_expr_to_structured(a) for a in expr.args]
        if len(factors) == 2:
            a, b = factors
            if a.get("type") == "number" and a.get("value") == -1:
                return {"type": "neg", "operand": b}
            if b.get("type") == "number" and b.get("value") == -1:
                return {"type": "neg", "operand": a}
        return {"type": "mul", "operands": factors}
    if expr.is_Pow:
        base, exp = expr.args
        return {"type": "pow", "operands": [_expr_to_structured(base), _expr_to_structured(exp)]}
    if isinstance(expr, sp.Subs):
        return {"type": "other", "latex": latex(expr)}
    if hasattr(expr, "func") and hasattr(expr.func, "is_Function") and expr.func.is_Function:
        return {
            "type": "func",
            "name": str(expr.func.__name__ if hasattr(expr.func, "__name__") else expr.func),
            "operand": _expr_to_structured(expr.args[0]),
        }
    if hasattr(expr, "func") and len(expr.args) > 0:
        try:
            name = str(expr.func.__name__)
        except AttributeError:
            name = str(expr.func)
        return {"type": "func", "name": name, "operands": [_expr_to_structured(a) for a in expr.args]}
    return {"type": "other", "latex": latex(expr)}


def _matrix_to_structured(mat: Matrix) -> List[List[Dict[str, Any]]]:
    rows, cols = mat.shape
    result = []
    for i in range(rows):
        row = [_expr_to_structured(mat[i, j]) for j in range(cols)]
        result.append(row)
    return result


# ── SymEngine ─────────────────────────────────────────────────────

class SymEngine:
    """
    符号引擎：管理所有符号变量、表达式、雅可比矩阵。

    用法:
        engine = SymEngine(problem_def, logger=print)
        engine.build_all()
    """

    def __init__(
        self,
        problem_def: ProblemDef,
        simplify_level: str = "none",
        logger: Optional[Callable[[str], None]] = None,
    ):
        self._pd = problem_def
        self._simplify_level = simplify_level or problem_def.config.simplify_level
        self._log = logger or _null_logger

        # 符号表
        self.x_syms: List[Symbol] = []
        self.u_syms: List[Symbol] = []
        self.p_syms: List[Symbol] = []
        self._name_to_sym: Dict[str, Symbol] = {}

        # 辅助表达式（只包含动力学闭包中的）
        self.aux_names: List[str] = []
        self.aux_exprs: Dict[str, sp.Expr] = {}
        self.aux_used_count: int = 0
        self.aux_ignored_count: int = 0

        # 动力学
        self.f_exprs: List[sp.Expr] = []
        self.f_original_rhs: List[str] = []  # 用户原始 RHS 字符串（含辅助变量引用）
        self.f_vec: Optional[Matrix] = None
        self.A_mat: Optional[Matrix] = None
        self.B_mat: Optional[Matrix] = None

        # 计时统计
        self.stats: Dict[str, float] = {}

    # ── 构造方法 ──────────────────────────────────────────────────

    def build_all(self) -> None:
        """执行全部构建步骤"""
        t0 = time.perf_counter()

        self._build_symbols()
        self._log(
            f"SymEngine: states={self.nx}, controls={self.nu}, params={self.np}"
        )

        t1 = time.perf_counter()
        self._build_auxiliaries()
        self.stats["parse_auxiliaries"] = time.perf_counter() - t1
        self._log(
            f"SymEngine: aux used={self.aux_used_count}, "
            f"ignored={self.aux_ignored_count}, "
            f"time={self.stats['parse_auxiliaries']:.3f}s"
        )

        t2 = time.perf_counter()
        self._build_dynamics()
        self.stats["build_dynamics"] = time.perf_counter() - t2
        self._log(
            f"SymEngine: dynamics built, time={self.stats['build_dynamics']:.3f}s"
        )

        t3 = time.perf_counter()
        self._compute_jacobians()
        self.stats["jacobian_total"] = time.perf_counter() - t3
        self._log(
            f"SymEngine: jacobians computed, time={self.stats['jacobian_total']:.3f}s"
        )

        self.stats["total"] = time.perf_counter() - t0
        self._log(f"SymEngine: total time={self.stats['total']:.3f}s")

    def _build_symbols(self) -> None:
        """创建 SymPy 符号"""
        for i, sv in enumerate(self._pd.states):
            sym = Symbol(f"x_{i}")
            self.x_syms.append(sym)
            self._name_to_sym[sv.name] = sym

        for i, cv in enumerate(self._pd.controls):
            sym = Symbol(f"u_{i}")
            self.u_syms.append(sym)
            self._name_to_sym[cv.name] = sym

        for i, pv in enumerate(self._pd.parameters):
            sym = Symbol(f"p_{i}")
            self.p_syms.append(sym)
            self._name_to_sym[pv.name] = sym

    def _build_auxiliaries(self) -> None:
        """
        只解析动力学依赖闭包中的辅助表达式。
        拓扑排序后依次解析——不调用 simplify。
        """
        pd = self._pd
        closure = set(pd.dynamics_aux_closure)

        if not closure:
            self.aux_ignored_count = len(pd.auxiliaries)
            return

        # 只保留闭包内的 auxiliary
        aux_map: Dict[str, AuxiliaryDef] = {
            a.name: a for a in pd.auxiliaries if a.name in closure
        }

        # 构建依赖图（使用 final_deps = declared ∪ inferred）
        in_degree: Dict[str, int] = {}
        dependents: Dict[str, List[str]] = {}
        final_deps = getattr(pd, '_final_deps', {})
        for name, a in aux_map.items():
            deps = final_deps.get(name, [])
            deps = [d for d in deps if d in aux_map]
            in_degree[name] = len(deps)
            for d in deps:
                dependents.setdefault(d, []).append(name)

        # Kahn 拓扑排序
        queue: deque[str] = deque(n for n, deg in in_degree.items() if deg == 0)
        sorted_names: List[str] = []
        while queue:
            name = queue.popleft()
            sorted_names.append(name)
            for dep in dependents.get(name, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if len(sorted_names) != len(aux_map):
            remaining = set(aux_map.keys()) - set(sorted_names)
            raise ValueError(f"辅助表达式存在循环依赖: {remaining}")

        # 按拓扑序解析 — 不做 simplify
        local_ns = dict(self._name_to_sym)
        local_ns.update({
            "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
            "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
            "atan2": sp.atan2,
            "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt,
            "abs": sp.Abs, "sign": sp.sign,
            "pow": lambda a, b: a ** b,
        })

        for name in sorted_names:
            a = aux_map[name]
            try:
                parsed = sp.sympify(a.expr, locals=local_ns)
            except Exception as e:
                raise ValueError(f"无法解析辅助表达式 '{a.name}' = '{a.expr}': {e}")
            # 根据 simplify_level 决定是否简化（默认不简化）
            local_ns[name] = self._maybe_simplify(parsed)
            self.aux_exprs[name] = local_ns[name]

        self.aux_names = sorted_names
        self.aux_used_count = len(sorted_names)
        self.aux_ignored_count = len(pd.auxiliaries) - len(sorted_names)

    def _build_dynamics(self) -> None:
        """为每个状态构建 f[i] = rhs"""
        pd = self._pd

        local_ns = dict(self._name_to_sym)
        local_ns.update(self.aux_exprs)
        local_ns.update({
            "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
            "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
            "atan2": sp.atan2,
            "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt,
            "abs": sp.Abs, "sign": sp.sign,
            "pow": lambda a, b: a ** b,
        })

        state_index = {sv.name: i for i, sv in enumerate(pd.states)}
        self.f_exprs = [sp.Integer(0)] * pd.nx
        self.f_original_rhs = [""] * pd.nx

        for d in pd.dynamics:
            if d.state not in state_index:
                raise ValueError(f"动力学方程引用了未定义的状态: {d.state}")
            idx = state_index[d.state]
            self.f_original_rhs[idx] = d.rhs  # 保留用户原始 RHS（含辅助变量引用）
            try:
                parsed = sp.sympify(d.rhs, locals=local_ns)
            except Exception as e:
                raise ValueError(f"无法解析动力学 RHS '{d.state}' = '{d.rhs}': {e}")
            self.f_exprs[idx] = self._maybe_simplify(parsed)

        self.f_vec = Matrix(self.f_exprs)

    def _compute_jacobians(self) -> None:
        """计算 A = ∂f/∂x, B = ∂f/∂u（如 derive_jacobian_expressions=False 则跳过）"""
        if self.f_vec is None:
            raise RuntimeError("先调用 build_all() 构建动力学")

        if not self._pd.config.derive_jacobian_expressions:
            self._log("SymEngine: jacobians skipped (derive_jacobian_expressions=False)")
            self.stats["jacobian_df_dx"] = 0.0
            self.stats["jacobian_df_du"] = 0.0
            return

        x_vec = Matrix(self.x_syms)
        u_vec = Matrix(self.u_syms)

        t0 = time.perf_counter()
        self.A_mat = self.f_vec.jacobian(x_vec)
        self.stats["jacobian_df_dx"] = time.perf_counter() - t0

        t1 = time.perf_counter()
        self.B_mat = self.f_vec.jacobian(u_vec)
        self.stats["jacobian_df_du"] = time.perf_counter() - t1

    def _maybe_simplify(self, expr: sp.Expr) -> sp.Expr:
        """根据 simplify_level 决定是否调用简化"""
        if self._simplify_level == "none":
            return expr
        elif self._simplify_level == "basic":
            return sp.expand(expr)
        else:
            return sp.simplify(expr)

    # ── 输出方法 ──────────────────────────────────────────────────

    def get_latex(self, expr: sp.Expr) -> str:
        return latex(expr)

    def get_c_code(self, expr: sp.Expr) -> str:
        return ccode(expr)

    def get_structured(self, expr: sp.Expr) -> Dict[str, Any]:
        return _expr_to_structured(expr)

    def get_matrix_latex(self, mat: Matrix) -> List[List[str]]:
        rows, cols = mat.shape
        return [[latex(mat[i, j]) for j in range(cols)] for i in range(rows)]

    def get_matrix_c_code(self, mat: Matrix) -> List[List[str]]:
        rows, cols = mat.shape
        return [[ccode(mat[i, j]) for j in range(cols)] for i in range(rows)]

    def get_matrix_structured(self, mat: Matrix) -> List[List[Dict[str, Any]]]:
        return _matrix_to_structured(mat)

    # ── 查询 ──────────────────────────────────────────────────────

    @property
    def nx(self) -> int:
        return self._pd.nx

    @property
    def nu(self) -> int:
        return self._pd.nu

    @property
    def np(self) -> int:
        return self._pd.np
