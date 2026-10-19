"""Descriptive summaries computed from the CSV tables (M8 Stage 4; DoD: "CSV results can be
summarized").

Deliberately descriptive: no significance tests, no claim that one agent is better (statistical
comparison belongs to M9). Rules applied:

* Truncated games (status other than `completed`) are counted by status and are *excluded*
  from every score, rank and win metric (D8); their faults, timeouts and false claims still
  count in the per-agent totals.
* `rank1_share` counts every seat with rank 1, so a tie for first counts for each tied seat;
  `outright_win_share` counts only an untied rank 1. Ties are never broken (D7).
* Agents are identified by their lineup entry (`lineup_index`, type, version, effective config),
  not by the seat they happened to occupy, so seat rotation does not mix them up; the `seat`
  table shows any position effect separately.

Output is a long table of `(table, group, metric, value)` text rows, deterministic in order and
formatting (`.6f` for fractions and means).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from ..simulation import TERMINATION_STATUSES

SUMMARY_COLUMNS = ("table", "group", "metric", "value")
COMPLETED = "completed"


def _f(value: float) -> str:
    return format(value, ".6f")


def _mean(values: Sequence[float]) -> str:
    return _f(sum(values) / len(values)) if values else ""


def _share(count: int, total: int) -> str:
    return _f(count / total) if total else ""


def summarize(
    game_rows: Sequence[Mapping[str, str]], seat_rows: Sequence[Mapping[str, str]]
) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    total = len(game_rows)
    out.append(("batch", "all", "games", str(total)))
    for status in TERMINATION_STATUSES:
        count = sum(row["status"] == status for row in game_rows)
        out.append(("status", status, "games", str(count)))
        out.append(("status", status, "share", _share(count, total)))
    completed = [row for row in game_rows if row["status"] == COMPLETED]
    out.append(("batch", "completed", "mean_actions", _mean([int(r["actions"]) for r in completed])))
    out.append(("batch", "completed", "mean_draw_restarts", _mean([int(r["draw_restarts"]) for r in completed])))
    out.append(("batch", "all", "mean_actions", _mean([int(r["actions"]) for r in game_rows])))
    out.append(("batch", "all", "mean_draw_restarts", _mean([int(r["draw_restarts"]) for r in game_rows])))
    out.append(("batch", "completed", "ties_for_first", str(sum(r["tie_for_first"] == "true" for r in completed))))

    by_agent: dict[tuple[str, str, str, str], list[Mapping[str, str]]] = defaultdict(list)
    by_seat: dict[int, list[Mapping[str, str]]] = defaultdict(list)
    for row in seat_rows:
        key = (row["lineup_index"].zfill(4), row["agent_type"], row["agent_version"], row["agent_config_json"])
        by_agent[key].append(row)
        if row["status"] == COMPLETED:
            by_seat[int(row["seat"])].append(row)

    for key in sorted(by_agent):
        rows = by_agent[key]
        done = [r for r in rows if r["status"] == COMPLETED]
        group = f"lineup={int(key[0])}|{key[1]}@{key[2]}|{key[3]}"
        ranks = [int(r["rank"]) for r in done]
        out += [
            ("agent", group, "games", str(len(rows))),
            ("agent", group, "completed_games", str(len(done))),
            ("agent", group, "mean_score", _mean([int(r["score"]) for r in done])),
            ("agent", group, "mean_rank", _mean(ranks)),
            ("agent", group, "rank1_share", _share(sum(r == 1 for r in ranks), len(done))),
            ("agent", group, "outright_win_share",
             _share(sum(r["rank"] == "1" and r["tied"] == "false" for r in done), len(done))),
            ("agent", group, "false_claims", str(sum(int(r["false_claims"]) for r in rows))),
            ("agent", group, "timeouts", str(sum(int(r["timeouts"]) for r in rows))),
            ("agent", group, "agent_faults", str(sum(int(r["agent_faults"]) for r in rows))),
        ]  # fmt: skip

    for seat in sorted(by_seat):
        rows = by_seat[seat]
        group = f"seat={seat}"
        out += [
            ("seat", group, "completed_games", str(len(rows))),
            ("seat", group, "mean_score", _mean([int(r["score"]) for r in rows])),
            ("seat", group, "rank1_share", _share(sum(r["rank"] == "1" for r in rows), len(rows))),
        ]
    return out


__all__ = ["SUMMARY_COLUMNS", "summarize"]
