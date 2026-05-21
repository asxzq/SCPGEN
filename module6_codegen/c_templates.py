"""Module6 C 代码模板。

每个模板函数接收 Module6IR 并返回完整的 C 源码字符串。
模板使用 Python f-string 风格，不依赖 Jinja2。
"""

from __future__ import annotations

from typing import List
from scpgen.module6_codegen.models import (
    Module6IR, VariableBlock, ObjectiveEntry,
    SocBlock, SocAssemblyEntry, RowBlock, EcosDimensions,
    AssemblyRowBlock, MatrixBlock, RhsBlock,
)


# ==== 工具函数 ====

def _macro_name(name: str) -> str:
    """将变量块名转为 C 宏名。"""
    return "SCPGEN_" + name.upper().replace(" ", "_").replace("-", "_")


def _safe_c_identifier(name: str) -> str:
    """将字符串转为安全的 C 标识符。"""
    import re
    # 替换特殊字符
    result = name.replace("+", "_PLUS_").replace("-", "_MINUS_").replace("*", "_STAR_")
    result = result.replace("/", "_DIV_").replace("(", "_LPAREN_").replace(")", "_RPAREN_")
    result = result.replace(" ", "_").replace(".", "_")
    # 确保以字母或下划线开头
    result = re.sub(r'[^a-zA-Z0-9_]', '_', result)
    if result and result[0].isdigit():
        result = "_" + result
    return result


def _safe_c_comment(text: str) -> str:
    """转义 C 注释中的特殊字符。"""
    return text.replace("*/", "*\\/").replace("/*", "/\\*")


def _coefficient_to_c_value(coeff, rho_symbol: str = "rho_vc") -> str:
    """将系数转换为 C 代码中的值表达式。

    数值直接输出，符号名如 "rho_vc" 转为 "params->rho_vc"。
    """
    if isinstance(coeff, (int, float)):
        if coeff == 1:
            return "1.0"
        if coeff == -1:
            return "-1.0"
        if coeff == 0:
            return "0.0"
        return str(float(coeff))
    s = str(coeff).strip()
    # 符号名称 → params->xxx
    if s.replace("_", "").isalpha() or s in ("rho_vc",):
        return f"params->{s}"
    # 包含表达式的（如 sqrt(2*rho_vc)）→ 映射为 params->rho_vc
    if "rho_vc" in s or "rho_" in s:
        # 将符号转为 params->xxx
        import re
        result = s
        for sym in re.findall(r'[a-zA-Z_][a-zA-Z_0-9]*', s):
            if sym in ("sqrt", "sum", "abs"):
                continue
            result = result.replace(sym, f"params->{sym}")
        return result
    return s


def _generate_header_guard_begin(guard: str) -> str:
    return f"""#ifndef {guard}
#define {guard}"""


def _generate_header_guard_end(guard: str) -> str:
    return f"""#endif /* {guard} */"""


# ==== scpgen_types.h ====

def generate_types_h(ir: Module6IR) -> str:
    """生成 scpgen_types.h"""
    lines = [
        _generate_header_guard_begin("SCPGEN_TYPES_H"),
        "",
        "#include <stddef.h>",
        "",
        "/* ================================================================",
        f" * SCPGEN 类型定义 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
        "/* ==== 基础类型 ==== */",
        "/** SCPGEN 浮点类型 (默认 double) */",
        "typedef double scpgen_float;",
        "",
        "/** SCPGEN 整数类型 */",
        "typedef int scpgen_int;",
        "",
        "/* ==== 错误码 ==== */",
        "#define SCPGEN_SUCCESS               0",
        "#define SCPGEN_ERR_INVALID_ARGUMENT -1",
        "#define SCPGEN_ERR_NOT_IMPLEMENTED  -2",
        "#define SCPGEN_ERR_BUFFER_TOO_SMALL -3",
        "#define SCPGEN_ERR_CALLBACK_FAILED  -4",
        "",
        _generate_header_guard_end("SCPGEN_TYPES_H"),
        "",
    ]
    return "\n".join(lines)


# ==== scpgen_dims.h ====

def generate_dims_h(ir: Module6IR) -> str:
    """生成 scpgen_dims.h"""
    d = ir.dims

    lines = [
        _generate_header_guard_begin("SCPGEN_DIMS_H"),
        "",
        '#include "scpgen_types.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN 维度宏定义 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
        "/* ==== ECOS 问题维度 ==== */",
        f"/** ECOS 优化变量 y 的总维度 */",
        f"#define SCPGEN_N     {d.n}",
        "",
        f"/** 等式约束行数 (A y = b) */",
        f"#define SCPGEN_P     {d.p}",
        "",
        f"/** 锥约束总行数 (G y + s = h, s in K) */",
        f"#define SCPGEN_M     {d.m}",
        "",
        f"/** 非负正交锥 R_+^l 维度（线性不等式行数） */",
        f"#define SCPGEN_L     {d.l}",
        "",
        f"/** 二阶锥个数 */",
        f"#define SCPGEN_NUM_SOC     {len(d.q)}",
        "",
        "/* ==== 原始变量与扩展变量维度 ==== */",
        f"/** 原始决策变量维度（不含 epigraph 变量） */",
        f"#define SCPGEN_DIM_Z     {ir.dim_z}",
        "",
        f"/** ECOS 扩展变量维度（等于 SCPGEN_N） */",
        f"#define SCPGEN_DIM_Y     {ir.dim_y}",
        "",
        "/* ==== Dense 矩阵尺寸 ==== */",
        f"/** A_dense 数组长度 (p * n, row-major) */",
        f"#define SCPGEN_A_DENSE_SIZE     {ir.A_dense_size}",
        "",
        f"/** G_dense 数组长度 (m * n, row-major) */",
        f"#define SCPGEN_G_DENSE_SIZE     {ir.G_dense_size}",
        "",
    ]

    if d.q:
        lines.append("/** 二阶锥各锥维度 */")
        for i, qi in enumerate(d.q):
            lines.append(f"#define SCPGEN_Q{i}     {qi}")
        lines.append("")
        lines.append("/** 二阶锥维度数组 (extern, 定义在 scpgen_problem.c) */")
        lines.append("extern const scpgen_int SCPGEN_Q[SCPGEN_NUM_SOC];")
    else:
        lines.append("/** 无二阶锥 */")
        lines.append("/* SCPGEN_Q 未定义 */")

    lines.append("")
    lines.append(_generate_header_guard_end("SCPGEN_DIMS_H"))
    lines.append("")

    return "\n".join(lines)


# ==== scpgen_indices.h ====

def generate_indices_h(ir: Module6IR) -> str:
    """生成 scpgen_indices.h"""
    lines = [
        _generate_header_guard_begin("SCPGEN_INDICES_H"),
        "",
        '#include "scpgen_dims.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN 变量索引宏 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " *",
        " * 列范围语义: [START, END] inclusive",
        " * 行范围语义: 使用半开区间 [row_range_exclusive_start, row_range_exclusive_end)",
        " * ================================================================ */",
        "",
        "/* ==== 变量列索引 ==== */",
    ]

    for vb in ir.variable_blocks:
        macro_prefix = _macro_name(vb.name)
        lines.append(f"/* {vb.name}: {vb.role} (dim={vb.dimension_concrete}, source={vb.source_module}) */")
        lines.append(f"#define {macro_prefix}_COL_START     {vb.column_start_concrete}")
        lines.append(f"#define {macro_prefix}_COL_END       {vb.column_end_concrete}")
        lines.append(f"#define {macro_prefix}_DIM           {vb.dimension_concrete}")
        lines.append("")

    # 行范围宏
    lines.append("/* ==== 等式约束 A 行范围 ==== */")
    for rb in ir.equalities.row_blocks:
        name = _macro_name(rb.name)
        rr = rb.row_range_exclusive
        if rr and len(rr) >= 2:
            lines.append(f"#define {name}_ROW_START     {rr[0]}")
            lines.append(f"#define {name}_ROW_END_EXCL  {rr[1]}")
            lines.append(f"#define {name}_ROW_DIM       {rr[1] - rr[0]}")
        lines.append("")

    lines.append("/* ==== 不等式约束 G 行范围（半开区间） ==== */")
    if ir.cones.dim_l > 0 and ir.cones.l_row_range_exclusive:
        lrr = ir.cones.l_row_range_exclusive
        lines.append(f"/* 非负正交锥 R_+^l: [{lrr[0]}, {lrr[1]}) */")
        lines.append(f"#define SCPGEN_L_ROW_START      {lrr[0]}")
        lines.append(f"#define SCPGEN_L_ROW_END_EXCL   {lrr[1]}")
        lines.append("")

    for i, sb in enumerate(ir.cones.soc_blocks):
        rr = sb.row_range_exclusive
        if rr and len(rr) >= 2:
            lines.append(f"/* SOC[{i}]: {sb.name}, dim={sb.dim}, [{rr[0]}, {rr[1]}) */")
            lines.append(f"#define SCPGEN_SOC{i}_ROW_START      {rr[0]}")
            lines.append(f"#define SCPGEN_SOC{i}_ROW_END_EXCL    {rr[1]}")
            lines.append(f"#define SCPGEN_SOC{i}_DIM             {sb.dim}")
            lines.append("")

    lines.append(_generate_header_guard_end("SCPGEN_INDICES_H"))
    lines.append("")

    return "\n".join(lines)


