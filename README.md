# ChitAI

AI-powered multiplayer game for decision-making under incomplete information

## Purpose

ChitAI digitizes a traditional multiplayer chit-passing game and provides an experimental environment for studying how AI agents make decisions when they cannot see the other players' hands. A single authoritative game engine is intended to support human games, mixed human/AI games, and AI-only simulations that produce reproducible, machine-readable logs.

## Research question
Does incorporating behavioural inference about opponents improve an AI agent's decision-making and performance in a multiplayer game with incomplete information?

This is a hypothesis, not a result. No experiments have been run, and no claim about agent performance is made.

## Project status

The gameplay rules and architecture have been finalized and documented. **Milestone 1 is implemented:** project scaffolding, `GameConfig` validation, fixed-name deck construction, seeded dealing, and starting-player rotation, with unit tests. Everything else is not implemented yet: no passing, claims, scoring, reactions, timeouts, anti-stall, agents, simulations, server, or browser UI. There is nothing playable yet.

## Documentation

[`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) is the master project record. It contains the authoritative gameplay rules (Section 3A), the adopted architecture (Section 5A), the milestone roadmap (Section 8A), open questions, and the change log.

## Setup and testing

Requires Python 3.12 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

`pip install -e ".[dev]"` installs the `chitai` package in editable mode plus pytest (the only dependency; the engine itself uses only the standard library).

### What exists in Milestone 1

The `chitai.engine` package provides:

- `GameConfig`: validated settings (4-8 players, round count a positive multiple of the player count, pass timeout greater than 0 and at most 15 seconds, integer seed).
- `build_deck(n)`: the fixed deck of `n` chit names, four copies each.
- `deal_round(config, completed_round, attempt=1)`: a seeded, reproducible deal of four chits per seat.
- `initiator_for_round(config, completed_round)`: starting seat, beginning at seat 0 and rotating one seat per completed round.

```python
from chitai.engine import GameConfig, deal_round

config = GameConfig(num_players=4, num_rounds=8, seed=42)
deal = deal_round(config, completed_round=0)
print(deal.initiator, deal.hands[0])
```

This is a library only; there is no game to run or play yet.
