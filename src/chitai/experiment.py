"""Compare two batch output directories: M9 control versus treatment (Stage 3).

Run as ``python -m chitai.experiment``. Pure standard library, read-only on the batch files, no
randomness, and nothing here is ever shown to an agent. Three commands:

    compare CONTROL TREATMENT [--focal 0] [--output FILE]
        Checks that the two batches are comparable (same settings, game seeds, seatings and
        opponents), then reports statuses, faults, the paired focal-seat comparison on games that
        COMPLETED in both, and MindBot's diagnostics. Exit 1 if a check fails.
    equivalent CONTROL OFF
        Checks that a MindBot batch with inference disabled reproduces the RuleBot control: the
        same games, rounds and public event stream byte for byte, the same seat results, and
        diagnostics showing no inference activity. Exit 1 if not.
    identical A B
        Checks that two output directories hold the same files with the same bytes (run-to-run
        determinism). Exit 1 if not.

What "paired" means here (verified from the runner's seed rules): two batches that differ only in
the focal lineup entry give each game index the same game seed, so the same deal for every
(round, attempt), and the same seating. Play then diverges whenever an agent acts differently, so
a pair is the same deal-and-seat setup, NOT the same game. Only games that completed in both
conditions enter a pair; every other game is counted by its status pair and never dropped
silently. The report is descriptive: it prints no p-value and makes no claim of improvement. The
standard error shown is the plain sample SE of the paired differences, a scale for how noisy the
mean is, not a test.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from .eventlog import AGENT_DIAGNOSTIC_KEYS, read_csv
from .simulation import TERMINATION_STATUSES

COMPLETED = "completed"
AGENT_IDENTITY = ("agent_type", "agent_version", "agent_config_json")
INFERENCE_ONLY_KEYS = ("use_inference", "epsilon")  # the settings that may differ in the focal entry
Row = Mapping[str, str]


class Run:
    """One batch output directory, read once."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_dir():
            raise ValueError(f"not a directory: {self.path}")
        self.config = json.loads((self.path / "config.json").read_text(encoding="utf-8"))
        self.games = read_csv(self.path / "games.csv")
        self.seats = read_csv(self.path / "seats.csv")
        self.rounds = read_csv(self.path / "rounds.csv")
        table = self.path / "agent_diagnostics.csv"
        self.diagnostics = read_csv(table) if table.exists() else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _se(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / (n - 1) / n) ** 0.5


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else format(value, ".4f")


def _pct(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{100.0 * part / whole:.2f}%"


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failures: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        self.lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail and not ok else ""))
        if not ok:
            self.failures.append(label)


def _focal_seats(run: Run, focal: int) -> dict[str, Row]:
    return {row["game_index"]: row for row in run.seats if row["lineup_index"] == str(focal)}


def _config_without_focal(config: Mapping, focal: int) -> dict:
    kept = {k: v for k, v in config.items() if k not in ("lineup", "output")}
    kept["opponents"] = [entry for i, entry in enumerate(config["lineup"]) if i != focal]
    return kept


def _strategy(entry: Mapping) -> dict:
    settings = {k: v for k, v in entry.get("agent_config", {}).items() if k not in INFERENCE_ONLY_KEYS}
    settings.setdefault("avoid_draw", True)
    settings.setdefault("non_target_order", "most_copies")
    return settings


def comparability(report: Report, control: Run, treatment: Run, focal: int) -> None:
    report.add("Comparability (control vs treatment):")
    cc, tc = control.config, treatment.config
    report.check(len(cc["lineup"]) == len(tc["lineup"]) > focal, "same number of seats and a valid focal entry")
    if report.failures:
        return
    report.check(
        _config_without_focal(cc, focal) == _config_without_focal(tc, focal),
        "same rules, caps, seed settings, rotation and opponents (everything except the focal entry)",
    )
    report.check(
        _strategy(cc["lineup"][focal]) == _strategy(tc["lineup"][focal]),
        "focal agents share the underlying strategy (avoid_draw, non_target_order)",
        f"{_strategy(cc['lineup'][focal])} vs {_strategy(tc['lineup'][focal])}",
    )
    report.check(
        [g["game_index"] for g in control.games] == [g["game_index"] for g in treatment.games],
        "same game indices",
    )
    report.check(
        [g["game_seed"] for g in control.games] == [g["game_seed"] for g in treatment.games],
        "same game seed for every game index (identical deals per round and attempt)",
    )
    seating = lambda run: [(r["game_index"], r["seat"], r["lineup_index"]) for r in run.seats]  # noqa: E731
    report.check(seating(control) == seating(treatment), "same seating of every lineup entry in every game")
    report.add(
        f"  focal entry {focal}: control = {cc['lineup'][focal]['agent_type']}, "
        f"treatment = {tc['lineup'][focal]['agent_type']} {tc['lineup'][focal].get('agent_config', {})}"
    )


