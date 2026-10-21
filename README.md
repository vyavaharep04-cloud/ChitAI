# ChitAI

AI-powered multiplayer game for decision-making under incomplete information

## Purpose

ChitAI digitizes a traditional multiplayer chit-passing game and provides an experimental environment for studying how AI agents make decisions when they cannot see the other players' hands. A single authoritative game engine is intended to support human games, mixed human/AI games, and AI-only simulations that produce reproducible, machine-readable logs.

## Research question
Does incorporating behavioural inference about opponents improve an AI agent's decision-making and performance in a multiplayer game with incomplete information?

This is a hypothesis, not a result. No experiments have been run, and no claim about agent performance is made.

## Project status

The gameplay rules and architecture have been finalized and documented. **Milestones 1 to 4 are implemented and merged into `main`; Milestone 5 is implemented on a feature branch awaiting review.** *(Update: Milestones 1 to 5 are merged into `main`; Milestone 6, timeouts and anti-stall draws, is implemented on a feature branch awaiting review.)* M1: project scaffolding, `GameConfig` validation, fixed-name deck construction, seeded dealing, and starting-player rotation. M2: game state, actions, events, invariants, and the **initial claim phase** (claim or decline, in deterministic order from the initiator). M3: **sequential passing** and ordinary claim opportunities (a five-chit receiver, and the initiator when the chit returns). M4: **false-claim penalties, round completion, and multi-round progression** (rotating initiator, fresh deals, a terminal state). M5: **valid-win resolution, player reactions, and scoring**. Everything else is not implemented yet: no timeouts, forced passes, anti-stall draws, agents, simulations, server, or browser UI. There is nothing playable yet.

*(Update: Milestone 7, player observations, per-seat legal actions and per-seat event views, is implemented and awaiting review.)*

*(Update: Milestone 8, RuleBot, a seeded AI-only simulation runner, event logs, CSV summaries and a batch command line, is implemented locally and awaiting review; see "What exists in Milestone 8" below. Only RuleBot exists as an agent: the behavioural-inference agent and the baseline comparison are Milestone 9, so no claim about agent performance is made.)*

*(Update: Milestone 10, a local FastAPI/WebSocket server and browser interface with optional AI opponents (RuleBot and MindBot), is implemented; see "Play in the browser (Milestone 10)" below. Milestone 9, the behavioural-inference agent MindBot and its experiment configurations, is in `main`; no claim about agent performance is made.)*

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

*(Update, Milestone 10: the `dev` extra now also installs `fastapi`, `uvicorn`, `websockets` and `httpx` for the web interface; the engine, observations and agents still use only the standard library. `pip install -e ".[web]"` installs only what is needed to run the server.)*

## Play in the browser (Milestone 10)

A local web interface (FastAPI, WebSockets, plain HTML/CSS/JavaScript, "Cosmic Edition" theme) lets people play the same authoritative engine used by the simulations. All rules, legality checks and scores live in the Python engine; the browser only displays what the server sends and requests actions.

### Run it

```powershell
pip install -e ".[dev]"
python -m chitai.api
```

Open <http://127.0.0.1:8000>. The server listens on `127.0.0.1` only (this machine); there is no LAN mode yet. Use `python -m chitai.api --port 8010` to change the port. Press Ctrl+C to stop.

### Human multiplayer

One person enters a display name, chooses 4 to 8 players, a round count (a multiple of the player count) and the decision timer (1 to 15 seconds), then clicks **Create room**. Everyone else enters a name and the four-letter room code and clicks **Join room**. When every seat is filled the host starts the game. Each player sees only their own hand and the public information the engine allows; a chit that is passed is visible only to the sender and the receiver.

### Human vs AI

Choose **Human vs AI** when creating a room. Pick the total number of players, how many are human (at least one, at least one AI seat), and a strategy for each AI seat. Humans take the first seats in join order and the AI seats follow, for example `human, RuleBot, MindBot, RuleBot`. The room shows which seats are AI (an "AI" badge in the waiting room and on the player cards). With one human the host can start immediately; with more, the other humans join with the code first.

Available AI agents (both existing agents, unchanged):

