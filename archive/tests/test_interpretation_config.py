"""Tests for the interpretation price table.

What it guards: a backend that reports only tokens has to be told what they
cost, and the failure mode of getting that wrong is silent -- a run that
reports itself as free, or at a made-up price, with the figure written into the
theory record where nothing later can tell it was wrong.
"""
import pytest
import yaml

from Isabelle_Semantic_Embedding.interpretation_driver import config as C


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point the loader at a config file of the test's own, and write it."""
    path = tmp_path / "interpretation_config"
    monkeypatch.setenv("INTERPRETATION_CONFIG_PATH", str(path))

    def write(data):
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        C.load_interpretation_config(force_reload=True)

    yield write
    C.load_interpretation_config(force_reload=True)      # drop the cached test data


def test_a_missing_config_is_seeded_from_the_template(tmp_path, monkeypatch):
    path = tmp_path / "etc" / "interpretation_config"
    monkeypatch.setenv("INTERPRETATION_CONFIG_PATH", str(path))
    try:
        data = C.load_interpretation_config(force_reload=True)
        assert path.exists(), "the user's copy is created on first use"
        assert "models" in data
        assert C.config_source() == path
    finally:
        C.load_interpretation_config(force_reload=True)


def test_prices_are_read_per_model(cfg):
    cfg({"models": {"some-model": {"pricing": {
        "input": 1e-6, "cached_input": 1e-7, "output": 1e-5}}}})
    assert C.pricing_of("some-model") == C.Pricing(1e-6, 1e-7, 1e-5)


def test_an_unpriced_model_says_what_to_add_and_where(cfg):
    cfg({"models": {}})
    with pytest.raises(C.MissingPricing) as e:
        C.pricing_of("some-model")
    assert "some-model" in str(e.value)
    assert str(C.config_source()) in str(e.value)


def test_a_half_filled_entry_names_the_missing_keys(cfg):
    """Defaulting one of the three to zero would under-report every run."""
    cfg({"models": {"some-model": {"pricing": {"input": 1e-6}}}})
    with pytest.raises(C.MissingPricing) as e:
        C.pricing_of("some-model")
    assert "cached_input" in str(e.value) and "output" in str(e.value)


# --- the arithmetic ---------------------------------------------------------

def test_cached_tokens_are_billed_once_at_the_cached_rate():
    """The backends report `input_tokens` INCLUDING the cached part; charging
    the full count at the uncached rate would overstate a cache hit tenfold."""
    p = C.Pricing(input=10.0, cached_input=1.0, output=100.0)
    assert p.cost(input_tokens=100, cached_input_tokens=0, output_tokens=0) == 1000.0
    assert p.cost(input_tokens=100, cached_input_tokens=100, output_tokens=0) == 100.0
    assert p.cost(input_tokens=100, cached_input_tokens=40, output_tokens=0) == 640.0


def test_output_tokens_are_taken_as_given():
    """Reasoning tokens are already part of the reported output count, so the
    price applies to that count once and nothing is added for them."""
    p = C.Pricing(input=0.0, cached_input=0.0, output=2.0)
    assert p.cost(input_tokens=0, cached_input_tokens=0, output_tokens=7) == 14.0


def test_a_nonsensical_cache_count_cannot_produce_a_negative_bill():
    p = C.Pricing(input=10.0, cached_input=1.0, output=0.0)
    assert p.cost(input_tokens=10, cached_input_tokens=50, output_tokens=0) == 50.0
