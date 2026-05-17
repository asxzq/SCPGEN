"""
SymPy symbolic engine.

Responsibilities (no intelligent inference):
  1. Parse YAML math expression strings → SymPy expressions
  2. Build a symbol table from ModelDef variables × node indices
  3. Compute Jacobians (dynamics RHS, constraints)
  4. Apply normalization transformation: x_phys = scale * x_norm
  5. Convert SymPy expressions → C code strings
"""

import sympy as sp
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

from .model import ModelDef, VariableDef, VarRole


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class SymContext:
    """
    Holds all symbolic information for one problem instance.

    Attributes:
        model: reference to the parsed ModelDef
        symbols: dict mapping canonical_name → sympy.Symbol
            canonical_name = "var@k"  e.g. "rx@0", "alpha@N"
        scales: dict mapping var_name → scale_value
        params: dict mapping param_name → sympy.Symbol
        ext_funcs: dict mapping func_name → sympy.Function
    """
    model: ModelDef
    symbols: Dict[str, sp.Symbol] = field(default_factory=dict)
    scales: Dict[str, float] = field(default_factory=dict)
    params: Dict[str, sp.Symbol] = field(default_factory=dict)
    ext_funcs: Dict[str, sp.Function] = field(default_factory=dict)
    _var_index_map: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self._build_symbol_table()

    def _build_symbol_table(self):
        """Create Symbol objects for all variables and parameters."""
        # Variable scales: look up from dimension → scale mapping
        for v in self.model.all_variables:
            self.scales[v.name] = self.model.scale_of(v.name)

        # Parameter symbols
        for p in self.model.parameters:
            self.params[p.name] = sp.Symbol(p.name, real=True)

        # Expression aliases as named symbols (referenced by name)
        for e in self.model.expressions:
            self.params[e.name] = sp.Symbol(e.name, real=True)

        # External functions as sympy Function symbols
        for ef in self.model.external_funcs:
            self.ext_funcs[ef.name] = sp.Function(ef.name)

        # Add 't' as time symbol
        self.params["t"] = sp.Symbol("t", real=True)

    def make_node_symbol(self, var_name: str, node: int) -> sp.Symbol:
        """Get or create a symbol for var_name at a specific node index."""
        key = f"{var_name}@{node}"
        if key not in self.symbols:
            self.symbols[key] = sp.Symbol(key, real=True)
        return self.symbols[key]

    def get_node_symbol(self, var_name: str, node: int) -> sp.Symbol:
        """Get existing symbol for var_name@node."""
        key = f"{var_name}@{node}"
        if key not in self.symbols:
            raise KeyError(f"Symbol '{key}' not found in context")
        return self.symbols[key]

    def get_param(self, name: str) -> sp.Symbol:
        """Get a parameter symbol."""
        if name not in self.params:
            self.params[name] = sp.Symbol(name, real=True)
        return self.params[name]

    def canonical_name(self, var_name: str, node: int) -> str:
        return f"{var_name}@{node}"

    @property
    def state_symbols(self) -> Dict[str, sp.Symbol]:
        """Return {name@k: symbol} only for state variables."""
        return {k: v for k, v in self.symbols.items()
                if k.split("@")[0] in self.model.state_names}

    @property
    def control_symbols(self) -> Dict[str, sp.Symbol]:
        return {k: v for k, v in self.symbols.items()
                if k.split("@")[0] in self.model.control_names}


# ── Expression Parser ────────────────────────────────────────────────────────

def expand_aliases(expr_str: str, model: "ModelDef") -> str:
    """
    Recursively expand expression aliases in an expression string.

    E.g. if model has expressions:
      rho = "rho0 * exp(-h / hs)",  q = "0.5 * rho * v^2"
    Then expand "0.5 * q * S_ref" → "0.5 * (0.5 * (rho0 * exp(-h / hs)) * v^2) * S_ref"

    Uses simple word-boundary replacement to avoid replacing substrings.
    """
    import re
    if not model.expressions:
        return expr_str

    # Build alias map sorted by name length (longest first to avoid partial matches)
    alias_map = {e.name: e.expr for e in model.expressions}

    # Repeatedly expand until stable (handles transitive aliases)
    max_iter = 20
    for _ in range(max_iter):
        changed = False
        for name, rhs in sorted(alias_map.items(), key=lambda x: -len(x[0])):
            # Replace whole-word occurrences only
            pattern = r'(?<![a-zA-Z0-9_])' + re.escape(name) + r'(?![a-zA-Z0-9_])'
            new_expr = re.sub(pattern, '(' + rhs + ')', expr_str)
            if new_expr != expr_str:
                expr_str = new_expr
                changed = True
        if not changed:
            break
    return expr_str


