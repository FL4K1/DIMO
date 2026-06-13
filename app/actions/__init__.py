"""
app/actions — Thin wrapper layer bridging Mark-XXXIX-OR-main action modules into DIMO.

Each wrapper adapts Mark's (parameters=dict, player=MockPlayer) calling convention
to DIMO's (**kwargs) → {success, result, error} convention.
"""
