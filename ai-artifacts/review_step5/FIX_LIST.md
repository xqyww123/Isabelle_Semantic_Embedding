# Step 5 review — fix list (judge: NOT acceptable until 1–3 land; 10 agents, 10 raised, 5 kept, 5 ruled, nothing for the user)

Production fixes (need the user's approval):
1. machinery-F2 (major): `_prefilter`'s `embed` call runs with the embed
   machinery's tracing ungated → 2–3 Isabelle tracing lines per judged
   entity, against `editor_tracing_messages` (1000; overflow blocks).  Fix:
   import `_embed_tracing_gated` from semantic_embedding; in `_prefilter`
   `token = _embed_tracing_gated.set(True)` before the `try`, `reset(token)`
   in a `finally`.  Test: `_FakeProvider.embed` records the flag; assert True.
2. gate-F1 (major): §12 #5 printed once per gate in flight, not once per
   run (gates already inside the failing `embed` all report).  Fix:
   `RunState.claim_prefilter_disable() -> bool` (flip and say whether this
   caller flipped); `_prefilter` logs the traceback unconditionally, reports
   only when the claim returns True; docstring reworded.  Plan edits by hand:
   §15.5 (the "flag before the report" sentence) and §5.4 Failures.  Test:
   parametrise the failure test over `delay in (0.0, 0.01)`, both entities'
   embeds failing, one line in both.
3. agreement-F4 (minor): on the prefilter timeout `{exc}` renders empty
   (`str(TimeoutError()) == ""`) → "did not respond: " with a dangling
   colon; the timeout is the dominant failure (the provider's retry ladder
   passes 60 s before it can raise).  Fix: `{str(exc) or type(exc).__name__}`.
   Test: assert the line in the timeout test.

Tests only (done, no approval needed):
4. agreement-F1 (major): the answer tool's `_NOT_ENROLLED` refusal was
   untested (mutation left the suite green).  Added
   `test_an_answer_for_an_entity_this_run_did_not_ask_for_is_refused`
   (fails with the clause removed, passes on the shipped code).

Bookkeeping only:
5. machinery-F3 (minor): no code change.  Derivation 7 understated the
   effect: until step 6 threads D16's `warn`, an unconfigured embedding
   service prints the whole 23-line setup message on the warning channel
   once per seeded theory.  Say so in SCOPE.md and the commit message.