# ==== scpgen_problem.h ====

def generate_problem_h(ir: Module6IR) -> str:
    """生成 scpgen_problem.h"""
    lines = [
        _generate_header_guard_begin("SCPGEN_PROBLEM_H"),
        "",
        '#include "scpgen_types.h"',
        '#include "scpgen_dims.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN 问题数据结构 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "/* ==== 参数结构体 ==== */",
        "typedef struct {",
    ]

    # 从 params_symbols 生成参数字段
    params_symbols = ir.params_symbols
    if params_symbols:
        for sym in params_symbols:
            lines.append(f"    scpgen_float {sym};  /**< 自动生成的参数 */")
        # 确保 rho_vc 始终存在
        if "rho_vc" not in params_symbols:
            lines.append("    scpgen_float rho_vc;  /**< 虚拟控制惩罚系数 (auto-added) */")
    else:
        lines.append("    scpgen_float rho_vc;  /**< 虚拟控制惩罚系数 */")

    lines.append("    scpgen_float zero_tol;  /**< 数值零容差 */")
    lines.append("} scpgen_params;")
    lines.append("")

    # 参考轨迹结构 — 使用 SCPGEN_DIM_Z 而非 SCPGEN_N
    lines.append("/* ==== 参考轨迹结构 ==== */")
    lines.append("typedef struct {")
    lines.append(f"    scpgen_float z[SCPGEN_DIM_Z];  /**< 当前参考轨迹 (原始变量维度) */")
    lines.append(f"    scpgen_float t;                 /**< 当前时刻 */")
    lines.append("} scpgen_reference;")
    lines.append("")

    # 问题数据
    lines.append("/* ==== 问题数据结构 ==== */")
    lines.append("typedef struct {")
    lines.append("    scpgen_params params;      /**< 问题参数 */")
    lines.append("    scpgen_reference ref;      /**< 参考轨迹 */")
    lines.append("} scpgen_problem;")
    lines.append("")

    lines.append("/* ==== 问题初始化 ==== */")
    lines.append("void scpgen_problem_init(scpgen_problem* prob);")
    lines.append("")

    lines.append("#ifdef __cplusplus")
    lines.append("}")
    lines.append("#endif")
    lines.append("")
    lines.append(_generate_header_guard_end("SCPGEN_PROBLEM_H"))
    lines.append("")

    return "\n".join(lines)


# ==== scpgen_problem.c ====

def generate_problem_c(ir: Module6IR) -> str:
    """生成 scpgen_problem.c"""
    lines = [
        '#include "scpgen_problem.h"',
        '#include "scpgen_dims.h"',
        '#include <string.h>',
        "",
        "/* ================================================================",
        f" * SCPGEN 问题数据结构实现 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
    ]

    # Q 数组定义
    if ir.dims.q:
        q_init = "{" + ", ".join(str(qi) for qi in ir.dims.q) + "}"
        lines.append(f"const scpgen_int SCPGEN_Q[SCPGEN_NUM_SOC] = {q_init};")
        lines.append("")

    lines.append("void scpgen_problem_init(scpgen_problem* prob) {")
    lines.append("    memset(prob, 0, sizeof(scpgen_problem));")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


# ==== scpgen_fill.h ====

def generate_fill_h(ir: Module6IR) -> str:
    """生成 scpgen_fill.h"""
    has_soc = bool(ir.cones.soc_blocks)

    lines = [
        _generate_header_guard_begin("SCPGEN_FILL_H"),
        "",
        '#include "scpgen_types.h"',
        '#include "scpgen_dims.h"',
        '#include "scpgen_problem.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN 矩阵/向量填充接口 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "/* ==== 向量清零 ==== */",
        "/** 将 c, b, h 向量清零。返回 SCPGEN_SUCCESS 或错误码。 */",
        "int scpgen_zero_vectors(scpgen_float* c, scpgen_float* b, scpgen_float* h);",
        "",
        "/* ==== Dense 矩阵清零 ==== */",
        "/** 将 A_dense, G_dense 清零。返回 SCPGEN_SUCCESS 或错误码。 */",
        "int scpgen_zero_dense_matrices(scpgen_float* A_dense, scpgen_float* G_dense);",
        "",
        "/* ==== 目标向量 c 填充 ==== */",
        "/**",
        " * 根据 objective_vector_plan 填充 c 向量。",
        " * 仅依赖 objective.objective_vector_plan.entries，",
        " * 不读取 quadratic_terms_canonicalized。",
        " * 使用 += 加性装配。",
        " */",
        "int scpgen_fill_c(scpgen_float* c, const scpgen_params* params);",
        "",
        "/* ==== b/h 向量填充 ==== */",
        "/** 填充等式约束右端向量 b (A y = b) */",
        "int scpgen_fill_b(scpgen_float* b, const scpgen_params* params, const scpgen_reference* ref);",
        "",
        "/** 填充锥约束右端向量 h (G y + s = h) */",
        "int scpgen_fill_h(scpgen_float* h, const scpgen_params* params, const scpgen_reference* ref);",
        "",
    ]

    if has_soc:
        lines.append("/* ==== SOC G/h 填充 ==== */")
        lines.append("/** 填充 SOC 锥对应行的 G 矩阵和 h 向量 */")
        lines.append("int scpgen_fill_soc_Gh(scpgen_float* G, scpgen_float* h, const scpgen_params* params);")
        lines.append("")

    lines.append("/* ==== A/G Dense 矩阵填充 ==== */")
    lines.append("/**")
    lines.append(" * 填充 A 矩阵 (dense, row-major, 尺寸 SCPGEN_A_DENSE_SIZE)。")
    lines.append(" * 遍历 assembly_row_blocks 并调用 scpgen_eval_matrix_block。")
    lines.append(" */")
    lines.append("int scpgen_fill_A_dense(scpgen_float* A_dense, const scpgen_params* params, const scpgen_reference* ref);")
    lines.append("")
    lines.append("/**")
    lines.append(" * 填充 G 矩阵线性锥部分 (dense, row-major, 尺寸 SCPGEN_G_DENSE_SIZE)。")
    lines.append(" * SOC 锥部分由 scpgen_fill_soc_Gh 填充。")
    lines.append(" */")
    lines.append("int scpgen_fill_G_dense(scpgen_float* G_dense, const scpgen_params* params, const scpgen_reference* ref);")
    lines.append("")

    lines.append("/* ==== 一站式 Dense 填充 ==== */")
    lines.append("/**")
    lines.append(" * 连续调用 zero → fill_c → fill_A_dense → fill_b → fill_G_dense → fill_soc_Gh → fill_h。")
    lines.append(" * 成功返回 SCPGEN_SUCCESS，失败返回首个错误码。")
    lines.append(" */")
    lines.append("int scpgen_fill_problem_dense(")
    lines.append("    scpgen_float* c,")
    lines.append("    scpgen_float* A_dense,")
    lines.append("    scpgen_float* b,")
    lines.append("    scpgen_float* G_dense,")
    lines.append("    scpgen_float* h,")
    lines.append("    const scpgen_params* params,")
    lines.append("    const scpgen_reference* ref")
    lines.append(");")
    lines.append("")

    lines.append("#ifdef __cplusplus")
    lines.append("}")
    lines.append("#endif")
    lines.append("")
    lines.append(_generate_header_guard_end("SCPGEN_FILL_H"))
    lines.append("")

    return "\n".join(lines)


# ==== scpgen_fill.c ====