def parse_expr(expr_str: str, ctx: SymContext, node: int = 0,
               local_bindings: Optional[Dict[str, sp.Symbol]] = None,
               expand: bool = True) -> sp.Expr:
    """
    Parse a math expression string into a SymPy expression.

    Args:
        expr_str: the math expression as a string
        ctx: SymContext with parameter & function symbols
        node: default node index for un-indexed variable references
        local_bindings: optional extra symbol bindings
        expand: if True, expand expression aliases before parsing

    Returns:
        sympy.Expr
    """
    from sympy.parsing.sympy_parser import (
        parse_expr as sympy_parse,
        standard_transformations,
        implicit_multiplication_application,
        convert_xor,
    )

    # Expand expression aliases first
    if expand and ctx.model.expressions:
        expr_str = expand_aliases(expr_str, ctx.model)

    # Build local symbol dict
    local = {}
    if local_bindings:
        local.update(local_bindings)

    # Add parameter symbols
    for name, sym in ctx.params.items():
        local[name] = sym

    # Add external function symbols
    for name, sym in ctx.ext_funcs.items():
        local[name] = sym

    # CRITICAL: Add all model variable names to override any sympy built-in
    for v in ctx.model.all_variables:
        local[v.name] = ctx.make_node_symbol(v.name, node)

    # Add common math symbols
    local.update({
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
        "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "atan2": sp.atan2,
        "sqrt": sp.sqrt, "abs": sp.Abs,
        "exp": sp.exp, "log": sp.log,
        "pi": sp.pi,
        "min": sp.Min, "max": sp.Max,
    })

    transformations = standard_transformations + (
        implicit_multiplication_application,
        convert_xor,
    )

    try:
        expr = sympy_parse(expr_str, local_dict=local,
                           transformations=transformations,
                           evaluate=True)
    except Exception as e:
        raise ValueError(f"Failed to parse expression '{expr_str}': {e}")

    # Post-process: replace bare variable names with node-indexed symbols
    expr = _resolve_variable_refs(expr, ctx, node)

    return expr


def _resolve_variable_refs(expr: sp.Expr, ctx: SymContext, default_node: int) -> sp.Expr:
    """
    Replace bare variable-name symbols with their node-indexed counterparts.

    E.g. "rx" → Symbol("rx@0") if default_node=0.
    Skips parameters, external functions, and math functions.
    """
    var_names = {v.name for v in ctx.model.all_variables}
    substitutions = {}

    for sym in expr.free_symbols:
        name = str(sym)
        if name in var_names:
            new_sym = ctx.make_node_symbol(name, default_node)
            if new_sym != sym:
                substitutions[sym] = new_sym

    if substitutions:
        expr = expr.subs(substitutions)

    return expr


# ── Normalization ────────────────────────────────────────────────────────────

def apply_normalization(expr: sp.Expr, ctx: SymContext) -> sp.Expr:
    """
    Transform an expression from physical space to normalized space.

    For each variable v with scale s_v:
        v_phys = s_v * v_norm

    This substitutes v_phys → s_v * v_norm in the expression.

    Args:
        expr: expression in physical variables
        ctx: SymContext with scale information

    Returns:
        expression in normalized variables
    """
    substitutions = {}
    for sym in expr.free_symbols:
        name = str(sym)
        # Extract base variable name from "name@node" pattern
        if "@" in name:
            base_name = name.split("@")[0]
            if base_name in ctx.scales:
                # physical = scale * normalized
                # We work in normalized space, so replace the unscaled symbol
                # with the scaled one: expr already uses the unscaled name.
                # Actually: we want to express everything in normalized vars.
                # If expr uses v_phys, substitute v_phys = s * v_norm.
                scale = ctx.scales[base_name]
                if scale != 1.0:
                    # The symbol in expr represents the physical quantity.
                    # Create a symbol for the normalized quantity.
                    norm_sym = sp.Symbol(f"{name}_norm", real=True)
                    substitutions[sym] = scale * norm_sym

    if substitutions:
        expr = expr.subs(substitutions)

    return expr


# ── Jacobian ─────────────────────────────────────────────────────────────────

def compute_jacobian(expr: sp.Expr, wrt_symbols: List[sp.Symbol]) -> sp.Matrix:
    """
    Compute the Jacobian of a scalar expression w.r.t. a list of symbols.

    Returns a 1×n row vector (sympy.Matrix).
    """
    if not wrt_symbols:
        return sp.Matrix([])
    return sp.Matrix([expr]).jacobian(sp.Matrix(wrt_symbols))


def compute_gradient(expr: sp.Expr, wrt_symbols: List[sp.Symbol]) -> sp.Matrix:
    """Compute gradient as a column vector."""
    jac = compute_jacobian(expr, wrt_symbols)
    return jac.T


# ── SymPy → C Code ───────────────────────────────────────────────────────────

