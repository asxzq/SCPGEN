"""
JSON Schema definitions for Stage 1 unified YAML problem description.

Stage 1 schemas:
  - UNIFIED_ORIGINAL_SCHEMA: validates original problem YAML (meta + grid + scale + model + transcription)
  - SUBPROBLEM_SCHEMA: validates compiled subproblem YAML (output of Stage 1)

LEGACY schemas (pre-Stage1 MODEL_SCHEMA / TRANSCRIPTION_SCHEMA) have been
moved to scpgen.legacy_schema.
"""

# ── CURRENT (Stage1): UNIFIED ORIGINAL PROBLEM SCHEMA ──────────────────────

UNIFIED_ORIGINAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["meta", "grid", "model", "transcription"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
                "macro_prefix": {"type": "string"},
                "function_prefix": {"type": "string"},
                "scalar_type": {"type": "string"},
                "index_type": {"type": "string"},
            }
        },
        "grid": {
            "type": "object",
            "required": ["N"],
            "properties": {
                "N": {"type": "integer", "minimum": 2},
                "state_grid": {"type": "string", "enum": ["node", "interval"]},
                "control_grid": {"type": "string", "enum": ["node", "interval"]},
                "time": {
                    "type": "object",
                    "required": ["interval_mode"],
                    "properties": {
                        "interval_mode": {
                            "type": "string",
                            "enum": ["fixed_interval", "optimizable_uniform_interval"]
                        },
                        "interval_symbol": {"type": "string"},
                        "reference_interval_symbol": {"type": "string"},
                        "perturbation_symbol": {"type": "string"},
                        "total_time": {"type": "string"},
                        "bounds": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2, "maxItems": 2
                        },
                    }
                }
            }
        },
        "scale": {
            "type": "object",
            "description": "Scale definitions: base (name→numeric) + derived (name→expression string)",
            "properties": {
                "base": {
                    "type": "object",
                    "description": "Base scale: dimension_name → {value: number, unit: string} or number",
                    "additionalProperties": {
                        "oneOf": [
                            {"type": "number"},
                            {"type": "object", "properties": {
                                "value": {"type": "number"},
                                "unit": {"type": "string"}
                            }}
                        ]
                    }
                },
                "derived": {
                    "type": "object",
                    "description": "Derived scale: dimension_name → expression string",
                    "additionalProperties": {"type": "string"}
                }
            }
        },
        "model": {
            "type": "object",
            "required": ["variables"],
            "properties": {
                "variables": {
                    "type": "object",
                    "properties": {
                        "states": {
                            "type": "object",
                            "description": "state_name → scale_name",
                            "additionalProperties": {"type": "string"}
                        },
                        "controls": {
                            "type": "object",
                            "description": "control_name → scale_name",
                            "additionalProperties": {"type": "string"}
                        },
                    }
                },
                "parameters": {
                    "type": "object",
                    "description": "parameter_name → scale_name",
                    "additionalProperties": {"type": "string"}
                },
                "expressions": {"type": ["array", "object"]},
                "dynamics": {"type": ["array", "object"]},
                "equalities": {"type": ["array", "object"]},
                "inequalities": {"type": ["array", "object"]},
                "objective": {"type": ["array", "object"]},
            }
        },
        "transcription": {
            "type": "object",
            "required": ["discretization_mode", "operations"],
            "properties": {
                "discretization_mode": {
                    "type": "string",
                    "enum": ["perturbation", "direct"]
                },
                "time": {"type": "object"},
                "operations": {"type": "array", "minItems": 1},
            }
        },
        "codegen": {"type": "object"},
    }
}


# ── SUBPROBLEM SCHEMA ───────────────────────────────────────────────────────

SUBPROBLEM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["meta", "dimensions", "scale_table", "variables", "parameters",
                 "expressions", "dynamics", "time",
                 "equalities", "inequalities", "objective", "validation"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["name", "version", "generated_from", "discretization_mode"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
                "generated_from": {"type": "string"},
                "discretization_mode": {
                    "type": "string",
                    "enum": ["perturbation", "direct"]
                },
            }
        },
        "dimensions": {
            "type": "object",
            "required": [
                "N", "n_nodes", "final_node", "n_states", "n_controls",
                "vars_per_node", "n_node_variables", "n_extra_variables",
                "nvar", "neq", "nineq", "objective_terms"
            ],
            "properties": {
                "N": {"type": "integer"},
                "n_nodes": {"type": "integer"},
                "final_node": {"type": "integer"},
                "n_states": {"type": "integer"},
                "n_controls": {"type": "integer"},
                "vars_per_node": {"type": "integer"},
                "n_node_variables": {"type": "integer"},
                "n_extra_variables": {"type": "integer"},
                "nvar": {"type": "integer"},
                "neq": {"type": "integer"},
                "nineq": {"type": "integer"},
                "objective_terms": {"type": "integer"},
            }
        },
        "scale_table": {"type": "object"},
        "variables": {
            "type": "object",
            "required": ["node_order", "node_variables", "extra_variables"],
            "properties": {
                "node_order": {
                    "type": "object",
                    "properties": {
                        "states": {"type": "array", "items": {"type": "string"}},
                        "controls": {"type": "array", "items": {"type": "string"}},
                    }
                },
                "node_variables": {"type": "array"},
                "extra_variables": {"type": "array"},
            }
        },
        "parameters": {"type": "object"},
        "expressions": {"type": "array"},
        "dynamics": {"type": "array"},
        "time": {
            "type": "object",
            "required": ["interval_mode", "interval_symbol"],
            "properties": {
                "interval_mode": {"type": "string"},
                "interval_symbol": {"type": "string"},
                "reference_interval_symbol": {"type": "string"},
                "perturbation_variable": {"type": ["string", "null"]},
                "perturbed_interval_expr": {"type": ["string", "null"]},
                "total_time_expr": {"type": "string"},
                "bounds": {"type": "array", "items": {"type": "string"}},
            }
        },
        "equalities": {
            "type": "object",
            "required": ["total_rows", "blocks"],
            "properties": {
                "total_rows": {"type": "integer"},
                "blocks": {"type": "array"},
            }
        },
        "inequalities": {
            "type": "object",
            "required": ["total_rows", "blocks"],
            "properties": {
                "total_rows": {"type": "integer"},
                "blocks": {"type": "array"},
            }
        },
        "objective": {
            "type": "object",
            "required": ["terms"],
            "properties": {
                "terms": {"type": "array"},
            }
        },
        "validation": {
            "type": "object",
            "required": ["row_convention", "required_checks"],
            "properties": {
                "row_convention": {"type": "object"},
                "required_checks": {"type": "array", "items": {"type": "string"}},
            }
        },
    }
}