def generate_fill_c(ir: Module6IR) -> str:
    """生成 scpgen_fill.c"""
    lines = [
        '#include "scpgen_fill.h"',
        '#include "scpgen_indices.h"',
        '#include "scpgen_callbacks.h"',
        '#include <string.h>',
        '#include <math.h>',
        "",
        "/* ================================================================",
        f" * SCPGEN 矩阵/向量填充实现 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
    ]

    # ── 辅助宏 ──
    lines.append("/* 辅助: NULL 指针检查 */")
    lines.append("#define SCPGEN_CHECK_NULL(ptr, func_name) \\")
    lines.append("    if (!(ptr)) { return SCPGEN_ERR_INVALID_ARGUMENT; }")
    lines.append("")

    # ── zero_vectors ──
    lines.append("/* ==== 向量清零 ==== */")
    lines.append("int scpgen_zero_vectors(scpgen_float* c, scpgen_float* b, scpgen_float* h) {")
    lines.append("    SCPGEN_CHECK_NULL(c, \"scpgen_zero_vectors\");")
    lines.append("    SCPGEN_CHECK_NULL(b, \"scpgen_zero_vectors\");")
    lines.append("    SCPGEN_CHECK_NULL(h, \"scpgen_zero_vectors\");")
    if ir.dims.n > 0:
        lines.append(f"    memset(c, 0, SCPGEN_N * sizeof(scpgen_float));")
    if ir.dims.p > 0:
        lines.append(f"    memset(b, 0, SCPGEN_P * sizeof(scpgen_float));")
    if ir.dims.m > 0:
        lines.append(f"    memset(h, 0, SCPGEN_M * sizeof(scpgen_float));")
    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")

    # ── zero_dense_matrices ──
    lines.append("/* ==== Dense 矩阵清零 ==== */")
    lines.append("int scpgen_zero_dense_matrices(scpgen_float* A_dense, scpgen_float* G_dense) {")
    lines.append("    SCPGEN_CHECK_NULL(A_dense, \"scpgen_zero_dense_matrices\");")
    lines.append("    SCPGEN_CHECK_NULL(G_dense, \"scpgen_zero_dense_matrices\");")
    if ir.A_dense_size > 0:
        lines.append(f"    memset(A_dense, 0, SCPGEN_A_DENSE_SIZE * sizeof(scpgen_float));")
    if ir.G_dense_size > 0:
        lines.append(f"    memset(G_dense, 0, SCPGEN_G_DENSE_SIZE * sizeof(scpgen_float));")
    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")

    # ── fill_c ── 使用 +=
    lines.append("/* ==== 目标向量 c 填充 ====")
    lines.append(" * 仅依赖 objective.objective_vector_plan.entries")
    lines.append(" * 不读取 quadratic_terms_canonicalized")
    lines.append(" * 使用 += 加性装配")
    lines.append(" */")
    lines.append("int scpgen_fill_c(scpgen_float* c, const scpgen_params* params) {")
    lines.append("    SCPGEN_CHECK_NULL(c, \"scpgen_fill_c\");")
    lines.append("    SCPGEN_CHECK_NULL(params, \"scpgen_fill_c\");")

    if ir.objective_plan.entries:
        for entry in ir.objective_plan.entries:
            coeff_c = _coefficient_to_c_value(entry.coefficient)
            start = entry.variable_column_start
            end = entry.variable_column_end
            if entry.applies_to == "single" or start == end:
                lines.append(f"    /* {entry.source_cost_term}: c[{start}] += {coeff_c} */")
                lines.append(f"    c[{start}] += {coeff_c};")
            else:
                lines.append(f"    /* {entry.source_cost_term}: c[{start}..{end}] += {coeff_c} */")
                lines.append(f"    for (int i = {start}; i <= {end}; i++) {{")
                lines.append(f"        c[i] += {coeff_c};")
                lines.append(f"    }}")
    else:
        lines.append("    /* 无目标向量条目 */")

    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")

    # ── fill_b ──
    _generate_fill_b_code(ir, lines)

    # ── fill_h ── 线性部分
    _generate_fill_h_linear_code(ir, lines)

    # ── fill_soc_Gh ──
    _generate_soc_gh_code(ir, lines)

    # ── fill_A_dense ──
    _generate_fill_A_dense_code(ir, lines)

    # ── fill_G_dense ──
    _generate_fill_G_dense_code(ir, lines)

    # ── fill_problem_dense ──
    _generate_fill_problem_dense_code(ir, lines)

    # cleanup
    lines.append("#undef SCPGEN_CHECK_NULL")
    lines.append("")

    return "\n".join(lines)


def _generate_fill_b_code(ir: Module6IR, lines: List[str]) -> None:
    """生成 scpgen_fill_b 函数。"""
    lines.append("/* ==== b 向量填充 (A y = b) ==== */")
    lines.append("int scpgen_fill_b(scpgen_float* b, const scpgen_params* params, const scpgen_reference* ref) {")
    lines.append("    SCPGEN_CHECK_NULL(b, \"scpgen_fill_b\");")
    lines.append("    SCPGEN_CHECK_NULL(params, \"scpgen_fill_b\");")
    lines.append("    SCPGEN_CHECK_NULL(ref, \"scpgen_fill_b\");")

    eq_blocks = ir.equalities.assembly_row_blocks
    if eq_blocks:
        for arb in eq_blocks:
            rr = arb.row_range_exclusive
            if not rr or rr[0] >= rr[1]:
                continue
            rhs = arb.rhs_block
            lines.append(f"")
            lines.append(f"    /* {arb.name}: rows [{rr[0]}, {rr[1]}) */")
            if rhs.name == "zero" or rhs.value == 0:
                lines.append(f"    for (int r = {rr[0]}; r < {rr[1]}; r++) b[r] = 0.0;")
            elif rhs.value is not None:
                lines.append(f"    for (int r = {rr[0]}; r < {rr[1]}; r++) b[r] = {float(rhs.value)};")
            else:
                # 需要 callback
                rpn = arb.rows_per_node
                lines.append(f"    for (int r = {rr[0]}; r < {rr[1]}; r++) {{")
                lines.append(f"        scpgen_float out_val = 0.0;")
                lines.append(f"        int local_r = r - {rr[0]};")
                if rpn > 0:
                    lines.append(f"        int ni = local_r / {rpn};")
                else:
                    lines.append(f"        int ni = 0;")
                lines.append(f"        int ret = scpgen_eval_rhs_block(")
                lines.append(f'            "{arb.name}", "rhs",')
                lines.append(f"            local_r, r, ni, params, ref, &out_val);")
                lines.append(f"        if (ret != SCPGEN_SUCCESS) return ret;")
                lines.append(f"        b[r] = out_val;")
                lines.append(f"    }}")
    else:
        lines.append("    /* 无等式约束行块 */")

    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")


def _generate_fill_h_linear_code(ir: Module6IR, lines: List[str]) -> None:
    """生成 scpgen_fill_h (线性锥部分)。"""
    lines.append("/* ==== h 向量填充 (G y + s = h) — 线性锥部分 ==== */")
    lines.append("int scpgen_fill_h(scpgen_float* h, const scpgen_params* params, const scpgen_reference* ref) {")
    lines.append("    SCPGEN_CHECK_NULL(h, \"scpgen_fill_h\");")
    lines.append("    SCPGEN_CHECK_NULL(params, \"scpgen_fill_h\");")
    lines.append("    SCPGEN_CHECK_NULL(ref, \"scpgen_fill_h\");")

    # 只处理线性锥部分 (0..l)，SOC 的 h 由 fill_soc_Gh 处理
    linear_blocks = [arb for arb in ir.inequalities.assembly_row_blocks
                     if arb.cone_type != "second_order"]
    if linear_blocks:
        for arb in linear_blocks:
            rr = arb.row_range_exclusive
            if not rr or rr[0] >= rr[1]:
                continue
            rhs = arb.rhs_block
            lines.append(f"")
            lines.append(f"    /* {arb.name}: rows [{rr[0]}, {rr[1]}) */")
            if rhs.name == "zero" or rhs.value == 0:
                lines.append(f"    for (int r = {rr[0]}; r < {rr[1]}; r++) h[r] = 0.0;")
            elif rhs.value is not None:
                lines.append(f"    for (int r = {rr[0]}; r < {rr[1]}; r++) h[r] = {float(rhs.value)};")
            else:
                rpn = arb.rows_per_node
                lines.append(f"    for (int r = {rr[0]}; r < {rr[1]}; r++) {{")
                lines.append(f"        scpgen_float out_val = 0.0;")
                lines.append(f"        int local_r = r - {rr[0]};")
                if rpn > 0:
                    lines.append(f"        int ni = local_r / {rpn};")
                else:
                    lines.append(f"        int ni = 0;")
                lines.append(f"        int ret = scpgen_eval_rhs_block(")
                lines.append(f'            "{arb.name}", "rhs",')
                lines.append(f"            local_r, r, ni, params, ref, &out_val);")
                lines.append(f"        if (ret != SCPGEN_SUCCESS) return ret;")
                lines.append(f"        h[r] = out_val;")
                lines.append(f"    }}")
    else:
        lines.append("    /* 无线性能约束行块 */")

    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")


