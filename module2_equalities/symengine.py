"""
符号引擎 — Module 2 等式约束的 SymPy 符号表达式构建与微分

镜像 Module 1 的 SymEngine 模式。
只处理等式约束引用的辅助函数闭包。
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional, Callable
from collections import deque
import time

import sympy as sp
from sympy import Symbol, Matrix, diff, latex, ccode

from .models import Module2InputDef, EqualityConstraintDef
from scpgen.common.expression_utils import preprocess_expression, replace_variable_names_in_expr


def _null_logger(msg: str) -> None:
    pass


class EqualitySymEngine:
    """
    Module 2 符号引擎：管理符号变量、约束表达式、雅可比矩阵。

    用法:
        engine = EqualitySymEngine(module_input, logger=print)
        engine.build_all()
    """

    def __init__(
        self,
        module_input: Module2InputDef,
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

        # 辅助表达式（只包含等式约束闭包中的）
        self.aux_names: List[str] = []
        self.aux_exprs: Dict[str, sp.Expr] = {}
        self.aux_used_count: int = 0
        self.aux_ignored_count: int = 0

        # 约束表达式和雅可比
        self.constraint_exprs: Dict[str, List[sp.Expr]] = {}  # name → [expr1, expr2, ...]
        self.constraint_Hx: Dict[str, List[sp.Matrix]] = {}   # name → [Hx1, Hx2, ...]
        self.constraint_Hu: Dict[str, List[sp.Matrix]] = {}   # name → [Hu1, Hu2, ...]

        # 计时
        self.stats: Dict[str, float] = {}

    # ── 构造方法 ──────────────────────────────────────────────────

    def build_all(self) -> None:
        """执行全部构建步骤"""
        t0 = time.perf_counter()

        self._build_symbols()
        self._log(
            f"EqualitySymEngine: states={self.nx}, controls={self.nu}, params={self.np}"
        )

        t1 = time.perf_counter()
        self._build_auxiliaries()
        self.stats["parse_auxiliaries"] = time.perf_counter() - t1
        self._log(
            f"EqualitySymEngine: aux used={self.aux_used_count}, "
            f"ignored={self.aux_ignored_count}, "
            f"time={self.stats['parse_auxiliaries']:.3f}s"
        )

        t2 = time.perf_counter()
        self._build_constraints()
        self.stats["build_constraints"] = time.perf_counter() - t2
        self._log(
            f"EqualitySymEngine: constraints built, time={self.stats['build_constraints']:.3f}s"
        )

        t3 = time.perf_counter()
        self._compute_jacobians()
        self.stats["jacobian_total"] = time.perf_counter() - t3
        self._log(
            f"EqualitySymEngine: jacobians computed, time={self.stats['jacobian_total']:.3f}s"
        )

        self.stats["total"] = time.perf_counter() - t0
        self._log(f"EqualitySymEngine: total time={self.stats['total']:.3f}s")

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
        """只解析等式约束依赖闭包中的辅助表达式"""
        mi = self._mi
        if not mi.auxiliaries:
            return

        # 构建 aux_map — **使用 safe_name 作为 key**
        # 这样约束表达式中被替换为 safe_name 的引用可以正确匹配
        aux_map = {}
        aux_expr_original: Dict[str, str] = {}  # safe_name → 原始 YAML 表达式
        aux_expr_preprocessed: Dict[str, str] = {}  # safe_name → 预处理后表达式
        for a in mi.auxiliaries:
            name = a["name"] if isinstance(a, dict) else a.name
            safe_name = mi.name_to_safe.get(name, name)
            expr_str = a["expr"] if isinstance(a, dict) else a.expr
            aux_map[safe_name] = a
            aux_expr_original[safe_name] = expr_str
            # 预处理 aux 表达式：语法标准化 + 变量名替换
            pp = preprocess_expression(expr_str)
            pp = replace_variable_names_in_expr(pp, mi.name_to_safe)
            aux_expr_preprocessed[safe_name] = pp
        aux_name_set = set(aux_map.keys())

        # 收集所有约束表达式中引用的符号（已经是 safe_name）
        referenced: set = set()
        for c in mi.constraints:
            for expr_str in c.scalar_expressions:
                referenced.update(self._extract_identifiers(expr_str))

        # BFS 扩展闭包 — 使用预处理后的 aux 表达式做依赖分析
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

    def _compute_aux_closure(
        self, aux_map: Dict, aux_name_set: set,
        aux_expr_preprocessed: Dict[str, str], referenced: set
    ):
        """计算辅助表达式依赖闭包（使用预处理后的表达式）"""
        mi = self._mi
        # 对每个 aux，提取声明的和推断的依赖
        declared_deps: Dict[str, set] = {}
        inferred_deps: Dict[str, set] = {}
        final_deps: Dict[str, set] = {}

        for name, a in aux_map.items():
            pp_expr = aux_expr_preprocessed.get(name, "")
            deps_list = a.get("dependencies", []) if isinstance(a, dict) else getattr(a, 'dependencies', [])
            # 将声明的依赖从 original name 转为 safe name
            declared_safe = {mi.name_to_safe.get(d, d) for d in deps_list}
            declared = declared_safe & aux_name_set
            inferred = self._extract_identifiers(pp_expr) & aux_name_set
            declared_deps[name] = declared
            inferred_deps[name] = inferred
            final_deps[name] = declared | inferred

        # BFS
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
        """为每条等式约束构建 SymPy 表达式"""
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
            for expr_str in c.scalar_expressions:
                try:
                    parsed = sp.sympify(expr_str, locals=local_ns)
                except Exception as e:
                    raise ValueError(
                        f"无法解析等式约束 '{c.name}' 的表达式 '{expr_str}': {e}"
                    )
                exprs.append(self._maybe_simplify(parsed))
            self.constraint_exprs[c.name] = exprs

    def _compute_jacobians(self) -> None:
        """计算每条约束的 Hx = dh/dx, Hu = dh/du"""
        x_vec = Matrix(self.x_syms) if self.x_syms else Matrix([])
        u_vec = Matrix(self.u_syms) if self.u_syms else Matrix([])

        for c in self._mi.constraints:
            hx_list = []
            hu_list = []
            for expr in self.constraint_exprs.get(c.name, []):
                # Hx = dh/dx (行向量, 1×nx)
                if self.nx > 0:
                    hx = Matrix([expr]).jacobian(x_vec)
                else:
                    hx = Matrix([])
                hx_list.append(hx)
                # Hu = dh/du (行向量, 1×nu)
                if self.nu > 0:
                    hu = Matrix([expr]).jacobian(u_vec)
                else:
                    hu = Matrix([])
                hu_list.append(hu)
            self.constraint_Hx[c.name] = hx_list
            self.constraint_Hu[c.name] = hu_list

    def _maybe_simplify(self, expr: sp.Expr) -> sp.Expr:
        """根据 simplify_level 决定是否简化"""
        if self._simplify_level == "none":
            return expr
        elif self._simplify_level == "basic":
            return sp.expand(expr)
        else:
            return sp.simplify(expr)

    @staticmethod
    def _extract_identifiers(expr_str: str) -> set:
        """从表达式字符串中提取标识符"""
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