def statuses(report: Report, control: Run, treatment: Run) -> tuple[dict[str, str], dict[str, str]]:
    report.add("")
    report.add("Game statuses (all games; nothing excluded here):")
    report.add(f"  {'status':<26}{'control':>9}{'treatment':>11}")
    cs = {g["game_index"]: g["status"] for g in control.games}
    ts = {g["game_index"]: g["status"] for g in treatment.games}
    for status in TERMINATION_STATUSES:
        report.add(f"  {status:<26}{sum(v == status for v in cs.values()):>9}{sum(v == status for v in ts.values()):>11}")
    report.add(f"  {'games':<26}{len(cs):>9}{len(ts):>11}")
    report.add(f"  completion rate           {_pct(sum(v == COMPLETED for v in cs.values()), len(cs)):>9}"
               f"{_pct(sum(v == COMPLETED for v in ts.values()), len(ts)):>11}")
    pairs = Counter((cs[g], ts[g]) for g in cs if g in ts)
    off_diagonal = {k: v for k, v in pairs.items() if k != (COMPLETED, COMPLETED)}
    report.add(f"  games completed in both (the only games used for score/rank pairs): {pairs[(COMPLETED, COMPLETED)]}")
    for (c, t), n in sorted(off_diagonal.items()):
        report.add(f"  not paired: control {c} / treatment {t}: {n} game(s)")
    report.add("")
    report.add("Faults, timeouts and false claims (all games, every seat; capped games included):")
    for label, run in (("control", control), ("treatment", treatment)):
        totals = {key: sum(int(r[key]) for r in run.seats) for key in ("agent_faults", "timeouts", "false_claims")}
        report.add(f"  {label:<10}" + "  ".join(f"{k}={v}" for k, v in totals.items()))
    return cs, ts


def paired(report: Report, control: Run, treatment: Run, focal: int, cs: dict, ts: dict) -> None:
    report.add("")
    report.add(f"Paired comparison of focal entry {focal} (treatment minus control), games completed in both:")
    cf, tf = _focal_seats(control, focal), _focal_seats(treatment, focal)
    both = [g for g in cs if cs[g] == COMPLETED and ts.get(g) == COMPLETED and g in cf and g in tf]
    report.add(f"  paired games: {len(both)}")
    if not both:
        report.add("  no paired games: nothing to compare")
        return
    for metric, better in (("score", "higher"), ("rank", "lower"), ("rounds_won", "higher")):
        c = [float(cf[g][metric]) for g in both]
        t = [float(tf[g][metric]) for g in both]
        d = [b - a for a, b in zip(c, t)]
        up, down = sum(x > 0 for x in d), sum(x < 0 for x in d)
        report.add(
            f"  {metric:<11} control {_fmt(_mean(c))}  treatment {_fmt(_mean(t))}  diff {_fmt(_mean(d))}"
            f" (SE {_fmt(_se(d))})  treatment higher/lower/equal in {up}/{down}/{len(d) - up - down} games"
            f"  [{better} is better]"
        )
    for label, rows in (("control", cf), ("treatment", tf)):
        first = sum(rows[g]["rank"] == "1" for g in both)
        outright = sum(rows[g]["rank"] == "1" and rows[g]["tied"] == "false" for g in both)
        report.add(f"  {label:<10} rank 1 (ties count): {first}/{len(both)}   outright first: {outright}/{len(both)}")
    report.add("  by focal seat position (paired games; descriptive, no inference):")
    for seat in sorted({cf[g]["seat"] for g in both}, key=int):
        group = [g for g in both if cf[g]["seat"] == seat]
        d = [float(tf[g]["score"]) - float(cf[g]["score"]) for g in group]
        report.add(f"    seat {seat}: games {len(group):>4}  mean score diff {_fmt(_mean(d))}")


