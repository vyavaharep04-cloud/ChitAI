# ChitAI — Project Context

**Research title:** *ChitAI: An AI-Powered Multiplayer Game for Decision-Making Under Incomplete Information*  
**Repository:** `vyavaharep04-cloud/ChitAI`  
**Default branch:** `main`  
**Status:** Planning / repository setup  
**Last updated:** 2026-10-16

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

### Players and chits
- 4–8 players.
- For `N` players, there are `N` unique chit names, each occurring exactly four times.
- Total chits: `4N`; each player starts with four.
- Shuffle and deal randomly at the start of every round.
- An initial four-of-a-kind hand is possible; its claim window needs explicit definition.

### Passing
- Pass clockwise; the starting player rotates each round.
- The receiver temporarily holds five chits: their four current chits plus the received chit.
- They select any one of the five to pass onward, including the chit just received.
- After passing, the player holds four again.

### Claims and scoring
- A player may claim when their four held chits match, or when at least four of the five temporarily held chits match.
- Claims are explicit actions; do not automatically announce a win.
- Passing forfeits that claim opportunity until the player's next opportunity.
- The first valid claim received by the authoritative server wins.
- A false claim ends the round: claimant gets `−(N−1)` points; everyone else gets `0`.
- After a valid win, every other player reacts; the winner does not react.
- Winner scores `N`; other players score `N−1`, `N−2`, …, `1` according to reaction order.
- Server-side logic must validate claims, actions, ordering, and scores; do not trust the client UI.

### Rounds, timeout, and anti-stall
- Room creator chooses the round count.
- Round count must be a multiple of `N` and include at least one complete starting-player rotation.
- Reshuffle and redeal all chits every round.
- Pass timeout is at most 15 seconds; room creator may choose a shorter timeout.
- Automatic action on timeout is **not yet decided**.
- If the same player passes the same chit name for 10 consecutive passes, force a reshuffle.
- Passing another chit name resets the consecutive count for the prior name and begins/continues tracking for the new name as appropriate.
- The exact transition after a forced reshuffle remains unresolved.

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

Suggested structure (adapt after inspecting the repository; do not duplicate existing code):

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

## 6. Simulation and research logging

Build the simulation runner early, before polishing the UI. It must run without launching the web server.

At minimum, log per game:
- Run/experiment ID and random seed.
- Player count and round count.
- Agent type, version/configuration, and seat assignment.
- Winner/rank and final scores.
- False claims, timeouts, and forced reshuffles.

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

Local browser play is desired. Same-Wi-Fi local-network access is also desirable; test it early if it is a priority rather than assuming localhost works across devices.

Stretch features: public chat, disconnect recovery/reconnection, more agent personalities, tournaments, and richer analytics. These must not delay core rules, privacy, or simulation correctness.

## 8. Delivery priorities

1. Resolve remaining rule ambiguities.
2. Implement pure engine and unit tests.
3. Implement restricted player observations and privacy tests.
4. Implement RuleBot and seeded AI-only simulation.
5. Add SmartBot and MindBot as time permits.
6. Produce reproducible logs and metric summaries.
7. Add a basic browser UI using the same engine.
8. Test mixed rooms and local-network access.
9. Write the report from actual implementation and results.

Avoid starting with a complex UI or adding advanced algorithms before the rules and baseline experiment work reliably.

## 9. Open decisions — do not silently invent rules

1. **Timeout policy:** Which legal action is automatic when a player times out? Deterministic or random? How is randomness seeded?
2. **Forced reshuffle:** Does it restart the round? Who starts next, and what happens to scores/state?
3. **Simultaneous claims:** Server receipt order is the current rule; define and test exact event-loop ordering.
4. **Claim timing with five chits:** Can a player claim instead of passing, and exactly when is the five-chit condition evaluated?
5. **Reaction timeout:** Is there a timeout and what automatic response applies?
6. **Custom chit names:** Fixed names or configurable? If configurable, define uniqueness and validation.
7. **Round count:** Confirm minimum `N` and valid positive multiples of `N`.
8. **Starting-player rotation:** Confirm one-seat rotation each round, including after false claims or forced reshuffles.
9. **Consecutive-pass tracking:** Define counters and reset behaviour precisely.
10. **Observation history:** Specify public/private information and what each player remembers.
11. **Initial four-of-a-kind:** Define the initial claim window and consequences of not claiming.
12. **Reaction scoring:** Define how reaction order, ties, and late responses are resolved.

Resolve each item explicitly and add tests for it.

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
- Created feature branch `docs/add-project-context` from `main` to hold this context document. No pull request has been opened yet.
- Next: add this file to the feature branch, inspect the diff, then open a PR targeting `main`; resolve open rule decisions before engine implementation.
