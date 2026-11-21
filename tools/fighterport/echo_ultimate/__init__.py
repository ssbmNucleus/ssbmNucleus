"""Smash Ultimate source assets: extraction and decode into the FK format.

This is the ORIGINAL-GAME import path. Shulk's shipped movesets source 237 of
their 244 clips from Ultimate's own `motion/body/...` files against the real
`model/body/c00/model.nusktb` skeleton -- they are not motion capture.

The retarget/bake toolchain those decoded clips feed into lives in `fighter_port`.
"""
from __future__ import annotations

__all__ = ["decode"]