def _generate_soc_gh_code(ir: Module6IR, lines: List[str]) -> None:
    """生成 scpgen_fill_soc_Gh。"""
    if not ir.cones.soc_blocks:
        lines.append("/* 无 SOC 锥，不生成 scpgen_fill_soc_Gh */")
        lines.append("")
        return

    lines.append("/* ==== SOC 锥 G/h 填充 ==== */")
    lines.append("int scpgen_fill_soc_Gh(scpgen_float* G, scpgen_float* h, const scpgen_params* params) {")
    lines.append("    SCPGEN_CHECK_NULL(G, \"scpgen_fill_soc_Gh\");")
    lines.append("    SCPGEN_CHECK_NULL(h, \"scpgen_fill_soc_Gh\");")
    lines.append("    SCPGEN_CHECK_NULL(params, \"scpgen_fill_soc_Gh\");")

    for i, sb in enumerate(ir.cones.soc_blocks):
        rr = sb.row_range_exclusive
        if not rr:
            continue
        gsr = rr[0]
        lines.append(f"")
        lines.append(f"    /* ==== SOC[{i}]: {sb.name} (dim={sb.dim}, rows [{gsr}, {rr[1]})) ==== */")

        for sa in sb.soc_assembly:
            role = sa.role
            h_val = sa.h_value

            if role == "head":
                lr = sa.local_row
                gr = gsr + lr
                h_str = _coefficient_to_c_value(h_val, sb.rho_symbol)
                lines.append(f"    /* head: G row {gr}, h[{gr}] = {h_str} */")
                lines.append(f"    h[{gr}] = {h_str};")
                for entry in sa.entries:
                    var = entry.get("variable", "")
                    coeff_G = entry.get("coefficient_in_G", 0)
                    cs = _coefficient_to_c_value(coeff_G, sb.rho_symbol)
                    for vb in ir.variable_blocks:
                        if vb.name == var:
                            lines.append(f"    G[{gr} * SCPGEN_N + {vb.column_start_concrete}] += {cs};  /* {var} */")
                            break

            elif role == "tail_scaled_variable":
                slr = sa.local_row_start
                elr = sa.local_row_end
                lines.append(f"    /* tail_scaled: G rows [{gsr + slr}..{gsr + elr}], h=0 */")
                for entry in sa.entries:
                    vblock = entry.get("variable_block", "")
                    coeff_G = entry.get("coefficient_in_G", 0)
                    cs = _coefficient_to_c_value(coeff_G, sb.rho_symbol)
                    for vb in ir.variable_blocks:
                        if vb.name == vblock:
                            lines.append(f"    for (int k = 0; k < {vb.dimension_concrete}; k++) {{")
                            lines.append(f"        int gr = {gsr} + {slr} + k;")
                            lines.append(f"        int gc = {vb.column_start_concrete} + k;")
                            lines.append(f"        G[gr * SCPGEN_N + gc] += {cs};")
                            lines.append(f"    }}")
                            break

            elif role == "tail_epigraph_shift":
                lr = sa.local_row
                gr = gsr + lr
                h_str = _coefficient_to_c_value(h_val, sb.rho_symbol)
                lines.append(f"    /* tail_epigraph: G row {gr}, h[{gr}] = {h_str} */")
                lines.append(f"    h[{gr}] = {h_str};")
                for entry in sa.entries:
                    var = entry.get("variable", "")
                    coeff_G = entry.get("coefficient_in_G", 0)
                    cs = _coefficient_to_c_value(coeff_G, sb.rho_symbol)
                    for vb in ir.variable_blocks:
                        if vb.name == var:
                            lines.append(f"    G[{gr} * SCPGEN_N + {vb.column_start_concrete}] += {cs};  /* {var} */")
                            break

    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")


def _generate_fill_A_dense_code(ir: Module6IR, lines: List[str]) -> None:
    """生成 scpgen_fill_A_dense — per-node整块callback + 正确列偏移。"""
    lines.append("/* ==== A 矩阵 Dense 填充 ==== */")
    lines.append("int scpgen_fill_A_dense(scpgen_float* A_dense, const scpgen_params* params, const scpgen_reference* ref) {")
    lines.append("    SCPGEN_CHECK_NULL(A_dense, \"scpgen_fill_A_dense\");")
    lines.append("    SCPGEN_CHECK_NULL(params, \"scpgen_fill_A_dense\");")
    lines.append("    SCPGEN_CHECK_NULL(ref, \"scpgen_fill_A_dense\");")

    eq_blocks = ir.equalities.assembly_row_blocks
    if eq_blocks:
        for arb in eq_blocks:
            rr = arb.row_range_exclusive
            if not rr or rr[0] >= rr[1]:
                continue
            rpn = arb.rows_per_node
            nc = arb.node_count if rpn > 0 else 1
            rr_start = rr[0]
            lines.append(f"")
            lines.append(f"    /* ==== {arb.name}: rows [{rr_start}, {rr[1]}), rows_per_node={rpn}, node_count={nc} ==== */")

            if not arb.matrix_blocks:
                lines.append(f"    /* 无 matrix_blocks，跳过 */")
                continue

            for mb in arb.matrix_blocks:
                var_block = _find_var_block(ir, mb.variable_block)
                if not var_block:
                    lines.append(f"    /* matrix_block '{mb.name}': variable_block '{mb.variable_block}' 未找到 */")
                    continue

                col_start = var_block.column_start_concrete
                mb_rows = mb.shape_rows
                mb_cols = mb.shape_cols
                node_tag = mb.node

                coeff = mb.coefficient_value
                is_identity = bool(coeff and ("+I" in coeff or "-I" in coeff or "I_" in coeff or "_I_" in coeff))
                sign = "-" if is_identity and coeff.startswith("-") else ""

                if is_identity and not mb.is_diagonal and nc <= 1:
                    # 非对角 identity 且只有一个节点 → 逐行对角
                    lines.append(f"    /* {mb.name}: {sign}I block at cols [{col_start}..{col_start + mb_rows - 1}] */")
                    for lr_var in range(mb_rows):
                        gr = rr_start + lr_var
                        gc = col_start + lr_var
                        lines.append(f"    A_dense[{gr} * SCPGEN_N + {gc}] += {sign}1.0;")
                else:
                    # per-node 循环
                    lines.append(f"    /* {mb.name}: shape=[{mb_rows},{mb_cols}], node='{node_tag}', var_block='{mb.variable_block}' */")
                    for ni in range(nc):
                        col_off = _compute_node_col_offset(col_start, mb_cols, node_tag, ni)
                        if is_identity:
                            # 对角 identity 块
                            for lr_var in range(min(mb_rows, mb_cols)):
                                gr = rr_start + ni * rpn + lr_var
                                lines.append(f"    A_dense[{gr} * SCPGEN_N + {col_off + lr_var}] += {sign}1.0;  /* node {ni} */")
                        else:
                            # 整块callback: 每次返回 shape_rows×shape_cols 个值
                            out_size = mb_rows * mb_cols
                            node_index = ni
                            lines.append(f"    {{ /* node {ni} */")
                            lines.append(f"        scpgen_float out_vals[{out_size}];")
                            lines.append(f"        int ret = scpgen_eval_matrix_block(")
                            lines.append(f'            "{arb.name}", "{mb.name}",')
                            lines.append(f"            0, {rr_start + ni * rpn}, {node_index},")
                            lines.append(f"            params, ref, out_vals, {out_size});")
                            lines.append(f"        if (ret != SCPGEN_SUCCESS) return ret;")
                            lines.append(f"        for (int lr = 0; lr < {mb_rows}; lr++) {{")
                            lines.append(f"            int gr = {rr_start} + {ni} * {rpn} + lr;")
                            lines.append(f"            for (int j = 0; j < {mb_cols}; j++) {{")
                            lines.append(f"                A_dense[gr * SCPGEN_N + {col_off} + j] += out_vals[lr * {mb_cols} + j];")
                            lines.append(f"            }}")
                            lines.append(f"        }}")
                            lines.append(f"    }}")
    else:
        lines.append("    /* 无等式约束行块 */")

    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")


