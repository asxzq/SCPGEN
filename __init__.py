"""
scpgen — SCP/SOCP Problem Description → CSC Sparse Matrix Fill C Code Generator.

Reads a two-layer YAML problem description (model + transcription),
performs symbolic differentiation & normalization via SymPy, freezes CSC
sparsity patterns, and generates C source files for matrix fill routines.

Two-stage pipeline:
  Stage 1:  Original YAML → SubProblem YAML  (subproblem_compiler.py)
  Stage 2:  SubProblem YAML → C code         (future)

Scope: problem → SOCP data matrix fill code only.
NOT included: solver, KKT analysis, LDLT decomposition.
"""

__version__ = "0.2.0"
__all__ = [
    "ModelDef", "TranscriptionDef",
    "parse_problem", "parse_original_problem",
    "CodeGenerator", "SubproblemCompiler",
]