def sympy_to_c(expr: sp.Expr, var_name_map: Optional[Dict[str, str]] = None) -> str:
    """
    Convert a SymPy expression to a C code string.

    Handles:
      - Regular symbols via var_name_map or @-suffix replacement
      - External function calls (sp.Function) → direct C function call syntax
      - Built-in math functions (sin, cos, etc.) via sympy's ccode printer

    Args:
        expr: SymPy expression
        var_name_map: optional dict mapping sympy symbol names → C variable names.
                      e.g. {"rx@0": "x[0]", "g0": "param.g0"}

    Returns:
        C code string (e.g. "x[0]*cos(x[4]) + param.g0 + get_thrust(t)")
    """
    if var_name_map is None:
        var_name_map = {}

    from sympy.printing.c import ccode
    from sympy.core.function import AppliedUndef

    # Step 1: Replace Function calls (like get_thrust, get_mass) with
    func_subs = {}
    for atom in expr.atoms(AppliedUndef):
        func_name = str(type(atom).__name__)  # e.g. "get_thrust"
        # Build the C function call: func_name(arg1, arg2, ...)
        c_args = []
        for arg in atom.args:
            arg_c = sympy_to_c(arg, var_name_map)
            c_args.append(arg_c)
        c_func_call = func_name + "(" + ", ".join(c_args) + ")"
        func_subs[atom] = sp.Symbol("__FUNC__" + c_func_call + "__FUNC__")

    if func_subs:
        expr = expr.subs(func_subs)

    # Step 2: Replace symbols using var_name_map
    subs = {}
    for sym in expr.free_symbols:
        sym_name = str(sym)
        if sym_name.startswith("__FUNC__") and sym_name.endswith("__FUNC__"):
            # This is a function call placeholder, keep the name
            subs[sym] = sp.Symbol(sym_name[8:-8])  # strip markers
        elif sym_name in var_name_map:
            c_name = var_name_map[sym_name]
            subs[sym] = sp.Symbol(c_name)
        elif "@" in sym_name:
            # Convert "rx@0" → "rx_0" for C compatibility
            c_name = sym_name.replace("@", "_")
            subs[sym] = sp.Symbol(c_name)

    if subs:
        expr = expr.subs(subs)

    # Step 3: Use ccode for the remaining expression
    code = ccode(expr)

    # Step 4: Clean up — remove any remaining quotes around function markers
    # that ccode might have added
    code = code.replace('"', '')

    return code


def generate_symbolic_dynamics_jacobian(
    ctx: SymContext, node: int
) -> Dict[str, sp.Matrix]:
    """
    Compute the full Jacobian of the dynamics RHS vector w.r.t. all state and
    control variables at a given node.

    Returns:
        {
            "A": Jacobian w.r.t. states  (n_states × n_states),
            "B": Jacobian w.r.t. controls (n_states × n_controls),
            "f": RHS vector (n_states × 1),
        }
    """
    n_states = len(ctx.model.states)
    n_ctrl = len(ctx.model.controls)

    # Collect symbols
    state_syms = [ctx.make_node_symbol(s.name, node) for s in ctx.model.states]
    ctrl_syms = [ctx.make_node_symbol(c.name, node) for c in ctx.model.controls]

    # Parse RHS expressions
    rhs_exprs = []
    for dyn in ctx.model.dynamics:
        expr = parse_expr(dyn.rhs, ctx, node=node)
        rhs_exprs.append(expr)

    f_vec = sp.Matrix(rhs_exprs)

    # Jacobians
    A_mat = f_vec.jacobian(sp.Matrix(state_syms)) if state_syms else sp.Matrix([])
    B_mat = f_vec.jacobian(sp.Matrix(ctrl_syms)) if ctrl_syms else sp.Matrix([])

    return {"A": A_mat, "B": B_mat, "f": f_vec}


def generate_path_constraint_gradient(
    ctx: SymContext, expr_str: str, node: int
) -> Dict[str, sp.Expr]:
    """
    Compute the gradient of a path constraint expression g(x,u)
    w.r.t. all state and control variables at a given node.

    Returns:
        {
            "g":     the expression g(x,u) evaluated symbolically,
            "dg_dx": list of ∂g/∂x_i  (length n_states),
            "dg_du": list of ∂g/∂u_i  (length n_controls),
        }
    """
    n_states = len(ctx.model.states)
    n_ctrl = len(ctx.model.controls)

    state_syms = [ctx.make_node_symbol(s.name, node) for s in ctx.model.states]
    ctrl_syms = [ctx.make_node_symbol(c.name, node) for c in ctx.model.controls]

    g_expr = parse_expr(expr_str, ctx, node=node)

    dg_dx = [sp.diff(g_expr, sym) for sym in state_syms]
    dg_du = [sp.diff(g_expr, sym) for sym in ctrl_syms]

    return {"g": g_expr, "dg_dx": dg_dx, "dg_du": dg_du}
