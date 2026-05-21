"""
符号引擎 — Module 3 不等式约束的 SymPy 符号表达式构建与微分

镜像 Module 1/2 的 SymEngine 模式。
只处理不等式约束引用的辅助函数闭包（含 dynamics 未使用的 heatflux、overload 等）。
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional, Callable
from collections import deque
import time

import sympy as sp
from sympy import Symbol, Matrix, latex, ccode

from .models import Module3InputDef, InequalityConstraintDef
from scpgen.common.expression_utils import preprocess_expression, replace_variable_names_in_expr


def _null_logger(msg: str) -> None:
    pass


class InequalitySymEngine:
    """
    Module 3 符号引擎：管理符号变量、约束表达式、雅可比矩阵。

    用法:
        engine = InequalitySymEngine(module_input, logger=print)
        engine.build_all()
    """

    def __init__(
        self,
        module_input: Module3InputDef,
        simplify_level: str = "none",
        logger: Optional[Callable[[str], None]] = None,
    ):
        self._mi = module_input
        self._simplify_level = simplify_level
        self._log = logger or _null_logger

        # 符号表
        self.x_syms: List[Symbol] = []
        self.u_syms: List[Symbol] = []
        self.p_syms: List[Symbol] = []
        self._name_to_sym: Dict[str, Symbol] = {}

        # 辅助表达式（只包含不等式约束闭包中的）
        self.aux_names: List[str] = []
        self.aux_exprs: Dict[str, sp.Expr] = {}
        self.aux_used_count: int = 0
        self.aux_ignored_count: int = 0

        # 约束表达式和雅可比
        self.constraint_exprs: Dict[str, List[sp.Expr]] = {}  # name → [g1, g2, ...]
        self.constraint_Gx: Dict[str, List[sp.Matrix]] = {}   # name → [Gx1, Gx2, ...]
        self.constraint_Gu: Dict[str, List[sp.Matrix]] = {}   # name → [Gu1, Gu2, ...]

        # 计时
        self.stats: Dict[str, float] = {}

    # ── 构造方法 ──────────────────────────────────────────────────

    def build_all(self) -> None:
        """执行全部构建步骤"""
        t0 = time.perf_counter()

        self._build_symbols()
        self._log(
            f"InequalitySymEngine: states={self.nx}, controls={self.nu}, params={self.np}"
        )

        t1 = time.perf_counter()
        self._build_auxiliaries()
        self.stats["parse_auxiliaries"] = time.perf_counter() - t1
        self._log(
            f"InequalitySymEngine: aux used={self.aux_used_count}, "
            f"ignored={self.aux_ignored_count}, "
            f"time={self.stats['parse_auxiliaries']:.3f}s"
        )

        t2 = time.perf_counter()
        self._build_constraints()
        self.stats["build_constraints"] = time.perf_counter() - t2
        self._log(
            f"InequalitySymEngine: constraints built, time={self.stats['build_constraints']:.3f}s"
        )

        t3 = time.perf_counter()
        self._compute_jacobians()
        self.stats["jacobian_total"] = time.perf_counter() - t3
        self._log(
            f"InequalitySymEngine: jacobians computed, time={self.stats['jacobian_total']:.3f}s"
        )

        self.stats["total"] = time.perf_counter() - t0
        self._log(f"InequalitySymEngine: total time={self.stats['total']:.3f}s")

    def _build_symbols(self) -> None:
        """创建 SymPy 符号"""
        mi = self._mi
        for i, sv in enumerate(mi.states):
            name = sv["name"] if isinstance(sv, dict) else sv.name
            safe_name = mi.name_to_safe.get(name, name)
            sym = Symbol(f"x_{i}")
            self.x_syms.append(sym)
            self._name_to_sym[safe_name] = sym

        for i, cv in enumerate(mi.controls):
            name = cv["name"] if isinstance(cv, dict) else cv.name
            safe_name = mi.name_to_safe.get(name, name)
            sym = Symbol(f"u_{i}")
            self.u_syms.append(sym)
            self._name_to_sym[safe_name] = sym

        for i, pv in enumerate(mi.parameters):
            name = pv["name"] if isinstance(pv, dict) else pv.name
            safe_name = mi.name_to_safe.get(name, name)
            sym = Symbol(f"p_{i}")
            self.p_syms.append(sym)
            self._name_to_sym[safe_name] = sym

    def _build_auxiliaries(self) -> None:
        """
        只解析不等式约束依赖闭包中的辅助表达式。
        与 Module 1 不同：Module 3 必须处理 inequality 专用 auxiliary
        （如 heatflux、overload），这些是 dynamics 未使用的。
        """
        mi = self._mi
        if not mi.auxiliaries:
            return

        # 构建 aux_map — **使用 safe_name 作为 key**
        aux_map = {}
        aux_expr_original: Dict[str, str] = {}
        aux_expr_preprocessed: Dict[str, str] = {}
        for a in mi.auxiliaries:
            name = a["name"] if isinstance(a, dict) else a.name
            safe_name = mi.name_to_safe.get(name, name)
            expr_str = a["expr"] if isinstance(a, dict) else a.expr
            aux_map[safe_name] = a
            aux_expr_original[safe_name] = expr_str
            pp = preprocess_expression(expr_str)
            pp = replace_variable_names_in_expr(pp, mi.name_to_safe)
            aux_expr_preprocessed[safe_name] = pp
        aux_name_set = set(aux_map.keys())

        # 收集所有不等式约束表达式中引用的符号（已经是 safe_name）
        referenced: set = set()
        for c in mi.constraints:
            for expr_str in c.normalized_expressions:
                referenced.update(self._extract_identifiers(expr_str))

        # BFS 扩展闭包
        closure, declared_deps, inferred_deps, final_deps = self._compute_aux_closure(
            aux_map, aux_name_set, aux_expr_preprocessed, referenced
        )

        if not closure:
            self.aux_ignored_count = len(mi.auxiliaries)
            return

        # 拓扑排序
        sorted_names = self._topo_sort_aux(aux_map, closure, final_deps)

        # 按拓扑序解析 — 使用预处理后的表达式
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
            pp_expr = aux_expr_preprocessed[name]
            try:
                parsed = sp.sympify(pp_expr, locals=local_ns)
            except Exception as e:
                raise ValueError(
                    f"无法解析辅助表达式 '{name}' = '{pp_expr}': {e}"
                )
            local_ns[name] = self._maybe_simplify(parsed)
            self.aux_exprs[name] = local_ns[name]

        self.aux_names = sorted_names
        self.aux_used_count = len(sorted_names)
        self.aux_ignored_count = len(mi.auxiliaries) - len(sorted_names)

    def _compute_aux_closure(self, aux_map, aux_name_set,
                            aux_expr_preprocessed, referenced):
        """计算辅助表达式依赖闭包（使用预处理后的表达式）"""
        mi = self._mi
        declared_deps: Dict[str, set] = {}
        inferred_deps: Dict[str, set] = {}
        final_deps: Dict[str, set] = {}

        for name, a in aux_map.items():
            pp_expr = aux_expr_preprocessed.get(name, "")
            deps_list = a.get("dependencies", []) if isinstance(a, dict) else getattr(a, 'dependencies', [])
            declared_safe = {mi.name_to_safe.get(d, d) for d in deps_list}
            declared = declared_safe & aux_name_set
            inferred = self._extract_identifiers(pp_expr) & aux_name_set
            declared_deps[name] = declared
            inferred_deps[name] = inferred
            final_deps[name] = declared | inferred

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

        return closure, declared_deps, inferred_deps, final_deps

    def _topo_sort_aux(self, aux_map, closure, final_deps):
        """拓扑排序辅助表达式"""
        in_degree: Dict[str, int] = {}
        dependents: Dict[str, List[str]] = {}
        for name in closure:
            deps = [d for d in final_deps.get(name, set()) if d in closure]
            in_degree[name] = len(deps)
            for d in deps:
                dependents.setdefault(d, []).append(name)

        queue: deque[str] = deque(n for n, deg in in_degree.items() if deg == 0)
        sorted_names: List[str] = []
        while queue:
            name = queue.popleft()
            sorted_names.append(name)
            for dep in dependents.get(name, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if len(sorted_names) != len(closure):
            remaining = closure - set(sorted_names)
            raise ValueError(f"辅助表达式存在循环依赖: {remaining}")

        return sorted_names

    def _build_constraints(self) -> None:
        """为每条不等式约束构建 SymPy 表达式"""
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

        for c in self._mi.constraints:
            exprs = []
            for expr_str in c.normalized_expressions:
                try:
                    parsed = sp.sympify(expr_str, locals=local_ns)
                except Exception as e:
                    raise ValueError(
                        f"无法解析不等式约束 '{c.name}' 的表达式 '{expr_str}': {e}"
                    )
                exprs.append(self._maybe_simplify(parsed))
            self.constraint_exprs[c.name] = exprs

    def _compute_jacobians(self) -> None:
        """计算每条约束的 Gx = dg/dx, Gu = dg/du"""
        x_vec = Matrix(self.x_syms) if self.x_syms else Matrix([])
        u_vec = Matrix(self.u_syms) if self.u_syms else Matrix([])

        for c in self._mi.constraints:
            gx_list = []
            gu_list = []
            for expr in self.constraint_exprs.get(c.name, []):
                if self.nx > 0:
                    gx = Matrix([expr]).jacobian(x_vec)
                else:
                    gx = Matrix([])
                gx_list.append(gx)
                if self.nu > 0:
                    gu = Matrix([expr]).jacobian(u_vec)
                else:
                    gu = Matrix([])
                gu_list.append(gu)
            self.constraint_Gx[c.name] = gx_list
            self.constraint_Gu[c.name] = gu_list

    def _maybe_simplify(self, expr: sp.Expr) -> sp.Expr:
        if self._simplify_level == "none":
            return expr
        elif self._simplify_level == "basic":
            return sp.expand(expr)
        else:
            return sp.simplify(expr)

    @staticmethod
    def _extract_identifiers(expr_str: str) -> set:
        import re
        known_funcs = {
            "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
            "exp", "log", "sqrt", "abs", "sign", "pow",
        }
        ids = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr_str))
        return ids - known_funcs

    # ── 输出方法 ──────────────────────────────────────────────────

    def get_latex(self, expr: sp.Expr) -> str:
        return latex(expr)

    def get_c_code(self, expr: sp.Expr) -> str:
        return ccode(expr)

    # ── 查询 ──────────────────────────────────────────────────────

    @property
    def nx(self) -> int:
        return self._mi.nx

    @property
    def nu(self) -> int:
        return self._mi.nu

    @property
    def np(self) -> int:
        return self._mi.np
