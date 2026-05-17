"""
CSC sparse pattern freezer.

Before any numerical values are computed, the sparsity pattern of A and G
matrices is fully determined by:
  - The variable layout (which determines column indices)
  - The constraint structure (which determines which rows touch which columns)

This module:
  1. Collects (row, col) annotations for each nonzero entry.
  2. Builds CSC column pointers (Ajc/Gjc) and row index arrays (Air/Gir).
  3. Provides a jfill mechanism: for each column, a write cursor that
     advances as values are filled, enabling O(1) direct sparse writes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple


@dataclass
class SparsityPattern:
    """
    Pre-computed CSC sparse structure for A and G matrices.

    The structure is frozen after construction. At code-generation time,
    the generated C fill function uses jfill cursors (analogous to the
    reference implementations) to write values directly into pre-allocated
    CSC arrays without any runtime sparsity search.

    CSC format:
      Ajc[j]   = start offset of column j in Apr/Air arrays
      Ajc[j+1] = one past the last element of column j
      Air[k]   = row index of the k-th nonzero
      Apr[k]   = value of the k-th nonzero (filled at runtime)
    """

    num_cols: int = 0

    # For A matrix (equality constraints)
    A_row_cols: Dict[int, Set[int]] = field(default_factory=dict)  # row → set of cols
    Ajc: List[int] = field(default_factory=list)
    Air: List[int] = field(default_factory=list)

    # For G matrix (inequality constraints)
    G_row_cols: Dict[int, Set[int]] = field(default_factory=dict)
    Gjc: List[int] = field(default_factory=list)
    Gir: List[int] = field(default_factory=list)

    # Ordered nonzeros per column (for jfill cursor initialization)
    _A_col_entries: Dict[int, List[int]] = field(default_factory=dict)  # col → sorted rows
    _G_col_entries: Dict[int, List[int]] = field(default_factory=dict)

    def __init__(self, num_cols: int):
        self.num_cols = num_cols
        self.A_row_cols = {}
        self.G_row_cols = {}

    # ── Registration ─────────────────────────────────────────────────────

    def register_A_nz(self, row: int, col: int):
        """Register a nonzero at (row, col) in the A matrix."""
        self.A_row_cols.setdefault(row, set()).add(col)

    def register_G_nz(self, row: int, col: int):
        """Register a nonzero at (row, col) in the G matrix."""
        self.G_row_cols.setdefault(row, set()).add(col)

    def register_A_nz_block(self, rows: List[int], cols: List[int]):
        """Register a dense block of nonzeros."""
        for r in rows:
            for c in cols:
                self.register_A_nz(r, c)

    def register_G_nz_block(self, rows: List[int], cols: List[int]):
        for r in rows:
            for c in cols:
                self.register_G_nz(r, c)

    # ── Freeze ────────────────────────────────────────────────────────────

    def freeze(self):
        """
        Build the CSC column-pointer and row-index arrays from registered
        nonzeros. Call once after all operations have registered their sparsity.
        """
        self.Ajc, self.Air, self._A_col_entries = self._build_csc(
            self.A_row_cols, self.num_cols
        )
        self.Gjc, self.Gir, self._G_col_entries = self._build_csc(
            self.G_row_cols, self.num_cols
        )

    @staticmethod
    def _build_csc(
        row_cols: Dict[int, Set[int]], num_cols: int
    ) -> Tuple[List[int], List[int], Dict[int, List[int]]]:
        """
        Build CSC arrays from row→cols mapping.

        Returns:
            (jc, ir, col_entries) where col_entries[col] = sorted list of rows
        """
        # Invert: for each column, collect rows
        col_rows: Dict[int, List[int]] = {c: [] for c in range(num_cols)}
        for r, cols in row_cols.items():
            for c in cols:
                if c < num_cols:
                    col_rows[c].append(r)

        # Sort rows within each column
        col_entries: Dict[int, List[int]] = {}
        for c in range(num_cols):
            col_entries[c] = sorted(col_rows.get(c, []))

        # Build jc (column pointers) and ir (row indices)
        jc = [0]
        ir = []
        for c in range(num_cols):
            entries = col_entries[c]
            ir.extend(entries)
            jc.append(jc[-1] + len(entries))

        return jc, ir, col_entries

    # ── Query ─────────────────────────────────────────────────────────────

    @property
    def nnz_A(self) -> int:
        return len(self.Air)

    @property
    def nnz_G(self) -> int:
        return len(self.Gir)

    def get_A_rows_in_col(self, col: int) -> List[int]:
        """Return sorted row indices for a given column in A."""
        return self._A_col_entries.get(col, [])

    def get_G_rows_in_col(self, col: int) -> List[int]:
        """Return sorted row indices for a given column in G."""
        return self._G_col_entries.get(col, [])

    def summary(self) -> str:
        return (
            f"SparsityPattern: nnz_A={self.nnz_A}, nnz_G={self.nnz_G}, "
            f"cols={self.num_cols}"
        )
