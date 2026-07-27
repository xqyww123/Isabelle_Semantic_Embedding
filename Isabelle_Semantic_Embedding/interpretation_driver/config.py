"""Per-model prices for the backends that report tokens rather than money.

Lives at ``$ISABELLE_HOME_USER/etc/interpretation_config``, seeded from
``interpretation_config_template.yaml``; ``INTERPRETATION_CONFIG_PATH``
overrides the location.  Same machinery as the embedding config.

A backend that reports its own dollar cost (Claude Code does) never comes here.
"""

from __future__ import annotations

import pathlib
from typing import NamedTuple

from .._user_config import User_Config, isabelle_etc

_CONFIG = User_Config("interpretation_config_template.yaml",
                      "INTERPRETATION_CONFIG_PATH",
                      isabelle_etc("interpretation_config"))


def load_interpretation_config(force_reload: bool = False) -> dict:
    return _CONFIG.load(force_reload)


def config_source() -> "pathlib.Path | None":
    """Path the active config was loaded from (for diagnostics)."""
    return _CONFIG.source()


class Pricing(NamedTuple):
    """Dollars per token, by kind."""
    input: float
    cached_input: float
    output: float

    def cost(self, *, input_tokens: int, cached_input_tokens: int,
             output_tokens: int) -> float:
        """Dollars for one turn's usage.

        `input_tokens` is the FULL input count, cached part included -- that is
        how the backends report it -- so the cached tokens are billed at their
        own rate and only the remainder at the uncached one.  `output_tokens`
        likewise already includes reasoning tokens; they are not billed twice."""
        uncached = max(0, input_tokens - cached_input_tokens)
        return (uncached * self.input
                + cached_input_tokens * self.cached_input
                + output_tokens * self.output)


class MissingPricing(Exception):
    """No prices are configured for a model a backend needs prices for.

    Raised where the run can still be stopped -- before the first request --
    because the alternative is a run that reports itself as free."""

    def __init__(self, model: str, missing: str = "") -> None:
        self.model = model
        where = config_source() or "(no config file could be located)"
        detail = f" is missing {missing}" if missing else " has no prices"
        super().__init__(
            f"Semantic interpretation cannot start: model {model!r}{detail} in "
            f"{where}. Add it under `models:` (input, cached_input and output, "
            f"in dollars per token), then retry.")


def pricing_of(model: str) -> Pricing:
    """Prices for `model`, or raise MissingPricing naming what to add where."""
    models = load_interpretation_config().get("models") or {}
    entry = (models.get(model) or {}).get("pricing") or {}
    missing = [k for k in ("input", "cached_input", "output") if k not in entry]
    if not entry or missing:
        raise MissingPricing(model, ", ".join(missing))
    return Pricing(float(entry["input"]), float(entry["cached_input"]),
                   float(entry["output"]))