def _generate_fill_G_dense_code(ir: Module6IR, lines: List[str]) -> None:
    """生成 scpgen_fill_G_dense（线性锥部分）— per-node整块callback + 正确列偏移。"""
    lines.append("/* ==== G 矩阵 Dense 填充（线性锥部分） ==== */")
    lines.append("int scpgen_fill_G_dense(scpgen_float* G_dense, const scpgen_params* params, const scpgen_reference* ref) {")
    lines.append("    SCPGEN_CHECK_NULL(G_dense, \"scpgen_fill_G_dense\");")
    lines.append("    SCPGEN_CHECK_NULL(params, \"scpgen_fill_G_dense\");")
    lines.append("    SCPGEN_CHECK_NULL(ref, \"scpgen_fill_G_dense\");")

    linear_blocks = [arb for arb in ir.inequalities.assembly_row_blocks
                     if arb.cone_type != "second_order"]
    if linear_blocks:
        for arb in linear_blocks:
            rr = arb.row_range_exclusive
            if not rr or rr[0] >= rr[1]:
                continue
            rpn = arb.rows_per_node
            nc = arb.node_count if rpn > 0 else 1
            rr_start = rr[0]
            lines.append(f"")
            lines.append(f"    /* ==== {arb.name}: rows [{rr_start}, {rr[1]}), rows_per_node={rpn}, node_count={nc} ==== */")

            if not arb.matrix_blocks:
                lines.append(f"    /* 无 matrix_blocks，跳过 */")
                continue

            for mb in arb.matrix_blocks:
                var_block = _find_var_block(ir, mb.variable_block)
                if not var_block:
                    lines.append(f"    /* matrix_block '{mb.name}': variable_block '{mb.variable_block}' 未找到 */")
                    continue

                col_start = var_block.column_start_concrete
                mb_rows = mb.shape_rows
                mb_cols = mb.shape_cols
                node_tag = mb.node

                coeff = mb.coefficient_value
                is_identity = bool(coeff and ("+I" in coeff or "-I" in coeff or "I_" in coeff or "_I_" in coeff))
                sign = "-" if is_identity and coeff.startswith("-") else ""

                if is_identity and not mb.is_diagonal and nc <= 1:
                    # 非对角 identity 且只有一个节点 → 逐行对角
                    lines.append(f"    /* {mb.name}: {sign}I block at cols [{col_start}..{col_start + mb_rows - 1}] */")
                    for lr_var in range(mb_rows):
                        gr = rr_start + lr_var
                        gc = col_start + lr_var
                        lines.append(f"    G_dense[{gr} * SCPGEN_N + {gc}] += {sign}1.0;")
                else:
                    # per-node 循环
                    lines.append(f"    /* {mb.name}: shape=[{mb_rows},{mb_cols}], node='{node_tag}', var_block='{mb.variable_block}' */")
                    for ni in range(nc):
                        col_off = _compute_node_col_offset(col_start, mb_cols, node_tag, ni)
                        if is_identity:
                            # 对角 identity 块
                            for lr_var in range(min(mb_rows, mb_cols)):
                                gr = rr_start + ni * rpn + lr_var
                                lines.append(f"    G_dense[{gr} * SCPGEN_N + {col_off + lr_var}] += {sign}1.0;  /* node {ni} */")
                        else:
                            # 整块callback: 每次返回 shape_rows×shape_cols 个值
                            out_size = mb_rows * mb_cols
                            node_index = ni
                            lines.append(f"    {{ /* node {ni} */")
                            lines.append(f"        scpgen_float out_vals[{out_size}];")
                            lines.append(f"        int ret = scpgen_eval_matrix_block(")
                            lines.append(f'            "{arb.name}", "{mb.name}",')
                            lines.append(f"            0, {rr_start + ni * rpn}, {node_index},")
                            lines.append(f"            params, ref, out_vals, {out_size});")
                            lines.append(f"        if (ret != SCPGEN_SUCCESS) return ret;")
                            lines.append(f"        for (int lr = 0; lr < {mb_rows}; lr++) {{")
                            lines.append(f"            int gr = {rr_start} + {ni} * {rpn} + lr;")
                            lines.append(f"            for (int j = 0; j < {mb_cols}; j++) {{")
                            lines.append(f"                G_dense[gr * SCPGEN_N + {col_off} + j] += out_vals[lr * {mb_cols} + j];")
                            lines.append(f"            }}")
                            lines.append(f"        }}")
                            lines.append(f"    }}")
    else:
        lines.append("    /* 无线性能约束行块 */")

    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")
    lines.append("")