- **RuleBot**: the rule-based baseline, configured with `non_target_order = fewest_copies`.
- **MindBot**: the behavioural-inference agent, configured with `non_target_order = fewest_copies` and `use_inference = true`.

These are the same configurations as the M9 `calibration-treatment` / `calibration-control` experiment files. The server builds one separate agent instance per AI seat for each game and gives each agent only its own seat's observation and legal actions. A failing agent is handled as the simulation runner handles it: a single decision becomes a host timeout; a failing reactor is skipped; if every remaining reactor is a failed AI the room is closed with a clear message. If an AI cannot be built, room creation fails with an error and no other agent is substituted.

AI pacing: AI seats wait about 0.9 seconds before a move, and about 2 seconds before reacting after a valid claim, so a person can follow the game and has a window to react first. Reaction order affects scores, so results from browser play are not comparable with the simulation experiments. A four-round game against three AI seats takes roughly a minute at this pacing. **No claim is made that MindBot plays better than RuleBot**; that question belongs to the M9 experiments, not to this interface.

### Run the tests

```powershell
pytest
```

The web tests are in `tests/api/` (room logic, WebSocket protocol, privacy, AI orchestration, static assets).

### Current limitations

- Local only: loopback binding; no LAN mode, accounts or persistence. Rooms live in memory and disappear when the last human leaves or the server stops.
- No reconnection: closing or refreshing a tab loses that seat. The seat stays in the game, host timers keep running for it, and the game ends when all humans have left.
- A human who must react while two or more reactions are still pending has no timeout (a rule of the game), so an idle or disconnected human can stall a room.
- AI rooms need at least one human; there is no spectator mode and no AI-only room (use the batch simulator for that).
- AI strategy choices are limited to the two presets above; other RuleBot variants are not exposed.
- The browser interface was verified with an automated simulated-DOM harness against the live server and with the pytest suite. It still needs a look in a real browser (layout, colours, keyboard use).

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

**Limits of M4.** *(Update: Milestone 5 now resolves valid claims, see below; the rest of this paragraph still holds.)* A valid claim still ended in the `WIN_DECLARED` holding phase: no winner score, no reactions, and the round was not completed. There are no draws, forced passes or timeouts (Milestone 6), so callers must still bound their own pass loops. `Phase.FALSE_CLAIM` remains in the enum only as an internal transient phase; the engine never returns it.

### What exists in Milestone 5

A valid claim now runs the whole win lifecycle (PROJECT_CONTEXT.md §3A.5-§3A.6):

- A valid claim makes the claimant the **winner** and moves the game to `WIN_DECLARED`, which is now the *reaction* phase. There is no single decision point there: every non-winner who has not yet reacted may react.
- A reaction is an explicit action, `ReactAction(seat)`. The order in which the engine **accepts** these actions is the reaction order; the engine has no clock, timer or latency. Rejected: the winner (`winner_cannot_react`), a player who already reacted (`already_reacted`), an invalid seat, a reaction in any other phase (`action_not_available`), and any action after the game is over. Rejected actions change nothing.
- Scores: for `N` players the winner scores `N`, and the non-winners score `N-1`, `N-2`, ..., `1` in reaction order. The winner's score never depends on reaction order. Scores are **added** to the running totals, and only when the last non-winner has reacted; nothing is scored before that, and a round is never scored twice.
- The last reaction completes the round in the same `apply_action` call (as a false claim does in M4): `completed_rounds` rises by one, the engine deals the next round (fresh seeded deal, attempt 1, initiator rotated one seat clockwise, scores carried over) or, after the last configured round, returns `GAME_OVER`. The final non-winner also reacts with an explicit `ReactAction`; there is no timeout (Milestone 6), and a later timeout can issue that same action.
- New events: `PlayerReacted` (seat, 1-based position, winner), `ValidWinScored` (winner, reaction order, per-seat changes, new totals) and a `RoundCompleted` with outcome `"valid_win"`. Public views contain no chit identities.
- `legal_actions(state)` lists a `ReactAction` per pending non-winner; `pending_reactors(state)` returns those seats. `winner_score`, `reaction_score`, `valid_win_score_changes` and `valid_win_round_total` (in `scoring.py`) are the pure scoring functions. The score invariant now accepts positive scores as well as M4 penalties.

