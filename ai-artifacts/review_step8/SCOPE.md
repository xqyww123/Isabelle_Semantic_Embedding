# Review of step 8: user-visible texts (§12), documentation (§11), and the deferred elegance-INT-4 cleanup

All paths are relative to `contrib/Semantic_Embedding/` (absolute root:
`/home/qiyuan/Current/MLML/contrib/Semantic_Embedding/`).  The code under
review is the WORKING TREE of this repository: HEAD `6cac576` plus the
uncommitted change set captured in `ai-artifacts/review_step8/working_tree.diff`
(read the diff first, then the files on disk).  One more edited file lives
outside this repository: `/home/qiyuan/Current/MLML/CHECK_OUTDATE_PLAN.md`
(the parent design, untracked; read it on disk, its sections named below).
Two foreign uncommitted edits are NOT part of the review and must be
ignored: `Tools/entity_position.ML`, `archive/tests/test_migrate_from_collection.py`.

Do not modify any file.  You may run pytest (command below) and small
Python probes over a throw-away `SEMANTIC_DB_DIR`; never run `isabelle
build`; never start, connect to, or kill any Isabelle process; never point
anything at the real cache.

## What step 8 is

The last item of the implementation order (`ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md`
§13 item 8): put every approved user-visible text of §12 at its site, bring
the documentation of §11 up to date, and apply the one cleanup the
integration review deferred to this step (`ai-artifacts/review_integration/judge.json`,
finding `elegance-INT-4`, ruling "fix").  No new behaviour is designed here;
the texts were approved by the user verbatim on 2026-09-08 (§12), and the
sites were found by grepping each current text's distinctive words.

### §12 texts, site by site (verify each against §12 of the plan)

