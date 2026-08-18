# Dynamic-collection member records: naming and position

Forward plan. What this document describes has not been implemented; no production code
has been changed for it.

## 1. The situation

A `named_theorems` collection — or any collection made with `add_thms_dynamic` — is one
entry in Isabelle's fact name space whose value is a function. Its members are not in that
name space at all: they live in an `Item_Net` that carries no positions and no names of
their own. So when our enumeration meets a member it has nothing to call it and nowhere to
point, and it invents both: the name becomes the collection's name plus the member's
1-based position in that sweep's member list, rendered at
`Tools/semantic_store.ML:852-856`, and the position is left empty.

Two consequences, and only the first is a defect worth acting on.

**The invented name looks citable and is not stable.** `tendsto_intros(123)` is exactly the
shape of an Isabelle fact selection, so a reader — human or agent — may lift it and use it.
But the index counts members in the cone of whichever theory was being swept, so the same
string denotes different theorems in different contexts. Measured on the current store,
`Topological_Spaces.tendsto_intros(123)` names two different propositions; before an earlier
repair it named eight. An ordinary shared name does not invite citation; this one does, and
that distinction is why this is worth fixing while the store's other ambiguous names are
not.

**The absent position is correct, not a defect.** These theorems genuinely have no
declaration site of their own (ENTITY_POSITION_PLAN.md §10 rule 1). Nothing below tries to
invent one.

Scale: **9,598 records of 1,343,793 (0.7 %)**, spread over 137 collections. The rest of the
store's `X(i)` names — 320,439 of them — belong to static multi-theorem bundles, whose
indices are stable and whose records carry real positions; nothing below touches those.

## 2. What we will do

### 2.1 Stop a stored name reaching an LLM where a live one is already in hand

Two sites, about five lines, no data change, no release.

**The pattern-only query branch** (`contrib/Isa-Mini/IsaMini/AoA/model.py:2318-2322`). When
a query carries term patterns but no description, the loop iterates
`for uk, name, _ in entries` — where `name` is the live, context-resolved name from this
query's own enumeration — and then appends `rec` with its stored name untouched. Use
`rec._replace(name=name)`.

**The by-name entity query** (`contrib/Isa-Mini/IsaMini/AoA/retrieval.py:937`, reachable with
any entity kind through `IsaMini.query_by_name`, `toplevel.py:65-73`). It prints `rec.name`.
Print the name that actually resolved instead — `short` in the retry branch that resolves a
short xname, otherwise `name`. Note that `rec.name` is fully qualified while the caller's
may not be, so this must not be a blind substitution.

A third site is **not** fixed: the head of the embedded document is the stored name
(`Isabelle_Semantic_Embedding/document_text.py:50` via `Record.pretty_print`,
`semantics.py:279-283`). Changing what is rendered there would alter what a record's vector
should be with no record write to invalidate it, leaving vectors permanently stale and
undetectable. The index costs a few tokens at the head of a document whose body carries the
meaning; it stays.

### 2.2 Record on each record that its stored name is an invented member form

**The predicate is about the name, not about the entity's origin.** It is true exactly when
`build_entries` rendered the name from a member index (`Tools/semantic_store.ML:852-856`).
It is *not* "this entity came from a dynamic collection": 4,524 records that came from
dynamic collections already carry ordinary static names and real positions, and must not be
flagged. Any member that later acquires a real name must not be flagged either.

**Name and type.** A boolean field, `name_is_member_form`; ML `bool`; msgpack `true` /
`false`; absent on records written before the field existed. Readers test for `is True`.

**Where it is set and how it travels.** In ML at the render site above; onto the
`interpret_file` wire (`packTuple10` → `packTuple11`, `Tools/semantic_store.ML:378-383`);
into `Entry` (`Isabelle_Semantic_Embedding/semantic_interpretation.py:222`, built at
`:1247`); into the `Record` at the point the entry becomes a record (`:373`); and into the
codec as field 14 (`semantics.py` `_decode`/`_encode`).

**Existing records get it once, by name.** The criterion is: the name matches
`^(.*)\((\d+)\)$` and the base names a `THEOREM_COLLECTION` record. On the current corpus
this is exact in both directions — every record it selects lacks a position, every record it
rejects has one, zero exceptions. The criterion depends on the corpus (a future snapshot
could add a static bundle whose name also names a collection), which is why it is used once
over records that already exist and never as a test at read time.

### 2.3 Render the invented form where results are shown to a person

A reader is shown `tendsto_intros(_)` in place of `tendsto_intros(123)`. `(_)` is chosen
because an Isabelle fact selection takes a number (`Pure/Isar/parse.ML:471-473`), so a
citation of `coll(_)` fails loudly rather than resolving to the wrong theorem — which a bare
`coll` would do.

**Exactly one place: where a result is rendered for display.** Not in the data the search
site is built from, because there the name is not display-only — it feeds the identity hash
that collapses results onto one entity page and the subtoken array behind the name filter,
so rewriting it there would merge distinct records and change what the filter matches.

**And nowhere else.** Each exclusion below would break something specific:

- `Record.pretty_print` and anything `document_text_of` reaches — stale, undetectable
  vectors, as in §2.1.
- Isa-Mini/AoA's retrieval and citation path — there the displayed name is a handle, not a
  label: it is passed back to ML to resolve (`model.py:2347`), becomes `FactByName` "as the
  model writes it" (`:2443-2447`), and is re-resolved (`retrieval.py:574`). A member form
  there is unresolvable.
- The by-name lookup path (`model.py:2198-2201`), for the same reason.
- Any online read path in `Semantic_DB`, whose records are handed on for ML resolution.

