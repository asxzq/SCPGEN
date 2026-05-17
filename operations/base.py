"""
Base class and registry for processing operations.

Each operation type declared in transcription.operations is implemented
as a ProcessingOp subclass. New types can be registered via @register_op.

Lifecycle:
  1. analyze_sparsity(index_map, sparsity) — declare where nonzeros go
  2. generate_fill_code(index_map, sparsity) → str — produce C fill code
  3. generate_decl_code() → str — produce C declarations if needed
"""

from abc import ABC, abstractmethod
from typing import Dict, Type


# ── Registry ─────────────────────────────────────────────────────────────────

_OP_REGISTRY: Dict[str, Type["ProcessingOp"]] = {}


def register_op(op_type: str):
    """Decorator to register a ProcessingOp subclass."""
    def decorator(cls: Type["ProcessingOp"]):
        _OP_REGISTRY[op_type] = cls
        cls.op_type = op_type
        return cls
    return decorator


def get_op_registry() -> Dict[str, Type["ProcessingOp"]]:
    return dict(_OP_REGISTRY)


# ── Base Class ───────────────────────────────────────────────────────────────

class ProcessingOp(ABC):
    """
    Abstract base for a transcription processing operation.

    Subclasses must define:
      - op_type: str (set automatically by @register_op)
      - analyze_sparsity()
      - generate_fill_code()
    """

    op_type: str = ""

    def __init__(self, params: dict):
        self.params = params
        self.exports = params.get("exports", [])

    @abstractmethod
    def analyze_sparsity(self, index_map: "IndexMap", sparsity: "SparsityPattern") -> None:
        """
        Analyze which matrix entries this operation touches and register
        them in the SparsityPattern.

        Args:
            index_map: Provides var_name@node → global column index.
            sparsity:  Mutable SparsityPattern to register nonzero locations.
        """
        ...

    @abstractmethod
    def generate_fill_code(self, index_map: "IndexMap", sparsity: "SparsityPattern") -> str:
        """
        Generate the C code snippet that fills values into A,b,G,h,c,Q
        for one SCP iteration.

        Returns a string of C code (to be embedded in the fill function).
        """
        ...

    def generate_decl_code(self) -> str:
        """Optional: extra C declarations needed by this operation."""
        return ""
