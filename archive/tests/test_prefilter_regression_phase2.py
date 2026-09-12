"""The non-LLM regression of plan §10 over the phase-2 measurement data
(ai-artifacts/similarity_measurement/REPORT_PHASE2.md): with the production
prefilter constant and the production decision rule -- UNCHANGED iff the
judge said "same" AND the cosine of the two embedding documents is at least
`_GATE_SIMILARITY` -- no real change of a tracked entity is called unchanged.

The data: `pairs_phase2.json` (every pair's cosine per text form; the
`|doc` form is what the production prefilter embeds), `judge_phase2.json`
(the judge's verdict per pair).  The strict ground truth of a real change is
judge_stats.py's `must` set: a definitional pair of an edited root whose
grade is not cosmetic and whose statement changed or which is the root
itself.  No embedding call, no LLM: the measurement was paid once.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from Isabelle_Semantic_Embedding.semantic_interpretation import _GATE_SIMILARITY

_DATA = pathlib.Path(__file__).resolve().parents[2] / "ai-artifacts" / "similarity_measurement"
_DOC = "Qwen/Qwen3-Embedding-8B|doc"
_TRACKED = {"constant", "type", "typeclass", "locale"}


@pytest.fixture(scope="module")
def phase2():
    if not (_DATA / "pairs_phase2.json").is_file():
        pytest.skip("phase-2 measurement data not present")
    pairs = json.loads((_DATA / "pairs_phase2.json").read_text())["pairs"]
    judged = json.loads((_DATA / "judge_phase2.json").read_text())["judgements"]
    key = lambda r: (r["entity"], r["kind"], r["g1"], r["g2"])
    by_key = {key(p): p for p in pairs}
    return [(r, by_key[key(r)]) for r in judged if key(r) in by_key]


def _unchanged(judgement, pair) -> bool:
    """The production gate's UNCHANGED (§3, D2): an explicit "same" from the
    judge with the prefilter's cosine at or above the constant; an
    uncomputable cosine defers to the judge alone."""
    sim = pair["sims"].get(_DOC)
    return judgement["same"] is True and (sim is None or sim >= _GATE_SIMILARITY)


def test_no_real_change_of_a_tracked_entity_is_called_unchanged(phase2):
    must = [(r, p) for r, p in phase2
            if r["class"] == "definitional" and r["grade"] != "a-cosmetic"
            and (not p["expr_same"] or r["entity"] == r["root"])]
    tracked = [(r, p) for r, p in must if r["kind"] in _TRACKED]
    assert len(must) > 50 and tracked, "the strict ground-truth set is populated"
    misses = [(r["entity"], r["kind"], r["g1"], r["g2"], p["sims"].get(_DOC))
              for r, p in tracked if _unchanged(r, p)]
    assert misses == [], f"real changes called unchanged at {_GATE_SIMILARITY}: {misses}"


def test_the_constant_is_the_measured_operating_point(phase2):
    """The prefilter constant sits where the measurement put it: at 0.90 no
    real change slips through even over ALL kinds, while the judge alone
    (no backstop) lets one through -- so the backstop is doing its job."""
    must = [(r, p) for r, p in phase2
            if r["class"] == "definitional" and r["grade"] != "a-cosmetic"
            and (not p["expr_same"] or r["entity"] == r["root"])]
    judge_alone = [r for r, _ in must if r["same"] is True]
    assert judge_alone, "the judge alone misses at least one real change (the measurement's finding)"
    assert all(not _unchanged(r, p) for r, p in must)
