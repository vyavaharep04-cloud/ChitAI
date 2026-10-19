"""Batch runs of seeded AI-only games, with files (M8 Stage 5).

Sits above `simulation` and `eventlog`; it is the only place that creates run directories.
"""

from .cli import main
from .manifest import MANIFEST_NAME, MANIFEST_SCHEMA_VERSION
from .runner import BatchError, effective_config, run_batch

__all__ = ["MANIFEST_NAME", "MANIFEST_SCHEMA_VERSION", "BatchError", "effective_config", "main", "run_batch"]
