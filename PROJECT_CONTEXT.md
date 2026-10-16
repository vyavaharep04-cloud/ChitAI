# ChitAI — Project Context

**Research title:** *ChitAI: An AI-Powered Multiplayer Game for Decision-Making Under Incomplete Information*
**Repository:** `vyavaharep04-cloud/ChitAI`
**Default branch:** `main`
**Status:** Specification and architecture finalized (2026-10-17); implementation not started — no application code or tests exist yet **Last updated:** 2026-10-17

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

**Status: planned design. No application code, modules, or tests exist yet.** Modules are created only when their milestone begins; none are created in advance as empty placeholders.

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
| `engine/state.py` | later | Phase, decision point, hands, chit movement, completed-round and attempt counters, scores. |
| `engine/actions.py` | later | Player actions (claim, decline, pass, and engine-generated timeout actions, later reactions). |
| `engine/events.py` | later | Sequenced events with separate public and private views. |
| `engine/rules.py` | later | Pure rule functions: claim eligibility, claim validity (four-of-four, four-of-five), legal actions. |
| `engine/invariants.py` | later | Checks for hand sizes, `4N` total chits, four copies per name, and phase/decision-point consistency. |
| `engine/engine.py` | later | The single authoritative engine: validates and applies actions; rejected actions leave state unchanged. |
| `engine/scoring.py` | later | False-claim penalties, win scores, reaction-order scoring, tie-breaking by authoritative sequence. |
| `agents/` | later | RuleBot, SmartBot, MindBot behind one interface. |
| `observations/` | later | Player-specific, privacy-safe views and legal-action lists. |
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

**M1 — Scaffolding, configuration, deck, seeded deal, rotation (strictly limited):**
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
- M2: state, actions, events, invariants, and the initial claim phase (claim, decline, deterministic order).
- M3: sequential passing and ordinary claim opportunities, with hand-size and eligibility invariants.
- M4: false claims, round completion, rotation by completed round, and multi-round games.
- M5: reactions and scoring, including authoritative sequence tie-breaking.
- M6: timeouts, forced passes, anti-stall draws, attempt tracking, and the simulation draw cap.
- M7: privacy-safe observations, legal-action lists, and privacy tests.
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
2. Specify the exact public event history available to agents. Private information may only be retained by an agent if that agent legitimately observed it. *[Open — scheduled for the observations milestone (M7).]*
3. Implement claim/reaction event ordering using a single authoritative server sequence and record timestamps at microsecond precision where supported. *[Open — scheduled for the reaction/scoring milestone (M5).]*
4. Ensure a timeout-selected chit is chosen from the player's legal five-chit options and uses the seeded RNG in simulation. **[RESOLVED/CLARIFIED 2026-10-17: legal options are the player's held chits — five for a non-initiator, four for the initiator — §3A.7.]**
5. Add tests for anti-stall round restart, same initiator, unchanged score, and counter resets. *[Scheduled for M6; must also cover completed-round vs. attempt tracking.]*
6. If any historical detail conflicts with this summary, flag it for the owner instead of silently changing the rules.


### Open questions (genuinely unresolved as of 2026-10-17)
All other gameplay and architecture decisions are settled and recorded in §3A and §5A. None of the following blocks Milestone 1.
1. **Reaction mechanics for simulation:** how a "reaction" is represented, and how reaction order or latency for AI agents is modelled (for example a seeded latency model). Decide before the reaction/scoring milestone (M5).
2. **"Reacted/claimed" wording:** the earlier rule text says "reacted/claimed". It is interpreted as "reacted" because only one player can claim at a time. Owner confirmation pending.
3. **Timer for initial claim opportunities:** the duration is not separately specified. Proposed default: the room's configured decision timeout (at most 15 seconds).
4. **Anti-stall details:** proposed defaults, to be confirmed before M6: the draw is declared at the moment the tenth consecutive same-name pass is made (that chit is not delivered); the count is kept per player; timeout-forced passes and initiator passes count like any other pass; counts start fresh on every new attempt.
5. **Draw safety cap:** the behaviour is settled (stop and record, never award points). The default cap value and the recorded outcome format are chosen at the simulation milestone.
6. **Round-end reveal:** whether a claimed hand is publicly revealed at round end, which affects what agents may legitimately observe. Decide at the observations milestone (M7).
7. **Final ranking ties:** how equal total scores are ranked in summaries (shared rank or a tie-break rule). Decide when multi-round summaries are implemented.

## 10. Definition of done

- [ ] Documented and deterministic rules where needed.
- [ ] Engine supports 4–8 players and valid round counts.
- [ ] Passing, claims, false claims, reaction order, and scoring tested.
- [ ] Timeout and anti-stall policies implemented and tested.
- [ ] Observation privacy tests pass.
- [ ] RuleBot completes AI-only games.
- [ ] At least one additional agent can be compared with RuleBot.
- [ ] Seeded simulations produce repeatable logs.
- [ ] CSV results can be summarized.
- [ ] Basic browser UI uses the same engine.
- [ ] Mixed human/AI play tested if included in the promised scope.
- [ ] Research conclusions supported by actual results and limitations.
- [ ] Hand-size and claim-eligibility invariants enforced and tested at every transition.
- [ ] Initial claim order, automatic decline on timeout, and ineligible-claim rejection tested.
- [ ] Completed rounds and draw attempts tracked separately and tested.
- [ ] Simulation draw safety cap implemented and tested.
- [ ] README contains setup and run instructions.

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
