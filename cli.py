"""
scpgen CLI — Stage 1: Original YAML → Subproblem YAML Compiler.

Usage:
    scpgen compile              <original.yaml> [-o output_dir]
    scpgen validate-original    <original.yaml>
    scpgen validate-subproblem  <subproblem.yaml>
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import yaml

from .original_parser import parse_original_problem
from .subproblem_compiler import SubproblemCompiler
from .subproblem_models import subproblem_to_dict, subproblem_from_dict, SubProblemDef
from .subproblem_validator import validate_subproblem


def _compute_source_hash(filepath: str) -> str:
    """Compute SHA256 hash of the source file for provenance tracking."""
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def cmd_compile(args):
    """
    Stage 1: Compile original YAML → subproblem.yaml.
    Produces the intermediate subproblem description and a validation report.
    """
    print(f"Stage 1: Compiling '{args.input}' → subproblem.yaml ...")
    problem = parse_original_problem(args.input)

    # Validate grid constraints (control_grid must be node for now)
    if problem.grid.control_grid != "node":
        print(f"ERROR: control_grid='{problem.grid.control_grid}' not yet supported.")
        print("  Currently only control_grid='node' is supported.")
        sys.exit(1)

    compiler = SubproblemCompiler(problem)
    subproblem = compiler.compile()

    # Set provenance: POSIX relative path + source hash
    source_hash = _compute_source_hash(args.input)
    try:
        rel_path = Path(args.input).resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        # Input file is not under cwd; use absolute POSIX path
        rel_path = Path(args.input).resolve().as_posix()
    subproblem.meta.generated_from = f"{rel_path}#sha256={source_hash}"

    # Validate subproblem (with scale reference info for deep validation)
    # Collect extra variables from operation effects (time_effects is deprecated)
    extra_vars_from_effects = []
    for op in problem.transcription.operations:
        if op.effects:
            for iv in op.effects.introduces_variables:
                extra_vars_from_effects.append((iv.name, iv.scale))
    original_scales = {
        "extra_variables": extra_vars_from_effects,
        "parameters": dict(problem.model.parameters),
        "expressions": [
            {"name": e.name, "expr": e.expr}
            for e in problem.model.expressions
        ],
    }
    report = validate_subproblem(subproblem, original_scales)

    out_dir = args.output or "output"
    os.makedirs(out_dir, exist_ok=True)

    # Write subproblem.yaml
    sp_dict = subproblem_to_dict(subproblem)
    sp_path = os.path.join(out_dir, f"{problem.meta.name}_subproblem.yaml")
    with open(sp_path, "w", encoding="utf-8") as f:
        yaml.dump(sp_dict, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False, indent=2, width=120)

    # Write validation report
    report_path = os.path.join(out_dir, "subproblem_validation_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown(subproblem.meta.name))

    print(f"  -> {sp_path}")
    print(f"  -> {report_path}")
    print(f"  Validation: {'ALL PASSED' if report.all_passed else f'{report.failed_count} FAILED'}")

    if not report.all_passed:
        sys.exit(1)


def cmd_validate_original(args):
    """Validate an original problem YAML file structure and references."""
    try:
        problem = parse_original_problem(args.input)
        print(f"Valid problem: '{problem.meta.name}'")
        print(f"  States:      {problem.n_states} ({', '.join(problem.model.variables.state_names)})")
        print(f"  Controls:    {problem.n_controls} ({', '.join(problem.model.variables.control_names)})")
        print(f"  Nodes (N):  {problem.N}")
        print(f"  Dynamics:    {len(problem.model.dynamics)} equations")
        print(f"  Eq cons:     {len(problem.model.equalities)}")
        print(f"  Ineq cons:   {len(problem.model.inequalities)}")
        print(f"  Operations:  {len(problem.transcription.operations)}")
        print(f"  Expressions: {len(problem.model.expressions)}")
    except Exception as e:
        print(f"Validation failed: {e}")
        sys.exit(1)


def cmd_validate_subproblem(args):
    """Validate a generated subproblem YAML file — runs the full 15-check validator."""
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            sp_dict = yaml.safe_load(f)

        # Full deserialization: reconstruct SubProblemDef from all YAML sections
        sp = subproblem_from_dict(sp_dict)

        # Run the complete 15-check validator
        report = validate_subproblem(sp)

        # Print summary
        print(f"Subproblem: '{sp.meta.name}'")
        print(f"  Generated from: {sp.meta.generated_from}")
        print(f"  Dimensions: nvar={sp.dimensions.nvar}, neq={sp.dimensions.neq}, nineq={sp.dimensions.nineq}")
        print(f"  Variables: {sp.dimensions.n_states} states + {sp.dimensions.n_controls} controls")
        print(f"  Extra vars: {sp.dimensions.n_extra_variables}")
        print(f"  A blocks: {len(sp.equalities.blocks)}, G blocks: {len(sp.inequalities.blocks)}")
        print(f"  Objective terms: {len(sp.objective.terms)}")
        print()

        # Print full Markdown validation report
        print(report.to_markdown(sp.meta.name))

        if not report.all_passed:
            print(f"\n❌ VALIDATION FAILED — {report.failed_count} check(s) failed.")
            sys.exit(1)
        else:
            print(f"\n✅ ALL {len(report.checks)} CHECKS PASSED")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="scpgen Stage 1: Original YAML -> Subproblem YAML compiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scpgen compile examples/gliding.yaml -o output/
  python -m scpgen validate-original examples/gliding.yaml
  python -m scpgen validate-subproblem output/gliding_3dof_subproblem.yaml
        """
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # compile
    p_comp = sub.add_parser(
        "compile",
        help="Compile original YAML to subproblem.yaml (Stage 1)"
    )
    p_comp.add_argument("input", help="Original problem description YAML file")
    p_comp.add_argument("-o", "--output", default="output",
                        help="Output directory (default: output)")
    p_comp.set_defaults(func=cmd_compile)

    # validate-original
    p_val_orig = sub.add_parser(
        "validate-original",
        help="Validate an original problem YAML file"
    )
    p_val_orig.add_argument("input", help="Original problem description YAML file")
    p_val_orig.set_defaults(func=cmd_validate_original)

    # validate-subproblem
    p_val_sp = sub.add_parser(
        "validate-subproblem",
        help="Validate a generated subproblem YAML file"
    )
    p_val_sp.add_argument("input", help="Subproblem YAML file")
    p_val_sp.set_defaults(func=cmd_validate_subproblem)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
