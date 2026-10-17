import subprocess
import sys

from chitai.engine import derive_seed, make_rng


def test_same_inputs_same_seed():
    assert derive_seed(1, "deal", 0, 1) == derive_seed(1, "deal", 0, 1)


def test_different_inputs_different_seeds():
    base = derive_seed(1, "deal", 0, 1)
    assert derive_seed(2, "deal", 0, 1) != base
    assert derive_seed(1, "timeout", 0, 1) != base
    assert derive_seed(1, "deal", 1, 1) != base
    assert derive_seed(1, "deal", 0, 2) != base


def test_streams_reproducible():
    a = make_rng(7, "deal", 0, 1)
    b = make_rng(7, "deal", 0, 1)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_purpose_streams_are_independent():
    deal_first = make_rng(7, "deal", 0, 1).random()
    other = make_rng(7, "timeout", 0, 1)
    for _ in range(100):
        other.random()  # consuming another purpose must not matter
    assert make_rng(7, "deal", 0, 1).random() == deal_first


def test_derivation_is_stable_across_processes():
    # Guards against accidental use of the per-process-randomized built-in hash().
    code = "from chitai.engine import derive_seed; print(derive_seed(42, 'deal', 3, 1))"
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": str(s), "PYTHONPATH": "src"},
        ).stdout
        for s in (1, 2, 3)
    }
    assert len(outputs) == 1
    assert outputs.pop().strip() == str(derive_seed(42, "deal", 3, 1))