The reason for confining it: the field says the record's stored name is an invented form. It
does not say that rewriting the name is safe at a given call site — that is a property of the
call site. Restricting the rule to a surface that only ever displays removes the question.

## 3. Constraints an implementer must respect

**The codec drops a 14th field unless both halves are changed.** `_decode` pads to 13 and
slices `vals[:13]` (`semantics.py:365-367`); `_encode` emits 13. Both need the new count, or
every decode-modify-encode round trip silently loses the field.

**A re-interpretation clears it.** `write_answer` (`semantic_interpretation.py:372-379`)
builds a fresh `SemanticRecord`, so re-interpreting a member would drop the flag while its
name is still an invented form. The field must be threaded there.

**The backfill must not write through `Semantic_DB.__setitem__`** (`semantics.py:601-621`),
which invalidates vectors unconditionally and would force a re-embed of 9,598 records for a
field that is not part of the embedded document. Use a raw put as `set_positions` does
(`semantics.py:794-815`). That bypass needs an explicit grant of the kind
ENTITY_POSITION_PLAN.md L6 gave, not an assumption.

**The backfill must refuse to run against an installed system-layer database**, or
`_raw_for_update` (`semantics.py:694-703`) will copy 9,598 system records up into the user
layer.

**The backfill must skip EXPERIENCE records** (kind byte `0x08`): their names are
agent-chosen strings and may take any shape.

**The backfill writes the field on every record it walks** — `true` on a match, `false`
otherwise — so that after it runs, absent means only "this record was not reached".

**Renaming a record must clear the field.** Any pass that rewrites a record's name must
clear index 13 in the same write.

**The wire change is lockstep.** The conda package ships the Isabelle and Python halves
together, but PyPI ships the Python half alone, so both channels must be released together.
Make the arity failure self-describing: on unpacking the entry tuple, raise a message naming
the expected and actual arity and saying the two halves are from different releases.

**`snapshot_sync.SCHEMA_VERSION` is not bumped.** It was not bumped for the 13th field
either; bumping it would make every installed client refuse the snapshot.

**Tests that encode the arity** need updating: `test_entity_position_codec.py`'s wire-entry
builder and `test_entity_position_backfill.py`'s field-count assertions. A new test should
cover a collection with one member that has an invented name and one that does not.

## 4. Settled, and what is still to decide

**Settled: the field is stored, and ML supplies it.** Not derived at read time. The
consumer is the semantic-search front end, which serves live queries against a corpus that
keeps growing; applying a corpus-dependent test there would mean re-earning its correctness
on every future snapshot, and its failure mode is silent — a static bundle's stable `foo(3)`
rendered as an invented form. The enumeration knows the answer for certain at the moment it
invents the name, so that is where it is recorded. The costs in §3 are accepted.

**Settled: `Thm.get_name_hint` is used in the enumeration.** A member's theorem often
carries a tag naming the fact it was declared as, and that name has a real position; where it
resolves, the member gets that name and that position instead of an invented form, and the
member index is not appended. Where it does not resolve, the name stays `coll(i)` and §2.2's
field is set. It recovers nothing for the 9,598 records already in the store — that is
measured and is not a reason against it, because its purpose is that future sweeps stop
producing them.

Three things it must do, which the measurements settled:

- Pass through the `Thm_Name.T` the tag yields. Do not force an index of 0: that would
  collapse `foo(1)` and `foo(2)` onto one label, and two entries with one label abort the
  sweep on the label-uniqueness assert.
- Verify that the named fact's proposition equals the member's, with one `aconv` — both
  theorems are in hand. A name that resolves to a different fact of the same name in the
  sweep's context would otherwise produce that same aborting collision.
- Apply the guards the static path applies: reject a concealed name, a name hidden under
  `Long_Name.is_hidden`, and the unknown marker the tag defaults to.

**D1 — the order of work.** §2.1, §2.2 and the enumeration change above are independent of anything undecided and can be done now.
§2.2 is independent too. §2.3 lands when the search front end's display layer exists.

## 5. What was already done to the store

Recorded because it changed production data and nothing else records it.

On 2026-08-18, after a reflink backup (`semantics.lmdb.pre-rename-20260817-235750` and the
vector store's twin, entry counts verified equal), **4,524 records were given a real name and
a real position** taken from data the store already held, and their vectors were dropped and
re-embedded (744,481 tokens). Every edit was read back; 0 problems. Report:
`~/rename_report.json` on `cslh19`; the pass was `rename_dynamic_members.py`.

Where the names came from: a theorem-alike key is `XOR(constituent hashes) ++ tag ++
thm128[:15]`, so records of one proposition differ only in the kind byte. Where a member's
proposition already had a positioned record under another kind — the theorem face, enumerated
statically in some other theory's sweep — that record's name and position were copied onto
the member face (4,519 records: 4,439 introduction rules, 80 elimination rules). Five more
took a positioned record that sat on the very same key.

Two consequences that matter for the work above. **The repair is not a fixpoint**: its scan
completed before its own writes, so one further record (`Topological_Spaces.tendsto_intros(123)`)
became repairable during the run and is still unrepaired; a second run would find it.
**Store coverage afterwards**: 1,343,793 entity records, 98.78 % with a position; of the
16,368 without, 6,768 are EXPERIENCE records, 9,598 are the population this plan is about, and
2 are the methods `Named_Simpsets.simp` and `Named_Simpsets.simp_all`.

One measurement bears on D2 and is not worth repeating: `Thm.get_name_hint` recovers **0** of
those 9,598. Over eleven collections holding 7,099 of them, a probe covered 5,768 and named
none, although the same probe produced 305 members elsewhere whose names did resolve. The
reason is structural — a hint resolves exactly when the theorem is also a named static fact,
which is the same condition under which the repair above already renamed the record.
