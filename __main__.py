"""
scpgen — SCP/SOCP Problem Description → CSC Sparse Matrix Fill C Code Generator.

Reads a two-layer YAML problem description (model + transcription),
performs symbolic differentiation & normalization via SymPy, freezes CSC
sparsity patterns, and generates C source files for matrix fill routines.

Scope: problem → SOCP data matrix fill code only.
NOT included: solver, KKT analysis, LDLT decomposition.

Usage:
    python -m scpgen validate examples/ascent.yaml
    python -m scpgen generate examples/ascent.yaml -o output/
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
