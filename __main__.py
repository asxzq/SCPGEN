"""
scpgen — Stage 1: Original YAML → Subproblem YAML Compiler.

Usage:
    python -m scpgen compile          <original.yaml> [-o output/]
    python -m scpgen validate-original <original.yaml>
    python -m scpgen validate-subproblem <subproblem.yaml>

Stage 1 compiles an original problem YAML into a subproblem YAML,
which contains fully-expanded variable/constraint layout for downstream
C code generation (Stage 2).
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
