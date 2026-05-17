"""
C code generator.

Reads ModelDef + TranscriptionDef, runs symbolic analysis, freezes sparsity,
and renders Jinja2 templates to produce complete C source files.

Output files:
  - {name}_config.h       Compile-time macros & dimensions
  - {name}_dynamics.c     RHS / Jacobian evaluation
  - {name}_integration.c  Forward integration (RK4)
  - {name}_matrix.c       CSC sparsity init + fill_matrix()
  - {name}_normalize.c    Normalization / denormalization
"""

import os
from pathlib import Path
from typing import Dict, Optional

from jinja2 import Environment, FileSystemLoader

from .model import ModelDef
from .transcription import TranscriptionDef
from .symengine import SymContext, generate_symbolic_dynamics_jacobian, sympy_to_c, parse_expr
from .discretizer import IndexMap
from .sparsity import SparsityPattern
from .operations.base import get_op_registry, ProcessingOp

import sympy as sp


# ── Template Environment ────────────────────────────────────────────────────

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ── Code Generator ──────────────────────────────────────────────────────────

class CodeGenerator:
    """
    Main code generator. Orchestrates the full pipeline:

        ModelDef + TranscriptionDef
            → SymContext (symbolic)
            → IndexMap (discrete indexing)
            → SparsityPattern (frozen CSC)
            → C source code (Jinja2)
    """

    def __init__(self, model: ModelDef, transcription: TranscriptionDef):
        self.model = model
        self.transcription = transcription

        # Pipeline stages (lazy-initialized)
        self._sym_ctx: Optional[SymContext] = None
        self._index_map: Optional[IndexMap] = None
        self._sparsity: Optional[SparsityPattern] = None
        self._ops: Dict[str, ProcessingOp] = {}

    # ── Pipeline ────────────────────────────────────────────────────────

    def run_pipeline(self) -> dict:
        """Run all pipeline stages and return rendered outputs."""
        self._init_sym_context()
        self._init_index_map()
        self._init_sparsity()
        self._init_operations()
        self._run_sparsity_analysis()
        self._sparsity.freeze()

        return self._render_all()

    def _init_sym_context(self):
        self._sym_ctx = SymContext(self.model)
        # Pre-create symbols for all variable@node combinations
        N_NODES = self.model.N_NODES
        for v in self.model.all_variables:
            for k in range(N_NODES):
                self._sym_ctx.make_node_symbol(v.name, k)

    def _init_index_map(self):
        self._index_map = IndexMap(self.model, self.transcription)

    def _init_sparsity(self):
        self._sparsity = SparsityPattern(self._index_map.num_vars)

    def _init_operations(self):
        registry = get_op_registry()
        for op_decl in self.transcription.operations:
            op_type = op_decl.type
            if op_type not in registry:
                print(f"Warning: Unknown operation type '{op_type}', skipping")
                continue
            params = dict(op_decl.params)
            params["exports"] = [e.target.value for e in op_decl.exports]
            self._ops[op_type] = registry[op_type](params)

    def _run_sparsity_analysis(self):
        for op in self._ops.values():
            if hasattr(op, 'analyze_sparsity'):
                op.analyze_sparsity(self._index_map, self._sparsity)

    # ── Rendering ────────────────────────────────────────────────────────

    def _render_all(self) -> dict:
        """Render all output files. Returns {filename: content}."""
        env = _get_env()
        name = self.model.name
        outputs = {}

        # Common template variables
        ctx = self._make_template_context()

        # header.h — unified include file
        tpl = env.get_template("header.h.j2")
        outputs[f"{name}.h"] = tpl.render(**ctx)

        # config.h
        tpl = env.get_template("config.h.j2")
        outputs[f"{name}_config.h"] = tpl.render(**ctx)

        # dynamics.c
        tpl = env.get_template("dynamics.c.j2")
        outputs[f"{name}_dynamics.c"] = tpl.render(**ctx)

        # integration.c
        tpl = env.get_template("integration.c.j2")
        outputs[f"{name}_integration.c"] = tpl.render(**ctx)

        # matrix_fill.c
        tpl = env.get_template("matrix_fill.c.j2")
        outputs[f"{name}_matrix.c"] = tpl.render(**ctx)

        # normalize.c
        tpl = env.get_template("normalize.c.j2")
        outputs[f"{name}_normalize.c"] = tpl.render(**ctx)

        # scp_solve.c — SCP orchestration + ECOS integration
        tpl = env.get_template("scp_solve.c.j2")
        outputs[f"{name}_scp_solve.c"] = tpl.render(**ctx)

        return outputs

    def _make_template_context(self) -> dict:
        """Build the full template rendering context."""
        model = self.model
        idx = self._index_map
        sparsity = self._sparsity
        sym = self._sym_ctx
        N_INTERVALS = model.N_INTERVALS
        N_NODES = model.N_NODES
        FINAL_NODE = model.FINAL_NODE

        # ── Symbolic dynamics ──
        # Evaluate Jacobian at a representative node (node 0) for template
        jac = generate_symbolic_dynamics_jacobian(sym, 0)
        A_mat = jac["A"]  # n_states × n_states
        B_mat = jac["B"]  # n_states × n_controls
        f_vec = jac["f"]  # n_states × 1

        # Build C name map for sympy_to_c
        c_name_map = {}
        for s in model.states:
            c_name_map[f"{s.name}@0"] = f"x[{model.states.index(s)}]"
        for ctrl in model.controls:
            c_name_map[f"{ctrl.name}@0"] = f"u[{model.controls.index(ctrl)}]"
        for p in model.parameters:
            c_name_map[p.name] = f"p->{p.name}"

        # Convert RHS expressions
        rhs_c = []
        for entry in model.dynamics:
            expr = parse_expr(entry.rhs, sym, node=0)
            rhs_c.append(sympy_to_c(expr, c_name_map))

        # Convert Jacobian entries
        def jac_to_c(mat):
            result = []
            for i in range(mat.rows):
                row = []
                for j in range(mat.cols):
                    row.append(sympy_to_c(mat[i, j], c_name_map))
                result.append(row)
            return result

        A_c = jac_to_c(A_mat)
        B_c = jac_to_c(B_mat)

        # Replace external function calls with cached variable names
        # e.g. get_thrust(t) → _get_thrust, get_mass(t) → _get_mass
        def cache_funcalls(code_str: str) -> str:
            for ef in model.external_funcs:
                code_str = code_str.replace(ef.name + "(t)", "_" + ef.name)
            return code_str

        rhs_c_cached = [cache_funcalls(r) for r in rhs_c]
        A_c_cached = [[cache_funcalls(e) for e in row] for row in A_c]
        B_c_cached = [[cache_funcalls(e) for e in row] for row in B_c]

        # ── Cone sizes from registered operations ──
        cone_sizes = idx.cone_sizes
        if cone_sizes:
            cone_lines = []
            for i, sz in enumerate(cone_sizes):
                cone_lines.append(f"    q_cone[{i}] = {sz};")
            cone_code = "\n".join(cone_lines)
        else:
            cone_code = "    /* No SOC cones registered */"

        # ── NNZ from actual sparsity (frozen) ──
        nnz_A = sparsity.nnz_A
        nnz_G = sparsity.nnz_G

        # ── CSC array initializers ──
        ajc_c = self._array_init("Ajc", sparsity.Ajc)
        air_c = self._array_init("Air", sparsity.Air)
        gjc_c = self._array_init("Gjc", sparsity.Gjc)
        gir_c = self._array_init("Gir", sparsity.Gir)

        # ── Fill code from operations ──
        fill_parts = []
        for op in self._ops.values():
            if hasattr(op, 'generate_fill_code'):
                code = op.generate_fill_code(idx, sparsity, sym_ctx=sym)
                if code.strip():
                    fill_parts.append(code)
        fill_code = "\n".join(fill_parts)

        # Parameters for C code
        param_list = []
        for p in model.parameters:
            val = p.value
            c_val = str(val) if isinstance(val, (int, float)) else "0.0"
            c_type = "double"
            param_list.append({"c_type": c_type, "c_value": c_val, "name": p.name})

        return {
            "problem_name": model.name,
            "guard_name": model.name.upper(),
            "source_file": "",
            "version": "0.2.0",
            "N_INTERVALS": N_INTERVALS,
            "N_NODES": N_NODES,
            "FINAL_NODE": FINAL_NODE,
            "n_states": len(model.states),
            "n_controls": len(model.controls),
            "n_aux": len(model.auxiliaries),
            "vars_per_node": len(model.states) + len(model.controls) + len(model.auxiliaries),
            "num_vars": idx.num_vars,
            "num_A_rows": idx.num_A_rows,
            "num_G_linear_rows": idx.num_G_linear_rows,
            "num_G_cone_rows": idx.num_cone_rows,
            "num_G_rows": idx.num_G_rows,
            "cone_dim": max(cone_sizes) if cone_sizes else 1,
            "num_cones": idx.num_cones,
            "nnz_A": nnz_A,
            "nnz_G": nnz_G,
            "max_iter": self.transcription.scp_params.max_iter,
            "eps_convergence": self.transcription.scp_params.eps_convergence,
            "external_funcs": [
                {"name": ef.name, "signature": ef.signature, "description": ef.description}
                for ef in model.external_funcs
            ],
            "parameters": param_list,
            "states": model.states,
            "controls": model.controls,
            "all_variables": model.all_variables,
            "rhs_expressions": rhs_c_cached,
            "A_jacobian": A_c_cached,
            "B_jacobian": B_c_cached,
            "cone_init_code": cone_code,
            "cone_sizes": cone_sizes,
            "fill_code": fill_code,
            "Ajc_init": ajc_c,
            "Air_init": air_c,
            "Gjc_init": gjc_c,
            "Gir_init": gir_c,
            "scp_params": {
                "max_iter": self.transcription.scp_params.max_iter,
                "eps_convergence": self.transcription.scp_params.eps_convergence,
                "variable_mode": self.transcription.scp_params.variable_mode.value,
                "is_perturbation": self.transcription.scp_params.is_perturbation,
                "is_direct": self.transcription.scp_params.is_direct,
                "verbose": str(self.transcription.scp_params.verbose).lower(),
            },
            # Extra variable column bases (for C macro generation)
            "extra_vars": [
                {"name": name, "col": col}
                for name, col in idx._extra_vars.items()
            ],
            "extra_vars_total": idx.extra_vars_total,
            # Dimension-based scales for normalize.c
            "scale_values": {dim: sd.value for dim, sd in model.scales.items()},
            # Row index macros for generated code to reference
            "A_blocks": [{"label": label, "start": start, "end": end} for label, start, end in idx._A_blocks],
            "G_blocks": [{"label": label, "start": start, "end": end} for label, start, end in idx._G_blocks],
        }

    @staticmethod
    def _array_init(name: str, values: list) -> str:
        """Generate C array initializer from a list of values."""
        if not values:
            return f"/* {name} is empty */"
        # For large arrays, emit compactly
        vals = ", ".join(str(v) for v in values)
        return f"    /* {name}[{len(values)}] */\n    {{ {vals} }}"

    @staticmethod
    def _generate_csc_init(name: str, jc: list) -> str:
        """Generate C code to initialize CSC column pointers."""
        if not jc:
            return f"    /* {name} is empty */"
        lines = []
        for i, val in enumerate(jc):
            lines.append(f"    socp.{name}[{i}] = {val};")
        return "\n".join(lines)

    @staticmethod
    def _generate_air_init(name: str, ir: list) -> str:
        """Generate C code to initialize row indices."""
        if not ir:
            return f"    /* {name} is empty */"
        lines = []
        for i, val in enumerate(ir):
            lines.append(f"    socp.{name}[{i}] = {val};")
        return "\n".join(lines)

    # ── Write to disk ───────────────────────────────────────────────────

    def write_outputs(self, output_dir: str) -> list:
        """Write all generated files to output_dir. Returns list of paths."""
        outputs = self.run_pipeline()
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        written = []
        for filename, content in outputs.items():
            filepath = out_path / filename
            filepath.write_text(content, encoding="utf-8")
            written.append(str(filepath))

        return written