```python
from chitai.engine import (
    ClaimAction, Deal, GameConfig, ReactAction, apply_action, build_deck, start_from_deal,
)

config = GameConfig(num_players=4, num_rounds=4, seed=42)
deck = build_deck(4)
# A hand-built deal in which every seat holds four chits of one name, so a claim is valid.
deal = Deal(completed_round=0, attempt=1, initiator=0,
            hands=tuple(tuple(c for c in deck if c.name == deck[4 * s].name) for s in range(4)))
state = start_from_deal(config, deal).state

state = apply_action(state, ClaimAction(0)).state    # seat 0 claims a matching hand: it wins
print(state.phase.value, state.winner)               # win_declared 0
for seat in (3, 1, 2):                               # the engine's accepted-action order is the reaction order
    state = apply_action(state, ReactAction(seat)).state
print(state.scores, state.completed_rounds, state.initiator)
# win_declared 0
# (4, 2, 1, 3) 1 1   (winner 4; seat 3 reacted first: 3, seat 1: 2, seat 2: 1; round 1 begins, initiator seat 1)
```

**Limits of M5.** No timeouts, forced passes or anti-stall draws (Milestone 6), so callers must still bound their own pass loops. The engine records no wall-clock timestamps; reaction order is the engine's accepted-action order. There is no latency model for simulated reactions, no player observations, agents or UI.

### What exists in Milestone 6

Timeouts and the anti-stall rule (PROJECT_CONTEXT.md §3A.3, §3A.5-§3A.7):

- **The engine has no clock.** A timeout is an action the *host* issues when its own timer expires: `TimeoutAction(seat)`. The engine checks only that a timeout is *available* for that seat; it cannot check elapsed time. There are no sleeps, timers or threads. `GameConfig.pass_timeout_seconds` (greater than 0, at most 15) is the value the host should use for its timers; it never changes engine behaviour.
- An accepted timeout resolves through the ordinary transition, never a claim: in the **initial claim phase** it is an automatic decline; during **passing** it is a forced pass of one physical chit chosen uniformly from the seat's hand (four for the initiator, five for a receiver) with the seeded `"timeout"` stream; in the **reaction phase** it is only available for the *last* remaining non-winner, and resolves that reaction exactly like `ReactAction` (the last reactor scores 1 either way). While two or more non-winners remain it is rejected with `timeout_not_available`. All other rejections (wrong seat, invalid seat, game over) behave as for the ordinary actions and change nothing.
- A forced pass depends only on the master seed, the round, the attempt, the next sequence number and the set of chits held, so it is reproducible; a timeout uses its own random stream, so it can never change a later deal.
- **Anti-stall:** each seat's consecutive passes of one chit *name* are counted in `GameState.pass_streaks` (sparse `(seat, chit_name, count)` entries). Different physical copies of a name continue the streak, a different name restarts that seat's count at one, and other seats' passes never change it. The **tenth** consecutive same-name pass by one seat ends the attempt as a **draw**: that chit is *not delivered*, no score changes, `completed_rounds` is unchanged, the attempt number increases by one, and the engine immediately redeals (the seeded deal for the same round and the next attempt) with the **same initiator** and with every streak cleared. The redeal starts with the initial claim phase like any other deal. Forced passes and initiator passes count like any other pass.
- New events: `DecisionTimedOut(seat, decision_kind)` comes first, followed by the ordinary events of whatever the timeout resolved; `AttemptDrawn(seat, consecutive_passes)` is followed by the redeal's `DealEvent`. Public views never contain a chit name; the private debug view of `AttemptDrawn` adds the chit. Existing events, `legal_actions` and their public views are unchanged. `timeout_action(state)` returns the one `TimeoutAction` a host may issue now (or `None`); `timeout_chit(state)` is the chit a forced pass would pick.

