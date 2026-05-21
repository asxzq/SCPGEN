"""Module6 数据模型 — 解析 Module5 输出后的中间表示。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# ============================================================================
# 基础数据类
# ============================================================================

@dataclass
class EcosDimensions:
    """ECOS 问题维度。"""
    n: int = 0
    p: int = 0
    m: int = 0
    l: int = 0
    q: List[int] = field(default_factory=list)


@dataclass
class VariableBlock:
    """变量块描述。"""
    name: str = ""
    role: str = ""
    source_module: str = ""
    domain: str = "free"
    dimension_concrete: int = 0
    dimension_symbolic: str = ""
    column_start_concrete: int = 0
    column_end_concrete: int = 0
    in_original_z: bool = True


@dataclass
class ObjectiveEntry:
    """c 向量填充条目。"""
    source_cost_term: str = ""
    variable_block: str = ""
    coefficient: Any = 0
    applies_to: str = "all_elements"
    is_epigraph: bool = False
    variable_dimension_concrete: int = 0
    variable_column_start: int = 0
    variable_column_end: int = 0


@dataclass
class ObjectivePlan:
    """目标向量装配计划。"""
    entries: List[ObjectiveEntry] = field(default_factory=list)


@dataclass
class SocAssemblyEntry:
    """SOC 装配条目。"""
    role: str = ""
    local_row: int = -1
    local_row_start: int = -1
    local_row_end: int = -1
    h_value: Any = 0
    repeated_for: str = ""
    entries: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SocBlock:
    """二阶锥块描述。"""
    name: str = ""
    dim: int = 0
    row_range_exclusive: List[int] = field(default_factory=list)
    source_cost_term: str = ""
    epigraph_variable: str = ""
    vector_variable: str = ""
    vector_dimension_concrete: int = 0
    rho_symbol: str = ""
    soc_assembly: List[SocAssemblyEntry] = field(default_factory=list)


@dataclass
class MatrixBlock:
    """矩阵装配块 — 描述 A/G 中一个具体数值块。"""
    name: str = ""
    variable_block: str = ""
    shape_rows: int = 0
    shape_cols: int = 0
    coefficient_value: str = ""
    structure: str = ""
    is_diagonal: bool = False
    node: str = ""


@dataclass
class RhsBlock:
    """RHS 块 — 描述 b/h 中一个右端项。"""
    name: str = ""
    node: str = ""
    value: Optional[float] = None


@dataclass
class AssemblyRowBlock:
    """装配行块 — 增强版 RowBlock，包含 matrix_blocks 和 rhs_block。"""
    name: str = ""
    row_start_concrete: int = 0
    row_end_concrete: int = 0
    row_range_exclusive: List[int] = field(default_factory=list)
    source_module: str = ""
    variable_stencil: List[str] = field(default_factory=list)
    epigraph_columns_are_zero: bool = True
    epigraph_columns_have_nonzeros: bool = False
    matrix_blocks: List[MatrixBlock] = field(default_factory=list)
    rhs_block: RhsBlock = field(default_factory=RhsBlock)
    cone_type: str = ""
    rows_per_node: int = 0

    @property
    def node_count(self) -> int:
        """推导行块覆盖的节点数。"""
        if self.rows_per_node <= 0:
            return 0
        rr = self.row_range_exclusive
        if rr and len(rr) >= 2:
            total_rows = rr[1] - rr[0]
            if total_rows > 0:
                return total_rows // self.rows_per_node
        return 0


@dataclass
class RowBlock:
    """矩阵行块描述（简化版，兼容旧引用）。"""
    name: str = ""
    row_start_concrete: int = 0
    row_end_concrete: int = 0
    row_range_exclusive: Optional[List[int]] = None
    source_module: str = ""
    variable_stencil: List[str] = field(default_factory=list)
    epigraph_columns_are_zero: bool = True
    epigraph_columns_have_nonzeros: bool = False


@dataclass
class ConesInfo:
    """锥体信息。"""
    dim_l: int = 0
    l_row_range_exclusive: Optional[List[int]] = None
    soc_blocks: List[SocBlock] = field(default_factory=list)
    q_dims: List[int] = field(default_factory=list)


@dataclass
class EqualityInfo:
    """等式约束信息。"""
    A_rows: int = 0
    A_cols: int = 0
    row_blocks: List[RowBlock] = field(default_factory=list)
    assembly_row_blocks: List[AssemblyRowBlock] = field(default_factory=list)


@dataclass
class InequalityInfo:
    """不等式约束信息。"""
    G_rows: int = 0
    G_cols: int = 0
    has_epigraph_columns: bool = False
    row_blocks: List[RowBlock] = field(default_factory=list)
    assembly_row_blocks: List[AssemblyRowBlock] = field(default_factory=list)


@dataclass
class Module6IR:
    """Module6 内部中间表示。

    从 Module5 ECOS canonical IR YAML 解析得到。
    """
    problem_name: str = ""
    variable_mode: str = "perturbation"
    dim_z: int = 0
    dim_y: int = 0
    variable_blocks: List[VariableBlock] = field(default_factory=list)
    dims: EcosDimensions = field(default_factory=EcosDimensions)
    objective_plan: ObjectivePlan = field(default_factory=ObjectivePlan)
    cones: ConesInfo = field(default_factory=ConesInfo)
    equalities: EqualityInfo = field(default_factory=EqualityInfo)
    inequalities: InequalityInfo = field(default_factory=InequalityInfo)
    raw: Dict[str, Any] = field(default_factory=dict)

    # ── 便捷属性 ──
    @property
    def has_epigraph(self) -> bool:
        """是否存在 epigraph 变量。"""
        return self.dim_z < self.dim_y

    @property
    def A_dense_size(self) -> int:
        """A_dense 数组长度（row-major）。"""
        return self.dims.p * self.dims.n

    @property
    def G_dense_size(self) -> int:
        """G_dense 数组长度（row-major）。"""
        return self.dims.m * self.dims.n

    @property
    def params_symbols(self) -> List[str]:
        """从 objective entries 和 SOC blocks 中提取所有符号 coefficient。"""
        symbols: List[str] = []
        seen = set()
        for entry in self.objective_plan.entries:
            coeff = entry.coefficient
            if isinstance(coeff, str) and coeff and not _is_numeric(coeff):
                if coeff not in seen:
                    symbols.append(coeff)
                    seen.add(coeff)
        for sb in self.cones.soc_blocks:
            if sb.rho_symbol and sb.rho_symbol not in seen:
                symbols.append(sb.rho_symbol)
                seen.add(sb.rho_symbol)
        return symbols


def _is_numeric(s: str) -> bool:
    """检查字符串是否为纯数值。"""
    s = s.strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _derive_row_range_exclusive(start_concrete: int, end_concrete: int) -> List[int]:
    """从 inclusive 的 start/end_concrete 推导半开区间 [start, end+1)。"""
    return [start_concrete, end_concrete + 1]


# ============================================================================
# 解析函数
# ============================================================================

def parse_module5_output(m5_dict: Dict[str, Any]) -> Module6IR:
    """从 Module5 输出 YAML 解析为 Module6IR。"""
    ir = Module6IR(raw=m5_dict)

    # 问题信息
    problem = m5_dict.get("problem", {})
    ir.problem_name = problem.get("problem_name", "")
    ir.variable_mode = problem.get("variable_mode", "perturbation")
    ir.dim_z = problem.get("dim_z", 0)
    ir.dim_y = problem.get("dim_y", 0)

    # 变量块
    _parse_variable_blocks(ir, m5_dict)

    # ECOS 维度
    _parse_ecos_dimensions(ir, m5_dict)

    # 目标向量装配计划
    _parse_objective_plan(ir, m5_dict)

    # 锥体
    _parse_cones(ir, m5_dict)

    # 等式约束（含 assembly）
    _parse_equalities(ir, m5_dict)

    # 不等式约束（含 assembly）
    _parse_inequalities(ir, m5_dict)

    return ir


def _parse_variable_blocks(ir: Module6IR, m5_dict: Dict[str, Any]) -> None:
    """解析变量块。"""
    var_reg = m5_dict.get("variable_registry", {})
    ecos_vars = var_reg.get("ecos_variables", {})
    for b in ecos_vars.get("blocks", []):
        ir.variable_blocks.append(VariableBlock(
            name=b.get("name", ""),
            role=b.get("role", ""),
            source_module=b.get("source_module", ""),
            domain=b.get("domain", "free"),
            dimension_concrete=b.get("dimension_concrete", 0),
            dimension_symbolic=b.get("dimension_symbolic", ""),
            column_start_concrete=b.get("column_start_concrete", 0),
            column_end_concrete=b.get("column_end_concrete", 0),
            in_original_z=b.get("in_original_z", True),
        ))


def _parse_ecos_dimensions(ir: Module6IR, m5_dict: Dict[str, Any]) -> None:
    """解析 ECOS 维度。"""
    dims = m5_dict.get("ecos_problem", {}).get("dimensions", {})
    ir.dims = EcosDimensions(
        n=dims.get("n", 0),
        p=dims.get("p", 0),
        m=dims.get("m", 0),
        l=dims.get("l", 0),
        q=dims.get("q", []),
    )


def _parse_objective_plan(ir: Module6IR, m5_dict: Dict[str, Any]) -> None:
    """解析目标向量装配计划。"""
    obj = m5_dict.get("objective", {})
    plan = obj.get("objective_vector_plan", {})
    for entry in plan.get("entries", []):
        ir.objective_plan.entries.append(ObjectiveEntry(
            source_cost_term=entry.get("source_cost_term", ""),
            variable_block=entry.get("variable_block", ""),
            coefficient=entry.get("coefficient", 0),
            applies_to=entry.get("applies_to", "all_elements"),
            is_epigraph=entry.get("is_epigraph", False),
            variable_dimension_concrete=entry.get("variable_dimension_concrete", 0),
            variable_column_start=entry.get("variable_column_start", 0),
            variable_column_end=entry.get("variable_column_end", 0),
        ))


def _parse_cones(ir: Module6IR, m5_dict: Dict[str, Any]) -> None:
    """解析锥体信息。"""
    cones = m5_dict.get("cones", {})
    linear = cones.get("linear", {})
    soc = cones.get("second_order", {})

    soc_blocks = []
    for sb in soc.get("soc_blocks", []):
        soc_assembly = []
        for sa in sb.get("soc_assembly", []):
            soc_assembly.append(SocAssemblyEntry(
                role=sa.get("role", ""),
                local_row=sa.get("local_row", -1),
                local_row_start=sa.get("local_row_start", -1),
                local_row_end=sa.get("local_row_end", -1),
                h_value=sa.get("h_value", 0),
                repeated_for=sa.get("repeated_for", ""),
                entries=sa.get("entries", []),
            ))
        soc_blocks.append(SocBlock(
            name=sb.get("name", ""),
            dim=sb.get("dim", 0),
            row_range_exclusive=sb.get("row_range_exclusive", []),
            source_cost_term=sb.get("source_cost_term", ""),
            epigraph_variable=sb.get("epigraph_variable", ""),
            vector_variable=sb.get("vector_variable", ""),
            vector_dimension_concrete=sb.get("vector_dimension_concrete", 0),
            rho_symbol=sb.get("rho_symbol", ""),
            soc_assembly=soc_assembly,
        ))

    ir.cones = ConesInfo(
        dim_l=linear.get("dim_l", 0),
        l_row_range_exclusive=linear.get("row_range_exclusive"),
        soc_blocks=soc_blocks,
        q_dims=[sb["dim"] for sb in soc.get("q", [])],
    )


def _parse_equalities(ir: Module6IR, m5_dict: Dict[str, Any]) -> None:
    """解析等式约束（含 assembly_plan）。"""
    eq = m5_dict.get("equalities", {})
    eq_shape = eq.get("A_shape_concrete", [0, 0])
    eq_plan = eq.get("assembly_plan", {})

    eq_row_blocks = []
    eq_assembly_blocks = []
    for rb in eq_plan.get("row_blocks", []):
        rr = _derive_row_range_exclusive(
            rb.get("row_start_concrete", 0),
            rb.get("row_end_concrete", 0),
        )
        eq_row_blocks.append(RowBlock(
            name=rb.get("name", ""),
            row_start_concrete=rb.get("row_start_concrete", 0),
            row_end_concrete=rb.get("row_end_concrete", 0),
            row_range_exclusive=rr,
            source_module=rb.get("source_module", ""),
            variable_stencil=rb.get("variable_stencil", []),
            epigraph_columns_are_zero=rb.get("epigraph_columns_are_zero", True),
        ))
        mbs = _parse_matrix_blocks(rb.get("matrix_blocks", []))
        rhs = _parse_rhs_block(rb.get("rhs_block", {}))

        # 解析 row_layout 获取 rows_per_node
        row_layout = rb.get("row_layout", {})
        rpn = row_layout.get("rows_per_node", 0)
        if rpn <= 0:
            rpn = row_layout.get("rows_per_interval", 0)
        if rpn <= 0:
            rpn = row_layout.get("rows_per_variable", 0)

        eq_assembly_blocks.append(AssemblyRowBlock(
            name=rb.get("name", ""),
            row_start_concrete=rb.get("row_start_concrete", 0),
            row_end_concrete=rb.get("row_end_concrete", 0),
            row_range_exclusive=rr,
            source_module=rb.get("source_module", ""),
            variable_stencil=rb.get("variable_stencil", []),
            epigraph_columns_are_zero=rb.get("epigraph_columns_are_zero", True),
            matrix_blocks=mbs,
            rhs_block=rhs,
            rows_per_node=rpn,
        ))

    ir.equalities = EqualityInfo(
        A_rows=eq_shape[0] if len(eq_shape) > 0 else 0,
        A_cols=eq_shape[1] if len(eq_shape) > 1 else 0,
        row_blocks=eq_row_blocks,
        assembly_row_blocks=eq_assembly_blocks,
    )


def _parse_inequalities(ir: Module6IR, m5_dict: Dict[str, Any]) -> None:
    """解析不等式约束（含 matrix_assembly_plan）。"""
    ineq = m5_dict.get("inequalities", {})
    g_shape = ineq.get("G_shape_concrete", [0, 0])
    assembly_plan = m5_dict.get("matrix_assembly_plan", {})
    ineq_assembly = assembly_plan.get("inequality_assembly", {})

    ineq_row_blocks = []
    ineq_assembly_blocks = []

    for cone_block in ineq_assembly.get("row_order", []):
        cone_type = cone_block.get("cone_type", "")
        cone_rr = cone_block.get("row_range_exclusive")

        for rb in cone_block.get("blocks", []):
            # linear cone: 每个 block 使用自己的 row_range
            if cone_type == "linear":
                if rb.get("row_range_exclusive"):
                    rr = rb["row_range_exclusive"]
                else:
                    rr = [rb["row_start_concrete"], rb["row_end_concrete"] + 1]
            else:
                # SOC: 使用整个 cone 的 row_range
                rr = cone_rr if cone_rr else _derive_row_range_exclusive(
                    rb.get("row_start_concrete", 0),
                    rb.get("row_end_concrete", 0),
                )

            # 解析 row_layout 获取 rows_per_node
            row_layout = rb.get("row_layout", {})
            rpn = row_layout.get("rows_per_node", 0)
            if rpn <= 0:
                rpn = row_layout.get("rows_per_interval", 0)
            if rpn <= 0:
                rpn = row_layout.get("rows_per_variable", 0)

            ineq_row_blocks.append(RowBlock(
                name=rb.get("name", ""),
                row_start_concrete=rb.get("row_start_concrete", 0),
                row_end_concrete=rb.get("row_end_concrete", 0),
                row_range_exclusive=rr,
                source_module=rb.get("source_module", ""),
                variable_stencil=rb.get("variable_stencil", []),
                epigraph_columns_are_zero=rb.get(
                    "linear_inequality_epigraph_columns_are_zero", True
                ),
            ))
            mbs = _parse_matrix_blocks(rb.get("matrix_blocks", []))
            rhs = _parse_rhs_block(rb.get("rhs_block", {}))
            ineq_assembly_blocks.append(AssemblyRowBlock(
                name=rb.get("name", ""),
                row_start_concrete=rb.get("row_start_concrete", 0),
                row_end_concrete=rb.get("row_end_concrete", 0),
                row_range_exclusive=rr,
                source_module=rb.get("source_module", ""),
                variable_stencil=rb.get("variable_stencil", []),
                epigraph_columns_are_zero=rb.get(
                    "linear_inequality_epigraph_columns_are_zero", True
                ),
                matrix_blocks=mbs,
                rhs_block=rhs,
                cone_type=cone_type,
                rows_per_node=rpn,
            ))

        # SOC cone block
        if cone_type == "second_order" and cone_rr:
            soc_epi_zero = cone_block.get("epigraph_columns_are_zero", False)
            soc_epi_nonzero = cone_block.get("epigraph_columns_have_nonzeros", False)
            ineq_row_blocks.append(RowBlock(
                name=cone_block.get("cone_name", ""),
                row_start_concrete=cone_rr[0] if cone_rr else 0,
                row_end_concrete=(cone_rr[1] - 1) if cone_rr else 0,
                row_range_exclusive=cone_rr,
                source_module="module5_ecos",
                epigraph_columns_are_zero=soc_epi_zero,
                epigraph_columns_have_nonzeros=soc_epi_nonzero,
            ))
            ineq_assembly_blocks.append(AssemblyRowBlock(
                name=cone_block.get("cone_name", ""),
                row_start_concrete=cone_rr[0] if cone_rr else 0,
                row_end_concrete=(cone_rr[1] - 1) if cone_rr else 0,
                row_range_exclusive=cone_rr,
                source_module="module5_ecos",
                epigraph_columns_are_zero=soc_epi_zero,
                epigraph_columns_have_nonzeros=soc_epi_nonzero,
                matrix_blocks=[],
                rhs_block=RhsBlock(name="zero"),
                cone_type="second_order",
            ))

    ir.inequalities = InequalityInfo(
        G_rows=g_shape[0] if len(g_shape) > 0 else 0,
        G_cols=g_shape[1] if len(g_shape) > 1 else 0,
        has_epigraph_columns=ineq.get("has_epigraph_columns", False),
        row_blocks=ineq_row_blocks,
        assembly_row_blocks=ineq_assembly_blocks,
    )


def _parse_matrix_blocks(mb_list: List[Dict[str, Any]]) -> List[MatrixBlock]:
    """解析 matrix_blocks 列表。"""
    result = []
    for mb in mb_list:
        shape = mb.get("shape", [0, 0])
        result.append(MatrixBlock(
            name=mb.get("name", ""),
            variable_block=mb.get("variable_block", ""),
            shape_rows=shape[0] if len(shape) > 0 else 0,
            shape_cols=shape[1] if len(shape) > 1 else 0,
            coefficient_value=mb.get("coefficient_value", ""),
            structure=mb.get("structure", ""),
            is_diagonal=mb.get("is_diagonal", False),
            node=mb.get("node", ""),
        ))
    return result


def _parse_rhs_block(rhs_dict: Dict[str, Any]) -> RhsBlock:
    """解析 rhs_block。"""
    if not rhs_dict:
        return RhsBlock()
    return RhsBlock(
        name=rhs_dict.get("name", ""),
        node=rhs_dict.get("node", ""),
        value=rhs_dict.get("value"),
    )