def diagnostics(report: Report, control: Run, treatment: Run, focal: int, cs: dict, ts: dict) -> None:
    report.add("")
    report.add("MindBot diagnostics (treatment; counters are the agent's own decisions):")
    rows = treatment.diagnostics
    if not rows:
        report.add("  no agent_diagnostics.csv in the treatment batch (no diagnostic-capable agent seated)")
        return
    seat_of = {(r["game_index"], r["seat"]): r for r in treatment.seats}
    ok = all(
        (r["game_index"], r["seat"]) in seat_of
        and seat_of[(r["game_index"], r["seat"])]["lineup_index"] == r["lineup_index"]
        and seat_of[(r["game_index"], r["seat"])]["agent_type"] == r["agent_type"]
        and seat_of[(r["game_index"], r["seat"])]["status"] == r["status"]
        for r in rows
    )
    expected = {(r["game_index"], r["seat"]) for r in treatment.seats if r["agent_type"] == "mindbot"}
    report.check(ok and {(r["game_index"], r["seat"]) for r in rows} == expected,
                 "every diagnostics row is attributed to a MindBot seat of that game, and every MindBot seat has one")
    values = [{k: int(r[k]) for k in AGENT_DIAGNOSTIC_KEYS} for r in rows]
    report.check(
        all(v["decisions"] == v["matched_rulebot"] + v["inference_changed_action"]
            and v["inference_changed_action"] <= v["inference_eligible"] <= v["pass_decisions"] <= v["decisions"]
            for v in values),
        "counters are internally consistent (decisions = matched + changed; changed <= eligible <= passes <= decisions)",
    )
    for scope, keep in (("all games", lambda r: True), ("completed games only", lambda r: r["status"] == COMPLETED)):
        chosen = [{k: int(r[k]) for k in AGENT_DIAGNOSTIC_KEYS} for r in rows if keep(r)]
        total = Counter()
        for v in chosen:
            total.update(v)
        report.add(f"  {scope}: MindBot seats {len(chosen)}")
        report.add(f"    decisions {total['decisions']}  pass decisions {total['pass_decisions']}")
        report.add(f"    inference-eligible (tied target) {total['inference_eligible']}: "
                   f"{_pct(total['inference_eligible'], total['decisions'])} of decisions, "
                   f"{_pct(total['inference_eligible'], total['pass_decisions'])} of pass decisions")
        report.add(f"    inference changed the action {total['inference_changed_action']}: "
                   f"{_pct(total['inference_changed_action'], total['decisions'])} of decisions, "
                   f"{_pct(total['inference_changed_action'], total['inference_eligible'])} of eligible")
        report.add(f"    matched RuleBot {total['matched_rulebot']} ({_pct(total['matched_rulebot'], total['decisions'])})")
        report.add("    estimator: " + "  ".join(f"{k.removeprefix('estimator_')}={total[k]}" for k in AGENT_DIAGNOSTIC_KEYS if k.startswith("estimator_")))
    games_changed = sum(v["inference_changed_action"] > 0 for v in values)
    report.add(f"  games in which inference changed at least one action: {games_changed} of {len(values)}")
    report.check(
        all(v["estimator_unreconstructable"] == v["estimator_uniform_priors"] == v["estimator_normalisation_resets"] == 0 for v in values),
        "no unreconstructable transitions, uniform-prior recoveries or normalisation resets (none expected without faults)",
    )
    # If inference never changed a decision in a game, nothing in that game can differ from control.
    cgames = {g["game_index"]: g for g in control.games}
    tgames = {g["game_index"]: g for g in treatment.games}
    crounds, trounds = ({g: [r for r in run.rounds if r["game_index"] == g] for g in cgames} for run in (control, treatment))
    cfocal, tfocal = _focal_seats(control, focal), _focal_seats(treatment, focal)
    unchanged = [r["game_index"] for r, v in zip(rows, values) if v["inference_changed_action"] == 0 and r["lineup_index"] == str(focal)]
    bad = [g for g in unchanged
           if cgames.get(g) != tgames.get(g) or crounds.get(g) != trounds.get(g)
           or any(cfocal[g][k] != tfocal[g][k] for k in cfocal[g] if k not in AGENT_IDENTITY)]
    report.check(not bad, f"all {len(unchanged)} games with no changed action are identical to the control game", f"differ: {bad[:10]}")


