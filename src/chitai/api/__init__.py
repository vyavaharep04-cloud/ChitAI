"""Local web interface (Milestone 10): rooms, WebSocket protocol and static serving.

This package sits above the engine, observations and agents. It contains no game
rules: every action goes through `legal_actions_for`, `to_engine_action` and
`apply_action`, and every client message is built from `observe` and
`observe_event`. `rooms` is pure Python (no network, no asyncio); `server` is the
FastAPI/WebSocket layer.
"""
