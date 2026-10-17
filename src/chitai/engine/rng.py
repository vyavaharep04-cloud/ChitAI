"""Seeded, purpose-separated random streams (§3A.7, §5A).

Each stream is derived deterministically from the master seed, a purpose label,
and optional integer indices, using SHA-256 (never Python's built-in `hash()`,
which varies between runs). Streams are independent: drawing from one purpose
(for example timeouts) can never change another (for example deals).
"""

from __future__ import annotations

import hashlib
import random

DEAL = "deal"


def derive_seed(master_seed: int, purpose: str, *indices: int) -> int:
    """Deterministic 64-bit seed for (master_seed, purpose, indices)."""
    key = ":".join([str(master_seed), purpose, *(str(i) for i in indices)])
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def make_rng(master_seed: int, purpose: str, *indices: int) -> random.Random:
    """A fresh `random.Random` for the given purpose and indices."""
    return random.Random(derive_seed(master_seed, purpose, *indices))
