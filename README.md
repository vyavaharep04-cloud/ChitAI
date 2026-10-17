# ChitAI

AI-powered multiplayer game for decision-making under incomplete information

## Purpose

ChitAI digitizes a traditional multiplayer chit-passing game and provides an experimental environment for studying how AI agents make decisions when they cannot see the other players' hands. A single authoritative game engine is intended to support human games, mixed human/AI games, and AI-only simulations that produce reproducible, machine-readable logs.

## Research question
Does incorporating behavioural inference about opponents improve an AI agent's decision-making and performance in a multiplayer game with incomplete information?

This is a hypothesis, not a result. No experiments have been run, and no claim about agent performance is made.

## Project status

The gameplay rules and architecture have been finalized and documented. **Milestones 1, 2 and 3 are implemented and merged into `main`; Milestone 4 is implemented on a feature branch awaiting review.** M1: project scaffolding, `GameConfig` validation, fixed-name deck construction, seeded dealing, and starting-player rotation. M2: game state, actions, events, invariants, and the **initial claim phase** (claim or decline, in deterministic order from the initiator). M3: **sequential passing** and ordinary claim opportunities (a five-chit receiver, and the initiator when the chit returns). M4: **false-claim penalties, round completion, and multi-round progression** (rotating initiator, fresh deals, a terminal state). Everything else is not implemented yet: no valid-win scoring, reactions, timeouts, anti-stall draws, agents, simulations, server, or browser UI. There is nothing playable yet.

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
- When every seat has declined, the phase becomes `PASSING` with the initiator to make the first pass (see Milestone 3).
- `legal_actions(state)`, `check_invariants(state)` (run by the engine on every state it produces), and sequenced events with a `public_view()` (no chit identities) and a `debug_view()` (private; full hands).

```python
from chitai.engine import GameConfig, new_game, apply_action, ClaimAction, DeclineAction

state = new_game(GameConfig(num_players=4, num_rounds=4, seed=42)).state
step = apply_action(state, DeclineAction(0))      # seat 0 declines; seat 1 is next
print(step.state.decision_seat)                   # 1
print(apply_action(step.state, ClaimAction(3)))   # Rejected: not seat 3's opportunity
```

**Limits of M2.** A valid claim leaves the game in the holding phase `WIN_DECLARED` (reactions and scoring are Milestone 5). *(M2 also left false claims in a `FALSE_CLAIM` holding phase; Milestone 4 replaced that, see below.)* There are no timers, so an automatic decline on timeout is not implemented (Milestone 6).

### What exists in Milestone 3

Ordinary play now works up to the first claim (PROJECT_CONTEXT.md §3A.4):

- `PassAction(seat, chit)` passes one physical chit instance to the next seat clockwise. Delivery is atomic: the initiator then holds three chits and the receiver holds five.
- A non-initiator holding five may `ClaimAction` (valid when four of the five share a name) or pass any of the five. The initiator gets a claim opportunity again when a chit returns, holding four (valid only when all four match). The initiator has no claim opportunity at the first pass or while holding three.
- Declining exists only in the initial phase; during passing, passing forfeits the opportunity. The engine never claims for a player whose hand happens to match.
- Rejected actions (out of turn, no claim opportunity, a chit the seat does not hold, and so on) change nothing, apply no penalty, and consume no sequence number.
- Events: `ChitPassed` (public view shows sender and receiver only; the chit appears only in the private `debug_view()`) and `ClaimMade`.

```python
from chitai.engine import GameConfig, new_game, apply_action, DeclineAction, PassAction, legal_actions

state = new_game(GameConfig(num_players=4, num_rounds=4, seed=42)).state
for _ in range(4):                                   # everyone declines the initial claim
    state = apply_action(state, DeclineAction(state.decision_seat)).state
chit = state.hands[0][0]
state = apply_action(state, PassAction(0, chit)).state
print(len(state.hands[0]), len(state.hands[1]))      # 3 5
print(legal_actions(state)[0])                       # ClaimAction(seat=1)
```

**Limits of M3.** A valid claim made during passing ends in the `WIN_DECLARED` holding phase: no scoring and no round completion (Milestone 5). *(False claims are now completed by Milestone 4, see below.)* Nothing yet stops an endless pass cycle; anti-stall draws and timeouts are Milestone 6, so callers must bound their own loops.


### What exists in Milestone 4

A false claim now ends the round and the game moves on (PROJECT_CONTEXT.md §3A.5-§3A.6):

- An eligible claim that fails its matching rule (four of four at an initial or initiator-return claim, four of five for a receiving non-initiator) is a false claim. The claimant scores `-(N-1)`, every other seat scores 0, and no winner or reaction score is awarded. An ineligible claim is still rejected with no penalty and no change of state, scores, round counter or event sequence.
- The same `apply_action` call completes the round: `completed_rounds` rises by exactly one, scores are carried over, and the engine deals the next round (a fresh seeded deal for the new completed-round index, attempt 1, the initiator rotated one seat clockwise; seat 0 starts). After the last configured round the phase is `GAME_OVER` and the engine accepts no further action.
- Deals stay reproducible from the master seed, the completed-round index and the attempt number. Rejected actions consume neither randomness nor event sequence numbers, and event sequence numbers stay contiguous across round boundaries.
- New events: `FalseClaimPenalized` (score changes and totals), `RoundCompleted`, and `GameCompleted` (final scores). The next round starts with an ordinary `DealEvent`. Public views contain no chit identities.
- `false_claim_penalty(n)` and `false_claim_score_changes(n, claimant)` (new `scoring.py`) are the pure scoring functions.

```python
from chitai.engine import GameConfig, new_game, apply_action, ClaimAction, Phase

state = new_game(GameConfig(num_players=4, num_rounds=4, seed=42)).state
result = apply_action(state, ClaimAction(0))   # seat 0 claims at once
# if its hand did not match, the claim was false:
print(result.state.scores, result.state.completed_rounds, result.state.initiator)
# e.g. (-3, 0, 0, 0) 1 1   (seat 0 penalized, round 1 begins with seat 1 as initiator)
```

**Limits of M4.** A valid claim still ends in the `WIN_DECLARED` holding phase: no winner score, no reactions, and the round is not completed (Milestone 5), so a game that reaches a valid claim does not progress further yet. There are no draws, forced passes or timeouts (Milestone 6), so callers must still bound their own pass loops. `Phase.FALSE_CLAIM` remains in the enum only as an internal transient phase; the engine never returns it.

This is a library only; there is no game to run or play yet.