def _generate_fill_problem_dense_code(ir: Module6IR, lines: List[str]) -> None:
    """生成 scpgen_fill_problem_dense。"""
    lines.append("/* ==== 一站式 Dense 填充 ==== */")
    lines.append("int scpgen_fill_problem_dense(")
    lines.append("    scpgen_float* c,")
    lines.append("    scpgen_float* A_dense,")
    lines.append("    scpgen_float* b,")
    lines.append("    scpgen_float* G_dense,")
    lines.append("    scpgen_float* h,")
    lines.append("    const scpgen_params* params,")
    lines.append("    const scpgen_reference* ref")
    lines.append(") {")
    lines.append("    int ret;")
    lines.append("")
    lines.append("    ret = scpgen_zero_vectors(c, b, h);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    ret = scpgen_zero_dense_matrices(A_dense, G_dense);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    ret = scpgen_fill_c(c, params);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    ret = scpgen_fill_A_dense(A_dense, params, ref);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    ret = scpgen_fill_b(b, params, ref);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    ret = scpgen_fill_G_dense(G_dense, params, ref);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    has_soc = bool(ir.cones.soc_blocks)
    if has_soc:
        lines.append("")
        lines.append("    ret = scpgen_fill_soc_Gh(G_dense, h, params);")
        lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    ret = scpgen_fill_h(h, params, ref);")
    lines.append("    if (ret != SCPGEN_SUCCESS) return ret;")
    lines.append("")
    lines.append("    return SCPGEN_SUCCESS;")
    lines.append("}")


def _compute_node_col_offset(col_start: int, cols_per_node: int, node_tag: str, node_index: int) -> int:
    """根据 matrix_block.node 标签和 node_index 计算列偏移。

    - "k+1" → col_start + (node_index + 1) * cols_per_node
    - "scalar" → col_start (不偏移)
    - "k" 或空 → col_start + node_index * cols_per_node
    """
    if node_tag == "k+1":
        return col_start + (node_index + 1) * cols_per_node
    elif node_tag == "scalar":
        return col_start
    else:
        return col_start + node_index * cols_per_node


def _find_var_block(ir: Module6IR, name: str):
    """根据变量块名查找 VariableBlock。"""
    if not name:
        return None
    for vb in ir.variable_blocks:
        if vb.name == name:
            return vb
    return None


# ==== scpgen_callbacks.h ====

def generate_callbacks_h(ir: Module6IR) -> str:
    """生成 scpgen_callbacks.h"""
    lines = [
        _generate_header_guard_begin("SCPGEN_CALLBACKS_H"),
        "",
        '#include "scpgen_types.h"',
        '#include "scpgen_dims.h"',
        '#include "scpgen_problem.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN 数值回调接口 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " *",
        " * 这些回调函数负责计算矩阵块/RHS 中的具体数值。",
        " * 默认 stub 返回 SCPGEN_ERR_NOT_IMPLEMENTED。",
        " * 用户需要实现具体动力学/约束数值计算逻辑。",
        " * ================================================================ */",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "/* ==== 通用矩阵块求值回调 ==== */",
        "/**",
        " * 求值一个矩阵块的一行数值。",
        " *",
        " * @param row_block_name  行块名称 (如 \"dynamics_defect\", \"alpha_bounds\")",
        " * @param block_name      矩阵块名称 (如 \"C_xL\", \"C_uL\", \"+I_nx\")",
        " * @param local_row       行块内的局部行号",
        " * @param global_row      全局行号 (在 A/G 矩阵中)",
        " * @param node_index      离散节点索引",
        " * @param params          问题参数",
        " * @param ref             参考轨迹",
        " * @param out_values      输出数组 (长度 out_size)",
        " * @param out_size        输出数组长度",
        " * @return SCPGEN_SUCCESS 或错误码",
        " */",
        "int scpgen_eval_matrix_block(",
        '    const char* row_block_name,',
        '    const char* block_name,',
        "    scpgen_int local_row,",
        "    scpgen_int global_row,",
        "    scpgen_int node_index,",
        "    const scpgen_params* params,",
        "    const scpgen_reference* ref,",
        "    scpgen_float* out_values,",
        "    scpgen_int out_size",
        ");",
        "",
        "/* ==== RHS 求值回调 ==== */",
        "/**",
        " * 求值一个右端项。",
        " *",
        " * @param row_block_name  行块名称",
        " * @param rhs_block_name  RHS 块名称 (通常为 \"rhs\")",
        " * @param local_row       行块内的局部行号",
        " * @param global_row      全局行号",
        " * @param node_index      离散节点索引",
        " * @param params          问题参数",
        " * @param ref             参考轨迹",
        " * @param out_value       输出标量",
        " * @return SCPGEN_SUCCESS 或错误码",
        " */",
        "int scpgen_eval_rhs_block(",
        '    const char* row_block_name,',
        '    const char* rhs_block_name,',
        "    scpgen_int local_row,",
        "    scpgen_int global_row,",
        "    scpgen_int node_index,",
        "    const scpgen_params* params,",
        "    const scpgen_reference* ref,",
        "    scpgen_float* out_value",
        ");",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        _generate_header_guard_end("SCPGEN_CALLBACKS_H"),
        "",
    ]
    return "\n".join(lines)


# ==== scpgen_callbacks_stub.c ====

def generate_callbacks_stub_c(ir: Module6IR) -> str:
    """生成 scpgen_callbacks_stub.c"""
    lines = [
        '#include "scpgen_callbacks.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN 数值回调占位实现 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " *",
        " * 所有尚无公式的回调返回 SCPGEN_ERR_NOT_IMPLEMENTED。",
        " * 不填零后返回 success — 用户必须显式实现。",
        " * ================================================================ */",
        "",
        "int scpgen_eval_matrix_block(",
        '    const char* row_block_name,',
        '    const char* block_name,',
        "    scpgen_int local_row,",
        "    scpgen_int global_row,",
        "    scpgen_int node_index,",
        "    const scpgen_params* params,",
        "    const scpgen_reference* ref,",
        "    scpgen_float* out_values,",
        "    scpgen_int out_size",
        ") {",
        "    (void)row_block_name;",
        "    (void)block_name;",
        "    (void)local_row;",
        "    (void)global_row;",
        "    (void)node_index;",
        "    (void)params;",
        "    (void)ref;",
        "    (void)out_values;",
        "    (void)out_size;",
        "    return SCPGEN_ERR_NOT_IMPLEMENTED;",
        "}",
        "",
        "int scpgen_eval_rhs_block(",
        '    const char* row_block_name,',
        '    const char* rhs_block_name,',
        "    scpgen_int local_row,",
        "    scpgen_int global_row,",
        "    scpgen_int node_index,",
        "    const scpgen_params* params,",
        "    const scpgen_reference* ref,",
        "    scpgen_float* out_value",
        ") {",
        "    (void)row_block_name;",
        "    (void)rhs_block_name;",
        "    (void)local_row;",
        "    (void)global_row;",
        "    (void)node_index;",
        "    (void)params;",
        "    (void)ref;",
        "    (void)out_value;",
        "    return SCPGEN_ERR_NOT_IMPLEMENTED;",
        "}",
        "",
    ]
    return "\n".join(lines)


# ==== scpgen_ecos_setup.h ====

def generate_ecos_setup_h(ir: Module6IR) -> str:
    """生成 scpgen_ecos_setup.h"""
    lines = [
        _generate_header_guard_begin("SCPGEN_ECOS_SETUP_H"),
        "",
        '#include "scpgen_types.h"',
        '#include "scpgen_dims.h"',
        '#include "scpgen_problem.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN ECOS 求解器接口 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " *",
        " * 使用 SCPGEN_USE_ECOS 宏控制是否链接真正的 ECOS 库。",
        " * 默认不依赖 ECOS，可独立编译。",
        " * ================================================================ */",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "/* ==== ECOS 数据结构（前向声明） ==== */",
        "#ifdef SCPGEN_USE_ECOS",
        '  #include "ecos.h"',
        "  typedef pwork* scpgen_ecos_workptr;",
        "#else",
        "  typedef void* scpgen_ecos_workptr;",
        "#endif",
        "",
        "/* ==== ECOS 设置接口 ==== */",
        "scpgen_ecos_workptr scpgen_ecos_setup(",
        "    scpgen_int n,",
        "    scpgen_int m,",
        "    scpgen_int p,",
        "    scpgen_int l,",
        "    scpgen_int ncones,",
        "    scpgen_int* q,",
        "    scpgen_float* Gpr,",
        "    scpgen_int* Gjc,",
        "    scpgen_int* Gir,",
        "    scpgen_float* Apr,",
        "    scpgen_int* Ajc,",
        "    scpgen_int* Air,",
        "    scpgen_float* c,",
        "    scpgen_float* h,",
        "    scpgen_float* b",
        ");",
        "",
        "int scpgen_ecos_solve(scpgen_ecos_workptr work);",
        "",
        "void scpgen_ecos_cleanup(scpgen_ecos_workptr work);",
        "",
        "/* ==== 一站式 Setup（Dense → CSC → ECOS） ==== */",
        "#ifdef SCPGEN_USE_ECOS",
        "/**",
        " * 一站式问题数据容器。",
        " * 持有所有分配的数组和 ECOS work 指针，cleanup 时统一释放。",
        " */",
        "typedef struct scpgen_ecos_problem_data {",
        "    scpgen_float* c;",
        "    scpgen_float* b;",
        "    scpgen_float* h;",
        "    scpgen_int* Ajc;",
        "    scpgen_int* Air;",
        "    scpgen_float* Apr;",
        "    scpgen_int* Gjc;",
        "    scpgen_int* Gir;",
        "    scpgen_float* Gpr;",
        "    scpgen_ecos_workptr work;",
        "} scpgen_ecos_problem_data;",
        "",
        "/**",
        " * 从 params/ref 一站式构建 ECOS 问题。",
        " * 内部: fill_problem_dense → compress_A → compress_G → ECOS_setup",
        " * 返回 scpgen_ecos_problem_data（需 scpgen_ecos_cleanup_problem 释放）。",
        " */",
        "scpgen_ecos_problem_data* scpgen_ecos_setup_from_problem(",
        "    const scpgen_params* params,",
        "    const scpgen_reference* ref,",
        "    scpgen_float zero_tol",
        ");",
        "",
        "/**",
        " * 释放一站式构建的所有资源。",
        " */",
        "void scpgen_ecos_cleanup_problem(scpgen_ecos_problem_data* data);",
        "#endif",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        _generate_header_guard_end("SCPGEN_ECOS_SETUP_H"),
        "",
    ]

    return "\n".join(lines)


# ==== scpgen_ecos_setup.c ====

def generate_ecos_setup_c(ir: Module6IR) -> str:
    """生成 scpgen_ecos_setup.c"""
    lines = [
        '#include "scpgen_ecos_setup.h"',
        '#include "scpgen_types.h"',
        '#include "scpgen_fill.h"',
        '#include "scpgen_csc.h"',
        '#include <stddef.h>',
        '#include <stdlib.h>',
        "",
        "/* ================================================================",
        f" * SCPGEN ECOS 求解器接口实现 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
        "#ifdef SCPGEN_USE_ECOS",
        "",
        "scpgen_ecos_workptr scpgen_ecos_setup(",
        "    scpgen_int n, scpgen_int m, scpgen_int p, scpgen_int l, scpgen_int ncones, scpgen_int* q,",
        "    scpgen_float* Gpr, scpgen_int* Gjc, scpgen_int* Gir,",
        "    scpgen_float* Apr, scpgen_int* Ajc, scpgen_int* Air,",
        "    scpgen_float* c, scpgen_float* h, scpgen_float* b",
        ") {",
        "    return (scpgen_ecos_workptr)ECOS_setup(n, m, p, l, ncones, q,",
        "                                             Gpr, Gjc, Gir,",
        "                                             Apr, Ajc, Air,",
        "                                             c, h, b);",
        "}",
        "",
        "int scpgen_ecos_solve(scpgen_ecos_workptr work) {",
        "    if (!work) return -1;",
        "    return ECOS_solve((pwork*)work);",
        "}",
        "",
        "void scpgen_ecos_cleanup(scpgen_ecos_workptr work) {",
        "    if (work) ECOS_cleanup((pwork*)work, 0);",
        "}",
        "",
        "/* ==== 一站式 Setup（Dense → CSC → ECOS） ==== */",
        "scpgen_ecos_problem_data* scpgen_ecos_setup_from_problem(",
        "    const scpgen_params* params,",
        "    const scpgen_reference* ref,",
        "    scpgen_float zero_tol",
        ") {",
        "    if (!params || !ref) return NULL;",
        "",
        "    int ret;",
        "    scpgen_int nnz;",
        "",
        "    /* 分配 data 容器 */",
        "    scpgen_ecos_problem_data* data = (scpgen_ecos_problem_data*)malloc(sizeof(scpgen_ecos_problem_data));",
        "    if (!data) return NULL;",
        "    memset(data, 0, sizeof(scpgen_ecos_problem_data));",
        "",
        "    /* 分配 dense 数组 */",
        f"    data->c   = (scpgen_float*)malloc(SCPGEN_N * sizeof(scpgen_float));",
        f"    data->b   = (scpgen_float*)malloc(SCPGEN_P * sizeof(scpgen_float));",
        f"    data->h   = (scpgen_float*)malloc(SCPGEN_M * sizeof(scpgen_float));",
        f"    scpgen_float* A_d = (scpgen_float*)malloc(SCPGEN_A_DENSE_SIZE * sizeof(scpgen_float));",
        f"    scpgen_float* G_d = (scpgen_float*)malloc(SCPGEN_G_DENSE_SIZE * sizeof(scpgen_float));",
        "    if (!data->c || !data->b || !data->h || !A_d || !G_d) {",
        "        scpgen_ecos_cleanup_problem(data);",
        "        free(A_d); free(G_d);",
        "        return NULL;",
        "    }",
        "",
        "    /* 填充 dense 问题 */",
        "    ret = scpgen_fill_problem_dense(data->c, A_d, data->b, G_d, data->h, params, ref);",
        "    if (ret != SCPGEN_SUCCESS) {",
        "        scpgen_ecos_cleanup_problem(data);",
        "        free(A_d); free(G_d);",
        "        return NULL;",
        "    }",
        "",
        "    /* 压缩为 CSC */",
        "    ret = scpgen_compress_A_dense_to_csc(A_d, zero_tol, &data->Ajc, &data->Air, &data->Apr, &nnz);",
        "    if (ret != SCPGEN_SUCCESS) {",
        "        scpgen_ecos_cleanup_problem(data);",
        "        free(A_d); free(G_d);",
        "        return NULL;",
        "    }",
        "",
        "    ret = scpgen_compress_G_dense_to_csc(G_d, zero_tol, &data->Gjc, &data->Gir, &data->Gpr, &nnz);",
        "    if (ret != SCPGEN_SUCCESS) {",
        "        scpgen_ecos_cleanup_problem(data);",
        "        free(A_d); free(G_d);",
        "        return NULL;",
        "    }",
        "",
        "    /* 释放 dense 数组 */",
        "    free(A_d); free(G_d);",
        "",
        "    /* ECOS setup (标准顺序: Gpr,Gjc,Gir, Apr,Ajc,Air) */",
        "    data->work = scpgen_ecos_setup(",
        "        SCPGEN_N, SCPGEN_M, SCPGEN_P, SCPGEN_L, SCPGEN_NUM_SOC,",
        "        (scpgen_int*)SCPGEN_Q,",
        "        data->Gpr, data->Gjc, data->Gir,",
        "        data->Apr, data->Ajc, data->Air,",
        "        data->c, data->h, data->b);",
        "",
        "    if (!data->work) {",
        "        scpgen_ecos_cleanup_problem(data);",
        "        return NULL;",
        "    }",
        "",
        "    /* 注意: c/b/h 和 CSC 数组由 data 持有，调用 scpgen_ecos_cleanup_problem 统一释放 */",
        "    return data;",
        "}",
        "",
        "void scpgen_ecos_cleanup_problem(scpgen_ecos_problem_data* data) {",
        "    if (!data) return;",
        "    if (data->work) ECOS_cleanup((pwork*)data->work, 0);",
        "    free(data->c); free(data->b); free(data->h);",
        "    scpgen_free_csc(data->Ajc, data->Air, data->Apr);",
        "    scpgen_free_csc(data->Gjc, data->Gir, data->Gpr);",
        "    free(data);",
        "}",
        "",
        "#else /* !SCPGEN_USE_ECOS */",
        "",
        "scpgen_ecos_workptr scpgen_ecos_setup(",
        "    scpgen_int n, scpgen_int m, scpgen_int p, scpgen_int l, scpgen_int ncones, scpgen_int* q,",
        "    scpgen_float* Gpr, scpgen_int* Gjc, scpgen_int* Gir,",
        "    scpgen_float* Apr, scpgen_int* Ajc, scpgen_int* Air,",
        "    scpgen_float* c, scpgen_float* h, scpgen_float* b",
        ") {",
        "    (void)n; (void)m; (void)p; (void)l; (void)ncones; (void)q;",
        "    (void)Gpr; (void)Gjc; (void)Gir;",
        "    (void)Apr; (void)Ajc; (void)Air;",
        "    (void)c; (void)h; (void)b;",
        "    return NULL;",
        "}",
        "",
        "int scpgen_ecos_solve(scpgen_ecos_workptr work) {",
        "    (void)work;",
        "    return -1;",
        "}",
        "",
        "void scpgen_ecos_cleanup(scpgen_ecos_workptr work) {",
        "    (void)work;",
        "}",
        "",
        "#endif /* SCPGEN_USE_ECOS */",
        "",
    ]

    return "\n".join(lines)


# ==== scpgen_csc.h ====

def generate_csc_h(ir: Module6IR) -> str:
    """生成 scpgen_csc.h"""
    lines = [
        _generate_header_guard_begin("SCPGEN_CSC_H"),
        "",
        '#include "scpgen_types.h"',
        '#include "scpgen_dims.h"',
        "",
        "/* ================================================================",
        f" * SCPGEN Dense-to-CSC 压缩工具 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " *",
        " * 将 dense (row-major) 矩阵转换为 ECOS 所需的 CSC 格式。",
        " * 内部 malloc jc/ir/pr，调用方负责通过 scpgen_free_csc 释放。",
        " * ================================================================ */",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "/* ==== 通用 Dense-to-CSC ==== */",
        "int scpgen_dense_to_csc(",
        "    const scpgen_float* dense,",
        "    scpgen_int rows,",
        "    scpgen_int cols,",
        "    scpgen_float zero_tol,",
        "    scpgen_int** jc,",
        "    scpgen_int** ir,",
        "    scpgen_float** pr,",
        "    scpgen_int* out_nnz",
        ");",
        "",
        "void scpgen_free_csc(scpgen_int* jc, scpgen_int* ir, scpgen_float* pr);",
        "",
        "int scpgen_compress_A_dense_to_csc(",
        "    const scpgen_float* A_dense,",
        "    scpgen_float zero_tol,",
        "    scpgen_int** Ajc,",
        "    scpgen_int** Air,",
        "    scpgen_float** Apr,",
        "    scpgen_int* out_nnz",
        ");",
        "",
        "int scpgen_compress_G_dense_to_csc(",
        "    const scpgen_float* G_dense,",
        "    scpgen_float zero_tol,",
        "    scpgen_int** Gjc,",
        "    scpgen_int** Gir,",
        "    scpgen_float** Gpr,",
        "    scpgen_int* out_nnz",
        ");",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        _generate_header_guard_end("SCPGEN_CSC_H"),
        "",
    ]
    return "\n".join(lines)


# ==== scpgen_csc.c ====

def generate_csc_c(ir: Module6IR) -> str:
    """生成 scpgen_csc.c"""
    lines = [
        '#include "scpgen_csc.h"',
        '#include <stdlib.h>',
        '#include <math.h>',
        "",
        "/* ================================================================",
        f" * SCPGEN Dense-to-CSC 压缩实现 — {ir.problem_name}",
        " * 由 Module6 自动生成，请勿手动修改",
        " * ================================================================ */",
        "",
        "int scpgen_dense_to_csc(",
        "    const scpgen_float* dense,",
        "    scpgen_int rows,",
        "    scpgen_int cols,",
        "    scpgen_float zero_tol,",
        "    scpgen_int** jc,",
        "    scpgen_int** ir,",
        "    scpgen_float** pr,",
        "    scpgen_int* out_nnz",
        ") {",
        "    if (!dense || !jc || !ir || !pr || !out_nnz) {",
        "        return SCPGEN_ERR_INVALID_ARGUMENT;",
        "    }",
        "    if (rows <= 0 || cols <= 0) {",
        "        return SCPGEN_ERR_INVALID_ARGUMENT;",
        "    }",
        "",
        "    scpgen_float tol = (zero_tol < 0.0) ? 0.0 : zero_tol;",
        "",
        "    /* 第一遍: 统计每列非零数 */",
        "    scpgen_int* col_nnz = (scpgen_int*)calloc((size_t)cols, sizeof(scpgen_int));",
        "    if (!col_nnz) return SCPGEN_ERR_BUFFER_TOO_SMALL;",
        "    scpgen_int total_nnz = 0;",
        "    for (scpgen_int c = 0; c < cols; c++) {",
        "        for (scpgen_int r = 0; r < rows; r++) {",
        "            if (fabs(dense[r * cols + c]) > tol) {",
        "                col_nnz[c]++;",
        "                total_nnz++;",
        "            }",
        "        }",
        "    }",
        "",
        "    /* 分配 CSC 数组 */",
        "    *jc = (scpgen_int*)malloc(((size_t)cols + 1) * sizeof(scpgen_int));",
        "    *ir = (scpgen_int*)malloc((size_t)total_nnz * sizeof(scpgen_int));",
        "    *pr = (scpgen_float*)malloc((size_t)total_nnz * sizeof(scpgen_float));",
        "    if (!*jc || !*ir || !*pr) {",
        "        free(col_nnz);",
        "        free(*jc); free(*ir); free(*pr);",
        "        *jc = NULL; *ir = NULL; *pr = NULL;",
        "        return SCPGEN_ERR_BUFFER_TOO_SMALL;",
        "    }",
        "",
        "    /* 第二遍: 构建 jc 并填充 ir/pr */",
        "    scpgen_int nnz = 0;",
        "    for (scpgen_int c = 0; c < cols; c++) {",
        "        (*jc)[c] = nnz;",
        "        for (scpgen_int r = 0; r < rows; r++) {",
        "            scpgen_float val = dense[r * cols + c];",
        "            if (fabs(val) > tol) {",
        "                (*ir)[nnz] = r;",
        "                (*pr)[nnz] = val;",
        "                nnz++;",
        "            }",
        "        }",
        "    }",
        "    (*jc)[cols] = nnz;",
        "    *out_nnz = nnz;",
        "    free(col_nnz);",
        "    return SCPGEN_SUCCESS;",
        "}",
        "",
        "void scpgen_free_csc(scpgen_int* jc, scpgen_int* ir, scpgen_float* pr) {",
        "    free(jc); free(ir); free(pr);",
        "}",
        "",
        "int scpgen_compress_A_dense_to_csc(",
        "    const scpgen_float* A_dense,",
        "    scpgen_float zero_tol,",
        "    scpgen_int** Ajc,",
        "    scpgen_int** Air,",
        "    scpgen_float** Apr,",
        "    scpgen_int* out_nnz",
        ") {",
        "    return scpgen_dense_to_csc(A_dense, SCPGEN_P, SCPGEN_N, zero_tol,",
        "                                Ajc, Air, Apr, out_nnz);",
        "}",
        "",
        "int scpgen_compress_G_dense_to_csc(",
        "    const scpgen_float* G_dense,",
        "    scpgen_float zero_tol,",
        "    scpgen_int** Gjc,",
        "    scpgen_int** Gir,",
        "    scpgen_float** Gpr,",
        "    scpgen_int* out_nnz",
        ") {",
        "    return scpgen_dense_to_csc(G_dense, SCPGEN_M, SCPGEN_N, zero_tol,",
        "                                Gjc, Gir, Gpr, out_nnz);",
        "}",
        "",
    ]
    return "\n".join(lines)


# ==== README.md (generated) ====

def generate_readme(ir: Module6IR) -> str:
    """生成 generated_c/README.md"""
    lines = [
        f"# SCPGEN Generated C Code — {ir.problem_name}",
        "",
        "由 SCPGEN Module6 (C Code Generator) 自动生成。",
        "",
        "## 当前方案: Dense-First",
        "",
        "Module6 v2 采用 dense-first 方案:",
        "1. 先填充 dense A/G/c/b/h (row-major)",
        "2. 通过 dense_to_csc 压缩为 ECOS CSC 格式",
        "3. 后续版本可利用 Module5 已知非零结构生成固定 CSC pattern",
        "",
        "## 生成文件说明",
        "",
        "| 文件 | 说明 |",
        "|------|------|",
        "| `scpgen_types.h` | 类型定义 (scpgen_float, scpgen_int, 错误码) |",
        "| `scpgen_dims.h` | ECOS 维度宏 + DIM_Z/DIM_Y + DENSE_SIZE |",
        "| `scpgen_indices.h` | 变量列索引、行范围宏 (END_EXCL 半开区间) |",
        "| `scpgen_problem.h` | 问题数据结构 (params, reference) |",
        "| `scpgen_problem.c` | Q 数组定义, 问题初始化 |",
        "| `scpgen_fill.h` | Dense 填充接口声明 (全部返回 int 错误码) |",
        "| `scpgen_fill.c` | Dense 填充实现 (c/A/G/b/h + SOC G/h + 一站式) |",
        "| `scpgen_callbacks.h` | 数值回调接口 (matrix_block + rhs_block) |",
        "| `scpgen_callbacks_stub.c` | 回调占位 (返回 SCPGEN_ERR_NOT_IMPLEMENTED) |",
        "| `scpgen_csc.h` | Dense-to-CSC 压缩接口 |",
        "| `scpgen_csc.c` | Dense-to-CSC 压缩实现 (两遍扫描, 内部 malloc) |",
        "| `scpgen_ecos_setup.h` | ECOS 求解器接口 (需 SCPGEN_USE_ECOS) |",
        "| `scpgen_ecos_setup.c` | ECOS 求解器接口实现 |",
        "",
        "## 维度信息",
        "",
        f"- **ECOS**: n={ir.dims.n}, p={ir.dims.p}, m={ir.dims.m}, l={ir.dims.l}, q={ir.dims.q}",
        f"- **原始变量维度 (DIM_Z)**: {ir.dim_z}",
        f"- **ECOS 扩展维度 (DIM_Y)**: {ir.dim_y}",
        f"- **Dense A 大小**: {ir.A_dense_size} (= p * n)",
        f"- **Dense G 大小**: {ir.G_dense_size} (= m * n)",
        "",
        "## 使用方式",
        "",
        "### 1. 推荐: CMake 编译",
        "```bash",
        "mkdir -p build",
        "cmake -S . -B build",
        "cmake --build build",
        "```",
        "",
        "### 2. 或: 手动编译 (所有产物在 build/ 目录)",
        "```bash",
        "mkdir -p build/obj",
        "gcc -c -Wall -Werror -std=c99 scpgen_problem.c -o build/obj/scpgen_problem.o",
        "gcc -c -Wall -Werror -std=c99 scpgen_fill.c -o build/obj/scpgen_fill.o",
        "gcc -c -Wall -Werror -std=c99 scpgen_callbacks_stub.c -o build/obj/scpgen_callbacks_stub.o",
        "gcc -c -Wall -Werror -std=c99 scpgen_csc.c -o build/obj/scpgen_csc.o",
        "gcc -c -Wall -Werror -std=c99 scpgen_ecos_setup.c -o build/obj/scpgen_ecos_setup.o",
        "```",
        "",
        "### 3. 实现 callback 并运行",
        "用户需要实现 `scpgen_eval_matrix_block` 和 `scpgen_eval_rhs_block`。",
        "默认 stub 返回 SCPGEN_ERR_NOT_IMPLEMENTED。",
        "",
        "### 4. 链接 ECOS",
        "```bash",
        "gcc -DSCPGEN_USE_ECOS build/obj/*.o your_callbacks.c -lecos -lm",
        "```",
        "",
        "## Callback 接口",
        "",
        "- `scpgen_eval_matrix_block(row_block_name, block_name, ...)` — 按行求值矩阵块",
        "- `scpgen_eval_rhs_block(row_block_name, rhs_block_name, ...)` — 求值右端项",
        "",
        "## 注意",
        "",
        "C_x、C_u、rhs 等数值块由 callback 提供，不伪造动力学/约束公式。",
        "dense 矩阵统一 row-major: `A_dense[row * SCPGEN_N + col]`。",
        "",
    ]

    return "\n".join(lines)


# ==== CMakeLists.txt ====

def generate_cmake(ir: Module6IR) -> str:
    """生成 CMakeLists.txt"""
    lines = [
        "cmake_minimum_required(VERSION 3.10)",
        f"project(scpgen_{ir.problem_name} C)",
        "",
        "# SCPGEN Generated C Code",
        "# 由 Module6 自动生成",
        "",
        "set(CMAKE_C_STANDARD 99)",
        "",
        "add_library(scpgen_generated STATIC",
        "    scpgen_problem.c",
        "    scpgen_fill.c",
        "    scpgen_callbacks_stub.c",
        "    scpgen_csc.c",
        "    scpgen_ecos_setup.c",
        ")",
        "",
        "target_include_directories(scpgen_generated PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})",
        "",
        "# 可选: 启用 ECOS 支持",
        "# target_compile_definitions(scpgen_generated PUBLIC SCPGEN_USE_ECOS)",
        "# target_link_libraries(scpgen_generated ecos m)",
        "",
    ]

    return "\n".join(lines)
