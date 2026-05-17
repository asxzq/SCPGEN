"""
Processing operations for the transcription layer.

Each operation type (dynamics_linearize, box_constraints, etc.)
is implemented as a ProcessingOp subclass. New types can be registered
via the @register_op decorator for extensibility.
"""

from .base import ProcessingOp, register_op, get_op_registry

# Import all operation modules to trigger @register_op decorators
from . import dynamics
from . import constraints
from . import soc
from . import virtual_control

__all__ = ["ProcessingOp", "register_op", "get_op_registry"]
