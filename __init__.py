"""
scpgen — Stage 1: Original YAML → Subproblem YAML Compiler.

Reads unified YAML problem descriptions (meta + grid + scale + model +
transcription), performs grid expansion, variable/constraint allocation,
and generates the intermediate SubProblem YAML required by Stage 2.

Scope of Stage 1:
  - Parse original YAML → OriginalProblemDef
  - Compute dimensions, allocate variable columns, constraint rows
  - Generate SubProblem YAML with fixed layouts

NOT included in Stage 1:
  - C code generation (Stage 2)
  - Solver algorithms, KKT analysis, LDLT decomposition

Pipeline:
  python -m scpgen compile <original.yaml> [-o output/]
  python -m scpgen validate-original <original.yaml>
  python -m scpgen validate-subproblem <subproblem.yaml>
"""

__version__ = "1.0.0-stage1"

from .original_parser import parse_original_problem
from .subproblem_compiler import SubproblemCompiler
from .subproblem_models import (
    subproblem_to_dict,
    subproblem_from_dict,
    SubProblemDef,
    ObjectiveTerm,
    SubObjective,
)
from .subproblem_validator import validate_subproblem
from .original_problem import (
    ApproximationDecl,
    AddedObjectiveTerm,
    OriginalProblemDef,
    MetaDef,
    GridDef,
    TimeDef,
    OrigModelDef,
    OrigTranscriptionDef,
)

__all__ = [
    # Parser
    "parse_original_problem",
    # Compiler
    "SubproblemCompiler",
    # Serialization
    "subproblem_to_dict",
    "subproblem_from_dict",
    # Validation
    "validate_subproblem",
    "SubProblemDef",
    # Objective data models
    "ObjectiveTerm",
    "SubObjective",
    "ApproximationDecl",
    "AddedObjectiveTerm",
    # Data models (for reference)
    "OriginalProblemDef",
    "MetaDef",
    "GridDef",
    "TimeDef",
    "OrigModelDef",
    "OrigTranscriptionDef",
]
