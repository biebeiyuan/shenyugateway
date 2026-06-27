from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StarWeights:
    ch_content: float = 1.0
    ch_keyword: float = 0.8
    ch_chord: float = 0.6
    ch_harmony: float = 0.7
    ch_scene: float = 0.4
    ch_explicit: float = 0.5
    rrf_k: int = 60
    actr_floor: float = 0.5
    constant_boost: float = 1.3
    date_boost_max: float = 0.3
