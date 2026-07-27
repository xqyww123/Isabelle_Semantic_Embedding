"""The agent's skills must reach an installed copy.

They are the deformalisation agent's Isabelle knowledge: without them it still
runs, just uninformed, and the output is indistinguishable from a good run at
the same price.  They have been dropped from a wheel once already -- setuptools'
glob skips hidden directory components, so `Agent_Interpretation_Dir/**/*`
matched nothing at all and did so silently.

The check runs setuptools' OWN globbing (`build_py.find_data_files`) against
this project's real `package-data`, rather than re-implementing the glob rules
whose surprises are the whole problem.
"""
import pathlib
import tomllib

import pytest
from setuptools import Distribution
from setuptools.command.build_py import build_py

_ROOT = pathlib.Path(__file__).parent
_PACKAGE = "Isabelle_Semantic_Embedding"
_SKILLS = ("isabelle-intro-elim-rules", "isabelle-datatype", "isabelle-record")


def _packaged_files() -> set[str]:
    """The package-data files an install would carry, per setuptools itself."""
    with open(_ROOT / "pyproject.toml", "rb") as f:
        package_data = tomllib.load(f)["tool"]["setuptools"]["package-data"]
    dist = Distribution({"name": "probe", "package_data": package_data})
    cmd = build_py(dist)
    cmd.package_data = package_data
    cmd.manifest_files = {}
    cmd.exclude_package_data = {}
    src = str(_ROOT / _PACKAGE)
    return {str(pathlib.Path(p).relative_to(_ROOT / _PACKAGE).as_posix())
            for p in cmd.find_data_files(_PACKAGE, src)}


@pytest.mark.parametrize("backend_dir", [".claude", ".codex"])
@pytest.mark.parametrize("skill", _SKILLS)
def test_every_skill_ships_for_every_backend(backend_dir, skill):
    want = f"Agent_Interpretation_Dir/{backend_dir}/skills/{skill}/SKILL.md"
    assert want in _packaged_files(), (
        f"{want} would not be installed; check the package-data patterns in "
        f"pyproject.toml (a dot component must be spelled out)")


@pytest.mark.parametrize("backend_dir", [".claude", ".codex"])
@pytest.mark.parametrize("skill", _SKILLS)
def test_the_skills_are_not_empty(backend_dir, skill):
    """Shipping the path but not the content fails exactly as invisibly."""
    p = (_ROOT / _PACKAGE / "Agent_Interpretation_Dir" / backend_dir / "skills"
         / skill / "SKILL.md")
    assert p.is_file() and p.stat().st_size > 0


def test_the_two_backends_share_one_copy_of_each_skill():
    """`.codex/skills` is a symlink to `.claude/skills`, so the two cannot drift
    -- editing a skill for one backend edits it for both, by construction."""
    codex = _ROOT / _PACKAGE / "Agent_Interpretation_Dir" / ".codex" / "skills"
    claude = _ROOT / _PACKAGE / "Agent_Interpretation_Dir" / ".claude" / "skills"
    assert codex.is_symlink(), "expected a symlink, not a second copy"
    assert codex.resolve() == claude.resolve()