def compare(control: Run, treatment: Run, focal: int) -> Report:
    report = Report()
    report.add(f"CONTROL   {control.path}")
    report.add(f"TREATMENT {treatment.path}")
    report.add("")
    comparability(report, control, treatment, focal)
    if report.failures:
        report.add("")
        report.add("Comparability failed: no comparison is reported for batches that are not comparable.")
        return report
    cs, ts = statuses(report, control, treatment)
    paired(report, control, treatment, focal, cs, ts)
    diagnostics(report, control, treatment, focal, cs, ts)
    report.add("")
    report.add("Descriptive only. Differences from a calibration-sized sample are not evidence of improvement.")
    return report


def equivalent(control: Run, off: Run) -> Report:
    report = Report()
    report.add(f"CONTROL (RuleBot)          {control.path}")
    report.add(f"INFERENCE OFF (MindBot)    {off.path}")
    report.add("")
    report.add("Equivalence:")
    for name in ("games.csv", "rounds.csv", "events.jsonl"):
        a, b = control.path / name, off.path / name
        if a.exists() or b.exists():
            report.check(a.exists() and b.exists() and a.read_bytes() == b.read_bytes(), f"{name} is byte-identical")
    strip = lambda rows: [{k: v for k, v in r.items() if k not in AGENT_IDENTITY} for r in rows]  # noqa: E731
    report.check(strip(control.seats) == strip(off.seats), "seats.csv is identical apart from agent type, version and configuration")
    report.check(
        control.seats != off.seats and any(r["agent_type"] == "mindbot" for r in off.seats),
        "the inference-off batch really seats MindBot (the identity columns do differ)",
    )
    flags = [e.get("agent_config", {}).get("use_inference") for e in off.config["lineup"] if e["agent_type"] == "mindbot"]
    report.check(bool(flags) and all(f is False for f in flags), "every MindBot in the inference-off lineup has use_inference=false")
    rows = off.diagnostics or []
    values = [{k: int(r[k]) for k in AGENT_DIAGNOSTIC_KEYS} for r in rows]
    report.check(bool(values), "the inference-off batch wrote diagnostics")
    report.check(
        all(v["inference_eligible"] == v["inference_changed_action"] == v["estimator_deals"] == 0 and v["matched_rulebot"] == v["decisions"] for v in values),
        "diagnostics show no inference activity (no eligible or changed decisions, no estimator deals, every decision matched RuleBot)",
    )
    return report


def identical(a: Path, b: Path) -> Report:
    report = Report()
    report.add(f"A {a}")
    report.add(f"B {b}")
    names_a = sorted(p.name for p in a.iterdir() if p.is_file())
    names_b = sorted(p.name for p in b.iterdir() if p.is_file())
    report.check(names_a == names_b, "same file names", f"{names_a} vs {names_b}")
    for name in sorted(set(names_a) & set(names_b)):
        report.check((a / name).read_bytes() == (b / name).read_bytes(), f"{name} is byte-identical")
    return report


def _emit(report: Report, output: str | None) -> int:
    report.add("")
    report.add("RESULT: " + ("all checks passed" if not report.failures else f"{len(report.failures)} check(s) FAILED"))
    text = "\n".join(report.lines) + "\n"
    if output:
        with open(output, "x", encoding="utf-8", newline="\n") as handle:  # never overwrites
            handle.write(text)
    sys.stdout.write(text)
    return 0 if not report.failures else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chitai.experiment", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmp_ = sub.add_parser("compare", help="paired control/treatment comparison")
    cmp_.add_argument("control"), cmp_.add_argument("treatment")
    cmp_.add_argument("--focal", type=int, default=0, help="lineup index of the focal agent (default 0)")
    eq = sub.add_parser("equivalent", help="inference-off MindBot reproduces the RuleBot control")
    eq.add_argument("control"), eq.add_argument("off")
    same = sub.add_parser("identical", help="two output directories are byte-identical")
    same.add_argument("a"), same.add_argument("b")
    for p in (cmp_, eq, same):
        p.add_argument("--output", help="also write the report to this NEW file (UTF-8; never overwritten)")
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            report = compare(Run(args.control), Run(args.treatment), args.focal)
        elif args.command == "equivalent":
            report = equivalent(Run(args.control), Run(args.off))
        else:
            report = identical(Path(args.a), Path(args.b))
        return _emit(report, args.output)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
