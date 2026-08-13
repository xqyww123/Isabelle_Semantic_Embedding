"""
Isabelle Semantic Embedding module for premise selection and semantic search.
"""

from .premise_selection import (
    embed,
    embed_goal,
    embed_premises,
    embed_goal_and_premises,
    encode_goal,
    encode_premise,
)

from .theory_structure import mk_unicode_file, theory_info
from .hover import goto_definition, hover_message, command_at_position
from .semantic_interpretation import interpret_file, _interpret_file
from .semantics import (
    Semantic_DB,
    mk_query_by_name_tool as query_by_name_tool,
    _query,
    _is_interpreted,
    _mark_interpreted,
    _clean_wip,
    # RPC handlers register as an import side effect of @isabelle_remote_procedure,
    # so a handler missing from this list never registers and ML fails at CALL time
    # with an unknown-procedure error (ENTITY_POSITION_PLAN.md §15.6(e)).
    _backfill_positions,
)
from .rekey_dump import _dump_entities, _dump_preflight, _dump_scan
from . import semantics

__all__ = [
    "embed",
    "embed_goal",
    "embed_premises",
    "embed_goal_and_premises",
    "encode_goal",
    "encode_premise",
    "goto_definition",
    "hover_message",
    "command_at_position",
    "interpret_file",
    "Semantic_DB",
    "query_by_name_tool",
    "theory_info",
]
