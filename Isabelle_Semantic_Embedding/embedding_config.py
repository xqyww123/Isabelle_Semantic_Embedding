"""Loader for the embedding provider configuration.

The configuration lives at ``$ISABELLE_HOME_USER/etc/embedding_config`` (YAML).
On first use it is seeded from the bundled template
``embedding_config_template.yaml`` next to this module. It carries, keyed by the
*canonical* model name (HuggingFace name where one exists, else the canonical
id) and by the base_url domain (netloc):

  - ``dimension``:      per-model embedding vector dimension (required in use)
  - ``default_scores``: per-model {score, local} fallback for un-embedded entities
  - ``providers``:      per-domain ``normalization`` (canonical -> API model id)
                        and ``batch`` (Batch API shape) config

Set ``EMBEDDING_CONFIG_PATH`` to override the config file location (used by tests).
"""
from __future__ import annotations

import os
import pathlib
import shutil

import yaml

_TEMPLATE_PATH = pathlib.Path(__file__).parent / "embedding_config_template.yaml"

_config: dict | None = None
_config_source: pathlib.Path | None = None


def _isabelle_home_user() -> pathlib.Path | None:
    """Resolve $ISABELLE_HOME_USER, falling back to ~/.isabelle/$ISABELLE_IDENTIFIER."""
    env = os.getenv("ISABELLE_HOME_USER")
    if env:
        return pathlib.Path(env)
    ident = os.getenv("ISABELLE_IDENTIFIER")
    if ident:
        return pathlib.Path.home() / ".isabelle" / ident
    return None


def _resolve_config_path() -> pathlib.Path | None:
    """Path of the editable config file, or None if it cannot be located."""
    override = os.getenv("EMBEDDING_CONFIG_PATH")
    if override:
        return pathlib.Path(override)
    home = _isabelle_home_user()
    if home is None:
        return None
    return home / "etc" / "embedding_config"


def _ensure_seeded(path: pathlib.Path) -> None:
    """Copy the bundled template to `path` if it does not exist yet."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_TEMPLATE_PATH, path)


def load_embedding_config(force_reload: bool = False) -> dict:
    """Load (and cache) the embedding configuration dict.

    Seeds the user config from the bundled template on first run. If the user
    config location cannot be resolved (e.g. ISABELLE_HOME_USER unset), falls
    back to reading the bundled template read-only.
    """
    global _config, _config_source
    if _config is not None and not force_reload:
        return _config
    path = _resolve_config_path()
    if path is not None:
        _ensure_seeded(path)
        source = path
    else:
        source = _TEMPLATE_PATH
    with open(source, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _config = data
    _config_source = source
    return data


def config_source() -> pathlib.Path | None:
    """Path the active config was loaded from (for diagnostics)."""
    return _config_source


def dimension(model: str) -> int:
    """Embedding vector dimension for a canonical model name. Hard error if missing."""
    cfg = load_embedding_config()
    dims = cfg.get("dimension") or {}
    if model not in dims:
        raise KeyError(
            f"No 'dimension' entry for model {model!r} in embedding config "
            f"({_config_source}). Add it under 'dimension:'.")
    return int(dims[model])


def default_scores(model: str) -> tuple[float, float]:
    """(non-local, local) fallback scores for a model; defaults to (0.0, 0.0)."""
    cfg = load_embedding_config()
    entry = (cfg.get("default_scores") or {}).get(model)
    if not entry:
        return (0.0, 0.0)
    return (float(entry.get("score", 0.0)), float(entry.get("local", 0.0)))


def normalize(model: str) -> bool:
    """Whether to L2-normalize the model's returned vectors; defaults to False."""
    cfg = load_embedding_config()
    return bool((cfg.get("normalize") or {}).get(model, False))


def max_request_size(model: str, default: int = 2048) -> int:
    """Max texts per non-batch request for a model; defaults to `default`."""
    cfg = load_embedding_config()
    return int((cfg.get("max_request_size") or {}).get(model, default))


def _provider_entry(domain: str) -> dict:
    cfg = load_embedding_config()
    return (cfg.get("providers") or {}).get(domain) or {}


def api_model_name(domain: str, model: str) -> str:
    """The model id this domain expects in the API body; canonical name if unmapped."""
    norm = _provider_entry(domain).get("normalization") or {}
    return norm.get(model, model)


def batch_config(domain: str) -> dict | None:
    """Batch API config for this domain, or None if batch is not configured."""
    return _provider_entry(domain).get("batch")