```python
from dataclasses import replace
from chitai.engine import (
    DeclineAction, GameConfig, PassAction, apply_action, new_game, timeout_action,
)

config = GameConfig(num_players=4, num_rounds=4, seed=42, pass_timeout_seconds=10)
state = new_game(config).state
for _ in range(4):                                    # every initial opportunity: decline
    state = apply_action(state, DeclineAction(state.decision_seat)).state

print(timeout_action(state))                          # the host's timer expired for the initiator
result = apply_action(state, timeout_action(state))   # a forced pass of one of its four chits
print([type(e).__name__ for e in result.events])
# TimeoutAction(seat=0)
# ['DecisionTimedOut', 'ChitPassed']

seat = state.decision_seat
chit = state.hands[seat][0]
nine = replace(state, pass_streaks=((seat, chit.name, 9),))   # test setup: nine passes already made
drawn = apply_action(nine, PassAction(seat, chit))            # the tenth is a draw
print([type(e).__name__ for e in drawn.events])
print(drawn.state.completed_rounds, drawn.state.attempt, drawn.state.initiator, drawn.state.pass_streaks)
# ['AttemptDrawn', 'DealEvent']
# 0 2 0 ()
```

**Limits of M6.** The simulation **draw safety cap** is not in the engine: §3A.6 and §5A assign it to the simulation runner (Milestone 8), which can stop a run when `state.attempt` exceeds its cap. Because timeouts never claim, a game driven only by timeouts need not end, so hosts and simulators must still bound their own loops. No wall-clock timestamps, latency model, observations, agents, simulation runner or UI exist.

### What exists in Milestone 7

The new `chitai.observations` package is the privacy boundary for agents and clients (PROJECT_CONTEXT.md §3A.8, §4, §9 questions 29-32). It reads engine state and never changes the engine.

