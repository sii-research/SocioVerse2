"""DeterministicLLMClient — a pure-function stand-in for LLMClient (no network).

Used for the parity test and CI: because its outputs are a deterministic function of the
task inputs, the legacy model.step() path and the adapter path produce IDENTICAL metric
trajectories on the same seed, proving the adapter re-drives the dynamics faithfully —
without spending any API budget. Implements exactly the surface model.step() touches.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

_TRACT_RE = re.compile(r"Tract (\w+)")


def _hash(s: str) -> int:
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "big")


class DeterministicLLMClient:
    def __init__(self, dissatisfaction_threshold: float = 4.0, move_modulo: int = 3):
        self.dissat_threshold = dissatisfaction_threshold
        self.move_modulo = move_modulo
        self.call_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_log: list = []

    # --- surface used by SegregationModel.step() ---
    def get_current_call_id(self) -> int:
        return self.call_count

    def get_call_log_since(self, start_id: int) -> list:
        return []

    def get_stats(self) -> dict:
        return {
            "total_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }

    def batch_assess_satisfaction(self, tasks: list[dict]) -> list[dict]:
        out = []
        for task in tasks:
            self.call_count += 1
            h = _hash(f"sat|{task['archetype_key']}|{task['tract_id']}")
            sat = (h % 1000) / 100.0  # 0.00 .. 9.99
            out.append({
                "satisfaction": sat,
                "would_move": sat < self.dissat_threshold,
                "key_reasons": ["deterministic"],
            })
        return out

    def batch_evaluate_move(self, tasks: list[dict]) -> list[dict]:
        out = []
        for task in tasks:
            self.call_count += 1
            # Recover candidate tract ids from the description text (header "Tract <geoid>").
            ids = []
            seen = set()
            for cid in _TRACT_RE.findall(task.get("candidates_desc", "")):
                if cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
            if not ids:
                out.append({"ranked_candidates": [], "stay_score": 5.0, "reason": "no candidates"})
                continue
            h = _hash(f"move|{task['archetype_key']}|{task['tract_id']}")
            if h % self.move_modulo == 0:
                out.append({"ranked_candidates": [], "stay_score": 8.0, "reason": "stay"})
            else:
                pick = ids[h % len(ids)]
                out.append({
                    "ranked_candidates": [{"tract_id": pick, "score": 8.0}],
                    "stay_score": 5.0,
                    "reason": "deterministic move",
                })
        return out
