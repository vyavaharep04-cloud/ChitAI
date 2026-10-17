# ChitAI

AI-powered multiplayer game for decision-making under incomplete information

## Purpose

ChitAI digitizes a traditional multiplayer chit-passing game and provides an experimental environment for studying how AI agents make decisions when they cannot see the other players' hands. A single authoritative game engine is intended to support human games, mixed human/AI games, and AI-only simulations that produce reproducible, machine-readable logs.

## Research question
Does incorporating behavioural inference about opponents improve an AI agent's decision-making and performance in a multiplayer game with incomplete information?

This is a hypothesis, not a result. No experiments have been run, and no claim about agent performance is made.

## Project status

The gameplay rules and architecture have been finalized and documented. **Milestones 1 and 2 are implemented.** M1: project scaffolding, `GameConfig` validation, fixed-name deck construction, seeded dealing, and starting-player rotation. M2: game state, actions, events, invariants, and the **initial claim phase** (claim or decline, in deterministic order from the initiator). Everything else is not implemented yet: no passing, scoring, reactions, timeouts, anti-stall, agents, simulations, server, or browser UI. There is nothing playable yet.

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

### What exists in Milestone 2

The engine now models the initial claim phase (PROJECT_CONTEXT.md §3A.3):

- `new_game(config)`: starts round 0 with the seeded deal and returns the first `GameState` plus its events. `start_from_deal(config, deal)` starts from a given `Deal`.
- `apply_action(state, action)`: validates and applies a `ClaimAction(seat)` or `DeclineAction(seat)`. It returns `Accepted(state, events)` or `Rejected(reason, message)`. A rejected action changes nothing, applies no penalty, and consumes no event sequence number.
- Each seat gets exactly one initial opportunity, in order from the initiator clockwise, whether or not its hand matches. A claim is valid only with four chits of one name; any other eligible claim is a false claim. The engine never claims for a player.
- When every seat has declined, the phase becomes `PASSING` with the initiator to make the first pass (passing itself is not implemented).
- `legal_actions(state)`, `check_invariants(state)` (run by the engine on every state it produces), and sequenced events with a `public_view()` (no chit identities) and a `debug_view()` (private; full hands).

```python
from chitai.engine import GameConfig, new_game, apply_action, ClaimAction, DeclineAction

state = new_game(GameConfig(num_players=4, num_rounds=4, seed=42)).state
step = apply_action(state, DeclineAction(0))      # seat 0 declines; seat 1 is next
print(step.state.decision_seat)                   # 1
print(apply_action(step.state, ClaimAction(3)))   # Rejected: not seat 3's opportunity
```

**Limits of M2.** A valid claim leaves the game in the holding phase `WIN_DECLARED` (reactions and scoring are Milestone 5). A false claim leaves it in `FALSE_CLAIM` (the penalty and round completion are Milestone 4). No scores are applied and `completed_rounds` is not incremented. There are no timers, so an automatic decline on timeout is not implemented (Milestone 6).

This is a library only; there is no game to run or play yet.