- `observe(state, seat)` returns an `Observation`: public fields (players, rounds, round and attempt, initiator, phase, decision point, scores, hand sizes, winner, reaction order, pending reactors, `my_turn`, the chit names in play) and private fields (`my_seat`, `my_hand` as sorted chit **names**, and the observer's **own** anti-stall streak). `to_dict()` is JSON. It never contains the state, the config or seed, other seats' hands or streaks, physical copy ids, or timeout data.
- `legal_actions_for(state, seat)` lists only that seat's actions, built from the engine's own `legal_actions`: claim, decline, react, or `NamePassAction(seat, chit_name)`, one per distinct name held. It never contains another seat's action or a timeout. `to_engine_action(state, action)` returns the engine action (a physical `PassAction` for a name) only for an action that is in that list, otherwise `None`.
- `observe_event(event, seat)` / `observe_events(events, seat)` give the public view plus only what that seat may know: its own dealt hand, and the passed chit's name for the sender and receiver. A bystander never learns a passed chit. Claims, timeouts and draws stay public and reveal no chit. Nothing is revealed at round end. `seat=None` gives the public stream. `debug_view()` is never used.

```python
from chitai.engine import GameConfig, apply_action, new_game
from chitai.observations import legal_actions_for, observe, to_engine_action

state = new_game(GameConfig(num_players=4, num_rounds=4, seed=42)).state
obs = observe(state, 0)
print(obs.my_hand, obs.my_turn)                 # e.g. ('Cloud', 'Moon', 'Star', 'Sun') True
choice = legal_actions_for(state, 0)[1]         # DeclineAction(seat=0)
state = apply_action(state, to_engine_action(state, choice)).state
print(observe(state, 0).my_turn, observe(state, 1).my_turn)   # False True
```

**Limits of M7.** There is no runner-level action validation or generic agent-facing error handling yet (Milestone 8): a runner must build actions with the agent's own seat, accept only actions in `legal_actions_for(state, own_seat)`, translate them with `to_engine_action`, and must not forward the engine's `Rejected` messages to agents. There are no agents, simulation runner, logging, server or UI.

This is a library only; there is no game to run or play yet.

### What exists in Milestone 8

M8 adds an agent, a seeded AI-only game runner and file output. Packages, from the bottom up (each sits above the previous one and never changes how a game is played):

- `chitai.agents`: the `Agent` protocol and `RuleBot`, a fixed-heuristic baseline. RuleBot's heuristics are ordinary rules of thumb; it does **not** model opponents' behaviour.
- `chitai.simulation`: `SimulationConfig` (JSON), deterministic seeds, result records, shared-competition ranking, and `run_game(config, game_index)`, which plays one complete game through the real engine. Agents only ever receive their own `Observation` and legal actions. The host validates every answer first: an exception, an illegal or cross-seat action, a subclass or a timeout choice is an *agent fault*, resolved by the engine's own host-issued timeout and counted separately from it (no retries). The **draw cap** and **action cap** live here (the engine has none); both are required settings with **no default value**.
- `chitai.eventlog`: the public event log (each event's public view only), opt-in private diagnostics, three CSV tables (games, seats, rounds) and a descriptive summary.
- `chitai.batch`: `run_batch`, a manifest, and the command line below.

**Run a batch** (PowerShell or bash, from the repository root after `pip install -e ".[dev]"`; on a fresh checkout without installing, set `PYTHONPATH=src`). Create `my_batch.json`:

```json
{
  "lineup": [
    {"agent_type": "rulebot", "agent_config": {"non_target_order": "most_copies"}},
    {"agent_type": "rulebot", "agent_config": {"non_target_order": "fewest_copies"}},
    {"agent_type": "rulebot", "agent_config": {"non_target_order": "most_copies"}},
    {"agent_type": "rulebot", "agent_config": {"non_target_order": "fewest_copies"}}
  ],
  "num_players": 4,
  "num_rounds": 4,
  "batch_seed": 20261019,
  "game_count": 8,
  "games_per_seed": 4,
  "rotate_seats": true,
  "max_draw_restarts_per_round": 50,
  "max_actions_per_attempt": 2000,
  "output": {"public_event_log": true, "private_diagnostics": false}
}
```

The two caps above are **placeholder values for the example, not recommendations**; choosing them for a real experiment is an open decision (PROJECT_CONTEXT.md §9 question 33). Then:

```bash
python -m chitai.batch validate my_batch.json          # checks the file and the agents; plays nothing
python -m chitai.batch run my_batch.json --output runs/demo
python -m chitai.batch summarize runs/demo             # prints the summary table
```

`run` writes into a new or empty directory and refuses to overwrite anything. Files written (UTF-8, `\n` line endings):

| File | Content |
|---|---|
| `config.json` | the effective configuration; running it again reproduces the batch byte for byte |
| `games.csv`, `seats.csv`, `rounds.csv` | one row per game, per seat of a game, per completed round (host records; they contain the game seed) |
| `events.jsonl` | the public event log, one line per event, plus one `game_end` line per game; no hands, chit names or seeds |
| `private_diagnostics.jsonl` | only with `output.private_diagnostics`: private events (hands, a draw's chit) and agent-fault kinds. Never show it to an agent or client |
| `summary.csv` | descriptive summary (see below) |
| `manifest.json` | SHA-256 and size of every file, the configuration hash and status counts; written last, so a directory without it is an incomplete run |

**Reproducibility and fair comparison.** The same configuration gives byte-identical files on a machine: nothing depends on the clock, the path, Python's hash seed or set order. `games_per_seed: k` makes each run of `k` consecutive games share one deal seed, and `rotate_seats` moves the lineup one seat per game, so different agents can face identical deals from every seat. The summary identifies an agent by its lineup entry, not by the seat it happened to occupy, and reports seat position separately.

**What the summary does and does not do.** Games stopped by a cap or an unresolvable fault have no ranks, ties or winners; they are counted by status and are excluded from score, rank and win metrics. Ties are kept (`rank1_share` counts every tied first place, `outright_win_share` only untied ones) and never broken. The summary is descriptive only: it has no significance tests and does not say that any agent is better. Statistical comparison belongs to Milestone 9.

**Limits of M8.** Only RuleBot exists; there is no behavioural-inference agent and no comparison result. The RuleBot `non_target_order` variant and the cap values have not been chosen. A small preliminary RuleBot measurement (20 games per cell) was run outside the package with a separate script that is not part of these patches; it is not research evidence. Reaction order in simulations is a seeded permutation of the pending players, an experimental policy and not a model of human reaction speed. No server, browser UI or human play exists yet. Tests have been run on Linux; Windows runs are the owner's to record.
