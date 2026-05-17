"""
Discretization expander & global index allocator.

Responsibilities:
  1. Expand node range expressions (e.g. [0, "N"]) into concrete node lists.
  2. Assign a global column index in the decision vector x for each
     (variable, node) pair according to the variable_layout.
  3. Assign row indices for each constraint group in A and G matrices.
  4. Allocate extra variable columns (slack, virtual control) appended after
     regular variable@node columns.
  5. Register SOC cone dimensions from each operation.
  6. Provide O(1) lookup via IndexMap.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Union

from .model import ModelDef
from .transcription import TranscriptionDef, VarOrdering


@dataclass
class IndexMap:
    """
    Global index mappings for the SOCP problem.

    Provides O(1) lookup for:
      - var_index(var_name, node_k) → column in x vector
      - A_row_*, G_row_* → row offsets in constraint matrices
      - extra_var_col(name) → column of appended extra variable

    Also tracks the total dimensions of the problem.
    """
    model: ModelDef
    transcription: TranscriptionDef

    # ── Decision variable (column) indices ──
    # Maps canonical name "var@k" → global column index (0-based)
    _var_to_col: Dict[str, int] = field(default_factory=dict)

    # ── Extra variables (slack, virtual control) appended after regular vars ──
    # Maps extra variable name → global column index
    _extra_vars: Dict[str, int] = field(default_factory=dict)
    # Maps extra variable name → (node_start, node_end) for per-node extra vars
    _extra_var_nodes: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    _extra_var_count: int = 0

    # ── Constraint row indices ──
    _A_row_next: int = 0    # next available row in A/b
    _G_row_next: int = 0    # next available row in G/h (linear inequalities)
    _cone_row_next: int = 0 # next available row in cone constraints

    # Track row ranges for each constraint group
    _A_blocks: List[Tuple[str, int, int]] = field(default_factory=list)
    _G_blocks: List[Tuple[str, int, int]] = field(default_factory=list)

    # ── SOC cone dimension tracking ──
    # Each operation registers its cone sizes; aggregated into q_cone[] at codegen
    _cone_sizes: List[int] = field(default_factory=list)
    _cone_labels: List[str] = field(default_factory=list)

    def __post_init__(self):
        self._allocate_variables()

    # ── Variable Index Allocation ─────────────────────────────────────────

    def _allocate_variables(self):
        """Allocate column indices for all decision variables."""
        layout = self.transcription.variable_layout
        N_NODES = self.model.N_NODES  # number of discrete nodes

        # Resolve node ranges in each group
        resolved_groups = []
        for g in layout.groups:
            start = self._resolve_node(g.nodes[0], N_NODES)
            end = self._resolve_node(g.nodes[1], N_NODES)
            node_list = list(range(start, end + 1))
            resolved_groups.append((g.vars, node_list))

        col = 0

        if layout.ordering == VarOrdering.BY_NODE:
            # [var_group0@0, var_group1@0, ..., var_group0@1, var_group1@1, ...]
            max_nodes = max(
                (len(nl) for _, nl in resolved_groups), default=0
            )
            for k in range(max_nodes):
                for var_names, node_list in resolved_groups:
                    if k < len(node_list):
                        node = node_list[k]
                        for vname in var_names:
                            key = f"{vname}@{node}"
                            self._var_to_col[key] = col
                            col += 1
        else:  # BY_VARIABLE
            # [rx@0, rx@1, ..., rx@N, ry@0, ry@1, ..., ry@N, ...]
            for var_names, node_list in resolved_groups:
                for node in node_list:
                    for vname in var_names:
                        key = f"{vname}@{node}"
                        self._var_to_col[key] = col
                        col += 1

        self._num_vars = col

    @staticmethod
    def _resolve_node(raw_node, N_NODES: int) -> int:
        """Resolve a node expression: int stays int, 'N' → FINAL_NODE (= N_NODES - 1)."""
        if isinstance(raw_node, int):
            return raw_node
        if isinstance(raw_node, str) and raw_node.upper() == "N":
            return N_NODES - 1  # 'N' = FINAL_NODE = 最后一个节点的索引
        # Try to evaluate as integer
        try:
            return int(raw_node)
        except (ValueError, TypeError):
            raise ValueError(f"Cannot resolve node: {raw_node}")

    # ── Public Lookup API ────────────────────────────────────────────────

    def var_col(self, var_name: str, node: int) -> int:
        """Return the global column index for variable@node."""
        key = f"{var_name}@{node}"
        if key not in self._var_to_col:
            raise KeyError(f"No index assigned for '{key}'")
        return self._var_to_col[key]

    def var_col_or_none(self, var_name: str, node: int) -> int | None:
        """Return column index or None if not assigned."""
        return self._var_to_col.get(f"{var_name}@{node}")

    @property
    def num_vars(self) -> int:
        """Total number of decision variables (columns in A/G), including extras."""
        return self._num_vars + self._extra_var_count

    # ── Extra Variable Allocation (slack, virtual control) ───────────────

    def allocate_extra_var(self, name: str, node_start: int = 0,
                           node_end: int = 0) -> int:
        """
        Allocate one or more extra variable columns appended after regular vars.

        If node_start < node_end, allocates one column per node in [node_start, node_end].
        Otherwise allocates a single scalar column.

        Returns the first column index (or single column index for scalars).
        """
        if node_start < node_end:
            # Per-node extra variable: allocate one col per node
            start_col = self._num_vars + self._extra_var_count
            for node in range(node_start, node_end + 1):
                key = f"{name}@{node}"
                col = self._num_vars + self._extra_var_count
                self._var_to_col[key] = col
                self._extra_vars[key] = col
                self._extra_var_count += 1
            self._extra_var_nodes[name] = (node_start, node_end)
            return start_col
        else:
            # Scalar extra variable
            col = self._num_vars + self._extra_var_count
            self._extra_vars[name] = col
            self._var_to_col[name] = col
            self._extra_var_count += 1
            return col

    def extra_var_col(self, name: str, node: int = -1) -> int:
        """
        Return the global column index for an extra variable.

        Args:
            name: extra variable name (e.g. "zeta_dyn", "s_overload_limit")
            node: node index for per-node extra vars (-1 for scalar)
        """
        if node >= 0:
            key = f"{name}@{node}"
            if key in self._var_to_col:
                return self._var_to_col[key]
        if name in self._extra_vars:
            return self._extra_vars[name]
        raise KeyError(f"Extra variable '{name}' not allocated")

    @property
    def extra_var_names(self) -> List[str]:
        """Return names of all allocated extra variables."""
        return list(self._extra_vars.keys())

    @property
    def extra_vars_total(self) -> int:
        """Total number of extra variable columns."""
        return self._extra_var_count

    # ── SOC Cone Dimension Registration ──────────────────────────────────

    def register_cone_size(self, size: int, label: str = "") -> int:
        """
        Register a SOC cone dimension.

        Args:
            size: number of rows in this cone (including the apex t row)
            label: human-readable label for the cone

        Returns the cone index (0-based) in the q_cone[] array.
        """
        idx = len(self._cone_sizes)
        self._cone_sizes.append(size)
        self._cone_labels.append(label or f"cone_{idx}")
        return idx

    @property
    def num_cones(self) -> int:
        """Total number of SOC cones."""
        return len(self._cone_sizes)

    @property
    def cone_sizes(self) -> List[int]:
        """List of cone dimensions in order of registration."""
        return list(self._cone_sizes)

    # ── Constraint Row Allocation ────────────────────────────────────────

    def allocate_A_rows(self, label: str, count: int) -> int:
        """
        Allocate `count` rows in the A matrix.
        Returns the starting row index.
        """
        start = self._A_row_next
        self._A_blocks.append((label, start, start + count))
        self._A_row_next += count
        return start

    def allocate_G_rows(self, label: str, count: int) -> int:
        """Allocate `count` rows in the G matrix (linear inequalities)."""
        start = self._G_row_next
        self._G_blocks.append((label, start, start + count))
        self._G_row_next += count
        return start

    def allocate_cone_rows(self, count: int) -> int:
        """Allocate `count` rows in the cone constraint section.
        
        Cone rows are placed AFTER all linear inequality rows in the G matrix.
        Returns the global G row index.
        """
        start = self._G_row_next + self._cone_row_next
        self._cone_row_next += count
        return start

    @property
    def num_A_rows(self) -> int:
        return self._A_row_next

    @property
    def num_G_linear_rows(self) -> int:
        """Number of linear inequality rows (ECOS 'l' parameter)."""
        return self._G_row_next

    @property
    def num_G_rows(self) -> int:
        """Total G matrix rows = linear + cone."""
        return self._G_row_next + self._cone_row_next

    @property
    def num_cone_rows(self) -> int:
        return self._cone_row_next

    # ── Utility ──────────────────────────────────────────────────────────

    def summary(self) -> str:
        lines = [
            f"IndexMap summary:",
            f"  Decision variables (columns): {self.num_vars}",
            f"    (regular var@node: {self._num_vars}, extra: {self._extra_var_count})",
            f"  A matrix rows (equalities):  {self.num_A_rows}",
            f"  G matrix rows (inequalities): {self.num_G_rows}",
            f"  Cone rows:                    {self.num_cone_rows}",
            f"  SOC cones:                    {self.num_cones}",
        ]
        if self._cone_sizes:
            for i, (size, label) in enumerate(zip(self._cone_sizes, self._cone_labels)):
                lines.append(f"    cone[{i}] size={size} ← {label}")
        for label, start, end in self._A_blocks:
            lines.append(f"    A[{start}:{end}] ← {label}")
        for label, start, end in self._G_blocks:
            lines.append(f"    G[{start}:{end}] ← {label}")
        if self._extra_vars:
            for name, col in self._extra_vars.items():
                lines.append(f"    extra_var '{name}' → col {col}")
        return "\n".join(lines)