- `_report` in `semantic_interpretation.py` now prepends
  `[Semantic_Embedding] ` to every line it forwards to Isabelle (and logs
  the same string); every `_report` call site is a §12 text (#5, #7, #13,
  #14, #16; the startup check's #4).  The literal prefix of #4 was dropped
  accordingly.  #1–#3 (lock busy) were placed by step 7; #4 stays verbatim
  by the user's ruling; #15 (the give-up error) is raised, not reported,
  and already matched.
- #6 (`semantics.py`, the Yes branch of the AoA startup dialog):
  `[Semantic_Embedding] Choice received.` -- the two other branches of the
  dialog are not in §12 and are untouched (project rule: never change
  existing behaviour beyond the user's decision).
- #7 (closing line per theory), #16 (the three per-theory opening lines):
  `semantic_interpretation.py`, `interpret_file`.
- #8 (`Tools/interpret_command.ML`, the Isar command's confirmation): the
  approved wording; the pre-existing singular/plural switch on the number
  word was kept (`1 entity` / `n entities`), as before.  The theory count
  `m` is no longer shown (the approved text lists the theories instead).
- #9, #10, #11 (`semantics.py`, `update_interpretations`): the dialog's
  first line, the below-threshold tracing line, the non-interactive
  warning -- all "At least <n> …".
- #12: the approved dry-run comment sits at Python's `dry_run` branch
  (already there since step 4) and now in the signature comment of
  `Semantic_Store.dry_run` (`Tools/semantic_store.ML`).

### §11 documentation and comment sites

- `/home/qiyuan/Current/MLML/CHECK_OUTDATE_PLAN.md` (Chinese): glossary
  (`dry run` row rewritten as a lower bound; new rows `semantic change gate`
  and `eff*`), §3.1 construction point, §4.1 (eff* paragraph), §4.2 I2/I3/I4,
  §8 pipeline block, write-back disciplines 3 and 4, the dry-run metering
  paragraph, §14's dry-run acceptance row (the "n == actual work" assertion
  retired).
- ML and Python comment sites that stated the retired equality "dry-run
  count = live work": `Tools/semantic_store.ML` (signature of `dry_run`,
  `enumerate_entries`, `dry_run_payload`, the proof-channel de-duplication
  inside `dry_run` -- restated on the surviving premise "no uk may be
  counted twice inside one dry run, or n stops being a lower bound"),
  `Tools/interpret_command.ML` (the dry-run comment before the confirmation),
  `semantic_interpretation.py` (`interpret_file`'s docstring, the
  `_interpret_file_dry_run` RPC docstring).  The completeness-invariant
  comment in `interpret_file` was already restated per §15.4 in step 3
  and is unchanged.
- `doc/invalidation_limitations.md` (Chinese): new #7 and its index row;
  header lines updated.
- `README.md` §5: one sentence on the gate.

### elegance-INT-4

`AgentTask.__enter__/__exit__` deleted (they were `return self` / `pass`;
`Self` import dropped); the live construction site uses plain assignment
and its block is dedented (behaviour identical: `__exit__` returned None);
`historical_cost` is a `@staticmethod` taking the theory key, so the
all-cached branch reads the one stored tuple with no object built:
`CostSummary(*AgentTask.historical_cost(theory_key))`.  The judge's fix
text allowed either a staticmethod or a delegate; the staticmethod was
chosen and the one test call site (`test_layered_db.py`) updated.

## Tests

    cd /home/qiyuan/Current/MLML/contrib/Semantic_Embedding && \
    python -m pytest archive/tests -q -p no:cacheprovider --continue-on-collection-errors \
      --deselect archive/tests/test_agent_dir_packaging.py \
      --deselect archive/tests/test_config_resolution.py \
      --deselect archive/tests/test_fireworks_qwen.py

→ 408 passed (the three deselected modules are the 16 pre-existing,
unrelated failures documented in the previous reviews).  The two ML tests
(`Test/Interpretation_Driver_Config_Test.thy`, `Test/Interpretation_Lock_Test.thy`)
passed through the REPL server on a heap rebuilt from the edited ML
sources -- so the ML edits compile.  Do not repeat the ML run.

Three tests were adjusted for the texts: `test_update_interpretations.py`
(the Yes acknowledgement is now exactly #6), `test_semantic_change_gate.py`
(the two log-line asserts carry the prefix), `test_layered_db.py`
(`historical_cost` called as a staticmethod).

## The plan (authoritative)

`ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md`: §0 glossary, §2 user decisions
D1–D19 (do not re-open), §5.2 (the dry run as a lower bound and the
approved comment), §8.1 (release ordering), §11 (the documentation list
this step executes), §12 (the texts, verbatim), §13 item 8.  Every ruling
in `ai-artifacts/review_step*/judge.json`, `review_integration/*.json` is
settled; the user's declined proposals listed in
`ai-artifacts/review_integration/SCOPE.md` stay declined.

## What the review is asked to judge

1. Fidelity: is every §12 text at its site exactly as approved (modulo the
   documented singular/plural switch of #8)?  Is any §12 text missing a
   site, or any site still carrying an old wording?  Grep for distinctive
   words of the OLD wordings to check nothing was left behind.
2. No behaviour change beyond the texts and INT-4: the `_report` prefix
   must not reach any non-§12 line; the dedent must be behaviour-identical;
   `historical_cost` must read the same tuple as before.
3. Documentation truth: every sentence added to `CHECK_OUTDATE_PLAN.md`,
   `doc/invalidation_limitations.md`, the README and the comments must be
   TRUE of the code as it is (cite the code line when you dispute one).
   Numbers in `invalidation_limitations.md` #7 must match
   `ai-artifacts/similarity_measurement/REPORT_PHASE2.md` (§7, §11), the plan's
   §7, and `ai-artifacts/eff_shield_verification/REPORT.md`.
4. Comments: short and load-bearing; no comment may still state the
   retired equality between the dry-run count and the live work.
5. Elegance of INT-4 as applied.

## Project rules that bind the review

- Elegance is a review criterion equal to correctness; reject dirty hacks.
- Reuse code; never reinvent; consistent terminology (the plan's §0
  glossary).  Comments in code short and load-bearing.
- Nitpicking (style-only remarks, hypotheticals with no concrete failure,
  restating the plan, "consider adding a comment", re-raising a settled
  decision or a previous ruling, proposing to reword an APPROVED §12 text)
  is to be rejected harshly and named as such.
- If slightly relaxing one of the user's constraints or design decisions
  would make the code markedly simpler or more elegant, say so explicitly as
  a PROPOSAL for the user — do not smuggle it in as a bug.

## Round two: what changed since the first review (rulings of `judge.json`, applied 2026-09-12)

The diff to review is now `ai-artifacts/review_step8/working_tree_round2.diff`
(HEAD `6cac576` → working tree, foreign files excluded; it supersedes
`working_tree.diff`).  `judge.json` holds the first round's rulings.

- **docs-DOC-1 (major, user's decision).**  The judge refuted the claim
  that the dry-run count is a lower bound over a cone: `schedule_dag` scans
  a descendant theory only after its ancestors' writes, and an ancestor's
  UNCHANGED verdict raises its `interpreted_at` to eff\*, walling off a
  dependent in the later theory that the dry run had counted -- so the live
  run can send fewer.  The user ruled on 2026-09-12: the four texts §12
  #8–#11 say "About <n>" and gain one sentence, `The run interprets these
  and, where a meaning changed, their dependents.` (#8, #9) or `, and their
  dependents where a meaning changed` (#10); #11 only replaces "At least"
  by "About".  The plan's §12 #8–#11 carry the re-approved texts verbatim
  (with the singular forms noted there); §5.2 and §11 now state "neither
  bound … exact at zero"; `CHECK_OUTDATE_PLAN.md` (glossary `dry run` row,
  §8 pipeline block, §8 "n 不是界" paragraph, §14 row, the §8 caller-table
  row for `run_semantic_interpretation` -- behaviour-F4, approved by the
  user) and the cone-level comments (`interpret_command.ML`,
  `semantic_store.ML`'s `dry_run` signature, the `dry_run` docstring and
  the `_interpret_file_dry_run` docstring in `semantic_interpretation.py`)
  say the same.  The per-theory approved §12 #12 sentence is at
  `dry_run_payload` and Python's `dry_run` branch only.
- **texts-F1**: the `interpret_file_dry_run_cmd` comment rewritten as the
  judge prescribed.  **texts-F2**: superseded by DOC-1's new texts -- the
  ML site's switch now covers noun and verb (`1 entity … is` /
  `n entities … are`); Python's #10 gained `entity/entities`, `its/their`,
  `theory/theories`, #11 `theory/theories` (the user approved these
  singular forms).  **texts-F3**, **behaviour-F2**, **behaviour-F3**,
  **docs-DOC-3** (both sites), **docs-DOC-4**, **docs-DOC-5**,
  **elegance-S8-2**: applied as prescribed.  Three more "lower bound / at
  least" comment remnants found by grep were reworded (the dry-run host-log
  line, the warning-point comment in `semantics.py`, the proof-channel
  de-duplication comment).
- Rejected by the judge (do not re-raise): docs-DOC-6 (README sentence),
  docs-DOC-7 (#7's measurement header), elegance-S8-6 (§8 aliases and line
  anchors).

Suite after the changes: 408 passed, 16 deselected.  The ML sources were
recompiled by a fresh REPL heap and the two ML tests re-run (see the
round-two note at the end of this file once it is appended); do not repeat.

### What the re-review is asked to judge

1. Are the re-approved §12 #8–#11 texts at their sites verbatim (with the
   approved singular forms), and does no site or comment still say "At
   least" / "lower bound" in the cone-wide sense?  (`grep -n "At least\|at
   least\|lower bound\|LOWER BOUND"` over the four code files: the only
   survivors must be the per-theory §12 #12 comment at `dry_run_payload`
   and Python's `dry_run` branch, the per-theory clause of the `dry_run`
   docstring, and an unrelated measurement remark in `semantic_store.ML`.)
2. Is every sentence about the dry-run count in the two plan documents,
   the glossary, and the comments TRUE of the code (the "more or fewer"
   statement, "exact at zero", the per-theory lower bound)?
3. Were the first round's mechanical fixes applied exactly, with nothing
   else changed?

Round-two ML note: the heap was rebuilt from the round-two ML sources by a
fresh REPL server and both ML tests passed again (2026-09-12); the server
is stopped.  Do not start one.
