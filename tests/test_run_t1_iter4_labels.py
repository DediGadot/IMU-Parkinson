"""Tests for T1 per-item label loading."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_t1_iter4


def test_load_per_item_scores_masks_invalid_item_totals(tmp_path, monkeypatch):
    cache = tmp_path / "per_item_scores.json"
    cache.write_text(
        json.dumps(
            {
                "NLS036": {
                    "9": 4,
                    "15": 18,
                    "17": 18,
                    "(15, 'a')": 9,
                    "(15, 'b')": 9,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_t1_iter4, "PER_ITEM_CACHE", cache)

    scores = run_t1_iter4.load_per_item_scores()

    assert scores["NLS036"][9] == 4.0
    assert scores["NLS036"][17] == 18.0
    assert 15 not in scores["NLS036"]
