# ChitAI — Project Context

**Research title:** *ChitAI: An AI-Powered Multiplayer Game for Decision-Making Under Incomplete Information*
**Repository:** `vyavaharep04-cloud/ChitAI`
**Default branch:** `main`
**Status:** Specification and architecture finalized (2026-10-17). Milestone 1 implemented and tested locally (2026-10-17, uncommitted pending owner review) *[Update: merged into `main` via PR #3, merge commit `cbdf59e`]*; Milestone 2 implemented and tested locally on branch `feature/milestone-2-initial-claims` (2026-10-17, awaiting owner review); Milestones 3+ not started. *[Update 2026-10-17 — current status: Milestones 1, 2 and 3 are merged into `main` (M1 via PR #3, merge commit `cbdf59e`; M2 via PR #4, merge commit `f2e4753`; M3 merge commit `5b2256e`). Milestone 4 (false claims, round completion, multi-round progression) is implemented and tested on branch `feature/milestone-4-round-completion`, awaiting owner review; Milestones 5+ not started.]* *[Update 2026-10-17 — current status: per the owner, Milestones 1–4 are merged into `main` (`main` is at `dde4bda`, "Implement Milestone 4: False Claims and Round Progression"). Milestone 5 (valid-win resolution, player reactions and scoring) is implemented and tested on branch `feature/milestone-5-valid-win-resolution`, awaiting owner review; Milestones 6+ not started.]* *[Update 2026-10-18 — current status: Milestones 1–5 are merged into `main` (`089f3c4`, merge of PR #7). Milestone 6 (timeouts, forced passes and anti-stall draws) is implemented and tested on branch `feature/milestone-6-timeouts-anti-stall`, awaiting owner review; Milestones 7+ not started.]* *[Update 2026-10-18 — current status: Milestones 1–6 are merged into `main` (`62c832f`, merge of PR #8). Milestone 7 (privacy-safe player observations, per-seat legal actions and per-seat event views) is implemented and tested on top of `62c832f`, awaiting owner review; Milestones 8+ not started.]* **Last updated:** 2026-10-18

> Maintenance rule: Treat this as a persistent project record. Do not overwrite existing history. Append dated milestone notes to the Change Log, including decisions, changes, tests, and next actions.

## 1. Overview

ChitAI digitizes a traditional multiplayer chit-passing game and provides an experimental environment for studying AI decision-making under incomplete information. The same authoritative game engine must support human games, mixed human/AI rooms, and AI-only simulations. The project should produce reproducible, machine-readable experiment logs.

**Research question:** Does incorporating behavioural inference about opponents improve an AI agent's decision-making and performance in a multiplayer game with incomplete information?

This is a hypothesis, not a result. Do not claim that an agent performs better until experiments support that conclusion.

## 2. Candidate AI agents

- **RuleBot:** Transparent, rule-based baseline.
- **SmartBot:** Heuristic agent that scores legal actions using explicit features and configurable weights.
- **MindBot:** Opponent-aware agent that estimates behaviour from observations. Bayesian updating is a candidate approach, subject to implementation time and explainability.

All agents must use the same interface and receive only player-appropriate observations. Do not reveal hidden opponent cards to any agent. Compare agents with recorded seeds, balanced starting positions, and sufficient runs. Potential metrics include win rate, average score/rank, false-claim rate, claim opportunities taken/missed, timeouts, and forced reshuffles. Report limitations and inconclusive results honestly.

## 3. Current agreed game rules

> **Reading guide (added 2026-10-17):** Section 3A below is the single authoritative statement of the gameplay rules and claim lifecycle. The bullets in this Section 3 are retained as history. A bullet tagged **SUPERSEDED** must not be implemented. A bullet tagged *Clarified* remains valid as refined by Section 3A. If any text still conflicts with Section 3A, Section 3A wins and the conflict must be flagged to the owner.

### Players and chits
- 4–8 players.
- For `N` players, there are `N` unique chit names, each occurring exactly four times.
- Total chits: `4N`; each player starts with four.
- Shuffle and deal randomly at the start of every round.
- During the initial deal, every player receives an initial claim opportunity as soon as their four chits have been revealed to them. A valid claim requires all four to match. *[Clarified 2026-10-17 → §3A.3: opportunities are processed one at a time in deterministic order, beginning with the initiator and continuing clockwise. Each player may claim or decline whether or not their chits match; matching decides validity only.]*

### Passing
- Pass clockwise; the starting player rotates each round. *[Clarified 2026-10-17 → §3A.4, §3A.6: passing is sequential, not simultaneous. The initiator rotates after each completed round, not after a draw.]*
- The receiver temporarily holds five chits: their four current chits plus the received chit. *[Clarified 2026-10-17 → §3A.4: this describes a non-initiator receiver only. The initiator holds three chits while its passed chit is in transit and four when the chit returns; the initiator never holds five.]*
- They select any one of the five to pass onward, including the chit just received.
- After passing, the player holds four again.

### Claims and scoring
- **[SUPERSEDED 2026-10-17 → §3A.4, §3A.5: claim availability depends on phase and position in the passing sequence, not on whether the held chits match. Do not implement from this bullet.]** A player may claim when their four held chits match, or when at least four of the five temporarily held chits match.
- Claims are explicit actions; do not automatically announce a win.
- Passing forfeits that claim opportunity until the player's next opportunity.
- The first valid claim received by the authoritative server wins. *[Clarified 2026-10-17 → §3A.5: the first valid claim accepted by the authoritative engine fixes the winner; later claims cannot replace it.]*
- A false claim ends the round: claimant gets `−(N−1)` points; everyone else gets `0`. *[Clarified 2026-10-17 → §3A.5: applies only to eligible claims that fail the matching condition. A false claim completes the round; the next round has a fresh shuffle and deal and the next initiator.]*
- After a valid win, every other player reacts; the winner does not react.
- Winner scores `N`; other players score `N−1`, `N−2`, …, `1` according to reaction order.
- Do not apply a general timeout while multiple non-winners still need to react. When only one non-winner remains to react (for example, in a four-player game after the other three players have reacted/claimed), resolve that remaining reaction automatically by timeout. *[Clarified 2026-10-17: under sequential eligibility only one player can claim at a time, so "reacted/claimed" is interpreted as "reacted"; non-winners react and do not claim. Owner confirmation pending — see §9 Open questions.]*
- Record reaction timestamps at microsecond precision. If events share a timestamp, use the authoritative server's receipt/sequence order as the deterministic tie-breaker; timestamps alone must not determine fairness.
- Server-side logic must validate claims, actions, ordering, and scores; do not trust the client UI.

### Rounds, timeout, and anti-stall
- Room creator chooses the round count.
- Round count must be a multiple of `N` and include at least one complete starting-player rotation. *[Clarified 2026-10-17 → §3A.6: the count refers to completed rounds (valid win or false claim). Draw attempts are not counted.]*
- Reshuffle and redeal all chits every round.
- Pass timeout is at most 15 seconds; the room creator may choose a shorter duration.
- If a player runs out of time to pass, randomly select and pass one of the five chits. Simulations must use a seeded RNG for reproducibility. *[Clarified 2026-10-17 → §3A.7: the legal chits are those the player holds at the decision point — five for a non-initiator, four for the initiator — chosen uniformly among physical chit instances. A timeout never produces a claim.]*
- **[SUPERSEDED 2026-10-17 → §3A.4: the initiator's claim opportunity occurs only in the initial claim phase and when the passed chit returns to the initiator (who then holds four); never while the initiator holds three chits in transit. The non-initiator part of this bullet remains valid.]** On subsequent turns, the initiator's claim option is available while they hold four chits, whether or not those four match. A non-initiator's claim option becomes available when they receive a fifth chit. Claim validity is still checked against the matching rule.
- If the same player passes the same chit name for 10 consecutive passes, force a reshuffle and restart the round as a draw. The same player remains the initiator; no score is added or removed for that drawn round. *[Clarified 2026-10-17 → §3A.6: a draw ends the attempt, not a completed round; scores are preserved, the initiator is unchanged, the attempt number increments, and chits are reshuffled and redealt.]*
- Passing a different chit name resets the consecutive-pass count for the previously tracked name and starts tracking the newly passed name.

## 3A. Authoritative gameplay rules and claim lifecycle (finalized 2026-10-17)

> This section is the single authoritative statement of the ChitAI gameplay rules. It consolidates the rules supplied or confirmed by the project owner and supersedes earlier wording in Sections 3 and 9 wherever they differ.

### 3A.1 Terminology
- **Seat:** an integer `0 … N−1`. **Clockwise** means increasing seat index, wrapping from `N−1` to `0`.
- **Initiator:** the seat that begins a round's passing sequence. The first initiator is seat 0.
- **Chit name:** the identity used for all matching. **Physical chit instance:** one of the four copies of a chit name. Instances are distinguished internally when necessary (for example uniform random selection and private debug logs); matching uses chit names only.
- **Completed round:** a round that ends in a valid win (after reactions and scoring) or in a false claim.
- **Attempt:** one shuffle-and-deal within a round. A draw ends an attempt without completing the round, and the next attempt has an incremented attempt number. Completed rounds and attempt numbers are tracked separately.
- **Claim opportunity:** a point at which the engine offers one specific player the option to claim. Opportunities arise only from the phase and the position in the passing sequence, never from the hand happening to match.
- **Decision point:** the single player the engine is currently waiting for. During the initial claim phase and ordinary passing exactly one player is eligible to act at any time.

### 3A.2 Players and deck
- Support 4–8 players.
- For `N` players there are `N` fixed chit names, each appearing exactly four times, giving `4N` physical chit instances. Each player starts with four chits.
- Chit names are fixed. Chit customization is out of scope for the early prototype.
- Matching is based on chit name, never on visual presentation.
- The future UI should display attractive, decorative, card-like chits with distinctive symbols and colours. This presentation lives outside the engine (see §5A and §7) and must never influence matching or any game rule.

### 3A.3 Initial claim phase
- Shuffle and deal four chits to every player.
- Every player receives an initial claim opportunity immediately after the deal, regardless of whether their four chits match.
- Initial opportunities are processed one at a time in deterministic order, beginning with the initiator and continuing clockwise.
- An initial claim is valid only when all four chits have the same name.
- A player explicitly claims or explicitly declines.
- If a player times out during the initial phase, an automatic decline is recorded. The engine never claims on a player's behalf.
- An eligible claim that is not valid is a false claim (§3A.5).
- Ordinary passing begins only after every initial opportunity has been resolved without a valid claim. The initiator then makes the first pass. The initiator has no further claim opportunity at that point, because the initial opportunity has already been resolved.

### 3A.4 Sequential passing and claim opportunities
- Passing is sequential and clockwise, never simultaneous.
- The initiator begins with four chits. When the initiator passes a chit it leaves their hand, so the initiator holds **three** chits for as long as the pass cycle is in progress.
- The receiver, a non-initiator during this part of the cycle, temporarily holds **five** chits: their four plus the received chit. They receive a claim opportunity while holding five. A valid claim requires at least four of those five chits to have the same name.
- A non-initiator who does not claim passes one of the five physical chit instances, including the chit just received, and returns to holding four.
- The sequence continues clockwise.
- When the chit returns to the initiator, the initiator receives it and holds **four** chits again. The initiator then has a claim opportunity. A valid initiator-return claim requires all four chits to have the same name. The returning chit is whichever chit the previous player chose to pass; it need not be the chit the initiator originally sent.
- If the initiator passes, they choose one of their four chits, return to holding three while it is in transit, and the cycle repeats.
- The initiator never holds five chits and never has a claim opportunity while holding three.
- Claim availability is determined by phase and position in the passing sequence, not by whether the chits match. Matching determines only whether an eligible claim succeeds.
- Passing forfeits the current claim opportunity until the player's next eligible opportunity.
- Claims are explicit actions. The engine never claims for a player whose hand happens to satisfy the matching condition.
- Chit delivery is atomic within the authoritative engine: the chit leaves the passer's hand and enters the receiver's hand in a single engine step. UI animation must never determine game rules.
- Because each chit name has exactly four copies, five matching chits are impossible, so "at least four of five" means exactly four of the same name.

**Hand sizes and opportunities by state** (for `N` players):

| Situation | Decision point | Hand sizes | Claim opportunity? | Claim valid only if | Chits legal to pass |
|---|---|---|---|---|---|
| Initial claim phase | each seat in turn, initiator first | all players 4 | yes (claim or decline) | all 4 same name | none (no passing yet) |
| Initiator's first pass | initiator | all players 4 | no | not applicable | any of the initiator's 4 |
| Non-initiator has received a chit | that receiver | receiver 5, initiator 3, all others 4 | yes | at least 4 of the 5 same name | any of the 5 |
| Chit has returned to the initiator | initiator | all players 4 | yes | all 4 same name | any of the 4 |

At every resting state, the chits held plus any chit being moved always total exactly `4N`, and each chit name appears exactly four times.

### 3A.5 Claims, false claims, wins, and reactions
- An eligible claim that fails the applicable matching condition is a **false claim**. For `N` players the false claimant receives `−(N−1)` points and every other player receives `0`. The round ends immediately, and no winner score is awarded.
- A false claim completes the round. The next round uses a fresh shuffle and deal and the next initiator.
- A claim by an ineligible player is rejected without applying any false-claim penalty and without changing game state or scores.
- The first valid claim accepted by the authoritative engine fixes the winner. Later claims cannot replace that winner. Because only one player is eligible at a time, the engine's single decision point enforces this.
- After a valid win, non-winners react according to the reaction-order and scoring rules; the winner does not react.
- The winner scores `N`. Other players receive `N−1`, `N−2`, …, `1` points according to reaction order.
- No general reaction timeout applies while multiple non-winners still need to react. When only one non-winner remains, that remaining reaction is resolved automatically by timeout.
- Reaction timestamps are recorded at microsecond precision where supported. Authoritative server sequence/order breaks ties; timestamps alone never decide order.
- Server-side logic validates all claims, actions, ordering, and scores. The client UI is never trusted.

### 3A.6 Rounds, rotation, and anti-stall
- The configured completed-round count is a positive multiple of `N`.
- The first initiator is seat 0. After each completed round the initiator rotates by one seat clockwise. A valid win and a false claim each complete a round.
- If the same player passes the same chit name for ten consecutive passes, the attempt ends as a **draw**.
- A draw does not consume a completed round. On a draw: reshuffle and redeal, keep the same initiator, preserve all scores, and increment the attempt number.
- Passing a different chit name resets the tracked consecutive-pass count and starts tracking the newly passed name, as specified in the existing rule.
- Simulations must provide a configurable safety cap on repeated draw restarts. Reaching the cap stops and records the run; it must never silently award points or alter game rules.
- Completed rounds and attempt numbers are tracked separately.

### 3A.7 Timeouts and reproducibility
- Pass timeout is at most 15 seconds; the room creator may choose a shorter duration.
- A timeout during passing selects one of the legal physical chit instances uniformly at random. The initiator has four legal chits whenever it passes (at the first pass and after receiving the returning chit); a non-initiator has five. A timeout at an ordinary decision point is a forced pass and never a claim.
- A timeout during the initial claim phase is recorded as an automatic decline (§3A.3).
- Simulations use seeded randomness. Separate random streams are kept for separate purposes where practical, so that a timeout does not unexpectedly change future deals.

### 3A.8 Hidden information
- Each player sees only their own current hand.
- Only sender and receiver know the identity of the transferred chit. Other players may see sender and receiver but not the chit identity.
- Agents receive only information legitimately available to their represented player.
- Private engine state must never leak into agent observations.
- One authoritative engine supports human games, mixed human/AI games, and AI-only simulations, and is independent of the UI and network layer. (Technology choices are recorded in §5A.)

## 4. Hidden information and fairness

- Each player sees only their own current hand.
- Only sender and receiver know the identity of the passed chit.
- Other players may see who passed to whom, but not the chit identity.
- Each AI receives only information available to a human in the same position.
- The simulator may maintain full private state to resolve rules, but that state must never be passed into an agent observation.
- Agent memory/history may contain only legitimately observed information.
- Add tests proving that human and AI observation payloads do not leak hidden cards.

## 5. Architecture and stack

Proposed local-first stack:
- Python
- FastAPI
- WebSockets
- HTML/CSS/JavaScript
- pytest
- CSV for experiment summaries; JSON/JSONL can be used for event logs

Suggested structure (adapt after inspecting the repository; do not duplicate existing code): **[Original 2026-10-16 suggestion, retained as history. Superseded by §5A where they differ; in particular `logging/` is renamed `eventlog/`.]**

```text
ChitAI/
├── README.md
├── PROJECT_CONTEXT.md
├── pyproject.toml or requirements.txt
├── src/chitai/
│   ├── engine/          # State, rules, transitions, scoring
│   ├── agents/          # RuleBot, SmartBot, MindBot
│   ├── observations/    # Player-specific views
│   ├── simulation/      # Seeded runs and experiment runner
│   ├── api/             # FastAPI/WebSocket interface
│   └── logging/         # Events and experiment results
├── tests/
├── web/                  # Browser UI
└── experiments/          # Configurations and analysis
```

Engineering constraints:
1. One game engine for interactive play and simulation.
2. Server-authoritative state and action validation.
3. Common agent interface with restricted observations and legal actions.
4. Reproducible experiments with seeds and configuration/version logging.
5. Test rule transitions, scoring, claims, timeouts, reshuffles, rotation, and privacy.
6. Local-first prototype; no paid API or GPU required.
7. Do not claim tests were run unless they actually were.

A conceptual common agent contract could be:

```python
def choose_action(observation, legal_actions, memory, rng):
    # Return a legal action and updated agent memory.
    ...
```

The precise signature can change; consistency and information restrictions matter most.

## 5A. Adopted architecture and module responsibilities (finalized 2026-10-17)

**Status: planned design. [Update 2026-10-17: the Milestone 1 modules `engine/config.py`, `chits.py`, `rng.py`, `deal.py` now exist; all other modules remain planned and are not created.] **[Update 2026-10-17: the Milestone 2 modules `engine/state.py`, `actions.py`, `events.py`, `rules.py`, `invariants.py`, `engine.py` now exist; `scoring.py` and all non-engine packages remain planned.]** **[Update 2026-10-17: Milestone 3 adds no new module; it extends `actions.py` (`PassAction`), `state.py` (new decision kinds, `claim_decision_kind`), `events.py` (`ChitPassed`, `ClaimMade`), `rules.py`, `invariants.py` and `engine.py`.]** **[Update 2026-10-17: Milestone 4 adds `engine/scoring.py` (false-claim penalty only; win and reaction scoring remain M5) and extends `deal.py` (`rotation_initiator`), `state.py` (`Phase.GAME_OVER`), `events.py` (`FalseClaimPenalized`, `RoundCompleted`, `GameCompleted`), `invariants.py` and `engine.py`.]** **[Update 2026-10-17: Milestone 5 adds no new module; it extends `actions.py` (`ReactAction`), `state.py` (`reaction_order`), `events.py` (`PlayerReacted`, `ValidWinScored`, outcome `"valid_win"`), `scoring.py` (win and reaction scores), `rules.py` (`pending_reactors`, reaction `legal_actions`), `invariants.py` (reaction and score checks) and `engine.py` (`_apply_react`, `_complete_valid_win`, shared `_close_round`).]** **[Update 2026-10-18: Milestone 6 adds no new module; it extends `actions.py` (`TimeoutAction`), `state.py` (`pass_streaks`), `events.py` (`DecisionTimedOut`, `AttemptDrawn`), `rng.py` (the `TIMEOUT` stream label), `rules.py` (`CONSECUTIVE_PASS_LIMIT`, `update_pass_streaks`, `timeout_action`), `invariants.py` (streak checks) and `engine.py` (`_apply_timeout`, `timeout_chit`, `_draw_attempt`, the anti-stall check in `_apply_pass`).]** **[Update 2026-10-18: Milestone 7 adds the `observations/` package (`observation.py`, `legal.py`, `events.py`) *above* the engine and changes no engine file. The engine does not import it.]** Modules are created only when their milestone begins; none are created in advance as empty placeholders.

### Technology decisions
- Python 3.12-compatible code; pytest for automated tests.
- The core engine uses the Python standard library wherever practical. No dependency is installed before the milestone that needs it; Milestone 1 needs only pytest as a development dependency.
- FastAPI and WebSockets for the interactive server (later milestone); HTML/CSS/JavaScript for the browser UI.
- JSON/JSONL for event logs and CSV for experiment summaries.
- No paid APIs and no GPU requirement.
- `src/chitai/` package layout.
- The application package must not be named `logging` (it would be confused with Python's standard-library module); the event and result logging package is `eventlog`.

### Planned layout
```text
ChitAI/
├── pyproject.toml            # M1: project metadata and pytest configuration
├── README.md
├── PROJECT_CONTEXT.md
├── src/chitai/
│   ├── __init__.py           # M1
│   ├── engine/               # M1 package; later modules listed below
│   ├── agents/               # later
│   ├── observations/         # later
│   ├── simulation/           # later
│   ├── api/                  # later
│   └── eventlog/             # later
├── tests/                    # M1: tests/engine/
├── web/                      # later: browser UI
└── experiments/              # later: configurations and analysis
```

### Module responsibilities
| Module | Milestone | Responsibility |
|---|---|---|
| `engine/config.py` | M1 | `GameConfig` and validation: 4–8 players; completed-round count a positive multiple of N; pass timeout at most 15 seconds; seed. |
| `engine/chits.py` | M1 | Fixed chit names and physical chit instances; deck construction (`N` names × 4 copies). Matching by name only. |
| `engine/rng.py` | M1 | Seeded, purpose-separated random streams (for example deal vs. timeout) derived deterministically from the master seed, so a timeout cannot change later deals. Justified now because seeded dealing needs it. |
| `engine/deal.py` | M1 | Seeded dealing of four chits per player, and starting-player rotation (initiator for a given completed-round index). |
| `engine/state.py` | M2 (extended in M3) | Phase, decision point, hands, chit movement, completed-round and attempt counters, scores. |
| `engine/actions.py` | M2 (extended in M3) | Player actions (claim, decline, pass, and engine-generated timeout actions, later reactions). |
| `engine/events.py` | M2 (extended in M3) | Sequenced events with separate public and private views. |
| `engine/rules.py` | M2 (extended in M3) | Pure rule functions: claim eligibility, claim validity (four-of-four, four-of-five), legal actions. |
| `engine/invariants.py` | M2 (extended in M3) | Checks for hand sizes, `4N` total chits, four copies per name, and phase/decision-point consistency. |
| `engine/engine.py` | M2 (extended in M3) | The single authoritative engine: validates and applies actions; rejected actions leave state unchanged. |
| `engine/scoring.py` | later *[Update: false-claim penalty added in M4; win and reaction scores are M5]* | False-claim penalties, win scores, reaction-order scoring, tie-breaking by authoritative sequence. *[M4: only `false_claim_penalty` and `false_claim_score_changes` exist.]* *[M5: adds `winner_score`, `reaction_score`, `valid_win_round_total` and `valid_win_score_changes`; reaction order is the engine's accepted-action (sequence) order.]* |
| `agents/` | later | RuleBot, SmartBot, MindBot behind one interface. |
| `observations/` | later *[Update 2026-10-18: M7 — `observe(state, seat)` and `Observation`; `legal_actions_for(state, seat)`, name-based `NamePassAction` and `to_engine_action`; `observe_event` and `observe_events`. Reads engine state only; no engine change.]* | Player-specific, privacy-safe views and legal-action lists. |
| `simulation/` | later | Seeded AI-only runs, draw safety cap, batch/experiment runner. |
| `eventlog/` | later | JSONL event logs and CSV summaries. |
| `api/` | later | FastAPI/WebSocket interface over the same engine. |
| `web/` | later | Browser UI. Chit symbols and colours live here as a presentation lookup keyed by chit name. |

### Core design concepts (no code exists yet)
- **State** explicitly represents: the current phase (initial claims or ordinary passing); each player's hand, including the initiator's three-chit hand while a chit is in transit and a receiver's temporary five-chit hand; the current decision point and its kind (initial claim, initiator first pass, non-initiator receive, initiator return); completed-round count and attempt number separately; and scores.
- **Hand sizes and transitions** are enforced inside the authoritative engine, never in the UI.
- **Action results** are either accepted (producing events) or rejected with a reason. A rejected action leaves game state and scores unchanged. Violations of internal invariants indicate engine bugs and raise errors.
- **Randomness** uses separate streams for dealing and for timeouts. Seeds are derived deterministically (not with Python's built-in `hash()`, which varies between runs).
- **Presentation separation:** the engine knows chit names only.

### Additional engineering constraints (added 2026-10-17)
8. Hand-size and claim-eligibility invariants are enforced and tested at every state transition.
9. Presentation (symbols, colours, animation) is separate from engine logic and never affects rules.
10. Completed rounds and draw attempts are tracked separately.
11. Initial-phase automatic declines and timeout-forced passes are recorded as such, and a timeout never produces a claim.

## 6. Simulation and research logging

Build the simulation runner early, before polishing the UI. It must run without launching the web server.

At minimum, log per game:
- Run/experiment ID and random seed.
- Player count and round count.
- Agent type, version/configuration, and seat assignment.
- Winner/rank and final scores.
- False claims, timeouts, and forced reshuffles.
- Completed-round index and attempt number for each event, draw restarts, and whether the draw safety cap ended the run.

Where practical, log events such as round starts, starting player, public pass participants, claim attempts/results, reaction order, score changes, and timeout/anti-stall events. Never expose hidden card identities in agent-visible event streams. Keep any private debugging log separate from observations.

Make batches repeatable from saved configurations and seeds; export summaries to CSV.

## 7. UI and multiplayer scope

Core UI:
- Create/join room and configure player/round counts.
- Human-only, mixed human/AI, and AI-only play.
- Show the current player's own hand and decision state.
- Show public turn/pass information without leaking chit identities.
- Explicit claim/pass actions.
- Round result, reaction order, scores, and standings.
- Attractive, decorative, card-like chits with distinctive symbols and colours, kept separate from engine logic (matching is by chit name only; see §3A.2 and §5A).

Local browser play is desired. Same-Wi-Fi local-network access is also desirable; test it early if it is a priority rather than assuming localhost works across devices.

Stretch features: public chat, disconnect recovery/reconnection, more agent personalities, tournaments, and richer analytics. These must not delay core rules, privacy, or simulation correctness.

## 8. Delivery priorities

1. Inspect the repository and align this context document with the agreed rules. *[Documentation aligned 2026-10-17; implementation not started.]*
2. Implement the pure game engine and unit tests.
3. Implement restricted player observations and privacy tests.
4. Implement RuleBot and seeded AI-only simulation.
5. Implement SmartBot and compare it with RuleBot; consider MindBot after the core prototype is stable.
6. Produce reproducible logs and metric summaries.
7. Add a basic browser UI using the same engine.
8. Test mixed rooms and local-network access if time permits.
9. Write the report using actual implementation and experimental results.

Avoid starting with a complex UI or adding advanced algorithms before the rules and baseline experiment work reliably.

### 8A. Milestone roadmap (added 2026-10-17)

The order follows the delivery priorities above. Only Milestone 1 is fixed; later milestones are indicative and may be re-sliced when they begin. A milestone is complete only when its tests have actually been run and the results recorded in the change log.

**M1 — Scaffolding, configuration, deck, seeded deal, rotation (strictly limited)** *[Implemented and tested 2026-10-17; see Change Log. Update: merged into `main` via PR #3.]*:
1. `pyproject.toml` and pytest configuration.
2. Minimal `src/chitai/engine` package.
3. `GameConfig` and validation.
4. Fixed-name deck construction.
5. Seeded dealing.
6. Starting-player rotation.
7. Unit tests for the above.
8. Basic README setup and testing instructions (written when M1 exists, so that every documented command is real).

M1 explicitly excludes passing, claims, scoring, reactions, timeouts, anti-stall, agents, simulations, and the browser UI.

**Later milestones (indicative):**
- M2: state, actions, events, invariants, and the initial claim phase (claim, decline, deterministic order). *[Implemented and tested 2026-10-17 on `feature/milestone-2-initial-claims`; see Change Log. Update: merged into `main` via PR #4 (merge commit `f2e4753`).]*
- M3: sequential passing and ordinary claim opportunities, with hand-size and eligibility invariants. *[Implemented and tested 2026-10-17 on `feature/milestone-3-passing`; see Change Log. Update: merged into `main` (merge commit `5b2256e`).]*
- M4: false claims, round completion, rotation by completed round, and multi-round games. *[Implemented and tested 2026-10-17 on `feature/milestone-4-round-completion`; see Change Log. Awaiting owner review.]* *[Update: merged into `main` (`dde4bda`) per the owner.]*
- M5: reactions and scoring, including authoritative sequence tie-breaking. *[Implemented and tested 2026-10-17 on `feature/milestone-5-valid-win-resolution`; see Change Log. Awaiting owner review.]* *[Update 2026-10-18: merged into `main` (`089f3c4`, PR #7).]*
- M6: timeouts, forced passes, anti-stall draws, attempt tracking, and the simulation draw cap. *[Implemented and tested 2026-10-18 on `feature/milestone-6-timeouts-anti-stall`; see Change Log. Awaiting owner review. The simulation draw cap is *not* part of the engine: it belongs to the M8 simulation runner (§9 question 5, §9 question 24).]*
- M7: privacy-safe observations, legal-action lists, and privacy tests. *[Implemented and tested 2026-10-18 on top of `main` at `62c832f`; see Change Log. Awaiting owner review. Runner-level action validation and generic agent-facing errors are M8, not M7.]*
- M8: RuleBot, seeded AI-only simulation runner, JSONL event logs, CSV summaries.
- M9: SmartBot and comparison experiments; MindBot if time permits.
- M10: FastAPI/WebSocket server and the browser UI using the same engine.

## 9. Agreed implementation rules and remaining engineering details

The following gameplay choices have been supplied or confirmed by the project owner and must not be reopened casually:

- **Initial deal claim window:** Every player receives an initial claim opportunity as soon as their four initial chits have been revealed to them. A valid initial claim requires four identical chits. *[Refined 2026-10-17 → §3A.3: processed in deterministic order from the initiator clockwise; explicit claim or decline; a timeout is an automatic decline.]*
- **[SUPERSEDED 2026-10-17 → §3A.4: the initiator's claim opportunity occurs only in the initial phase and when the passed chit returns (initiator holds four). Never while holding three. The non-initiator part remains valid.]** **Initiator claim availability:** On subsequent turns, the initiator's claim option is available while they hold four chits, whether or not they match. A non-initiator gets the claim option when holding the temporary five-chit hand after receiving a chit. Claim validity is always checked against the matching rule.
- **Pass timeout:** Randomly pass one of the five chits when the player runs out of time. Use seeded randomness for reproducible simulations. *[Clarified 2026-10-17 → §3A.7: uniform among the legal physical chit instances — five for a non-initiator, four for the initiator.]*
- **Anti-stall:** Ten consecutive passes of the same chit name by the same player cause the round to restart as a draw. The same initiator starts again, and no score changes for the drawn round. *[Clarified 2026-10-17 → §3A.6: a draw does not consume a completed round; the attempt number increments.]*
- **Reaction timeout:** Do not apply a general timeout while multiple non-winners still need to react. When only one non-winner remains to react, resolve that remaining reaction automatically by timeout.
- **Reaction ordering:** Record reaction timestamps to microsecond precision. Use authoritative server receipt/sequence order as the deterministic tie-breaker if timestamps are equal; timestamps alone are not sufficient.
- **Round count:** For N players, the room creator chooses a positive number of rounds that is a multiple of N (N, 2N, 3N, ...), ensuring full starting-player rotations.
- **Starting player:** Rotate the initiator by one seat between rounds. An anti-stall draw restarts with the same initiator. *[Refined 2026-10-17 → §3A.6: the first initiator is seat 0; rotation happens after each completed round.]*
- **Claims:** The first valid claim accepted by the authoritative server wins. False claims end the round with the documented penalty. *[Clarified 2026-10-17 → §3A.5: an ineligible claim is rejected without penalty; a false claim completes the round.]*

### Engineering details to implement and test

1. Validate whether chit names are fixed or configurable; do not invent a user-facing customization feature unless needed. **[RESOLVED 2026-10-17: chit names are fixed and customization is out of scope for the early prototype — §3A.2.]**
2. Specify the exact public event history available to agents. Private information may only be retained by an agent if that agent legitimately observed it. *[Open — scheduled for the observations milestone (M7).]* *[RESOLVED 2026-10-18, M7, on the owner's M7 decisions: the agent-visible history is each event's `public_view()` plus only legitimately observed private data: a seat's own dealt hand in its `DealEvent` view, and the passed chit's name in the `ChitPassed` view of the sender and the receiver only. `debug_view()` is never used for an agent-facing view. See §9 questions 29–32.]*
3. Implement claim/reaction event ordering using a single authoritative server sequence and record timestamps at microsecond precision where supported. *[Open — scheduled for the reaction/scoring milestone (M5).]* *[Update 2026-10-17, M5: the single authoritative sequence part is implemented: reaction order is the order in which the engine accepts `ReactAction`s, and every event carries a contiguous `seq`. Recording microsecond timestamps is NOT done by the engine, which has no clock; it remains open for the transport and logging layers (M8/M10). See §9 question 18.]*
4. Ensure a timeout-selected chit is chosen from the player's legal five-chit options and uses the seeded RNG in simulation. **[RESOLVED/CLARIFIED 2026-10-17: legal options are the player's held chits — five for a non-initiator, four for the initiator — §3A.7.]**
5. Add tests for anti-stall round restart, same initiator, unchanged score, and counter resets. *[Scheduled for M6; must also cover completed-round vs. attempt tracking.]* *[Update 2026-10-18, M6: done; see `tests/engine/test_anti_stall.py`.]*
6. If any historical detail conflicts with this summary, flag it for the owner instead of silently changing the rules.


### Open questions (genuinely unresolved as of 2026-10-17)
All other gameplay and architecture decisions are settled and recorded in §3A and §5A. None of the following blocks Milestone 1.
1. **Reaction mechanics for simulation:** how a "reaction" is represented, and how reaction order or latency for AI agents is modelled (for example a seeded latency model). Decide before the reaction/scoring milestone (M5). *[PARTLY RESOLVED 2026-10-17, M5, on the owner's M5 brief: a reaction is an explicit engine action, `ReactAction(seat)`, and the authoritative engine's accepted-action order is the reaction order. No sleeps, timers, network latency or wall-clock scheduling exist in the engine. How a seeded latency model for AI agents would *generate* reaction actions remains open and is not part of M5 (see question 18).]*
2. **"Reacted/claimed" wording:** the earlier rule text says "reacted/claimed". It is interpreted as "reacted" because only one player can claim at a time. Owner confirmation pending. *[Update 2026-10-17, M5: unchanged and still pending. M5 implements it by letting every non-winner react explicitly, including the last one (question 19).]*
3. **Timer for initial claim opportunities:** the duration is not separately specified. Proposed default: the room's configured decision timeout (at most 15 seconds). *[Update 2026-10-18, M6: the engine has no clock, so it needs no duration. The host issues `TimeoutAction` when its own timer expires and should use `GameConfig.pass_timeout_seconds` (greater than 0, at most 15) for initial claims, passes and the last reaction. Provisional; see question 25.]*
4. **Anti-stall details:** proposed defaults, to be confirmed before M6: the draw is declared at the moment the tenth consecutive same-name pass is made (that chit is not delivered); the count is kept per player; timeout-forced passes and initiator passes count like any other pass; counts start fresh on every new attempt. *[RESOLVED 2026-10-18, M6, on the owner's M6 instruction: the tenth consecutive same-name pass by one player triggers the draw and that chit is not delivered; streaks are per player and per chit name (different physical copies count toward the same streak; a different name restarts that player's count at one; another player's pass never changes it); forced and initiator passes count like any other pass; streaks start empty in every new attempt and round. Implemented as specified. See questions 26-27.]*
5. **Draw safety cap:** the behaviour is settled (stop and record, never award points). The default cap value and the recorded outcome format are chosen at the simulation milestone. *[Update 2026-10-18, M6: confirmed as a simulation-runner responsibility; not implemented in the engine. See question 24.]*
6. **Round-end reveal:** whether a claimed hand is publicly revealed at round end, which affects what agents may legitimately observe. Decide at the observations milestone (M7). *[RESOLVED 2026-10-18, M7, on the owner's decision (Option A): the claimant's hand and the other players' hands are **not** revealed at round end, and no hand-reveal event exists. Claim validity stays public as already defined (§9 question 9). Observers therefore never learn what a claimant held.]*
7. **Final ranking ties:** how equal total scores are ranked in summaries (shared rank or a tie-break rule). Decide when multi-round summaries are implemented.
8. **M2 holding phases (added 2026-10-17):** M2 stops at `WIN_DECLARED` / `FALSE_CLAIM` without scoring or incrementing `completed_rounds`, because those belong to M5 and M4. Owner to confirm that M4/M5 should extend these phases rather than replace them. *[Update 2026-10-17: M3 sends claims made during ordinary passing to the same two holding phases, with the same limits.]* *[Update 2026-10-17, M4: `FALSE_CLAIM` is no longer a resting phase; the engine completes a false-claim round inside the claiming action. `WIN_DECLARED` remains the M5 holding phase, so the owner's question now concerns only that phase.]* *[RESOLVED in implementation 2026-10-17, M5: `WIN_DECLARED` is extended, not replaced. It is now the reaction phase (winner fixed, `reaction_order` collecting). The owner may still veto the choice at review.]*
9. **Public claim event (added 2026-10-17):** the public view of a claim event states the claimant and whether the claim was valid, but not the claimant's hand. This is a provisional choice pending open question 6 (round-end reveal, M7); only the private debug view contains the hand. *[RESOLVED 2026-10-18, M7: confirmed by the owner's Option A for question 6; claim views stay public as validity only.]*
10. **Pass addressing (added 2026-10-17, M3):** a `PassAction` names one *physical chit instance* (§3A.4: "one of the five physical chit instances"), not a chit name. Agents and UIs that think in names must map a name to an instance of their own choosing; the engine never picks between two copies on a player's behalf. Provisional; owner to confirm. *[Update 2026-10-18, M7: the engine is unchanged and still addresses physical instances. The agent-facing interface uses chit names only (question 29).]*
11. **No decline during passing (added 2026-10-17, M3):** §3A.4 says passing forfeits the current claim opportunity, so a player who does not claim simply passes. `DeclineAction` therefore exists only in the initial claim phase and is rejected (`action_not_available`) during passing. Owner to confirm this reading.
12. **No stall limit before M6 (added 2026-10-17, M3):** nothing yet ends an endless pass cycle (anti-stall draws are M6, §9 question 4). Callers, including tests, must bound their own loops until then. *[RESOLVED 2026-10-18, M6: the tenth consecutive same-name pass by one player now ends the attempt as a draw. A pass cycle can still be endless if players keep varying chit names, and timeouts never claim, so callers must still bound their own loops.]*
13. **False claim completes the round atomically (added 2026-10-17, M4):** one accepted claim returns the claim event, the penalty event, the round-completed event and then either the next round's `DealEvent` or `GameCompleted`; there is no separate "continue" action and the caller never sees a resting `FALSE_CLAIM` state. Provisional; owner to confirm. `Phase.FALSE_CLAIM` stays in the enum as an internal transient phase so the claim-consistency invariants still validate the claim before it is converted.
14. **Terminal state shape (added 2026-10-17, M4):** `Phase.GAME_OVER` has `completed_rounds == num_rounds`, attempt 1, initiator `completed_rounds % N` (seat 0, because the round count is a multiple of N), no decision point and no outcome fields. It keeps the hands of the final claim (the board as it ended; a receiver's claim leaves one five-chit and one three-chit hand), so chit conservation still holds. Provisional; owner to confirm.
15. **Score invariants are M4-specific (added 2026-10-17, M4):** `check_invariants` requires every score to be zero or a negative multiple of N-1, with at most one penalty per completed round. M5 introduces positive scores and must revise this check. Scores are public information, so the new events' public views include them. *[RESOLVED 2026-10-17, M5: the check is revised. Each seat must lie in [-(N-1)R, N*R] after R completed rounds, and the total must equal W*N(N+1)/2 - F*(N-1) for some W valid wins and F false claims with W+F <= R. The M4 negative-penalty scores remain valid.]*
16. **Attempt numbering across rounds (added 2026-10-17, M4):** a round that begins after a completed round always starts at attempt 1, as the M4 brief requires, and a finished game has attempt 1. Draw attempts (M6) will increment it within a round.
17. **Valid-claim games do not progress yet (added 2026-10-17, M4):** a valid claim still stops at `WIN_DECLARED` with no scores and no completed round. A game cannot be played to its end through valid wins until M5. *[RESOLVED 2026-10-17, M5: a valid claim now leads to reactions, scoring and round completion; see questions 18–23.]*
18. **Reaction timestamps and latency (added 2026-10-17, M5):** the engine consumes only the *order* of `ReactAction`s. Microsecond receipt timestamps (§3A.5, "where supported") are not recorded by the engine, which has no clock; the transport layer (M10) and the experiment log (M8) are the intended places. A seeded latency model for AI agents (later milestone) would turn sampled latencies into an action order before calling the engine. Provisional; owner to confirm.
19. **The last non-winner reacts explicitly (added 2026-10-17, M5):** §3A.5 says the last remaining reaction is resolved by timeout. Timeouts are M6, so in M5 the last non-winner also sends a `ReactAction`; there is never a stuck state. The last reactor always scores 1 whenever it acts, so no score depends on its timing. Alternative considered and not taken: auto-resolve the last reaction at once (score-equivalent, but it would bake a timeout meaning into M5 and drop the last player's action from the log). Open for M6: whether a timed-out reaction is the same action with a flag or a separate action/event. Provisional; owner to confirm. *[RESOLVED 2026-10-18, M6: a timed-out final reaction is a separate `TimeoutAction` that reuses `_apply_react` unchanged; the `ReactAction` is untouched. It is accepted only for the last remaining non-winner, is preceded by a `DecisionTimedOut` marker event with `decision_kind` `"final_reaction"`, and scores identically to an explicit reaction (the last reactor always scores 1). The explicit last `ReactAction` remains valid.]*
20. **Reaction eligibility (added 2026-10-17, M5):** all non-winners are eligible at the same time and may react in any order (there is no reaction turn order), because reaction order is what sets the scores. The winner never reacts. Provisional; owner to confirm.
21. **Atomic win completion (added 2026-10-17, M5):** as for a false claim (question 13), the last reaction scores the round, increments `completed_rounds` and starts the next round or `GAME_OVER` inside one `apply_action`; the returned events are `PlayerReacted`, `ValidWinScored`, `RoundCompleted` (outcome `"valid_win"`), then `DealEvent` or `GameCompleted`. A `WIN_DECLARED` state with all N-1 reactions is validated internally but never returned. `RoundCompleted.claimant` holds the winner for a valid win. Provisional; owner to confirm.
22. **Reactions are public (added 2026-10-17, M5):** `PlayerReacted` and `ValidWinScored` show seats, positions and scores and no chit identities, so they are public. Provisional pending the observations milestone (M7). *[RESOLVED 2026-10-18, M7: confirmed public; they appear unchanged in every seat's event view.]*
23. **Rejection reasons for reactions (added 2026-10-17, M5):** `winner_cannot_react`, `already_reacted`; a reaction outside the reaction phase is `action_not_available`; any action after `GAME_OVER` is `phase_not_accepting`; a claim, decline or pass during the reaction phase stays `phase_not_accepting`. Provisional.
24. **Draw safety cap placement (added 2026-10-18, M6):** the §8A roadmap line for M6 lists "the simulation draw cap" and the M1 change-log entry says the cap "belongs to M6", but §3A.6 says *simulations* must provide it, the §5A table assigns it to `simulation/`, §9 question 5 says its default value and outcome format are chosen "at the simulation milestone", and the §10 item is titled "Simulation draw safety cap". M6 treats the cap as a runner responsibility (M8) and adds **no** engine-level cap, no `GameConfig` field and no runner. The engine exposes everything a runner needs (`state.attempt`, the `AttemptDrawn` events) and never silently awards points. The wording conflict is recorded rather than resolved silently. Owner to confirm.
25. **Timeouts are host-issued (added 2026-10-18, M6):** `TimeoutAction(seat)` is not a player choice and is deliberately absent from `legal_actions` (which is unchanged). The engine validates only that a timeout is *available*; it cannot verify that time elapsed, because it has no clock (engineering constraint: no timers, sleeps or threads). A malicious or buggy host could therefore time a player out early; transport-layer trust (M10) is the place to guard that. A host exposes availability through `timeout_action(state)`. Provisional; owner to confirm. *[M7: `legal_actions_for` never returns a `TimeoutAction` and `to_engine_action` refuses one, so a timeout is never agent-selectable.]*
26. **Timeout and draw events (added 2026-10-18, M6):** an accepted timeout emits `DecisionTimedOut(seat, decision_kind)` *before* the ordinary events it resolves (`InitialClaimDeclined`, `ChitPassed`, `PlayerReacted` ...), which keep their shape; existing events and public views were not changed. `AttemptDrawn(seat, consecutive_passes, reason)` carries the round and attempt that *ended* and is followed by a `DealEvent` carrying the new attempt. The public views never contain a chit name, so players learn *that* a seat stalled but not which name; the private debug view of `AttemptDrawn` adds the chit. The tenth chit emits no `ChitPassed`. Provisional pending the observations milestone (M7). *[RESOLVED 2026-10-18, M7, on the owner's decision: `DecisionTimedOut` and `AttemptDrawn` stay public with their existing schema in every seat's view. Neither reveals the forced or the triggering chit to anyone, and the tenth chit is not revealed privately to the passer either (the passer's view of `AttemptDrawn` equals the public one). A forced pass is an ordinary `ChitPassed`, so its sender and receiver learn the chit as for any pass.]*
27. **A draw re-enters the initial claim phase (added 2026-10-18, M6):** a redeal is an ordinary fresh deal, so §3A.3 gives every seat an initial claim opportunity again (initiator first), and passing begins only after all are resolved. Provisional; owner to confirm. Related: the forced-pass stream is keyed by (master seed, completed round, attempt, next sequence number) on the sorted hand, which is deterministic for a given state but means the same hand at a different sequence number can force a different chit.
28. **Reaction timeout limited to the last non-winner (added 2026-10-18, M6):** `TimeoutAction` in the reaction phase is rejected with `timeout_not_available` unless exactly one non-winner remains (§3A.5), including for the winner and for seats that already reacted when several are pending. When one remains, a timeout by any other seat is rejected with `winner_cannot_react` or `already_reacted`. Provisional.
29. **Name-based agent actions (added 2026-10-18, M7, owner decision):** agent-facing observations, legal actions and event views use chit *names* and never a physical copy id. The agent-facing pass is `NamePassAction(seat, chit_name)`; `to_engine_action(state, action)` returns the engine action only when the action is exactly one of `legal_actions_for(state, action.seat)`, and maps a name to the held chit of that name with the **lowest copy index** (otherwise `None`, with no message). The copy chosen has no game effect, since matching is by name, and copy ids are never shown, so it cannot leak a sender's remaining hand. Claim, decline and react carry only a seat and reuse the engine classes. `legal_actions_for` filters and relabels the engine's `legal_actions`; no rule is duplicated. Its order is deterministic and independent of hand order (claim, decline or react, then passes sorted by name).
30. **Per-seat event views (added 2026-10-18, M7, owner decision):** `observe_event(event, seat)` is the event's `public_view()` plus, for `DealEvent`, `my_hand` (the seat's own dealt names, sorted) and, for `ChitPassed`, `chit_name` for the sender and receiver only. `seat=None` gives the purely public view. Claim, `DecisionTimedOut`, `AttemptDrawn` and every other event are public only; nothing reveals a hand at round end (question 6). The global `seq` is kept. Inherent public disclosures remain by rule: claim validity, and the fact that a seat made ten consecutive same-name passes (a draw).
31. **Own anti-stall streak (added 2026-10-18, M7, owner decision):** `Observation.my_pass_streak_name` and `my_pass_streak_count` (None and 0 when absent) carry the observer's own entry of `GameState.pass_streaks`; other seats' entries are never read, because their counts would reveal that consecutive passes shared a name to everyone but the receiver.
32. **Observation shape (added 2026-10-18, M7):** an `Observation` holds primitives and tuples only (to_dict gives JSON): public fields (`num_players`, `num_rounds`, `pass_timeout_seconds`, `chit_names`, `completed_rounds`, `attempt`, `initiator`, `phase`, `decision_seat`, `decision_kind`, `scores`, `hand_sizes`, `winner`, `reaction_order`, `pending_reactors`, `my_turn`) and private fields (`my_seat`, `my_hand` as sorted names, the own streak). Never exposed: `GameState`, `GameConfig` (its `seed` reconstructs every past and future deal), other hands, other streaks, copy ids, `timeout_chit`, debug views. `hand_sizes` is public (it follows from phase and position). In `game_over` the hands are those of the final claim (question 14). `observe` and `legal_actions_for` raise `ValueError` for an invalid seat, a host error; there is **no** agent-error framework in M7. Provisional; owner to confirm. **M8 boundary:** the runner must build actions with the agent's own seat, accept only actions `in legal_actions_for(state, own_seat)`, translate them with `to_engine_action`, and send generic payload-free errors to agents, because `apply_action` trusts `action.seat` and its `Rejected` messages may echo chit data.

## 10. Definition of done

- [ ] Documented and deterministic rules where needed.
- [ ] Engine supports 4–8 players and valid round counts.
- [ ] Passing, claims, false claims, reaction order, and scoring tested. *[M3: passing and ordinary claims tested; false-claim penalty, reactions and scoring are M4/M5.]* *[M4: false-claim penalty, round completion and multi-round progression tested; reaction order and win scoring are M5.]* *[M5: reaction order and valid-win scoring are tested at the engine level. Left unticked for the owner to tick at review.]*
- [ ] Timeout and anti-stall policies implemented and tested. *[M6: implemented and tested at the engine level (host-issued timeouts, forced passes, initial-claim automatic decline, last-reaction timeout, ten-pass anti-stall draw). Left unticked for the owner to tick at review.]*
- [ ] Observation privacy tests pass. *[M7: observation, legal-action, event-view and privacy tests (including hidden-twin and sender/receiver positive controls) exist and pass at the engine-plus-observation level. Left unticked for the owner to tick at review.]*
- [ ] RuleBot completes AI-only games.
- [ ] At least one additional agent can be compared with RuleBot.
- [ ] Seeded simulations produce repeatable logs.
- [ ] CSV results can be summarized.
- [ ] Basic browser UI uses the same engine.
- [ ] Mixed human/AI play tested if included in the promised scope.
- [ ] Research conclusions supported by actual results and limitations.
- [ ] Hand-size and claim-eligibility invariants enforced and tested at every transition. *[M3: enforced and tested for initial-phase and passing-phase states, including the three-chit initiator, five-chit receiver and chit-returned states and the outcome states of passing-phase claims. Stays unticked: false-claim scoring, reactions and draws add transitions in later milestones.]* *[M4: also enforced and tested for false-claim round completion, the next-round start, the terminal state and score values; stays unticked because valid-win scoring, reactions and draws add transitions.]* *[M5: also enforced and tested for the reaction phase, valid-win completion, the next-round start and `GAME_OVER` after a win, and for positive scores; stays unticked because draws (M6) add transitions.]* *[M6: also enforced and tested for timeout transitions, draws and redeals (streak invariants, fresh deal after a draw); every transition now exists, so the owner may tick this at review.]*
- [ ] Initial claim order, automatic decline on timeout, and ineligible-claim rejection tested. *[M2: initial claim order and ineligible-claim rejection tested; automatic decline on timeout is not implemented (M6).]* *[M6: automatic decline on timeout is implemented and tested (`TimeoutAction` in the initial phase equals a decline). Left unticked for the owner to tick at review.]*
- [ ] Completed rounds and draw attempts tracked separately and tested. *[M4: completed rounds are tracked and tested, including attempt restarting at 1 for each new round; draw attempts are M6, so this stays unticked.]* *[M6: draws increment the attempt without changing `completed_rounds`, scores or the initiator; tested, including attempt 3 and the restart at attempt 1 in the next round. Left unticked for the owner to tick at review.]*
- [ ] Simulation draw safety cap implemented and tested. *[M6: intentionally not implemented in the engine; it belongs to the M8 simulation runner (§9 questions 5 and 24). Stays unticked.]*
- [ ] README contains setup and run instructions. *[Setup and test instructions exist as of M1; there is nothing to run yet, so this stays unticked.]*

## 11. Collaboration workflow

For each substantial change:
1. Inspect existing files before editing.
2. Propose a small, scoped change.
3. Do not overwrite files or remove prior decisions without approval.
4. Add/update tests and run them.
5. Report exact files changed and actual test results.
6. Record decisions, changes, tests, and next actions in a dated changelog entry.
7. Keep this context document append-only for project history.

## 12. Change log

### 2026-10-16 — Initial consolidated context
- Consolidated the current game rules, research question, candidate agents, architecture, privacy requirements, simulation goals, delivery priorities, and open decisions.
- Confirmed public repository `vyavaharep04-cloud/ChitAI`, default branch `main`.
- Repository was at initial setup with a minimal README when last inspected; inspect the live repository before assuming implementation files exist.
- An earlier GitHub integration write attempt returned `403 Resource not accessible by integration`; after the user updated access, branch creation succeeded.
- Created feature branch `docs/add-project-context`, added this document, opened PR #1, and the owner merged it into `main`.
- Owner clarified additional rules: initial claim window for everyone after their initial four chits are revealed; random chit pass on timeout; initiator claim option while holding four regardless of match; non-initiator claim option on receiving a fifth chit; anti-stall restarts the round as a draw with the same initiator and unchanged score; reaction timeout only when one non-winner remains; microsecond reaction timestamps with deterministic server-order tie-breaking; round counts N, 2N, 3N, etc.
- Next: inspect the repository in VS Code, implement engine and tests before UI, and keep this context synchronized with actual code.

### 2026-10-16 — Rules clarified before implementation
- Recorded the project owner's explicit decisions for initial claims, initiator/non-initiator claim availability, random pass timeout, anti-stall draw restart, reaction timeout, microsecond reaction timestamps with server-order tie-breaking, and round-count multiples of player count.
- Updated delivery priorities to start implementation rather than reopen already-decided gameplay questions.
- No application code or tests were changed or run as part of this documentation update.

### 2026-10-17 — Final gameplay rules and architecture recorded
- **Type of change:** specification and architecture update only. No application code was written, and no tests were implemented or run, as part of this documentation change.
- Added §3A as the authoritative gameplay-rule and claim-lifecycle section, and §5A (adopted architecture and module responsibilities) and §8A (milestone roadmap).
- Recorded: fixed chit names (customization out of scope); initial claims processed in deterministic order from the initiator clockwise, with explicit claim or decline and an automatic decline on timeout; sequential clockwise passing; atomic chit delivery; the initiator's three-chit state while a chit is in transit and four-chit claim opportunity when the chit returns; five-chit claim opportunity for non-initiators only; ineligible claims rejected without penalty; false claims complete the round; rotation after each completed round starting at seat 0; draws do not consume a completed round and increment the attempt number; a configurable simulation draw cap; timeouts choose uniformly among legal physical chit instances (five for non-initiators, four for the initiator) and never claim.
- Reconciled earlier wording: the older claim bullets in §3 and §9 are retained with **SUPERSEDED** or *Clarified* tags pointing to §3A; engineering details 1 and 4 are marked resolved; the `logging/` package is renamed `eventlog/`.
- Milestone 1 scope fixed as: `pyproject.toml` and pytest configuration; minimal `src/chitai/engine` package; `GameConfig` and validation; fixed-name deck construction; seeded dealing; starting-player rotation; unit tests; basic README setup and testing instructions.
- Definition-of-done checkboxes added but none ticked; no implementation milestone has been completed.
- Open questions are recorded in §9 and none blocks Milestone 1.
- Next: commit this documentation change on a docs branch for review, then begin Milestone 1.

### 2026-10-17 — Milestone 1 implemented (local, uncommitted)
- **Scope:** exactly the M1 list in §8A: `pyproject.toml` and pytest configuration; minimal `src/chitai/engine` package; `GameConfig` and validation; fixed-name deck; seeded dealing; starting-player rotation; unit tests; README setup/testing instructions. No passing, claims, scoring, reactions, timeouts, anti-stall, agents, simulation, server, or UI code was written.
- **Files added:** `pyproject.toml`, `src/chitai/__init__.py`, `src/chitai/engine/{__init__,config,chits,rng,deal}.py`, `tests/engine/{test_config,test_chits,test_rng,test_deal,test_rotation}.py`. **Files modified:** `README.md` (status, setup, testing), `.gitignore` (added `*.egg-info/`, `build/`, `dist/`), this document.
- **Implementation decisions** (details the documents left unspecified; none changes a rule in §3A):
  1. *Chit names:* §3A.2 says names are fixed but does not list them. Placeholder names `Sun, Moon, Star, Cloud, Flame, Wave, Leaf, Stone` are defined in `chits.py`; N players use the first N. **Owner may rename them; this is a one-line change and affects no rule.**
  2. *Physical chit instances:* `Chit(name, copy)` with `copy` 0-3. `Chit.matches` compares names only.
  3. *Seed derivation:* SHA-256 of `"{seed}:{purpose}:{indices}"`, first 8 bytes (never built-in `hash()`). Streams are stateless per (purpose, indices): the deal for (completed round, attempt) depends only on the master seed, so deals are reproducible in any order and independent of other streams (e.g. timeouts). This realizes the "purpose-separated streams" of §5A without a stateful stream manager.
  4. *Attempt numbering:* attempts are numbered from 1 (§3A.1 says only "incremented"). A redeal after a draw is `deal_round(config, same_round, attempt + 1)`, with the same initiator, as §3A.6 requires.
  5. *Deal layout:* the shuffled deck is dealt in consecutive blocks of four, seat 0 first. Dealing order is not otherwise specified by the rules.
  6. *Config validation:* integer-only (booleans rejected) for players, rounds, and seed; `pass_timeout_seconds` must be greater than 0 and at most 15 (zero is rejected as meaningless; default 15). NaN and infinity are rejected. The draw safety cap (§3A.6) is deliberately not in `GameConfig` yet; it belongs to M6.
  7. *Deal API:* `deal_round` validates `0 <= completed_round < num_rounds` and `attempt >= 1`. `initiator_for_round` is a function of the completed-round index only, so a draw cannot change the initiator.
  8. *Packaging:* setuptools, `src` layout, Python >= 3.12, no runtime dependencies, pytest as the `dev` extra.
- **Tests actually run (2026-10-17, Python 3.12.3, pytest 9.1.1, Linux):** `pytest` -> **141 passed in 0.29-0.36 s**, both in the development virtualenv and in a fresh virtualenv created with `pip install -e ".[dev]"` (the README procedure). Sanity check: three deliberate code mutations (rotation off by one, three-chit hands, built-in `hash()` seeding) each made tests fail, then the originals were restored and the suite passed again. Not run: Windows/macOS, other Python versions. No coverage measurement was taken.
- **Not implemented / limits:** no game state, actions, or events exist; the deal is not yet connected to any phase or decision point; DoD checkboxes remain unticked.
- **Open questions §9:** none became blocking or was resolved by M1.
- **Next:** owner reviews and commits M1 on a feature branch; then M2 (state, actions, events, invariants, initial claim phase).

### 2026-10-17 — Milestone 2 implemented (local branch `feature/milestone-2-initial-claims`)
- **Preconditions checked:** M1 was merged into `main` (PR #3, merge commit `cbdf59e`; the M1 branch tip is an ancestor of `origin/main`); the M2 branch was created from `main` at `cbdf59e`. Baseline `pytest` on `main` before any change: 141 passed. (This supersedes the M1 entry's "local, uncommitted" status; that entry is left unchanged as history.)
- **Scope:** exactly the M2 line of §8A: state, actions, events, invariants, and the initial claim phase (claim, decline, deterministic order). No passing, five-chit claims, scoring, penalties, round completion, rotation after a round, reactions, timers or timeouts, anti-stall, observations, agents, simulation, server, or UI was written.
- **Files added:** `src/chitai/engine/{state,actions,events,rules,invariants,engine}.py`; `tests/engine/{helpers,test_rules,test_invariants,test_initial_claims,test_events}.py`. **Files modified:** `src/chitai/engine/__init__.py` (exports), `README.md`, this document (status line, §5A table and status note, §8A tags, §9 questions 8-9, §10 annotations, this entry). No M1 module was changed other than the `__init__` exports.
- **Behaviour implemented (all from §3A.3-§3A.5):** the initial opportunities are processed one seat at a time from the initiator clockwise (wrapping); every seat may claim or decline whether or not its hand matches; a claim is valid only when all four chits share a name, and an eligible non-matching claim is a false claim; the engine never claims for a player; a claim or decline by any seat other than the single decision point, an invalid seat, an unrecognized action, or any action outside the initial phase is rejected with no penalty, no state change and no sequence number consumed; after every seat has declined the phase becomes `PASSING` with the initiator as the decision point for the first pass (no further initiator claim); the first valid claim fixes the winner and later actions are rejected. `check_invariants` runs on every state the engine produces: seat count, four chits per hand, `4N` chits, each physical instance exactly once, four copies per name, scores shape, counter ranges, initiator for round, and phase/decision-point/outcome consistency (a recorded winner's hand must match; a false claimant's must not).
- **Implementation decisions** (details the documents left unspecified; none changes a §3A rule):
  1. *Holding phases:* `WIN_DECLARED` and `FALSE_CLAIM` are M2 stopping points. They record `winner` / `false_claimant`, apply no scores, and leave `completed_rounds` unchanged (§9 question 8).
  2. *Immutable state and results:* `GameState` is a frozen dataclass; `apply_action` returns `Accepted(state, events)` or `Rejected(reason, message)` and never mutates its input. `RejectionReason` is one of `unknown_action`, `invalid_seat`, `phase_not_accepting`, `not_decision_point`. Rejections are returned, not raised; an invalid `state` argument or a malformed deal is a programming error and raises (`TypeError`, `InvariantViolation`).
  3. *Resolution counter:* `initial_claims_resolved` counts seats whose opportunity is resolved (a claim resolves its own); the decision seat is derived as `order[resolved]` and cross-checked by an invariant.
  4. *Events:* `DealEvent`, `InitialClaimDeclined`, `InitialClaimMade`, `InitialClaimsResolved`, each with `seq`, `completed_round`, `attempt`. `public_view()` never contains chit identities; `debug_view()` is the private record. A public claim event states validity but not the hand (§9 question 9). Per-player observation views are M7.
  5. *Starting an attempt:* `new_game(config)` starts round 0, attempt 1; `start_from_deal(config, deal)` starts from any consistent `Deal` (also used to test later initiators and crafted hands). M2 does not carry scores or state between rounds.
  6. *Deferred:* automatic decline on timeout (§3A.3) needs timers and the open timer duration (§9 question 3), so it is left to M6; M2 has no timeout action.
- **Tests actually run (2026-10-17, Python 3.12.3, pytest 9.1.1, Linux, virtualenv created with `pip install -e ".[dev]"`):** full `pytest` -> **274 passed in about 0.5 s** (141 existing M1 tests plus 133 new). New tests cover all player counts 4-8, all initiators including wraparound, valid and false claims from every position in the order, three-of-a-kind and two-pair hands, matching players who decline, out-of-turn and already-declined claims, claims after resolution, after a win and after a false claim, invalid seats (negative, out of range, bool, float, string, None), unrecognized actions, immutability, contiguous event sequencing, public/debug view privacy, JSON serializability, corrupted-state detection for every invariant, and seeded random walks (200 games) checking invariants at each step. Sanity check: 12 deliberate code mutations (accepting out-of-turn claims, counter-clockwise order, order ignoring the initiator, three-of-four validity, not entering `PASSING`, a false-claim penalty, completing the round on a claim, leaking hands in two public views, not advancing the sequence, accepting bool seats, disabling the invariant checker) were each detected by at least one failing test; the originals were then restored and the suite passed again. Not run: Windows/macOS, other Python versions. No coverage measurement.
- **Not implemented / limits:** no passing; no timers; scores are never changed; the DoD checkboxes remain unticked (two are annotated as partially covered).
- **Next:** owner reviews and merges M2; then M3 (sequential passing and ordinary claim opportunities, hand-size and eligibility invariants for the three-chit initiator and five-chit receiver states).

### 2026-10-17 — Milestone 3 implemented (local branch `feature/milestone-3-passing`)
- **Preconditions checked:** `origin/main` was `f2e4753`, a two-parent merge commit whose second parent is `971ba6b`, the tip of `feature/milestone-2-initial-claims`. The `refs/pull/4/head` ref is also `971ba6b`, that tip is an ancestor of `main`, and the tree difference between the two is empty. M2 is therefore on `main`. (The GitHub API was rate-limited during the check, so PR #4's displayed status was inferred from these git facts rather than read from the PR page.) Baseline `pytest` on `main` before any change: 274 passed. The M3 branch was created from that `main`.
- **Scope:** exactly the M3 line of §8A: sequential passing and ordinary claim opportunities, with hand-size and eligibility invariants for the three-chit initiator and five-chit receiver states. No false-claim penalty, round completion, rotation after a round, multi-round play, reactions, scoring, timers or timeouts, anti-stall, observations, agents, simulation, server, or UI was written.
- **Files added:** `tests/engine/{test_passing,test_ordinary_claims,test_passing_invariants}.py`. **Files modified:** `src/chitai/engine/{actions,state,events,rules,invariants,engine,__init__}.py`, `tests/engine/{helpers,test_initial_claims,test_invariants}.py`, `README.md`, this document. No M1 module was touched.
- **Behaviour implemented (all from §3A.4-§3A.5):** the initiator makes the first pass while holding four chits; delivery is atomic, so the initiator then holds three and the next seat holds five; a non-initiator holding five may claim or pass any of the five (including the chit just received) and returns to four; passing continues strictly clockwise; when the chit reaches the initiator the initiator holds four again and may claim (valid only with four of one name) or pass; the returning chit need not be the one the initiator sent. A receiver's claim is valid when four of its five chits share a name. Claim availability depends only on phase and position, never on the hand, and the engine never claims for a player. A claim by a seat that is not the decision point, by the initiator at the first pass, or any pass of an unheld chit is rejected with no penalty, no state change and no sequence number consumed. A claim during passing ends in `WIN_DECLARED` or `FALSE_CLAIM`, the same holding phases as M2, with no score and no round completion. `check_invariants` now enforces the §3A.4 hand-size table on every state, plus decision-seat and decision-kind consistency and outcome consistency for passing-phase claims.
- **Implementation decisions** (none changes a §3A rule; owner confirmation requested for 1-3):
  1. *Pass addressing:* `PassAction(seat, chit)` names a physical chit instance (§9 question 10).
  2. *No decline in passing:* `DeclineAction` exists only in the initial phase (§9 question 11).
  3. *Holding phases reused:* passing-phase claims end in the M2 holding phases (§9 question 8).
  4. *New state field:* `GameState.claim_decision_kind` (default `None`) records the decision kind at which a claim was made, so the invariant checker knows whether the claimant should hold four or five chits and which matching rule applies. It is set for initial claims too and must be `None` outside `WIN_DECLARED` / `FALSE_CLAIM`.
  5. *New decision kinds:* `NON_INITIATOR_RECEIVE` and `INITIATOR_RETURN`; `CLAIM_KINDS` lists the kinds at which a claim is allowed.
  6. *Events:* `ChitPassed` (public view: sender and receiver only; the chit appears only in the private debug view, §3A.8) and `ClaimMade` (public view: seat and validity, not the hand, as for `InitialClaimMade`, §9 question 9). `InitialClaimMade` is unchanged.
  7. *Rejection reasons added:* `action_not_available`, `no_claim_opportunity`, `chit_not_held`. The M2 reasons are unchanged. The received chit is appended to the receiver's hand tuple, which keeps hands deterministic.
  8. *No stall guard:* see §9 question 12.
- **Changes to M2 tests (necessary, and rule-preserving):** `test_initiator_has_no_further_initial_opportunity_after_resolution` previously asserted that the first-pass state accepted nothing because passing did not exist. It now asserts the same rule (no further initiator claim; rejection, no penalty, unchanged state) with the M3 reasons, and that no claim or decline is legal. Two corrupted-state tests in `test_invariants.py` now set `claim_decision_kind` so that they still exercise the invariant they target rather than the new missing-kind check. All other M1/M2 tests are unchanged.
- **Tests actually run (2026-10-17, Python 3.12.3, Linux, virtualenv created with `pip install -e ".[dev]"`):** full `pytest` -> **370 passed in about 1.5 s** (the 274 existing tests plus 96 new: 53 in `test_passing.py`, 21 in `test_ordinary_claims.py`, 22 in `test_passing_invariants.py`). The baseline run and a few focused runs of individual files during development preceded this full run. Coverage added: every player count 4-8 and every initiator including wraparound; the full pass cycle and the return to the initiator after exactly N passes; the §3A.4 hand-size table at every step; four-of-five and four-of-four validity including adjacent and non-adjacent matches, three-of-a-kind, two pairs and three-plus-pair; a matching receiver who passes instead of claiming; ineligible, out-of-turn, unheld-chit and invalid-seat actions; no actions after a passing-phase claim; public/debug event privacy; contiguous event sequencing; corrupted-state detection for each new invariant; and seeded random play checked against an independent oracle. Sanity check: 11 deliberate mutations (receiver threshold of three, counter-clockwise passing, claim at the first pass, wrong rule on return, sender keeping the chit, return kind never set, a penalty on claims, decline accepted during passing, hand-size check disabled, chit identity leaked in the public view, unheld-chit pass accepted) were each detected by at least one failing test, on a throwaway copy of the repository. Not run: Windows/macOS, other Python versions. No coverage measurement.
- **Not implemented / limits:** no false-claim penalty or round completion (M4); no reactions or scoring (M5); no timeouts, forced passes or anti-stall (M6); scores are never changed; DoD checkboxes remain unticked (two are annotated).
- **Next:** owner reviews and merges M3; then M4 (false claims, round completion, rotation by completed round, multi-round games).

### 2026-10-17 — Milestone 4 implemented (local branch `feature/milestone-4-round-completion`)
- **Preconditions checked:** `origin/main` was `5b2256e`, a two-parent merge commit (parents `f2e4753` and `6948696`; `6948696` is an ancestor of `main`). M1, M2 and M3 are therefore all on `main`. The status line, §8A tags and §5A note were updated accordingly (earlier entries are unchanged as history). The M4 branch was created from that `main` with a clean working tree. Baseline `pytest` on `main` before any change: 370 passed (Linux, Python 3.12.3, pytest 9.1.1; the owner's own baseline was 370 on Windows, Python 3.12.10).
- **Scope:** exactly the M4 line of §8A: false claims, round completion, rotation by completed round, and multi-round games. No reactions, valid-win scoring, reaction timestamps or latency, timeouts, forced passes, draws or anti-stall, observations, agents, simulation runner, server or UI was written, and no unrelated rule was decided.
- **Behaviour implemented (§3A.5, §3A.6):** an eligible claim that fails its matching rule (four of four at the initial and initiator-return claims; four of five for a receiving non-initiator) now completes the round inside the same `apply_action` call. The claimant receives `-(N-1)`, every other seat receives 0, no winner or reaction score exists, and `completed_rounds` rises by exactly one. The engine then starts the next round automatically: fresh seeded deal for `(completed round, attempt 1)`, initiator rotated clockwise (seat 0 first), scores carried over, attempt numbering back at 1, event sequence continuing. After the last configured round the phase is `GAME_OVER` and every action is rejected (`phase_not_accepting`, "the game is over"). Ineligible claims are unchanged: rejected with no penalty, score change, round completion, state change, RNG use or sequence number. A valid claim still stops at `WIN_DECLARED` with no scores and no round completion (M5).
- **Files added:** `src/chitai/engine/scoring.py`; `tests/engine/{test_scoring,test_false_claims,test_round_progression}.py`. **Files modified:** `src/chitai/engine/{__init__,deal,engine,events,invariants,state}.py`, `tests/engine/{helpers,test_events,test_initial_claims,test_ordinary_claims,test_passing,test_passing_invariants}.py`, `README.md`, this document. `actions.py`, `rules.py`, `config.py`, `chits.py` and `rng.py` were not touched.
- **Implementation decisions** (none changes a §3A rule; owner confirmation requested, see §9 questions 13-17):
  1. *Atomic completion:* the claim, penalty, round completion and next-round start happen in one accepted action, so no resting `FALSE_CLAIM` state is ever returned. `Phase.FALSE_CLAIM` stays in the enum as an internal transient phase: the engine builds it, runs the existing claim-consistency invariants on it, then converts it. This preserves the M2/M3 invariant checks and the public enum.
  2. *Terminal state:* new `Phase.GAME_OVER`, with `completed_rounds == num_rounds`, attempt 1, no decision point and no outcome fields. It keeps the final claim's hands, so chit conservation holds; the invariant accepts only the claim-time hand shapes (all four, or one five and one three). Its initiator is `completed_rounds % N`, which is seat 0.
  3. *Rotation helper:* `deal.rotation_initiator(num_players, completed_rounds)` is the unchecked formula; `initiator_for_round` now calls it and behaves as before. The invariant checker uses `initiator_for_round` while a round is playable and `rotation_initiator` for the terminal state.
  4. *Events:* `FalseClaimPenalized` (seat, penalty, per-seat changes, new totals), `RoundCompleted` (outcome `"false_claim"`, claimant, running total), `GameCompleted` (final scores). The next round starts with an ordinary `DealEvent`; no separate event system. The penalty and completion events carry the index and attempt of the round that ended; the `DealEvent` carries the new round; `GameCompleted` carries `completed_round == num_rounds`, attempt 1. Scores are public, so public views include them; no view contains a chit identity.
  5. *Seeding:* no new randomness. The next deal is `deal_round(config, completed_rounds, 1)`, derived by SHA-256 from the master seed, so a rejected action cannot consume RNG and the existing purpose-separated design is unchanged. A test counts calls to the deal RNG: none on rejection or on a valid claim, none on the final false claim, exactly one on any other false claim.
  6. *Score invariants:* every score must be zero or a negative multiple of N-1, with at most one penalty per completed round (a game started at a crafted later round has fewer). This is M4-specific; M5 must revise it (§9 question 15).
  7. *`start_from_deal`:* public signature and behaviour unchanged; it now delegates to a private `_start_round` that also starts later rounds with carried scores and sequence.
- **Changes to existing tests (necessary, and rule-preserving):** tests that asserted the M2/M3 holding behaviour of a false claim (phase `FALSE_CLAIM`, zero scores, `completed_rounds` unchanged, `next_seq` advanced by one) now assert the M4 behaviour. The affected tests are in `test_initial_claims.py`, `test_ordinary_claims.py`, `test_passing.py`, `test_passing_invariants.py` and `test_events.py`. Two tests were renamed to match: `test_false_claim_applies_no_score_and_does_not_complete_the_round` became `test_false_claim_applies_the_penalty_and_completes_the_round`, and `test_no_actions_after_false_claim` became `test_no_actions_after_false_claim_in_the_final_round`. The random-walk test in `test_initial_claims.py` now stops at the first completed round. In the tests that cover both outcomes, the valid-claim assertions were kept as they were; the ineligible-claim, passing-mechanics and invariant-corruption tests are unchanged. No test was deleted.
- **Tests actually run (2026-10-17, Linux, Python 3.12.3, pytest 9.1.1, `pip install pytest`; no editable install, `pyproject.toml` supplies `pythonpath = ["src"]`):** the final full run, with `__pycache__` cleared first, was `python3 -m pytest` from the repository root -> **544 passed in 2.95 s** (the 370 existing tests plus 174 new: 25 in `test_scoring.py`, 105 in `test_false_claims.py`, 44 in `test_round_progression.py`). Focused runs of individual files and intermediate full runs (which showed the 25 expected failures in tests that encoded the old holding behaviour, before they were updated) happened during development; they are not part of the figure above. Coverage added: false claims from the initial phase, from a receiving non-initiator and from the returning initiator; N = 4, 5, 6, 7, 8; the penalty and zero for every other seat; ineligible claims (out of turn, first pass, holding three, invalid seats, already-declined seats) with no penalty, no round advance and no sequence use; exactly one `completed_rounds` increment; clockwise rotation over two full rotations for each N; reproducible fresh deals (equal to `deal_round`, different between rounds, identical on replay, different for another seed); accumulated scores; attempt restarting at 1 after a round that had attempt 3; the terminal state, rejection of every action type after it, and one-round-early boundary; event order, contiguous sequence numbers across round boundaries (with and without passing) and public-view privacy; invariants checked at every state of 300 generated multi-round games (60 per N); a valid claim after an earlier false-claim round; and corrupted-state detection for scores, round counters, initiator and the terminal state.
- **Sanity check:** 14 deliberate mutations were applied one at a time to a throwaway copy (penalty N instead of N-1, others also penalized, completed rounds +2, scores not carried over, next deal reusing the round index, attempt not restarted, game ending a round late, a sequence gap, terminal state accepting actions, hands leaked in the public deal view, rotation by two, the score invariant disabled, the terminal-shape invariant disabled, a valid claim also completing the round). Each was detected by at least one failing test. Not run: Windows/macOS, other Python versions. No coverage measurement.
- **Not implemented / limits:** valid-win scoring, win completion and reactions (M5); draws, forced passes, timeouts and attempt tracking beyond restarting at 1 (M6); nothing stops an endless pass cycle (§9 question 12), so generated-game tests bound their own loops. A game that reaches a valid claim stops at `WIN_DECLARED` (§9 question 17). DoD checkboxes remain unticked (three are annotated).
- **Next:** owner reviews and merges M4; then M5 (reactions and scoring, including authoritative sequence tie-breaking). Before M5 the owner should decide §9 question 1 (reaction mechanics) and confirm questions 13-15 above.

### 2026-10-17 — Milestone 5 implemented (local branch `feature/milestone-5-valid-win-resolution`)
- **Preconditions checked:** `main` (cloned from GitHub; `origin/main` and local `main` both at `dde4bda`, "Implement Milestone 4: False Claims and Round Progression") contains M1–M4, as the owner stated. The M5 branch was created from it with a clean working tree. Baseline `pytest` before any change: **544 passed** (Linux, Python 3.12.3, pytest 9.1.1; the owner's own baseline was 544 on Windows, Python 3.12.10).
- **Scope:** exactly the M5 line of §8A: valid-win resolution, player reactions, and scoring. No timeouts or timer machinery, forced passes, draws or anti-stall, observations, latency model, agents, simulation runner, server or UI was written, and no gameplay rule was changed.
- **Behaviour implemented (§3A.5, §3A.6):** a valid claim (initial phase, receiving non-initiator, or initiator return) fixes the winner and moves to `WIN_DECLARED`, now the reaction phase. Each non-winner may send `ReactAction(seat)` once, in any order; the engine's accepted-action order is the reaction order. The winner scores N and the non-winners N-1, N-2, ..., 1 in reaction order, added to the carried scores, once, when the last non-winner has reacted. That same call increments `completed_rounds` by one and then deals the next round (fresh seeded deal for the new completed-round index, attempt 1, initiator rotated one seat, scores carried over) or returns `GAME_OVER` after the last configured round. Rejected, with no state, score, sequence-number or RNG change: a winner reaction, a repeat reaction, an invalid seat, a reaction outside the reaction phase, and every action after `GAME_OVER`. M4 false-claim behaviour is unchanged.
- **Files added:** `tests/engine/test_valid_win.py`. **Files modified:** `src/chitai/engine/{__init__,actions,state,events,scoring,rules,invariants,engine}.py`, `tests/engine/{test_false_claims,test_ordinary_claims,test_round_progression}.py`, `README.md`, this document. `config.py`, `chits.py`, `rng.py` and `deal.py` were not touched.
- **Implementation decisions** (none changes a §3A rule; owner confirmation requested, see §9 questions 18–23):
  1. *Reaction model:* explicit `ReactAction(seat)`; accepted-action order is the reaction order (§9 question 1, on the owner's brief). No clock exists in the engine.
  2. *Phase and state:* `WIN_DECLARED` is extended as the reaction phase (§9 question 8); new field `GameState.reaction_order` (seats that have reacted; default `()`). There is no single decision point there: `decision_seat` and `decision_kind` are `None`.
  3. *Last reaction:* explicit, not auto-resolved and not timed out (§9 question 19); compatible with a later M6 timeout action.
  4. *Atomic completion:* the last reaction completes the round in one call (§9 question 21). The M4 tail was extracted as `_close_round`, shared by `_complete_false_claim` and `_complete_valid_win`; the false-claim event order and values are unchanged and are covered by the unchanged M4 tests.
  5. *Events:* `PlayerReacted(seat, position, winner)`, `ValidWinScored(winner, reaction_order, score_changes, scores)` (once per won round) and `RoundCompleted(outcome="valid_win", claimant=winner)`. No view contains a chit identity.
  6. *Rejections:* new `winner_cannot_react` and `already_reacted`; see §9 question 23.
  7. *Score invariant (§9 question 15):* per-seat bounds and total reachability, replacing the M4-only "zero or negative multiple of N-1" check. It applies in every phase, since scores change only when a round completes.
  8. *Legal actions:* in `WIN_DECLARED`, `legal_actions` returns one `ReactAction` per pending non-winner in ascending seat order; `pending_reactors(state)` returns those seats.
  9. *Determinism:* no new randomness. The next deal is `deal_round(config, completed_rounds, 1)`, so a rejected action or a non-completing reaction cannot consume RNG, and reaction order never affects the next deal.
- **Changes to existing tests (necessary, and rule-preserving):** in `test_false_claims.py`, `test_ordinary_claims.py` and `test_round_progression.py`, assertions of the form `legal_actions(won) == ()` now assert the M5 `ReactAction` tuple for the non-winners, and two tests were renamed (`test_valid_claims_are_unchanged_in_m4` became `test_valid_claim_enters_the_reaction_phase_without_scoring_yet`; `test_a_valid_claim_in_a_later_round_holds_without_win_scoring_or_completion` became `test_a_valid_claim_in_a_later_round_enters_reactions_without_scoring_yet`). The M4 generated-games helper `random_game` now also stops at `WIN_DECLARED`, so that test keeps its M4 scope (false-claim-only games); valid-win games are generated in `test_valid_win.py`. Every other assertion in those tests is unchanged, including the checks that claims, declines and passes in `WIN_DECLARED` are rejected with `phase_not_accepting`. No test was deleted or loosened.
- **Tests actually run (2026-10-17, Linux, Python 3.12.3, pytest 9.1.1, `pip install pytest`; `pyproject.toml` supplies `pythonpath = ["src"]`):** the final full run, with `__pycache__` cleared first, was `python3 -m pytest` from the repository root -> **708 passed in 3.82 s** (the 544 existing tests plus 164 new, all in `test_valid_win.py`). Earlier runs during development, including intermediate full runs that showed expected failures in the tests listed above and two bugs in my own new tests (an oracle that credited points before completion, and a script in which the winner reacted), are not part of that figure. Coverage added: the win lifecycle from each of the three claim positions for N = 4–8; winner recorded; legal reactions and their shrinkage; rejection of the winner, repeat reactions, invalid seat values, other actions, wrong-phase reactions, reactions after round completion and after `GAME_OVER`, with state, sequence and deal-RNG unchanged; exact scores for N = 4 and for every N = 4–8, all 6 reaction orders for N = 4, the same scores from every winning path; scoring applied once and not replayable; cumulative scores across rounds and after earlier false-claim penalties; M4 false-claim scoring after a win; completion exactly once; fresh seeded deal, initiator rotation for every initiator including wraparound, attempt reset (also at a later attempt in the final round); a win in the final round (including after earlier penalties for N = 4 and 8) ending the game; contiguous event sequence; identical outcomes for identical config, seed and actions; reactions not affecting the next deal; invariants at every state of the lifecycle and of generated games checked against an independent event-based score oracle; corrupted-state detection for reaction orders, reactions outside the reaction phase, and scores; public views JSON-safe and free of chit names. Not run: Windows/macOS, other Python versions. No coverage measurement.
- **Sanity check:** 15 deliberate mutations were applied one at a time to a throwaway copy (reaction score off by one, winner scoring N-1, winner not scored, scores overwritten instead of added, winner allowed to react, repeat reaction allowed, round completing one reaction early, `completed_rounds` +2, reaction order reversed in scoring, `reaction_order` not reset at game end, reactions accepted after game over, score invariant disabled, reaction invariant disabled, attempt not reset at game end, scoring event omitted). Each was detected by at least one failing test. Two first attempts were not valid evidence: one mutation did not apply (a pattern mismatch, so the unmutated code ran) and was redone correctly; and one genuinely survived, the stale attempt on `GAME_OVER`, because no test won the final round at an attempt above 1, so `test_a_win_at_a_later_attempt_in_the_final_round_ends_the_game_at_attempt_one` was added and both were rerun and detected.
- **Not implemented / limits:** no timeout, timer, forced-pass, draw or anti-stall logic (M6), so nothing stops an endless pass cycle (§9 question 12); no wall-clock reaction timestamps and no latency model (§9 question 18); no observations, agents, simulation, server or UI. DoD checkboxes remain unticked (three are annotated).
- **Next:** owner reviews and merges M5; then M6 (timeouts, forced passes, anti-stall draws, attempt tracking, the simulation draw cap). Before M6 the owner should confirm §9 questions 18–23 and decide questions 3 and 4, and how a timed-out final reaction is represented (question 19).

### 2026-10-18 — Milestone 6 implemented (local branch `feature/milestone-6-timeouts-anti-stall`)
- **Preconditions checked:** `main` (cloned from GitHub) is at `089f3c4`, the merge of PR #7, so M1–M5 are on `main`. The M6 branch was created from it with a clean working tree. Baseline `pytest` before any change: **708 passed** (Linux, Python 3.12.3; the owner's Windows baseline was also 708).
- **Scope:** the M6 line of §8A without the simulation draw cap: timeouts, forced passes, the anti-stall draw and attempt tracking. No observations, agents, simulation runner, draw cap, latency model, server or UI was written. No M1–M5 file was removed or rewritten, and **no existing test was modified**.
- **Behaviour implemented (§3A.3, §3A.5, §3A.6, §3A.7):**
  - *Timeouts are host-issued.* `TimeoutAction(seat)` is an action the host sends when its own timer expires. The engine has no clock, sleeps, timers or threads; it validates only that a timeout is available (§9 question 25). `legal_actions` is unchanged; `timeout_action(state)` returns the one timeout a host may issue.
  - *Initial claim phase:* an accepted timeout is an automatic decline, delegating to the existing decline transition; it never claims.
  - *Passing:* an accepted timeout is a forced pass of one physical chit chosen uniformly from the decision seat's hand (four for the initiator, five for a receiver) using `make_rng(seed, "timeout", completed_round, attempt, next_seq)` over the sorted hand (SHA-256 derivation, never `hash()`); the pass then goes through the ordinary pass transition, so anti-stall and invariants apply. A timeout never claims, even with a winning hand.
  - *Reaction phase:* a timeout is accepted only for the last remaining non-winner and delegates to the existing reaction transition (identical scoring: the last reactor scores 1). With two or more non-winners pending it is rejected as `timeout_not_available` (§3A.5).
  - *Anti-stall:* `GameState.pass_streaks` holds sparse `(seat, chit_name, count)` entries. Streaks are per player and per chit name; another physical copy of the name continues the streak, a different name restarts that player's count at one, and other players' passes never change it. The tenth consecutive same-name pass by one player ends the attempt as a draw before delivery: the chit is not delivered, scores and `completed_rounds` are unchanged, the same initiator redeals the seeded deal for (round, attempt + 1), and a new `GameState` starts with no streaks. Forced and initiator passes count like any other pass. `GAME_OVER` and every new deal have empty streaks.
- **Implementation decisions** (none changes a §3A rule; owner confirmation requested, see §9 questions 24–28):
  1. *Draw cap not in the engine* (§9 question 24): documentation conflict recorded rather than resolved silently.
  2. *Separate action, marker event:* `DecisionTimedOut` precedes the ordinary events, so `InitialClaimDeclined`, `ChitPassed` and `PlayerReacted` and every existing public view are unchanged.
  3. *`AttemptDrawn`* (new event) carries the ended attempt; its public view has the seat and count but not the chit name; its debug view adds the chit. The redeal follows as an ordinary `DealEvent`.
  4. *New rejection reason:* `timeout_not_available`. All other timeout rejections reuse existing reasons (`invalid_seat`, `not_decision_point`, `phase_not_accepting`, `winner_cannot_react`, `already_reacted`).
  5. *New invariants:* streaks are sorted by strictly increasing seat, with a chit name in play and a count from 1 to 9 (ten is a draw and never rests in state); empty in `INITIAL_CLAIMS` and `GAME_OVER`.
  6. *Redeal re-enters initial claims* (§9 question 27).
  7. *Exports and helpers:* `TimeoutAction`, `DecisionTimedOut`, `AttemptDrawn`, `timeout_action`, `timeout_chit`, `update_pass_streaks`, `CONSECUTIVE_PASS_LIMIT`, `TIMEOUT`, `DEAL`, `DRAW_REASON_REPEATED_PASS`, `TIMEOUT_KIND_FINAL_REACTION`.
- **Files added:** `tests/engine/test_timeouts.py`, `tests/engine/test_anti_stall.py`. **Files modified:** `src/chitai/engine/{__init__,actions,config,engine,events,invariants,rng,rules,state}.py`, `README.md`, this document. `chits.py`, `deal.py` and `scoring.py` were not touched; `config.py` changed in one docstring line only (the timeout is now used by hosts), with no behaviour change.
- **Tests actually run (2026-10-18, Linux, Python 3.12.3, pytest 9.1.1, `pip install pytest`; `pyproject.toml` supplies `pythonpath = ["src"]`):** the final full run, with `__pycache__` cleared first, was `python3 -m pytest` from the repository root -> **926 passed** (the 708 existing tests plus 218 new: 123 in `test_timeouts.py`, 95 in `test_anti_stall.py`). Earlier runs during development, including failures caused by mistakes in my own new tests (a missing sequence offset, a helper that used `decision_seat` in the reaction phase, and unreachable score totals in test data), are not part of that figure. Coverage added: timeout configuration boundaries and invalid values; availability at every decision point for N = 4–8; initial-claim timeout equal to a decline and never a claim; forced passes legal and equal to the ordinary pass of the chosen chit at the first pass, receive and return decisions; determinism for the same seed and state, dependence on the seed, independence from hand order, and uniformity over four and five physical chits (statistical bounds over 2000 fixed seeds); the pinned stream derivation; the last-reaction timeout equal to an explicit reaction for N = 4–8 and all three winning paths, scoring unchanged, and rejection while two or more non-winners remain; streak counting, resets, per-player independence and copy-independence; no draw at nine and a draw at exactly ten for N = 4–8 at every pass decision kind; the tenth chit not delivered (a receiver who would have won gets no claim); redeal with the same initiator for every rotation position, preserved scores, unchanged `completed_rounds`, incremented attempt (including attempt 3 and the restart at attempt 1 in the next round), cleared streaks and the seeded deal for (round, attempt + 1); a timeout-forced tenth pass; event order, contiguous sequence numbers and public/private views; rejected actions leaving state and streaks unchanged; corrupted-streak detection; seeded biased random play (24 games across N = 4, 6, 8) checked against an independent event-based streak oracle, with draws actually occurring; and reproducibility. Also run: `git diff --check`.
- **Sanity check:** 28 deliberate mutations were applied one at a time to throwaway copies (limit 9 and 11, no reset on a new name, streaks keyed by physical copy, other seats' streaks reset, attempt not incremented or incremented by two, scores reset by a draw, a completed round consumed by a draw, streaks surviving a draw, chit name leaked in the public draw view, draw event omitted, reaction timeout accepted with several pending (engine and helper), timeout from the wrong seat accepted, timeout using the deal stream, always choosing the first chit, ignoring hand sort, omitting the attempt from the stream key, marker event omitted or not sequenced, initial timeout claiming instead of declining, streak invariant disabled, streaks kept at `GAME_OVER`, streaks never stored, a loosened count bound, no timeout in the initial phase, and delivering the tenth chit). One mutation first **survived** (streaks kept at `GAME_OVER`), because no test ended a game after passing; `test_a_win_in_the_final_round_after_passing_ends_the_game_with_cleared_streaks` was added and the mutation was then detected. Not run: Windows/macOS, other Python versions. No coverage measurement.
- **Not implemented / limits:** the simulation draw safety cap (M8; §9 questions 5 and 24); wall-clock timestamps and latency models; observations, agents, simulation, server and UI. Because timeouts never claim and varying names avoids draws, a pass cycle can still run indefinitely: hosts and simulators must bound their own loops. DoD checkboxes remain unticked (five are annotated).
- **Next:** owner reviews and merges M6; then M7 (privacy-safe observations, legal-action lists, privacy tests). Before M7 the owner should confirm §9 questions 24–28 and decide how a timeout and a draw appear in per-player observations.

### 2026-10-18 — Milestone 7 implemented (on top of `main` at `62c832f`)
- **Preconditions checked:** `main` is at `62c832f` (merge of PR #8), so M1–M6 are on `main`. Baseline `pytest` before any change: **926 passed** (Linux, Python 3.12.3). Delivered as a unified patch against `62c832f`; nothing was committed, pushed or merged from the workspace. The work followed a planning pass that the owner approved with six decisions (recorded in §9 questions 6, 9, 22, 26 and 29–32).
- **Scope:** exactly M7 (§8A): player-specific observations, per-seat legal actions, name-based pass actions with an internal translation, per-seat event views, tests and documentation. No RuleBot, simulation runner, draw cap, JSONL/CSV logging, server, UI, hand-reveal event or agent-error framework was written, and no engine file was modified.
- **Behaviour implemented:**
  - `observe(state, seat) -> Observation` (public fields plus `my_seat`, `my_hand` as sorted chit names and the observer's own anti-stall streak; JSON via `to_dict()`).
  - `legal_actions_for(state, seat)`: the engine's `legal_actions` filtered to `seat` and relabelled by name; a pending non-winner gets `ReactAction`, the decision seat gets claim or decline or one `NamePassAction` per distinct name held; never another seat's action, never a timeout.
  - `to_engine_action(state, action)`: returns the engine action only for an action that is in `legal_actions_for(state, action.seat)`, else `None`; a name becomes the held chit of that name with the lowest copy index.
  - `observe_event` / `observe_events`: public view plus own dealt hand (`DealEvent`) and the passed chit's name (`ChitPassed`, sender and receiver only); `seat=None` is the public stream; `debug_view()` is never used.
  - `action_to_dict` for JSON-serializable agent actions.
- **Files added:** `src/chitai/observations/{__init__,observation,legal,events}.py`; `tests/observations/{__init__,support,test_observation,test_legal_actions,test_event_visibility,test_privacy_boundary}.py`. **Files modified:** `README.md`, this document. No engine module, no existing test and `pyproject.toml` were changed.
- **Tests actually run (2026-10-18, Linux, Python 3.12.3, pytest, `python3 -m pytest` from the repository root, `__pycache__` cleared first):** **1037 passed** (the 926 existing tests plus 111 new: 36 in `test_observation.py`, 46 in `test_legal_actions.py`, 25 in `test_event_visibility.py`, 4 in `test_privacy_boundary.py`). Coverage added: every phase (initial claims, first pass, receive, return, `WIN_DECLARED` with and without reactions, `GAME_OVER`) for N = 4–8; the field allowlist; own versus other streaks; determinism and hand-order independence; JSON round trip with primitives only and no seed, config, state, copy id or engine object; hidden-twin tests (other hands permuted, other streaks changed) for observations, legal actions and, over generated games, event streams; sender and receiver positive controls; claim, timeout and draw event views; reaction actions only for pending non-winners; no timeout ever exposed or translatable; every returned action accepted by the engine; a full game played through the agent interface only; AST checks that the layer imports no hidden or random engine names, never calls `debug_view`, and that the engine does not import it.
- **Sanity check:** 16 deliberate mutations were applied one at a time to a throwaway copy (another seat's hand, another seat's streak, the seed in an observation, copy ids in the hand, `my_turn` always true, no seat filter, no legality check in the translator, copy ids in pass names, a timeout exposed, a bool seat accepted, the chit shown to bystanders, `debug_view` used, another seat's hand in the deal view, the draw chit revealed, a claim hand revealed, a copy id in the passed-chit view). Each was detected by at least one failing test. Not run: Windows/macOS, other Python versions. No coverage measurement.
- **Not implemented / limits:** no runner-level action validation or generic agent errors (M8); no seat authentication (M8/M10); no agents, simulation, logging, server or UI. Inherent public disclosures remain by rule (claim validity; a draw shows that a seat passed one name ten times). DoD boxes stay unticked.
- **Next:** owner reviews M7; then M8 (RuleBot, seeded AI-only simulation runner, draw cap, JSONL event logs, CSV summaries, runner-level action validation).
