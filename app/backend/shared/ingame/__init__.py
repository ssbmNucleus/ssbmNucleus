"""
ingame -- in-app "Test in game" engine.

A self-contained, stdlib-only (plus Pillow, already bundled) port of the RAM-
feedback Slippi Melee control harness, so the packaged backend (mex_backend.exe)
can boot a freshly-built ISO, drive it to a real offline match, select the modded
character/stage, trigger effects, and decide PASS/CRASH/HUNG -- with NO extra user
installs (no Node, no melee_venv, no pywin32, no PowerShell) and WITHOUT touching
the user's own Slippi setup (it boots in a throwaway copy of the User dir).

Public entry point: shared.ingame.runner.run_test(...). Everything is Windows-only
(it reads emulated RAM and writes Dolphin's named pipe via kernel32).
"""

from .runner import run_test  # noqa: F401

__all__ = ["run_test"]
