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
declaration site of their own (ENTITY_POSITION_PLAN.md §10 rule 1, which §2.4 amends).
Nothing below invents one.

Scale: **9,598 records of 1,343,793 (0.7 %)**, spread over 137 collections. The rest of the
store's `X(i)` names — 320,439 of them — belong to static multi-theorem bundles, whose
indices are stable and whose records carry real positions; nothing below touches those.

## 2. What we will do

### 2.1 Stop a stored name reaching an LLM where a live one is already in hand

Four sites get the substitution: the three described next plus a fifth after them (the
numbering skips a fourth, which is deliberately not fixed — see below). Which of the two
substitution functions each site calls is stated once, in the table at the end.

**The pattern-only query branch** (`contrib/Isa-Mini/IsaMini/AoA/model.py:2318-2322`). When
a query carries term patterns but no description, the loop iterates
`for uk, name, _ in entries` — where `name` is the live, context-resolved name from this
query's own enumeration — and then appends `rec` with its stored name untouched.

**The by-name entity query** (`contrib/Isa-Mini/IsaMini/AoA/retrieval.py:937`, reachable with
any entity kind through `IsaMini.query_by_name`, `toplevel.py:65-73`). It prints `rec.name`.
Do **not** print the caller's `name`/`short`: `rec.name` is fully qualified and the caller's
may not be, so a blind substitution drops the qualification from every entity kind on every
by-name query. The qualified live name is already computed and thrown away on this very
call — `universal_key_of` is `universal_key_and_name_of` with the name discarded
(`Isabelle_RPC_Host/universal_key.py:206-209`, and `model.py:2207` already uses the
two-value form). Capture the resolved name in **both** branches, at `:918` and at `:924`. And
handle the case where the resolved live name carries **no** index: a collection holding exactly one
member resolves from the agent's bare `C`, `parse_thm_xname` returns no index
(`Isabelle_RPC/Tools/Universal_Key.ML:830-845`), and the live name is then the bare collection name
— the one thing §2.3 rules out showing. For a record whose `from_collection` is set, never display
an index-free live name; keep the stored name. See also the last paragraph of this section, which
removes the need for Python to reassemble anything at all.

**The interpretation agent's `query` MCP tool** (`semantics.py:1441-1459` → `query_by_name_raw`
`:1486` → `Semantic_DB.query(uk, with_pretty=True)` `:678-692` → `Record.pretty_print`
`:279-283`). This serves the **stored** name to the LLM that writes the corpus's English
(the tool is in the interpretation driver's list, `semantic_interpretation.py:1158-1166`, and
the system prompt directs the agent to it, `:195-198`). It is the most consequential of the
three: a bad name shown to a human causes confusion, a bad name shown to this model gets
written into the corpus. The vector argument that freezes the fourth site below does **not**
apply here — `semantics.py:686-691` states in code that the embed path no longer routes
through `query`.

**A fifth site, in the same file as the first**
(`contrib/Isa-Mini/IsaMini/AoA/model.py:2198-2204`). The bundle branch does
`rec._replace(name=ref_name, kind=tag)` unconditionally, and `ref_name` comes from ML's
`key_of_theorems_tagged`, whose `fun ref_at i = full_name ^ "(" ^ Int.toString i ^ ")"`
(`Isabelle_RPC/Tools/Universal_Key.ML:905`) manufactures the invented form over a `Facts.lookup`
that evaluates dynamic collections. So an agent asking for a collection by name gets
`tendsto_intros(37)` stamped over the real stored name on precisely the 4,524 records §5 repaired.
Give it `apply_live_name_if_member` (its row in the table below), and add the **chosen** name — not `ref_name` — to
`bundle_member_names` at `:2203`, so the `suppress_def` match still works.

**Two rules, so two named functions — the name at the call site is the policy.** There is no
single substitution: some callers must take the live name unconditionally, others only for
members. Wrapping both behaviours in one function with a flag would put a polarity decision at
every call site; a bare predicate would push `X if p(rec, live) else Y` into every caller. Instead,
two module-level record→record functions, the second defined via the first so the body exists once:

```python
def apply_live_name(rec, live):
    """Unconditionally prefer the live, context-resolved name. For callers whose
    records come from this query's own live enumeration: the name is a handle the
    agent will cite back, and the live one is the one guaranteed to resolve in the
    querying context."""
    return rec._replace(name=live) if live is not None else rec

def apply_live_name_if_member(rec, live):
    """Substitute only when the stored name is an invented member form (§2.2's
    field decides) AND the live name carries an index. An index-free live name is
    the bare collection name — the one thing §2.3 rules out showing (see the
    second site above). Everything else keeps its stored name: without the
    condition, the 4,524 records that already carry real names (§5) would be
    shown to a model as `tendsto_intros(37)` — the unstable string §1 calls the
    defect."""
    if rec.from_collection is not None and live is not None and _carries_index(live):
        return apply_live_name(rec, live)
    return rec
```

(`_apply_live_name`, `semantics.py:2046-2051`, is today's closure form of the first function —
lift it to module level; its closure variable `candidate_names.get(uk)` becomes the `live`
argument. `_carries_index(live)` is one regex — the name ends in `(digits)` — defined next to the
two functions; it tests the **live** string ML handed over, never the stored one. Measurement
backing the member condition: of the members a name can be found for at all, roughly 6 % are ones
the store knows and §2.4 cannot recover (§6).)

**Which caller takes which function** — the "why" column reduces to two reasons, and the reason
is a property of where the *name* came from, not of the display site: the record was surfaced by
this query's own live enumeration (unconditional), or the live name was resolved from a
caller-supplied string (conditional):

| caller | function | why |
|---|---|---|
| `semantics.py:2057` (`_resolve`, every scored candidate) | `apply_live_name` | record surfaced by this query's live enumeration; `candidate_names` is filled for every entry in both `Context` branches (`:1984-1985`, `:2000-2001`, `:2020`) |
| `semantics.py:2114` (every reranked candidate) | `apply_live_name` | same enumeration, same handle |
| the pattern-only branch (`model.py:2318-2322`, first site above) | `apply_live_name` | same population and provenance as the two rows above — its loop is a hand-copy of `_resolve` that dropped the substitution line; its `rec is None` fallback already uses the live name |
| the by-name entity query (`retrieval.py:918`, `:924`, second site above) | `apply_live_name_if_member` | the live name comes from resolving the caller's query string, and the index-free case must keep the stored name |
| `Semantic_DB.query`'s `live_name` (third site above) | `apply_live_name_if_member` | same threading as the second site |
| the bundle branch (`model.py:2198-2204`, fifth site above) | `apply_live_name_if_member` | its `ref_name` is manufactured `coll(i)`; the condition is what protects the 4,524 repaired records |

Flipping a conditional row to unconditional is forbidden until someone measures that the stored
name resolves in the querying context across the non-member population.

**Apply it to the record, never to a rendering.** This is the load-bearing instruction for the
third site. `Semantic_DB.query` returns `entity_document_text(rec)` (`semantics.py:678-692`), and
that function is `document_text.py:45-50` — the same module that builds the **embedding**
document, whose header says it is "the ONE place that decides, per `Record.kind`, what string a
record is embedded as". An implementer who reads §2.1 and goes looking for where the string is
built will land there and add a name branch or a `display=True` flag to `pretty_print`, which
changes the embedded document with no record write to invalidate the vector — exactly the failure
the excluded fourth site below exists to prevent, and silent, because no test compares an embedded
document against a displayed one. Instead: `Semantic_DB.query` gains `live_name: str | None = None`
and applies the substitution to `rec` before rendering; `query_by_name_raw` (`:1354-1366`) switches
from `universal_key_of` to `universal_key_and_name_of` to supply it — the same threading the second
site already needs. `document_text.py` is never opened and every caller keeps using `rec.name`.
`Semantic_DB.query` has other callers (`semantics.py:1419`, `:2547`, and
`Isabelle_Semantic_Embedding/desugar.py:119` — same package, not Isa-Mini),
so the new parameter defaults to `None` and they keep today's behaviour unchanged.

**Let ML hand Python the finished name.** Both the second and third sites otherwise have Python
rebuild `name(i)` from a string it was given. The rule for building that string is already owned by
ML and already implemented there: `key_of_theorems_tagged` composes it from `ref_at` and an `n > 1`
test in the same `local` block as `key_of_theorem` (`Isabelle_RPC/Tools/Universal_Key.ML`). Have
`key_of_theorem` return that same display name **as a new fifth component**, leaving `full_name`
and `is_global` untouched — replacing the fourth component would change what four other entity
kinds (18, 34, 50, 66) hand back and would break `is_global`, which must be computed from the bare
interned name. **All five by-name branches consume the new component** — the kind-2 branch
(`:1026-1027`) directly, and the four rule wrappers (`key_of_introduction_rule` /
`key_of_elimination_rule` / `key_of_induction_rule` / `key_of_case_split_rule`,
`Universal_Key.ML:940-955`) each by one line: their tuple destructure grows the fifth component
(the compiler forces this anyway) and their `(uk, name)` result returns the display name in place
of `full_name`. Do **not** leave them returning the index-free `full_name`: a member's rule faces
are the store's dominant member population (§5: 4,439 introduction + 80 elimination of the 4,524
repaired), and an index-free live name is exactly what `apply_live_name_if_member` must reject —
the wrappers would hand back a name composed inside `key_of_theorem` and thrown away four times,
and the stale stored `coll(i)` would keep being shown for precisely the records §1 calls the
defect. `key_of_theorem`'s own tuple, `is_global`, and the fourth component stay untouched; only
which half of the pair the wrappers return changes. Then `universal_key_and_name_of` hands Python
a string it never edits and the `parse_thm_xname` round trip disappears from both sites.

A fourth site is **not** fixed: the text `document_text_of` produces **for embedding**
(`Isabelle_Semantic_Embedding/document_text.py:50` via `Record.pretty_print`). Changing what
is rendered there would alter what a record's vector should be with no record write to
invalidate it, leaving vectors permanently stale and undetectable. The index costs a few
tokens at the head of a document whose body carries the meaning; it stays. Note the scope:
this exclusion is about the embedded document, not about every caller of `pretty_print`.

### 2.2 Give each record one value that says how it was named

**The shape.** "What is this entity called" is one fact about one entity, so it is one value —
not a name, plus a separate index, plus a separate flag, kept in step by hand. Declare it in
`Semantic_Store`, beside the tuple it belongs to:

```sml
datatype entity_name =
    Declared of string        (* adopted verbatim from the producer -- never invented by this
                                 enumeration; a fact name may carry a Thm_Name.print selection
                                 index, e.g. "Foo.bar(2)" *)
  | Member   of string * int  (* invented: the collection's full name, 1-based sweep index *)
```

`build_entries`' input tuple then loses its `int option` member-index component and its `string`
name component becomes `entity_name`, so it goes from five components to four
(`Tools/semantic_store.ML:174-176`, `:605-607`). `tag` at `:1530` wraps every non-member producer
as `Declared n` — true of every one of them, whatever their kind — and `member_entries` stops
re-joining a name and an index that arrived separately.

**`Declared of string` makes no claim about the string's internal structure, and that is the
point.** Four of the producers hand over a name that already carries a selection index —
`Theory_Structure` renders the rule lists' names with `Thm_Name.print (name, i)`
(`theory_structure.ML:283`, `:379`), so they arrive as `"Foo.bar(2)"`. That is the correct name
for those entities, and `Declared "Foo.bar(2)"` says exactly one thing about it: the name space
declared it. Nothing more is claimed, so nothing is false.

Contrast the shape this replaced. Reusing `Context_Callbacks.entry_name` — whose `Fixed` case
carries a `Thm_Name.T`, a pair meaning *fact name* and *which theorem of that fact* — would have
forced `tag` to build `Fixed ("Foo.bar(2)", 0)`: a value **claiming** there is a fact called
`Foo.bar(2)` and taking its theorem 0, while **meaning** fact `Foo.bar`, theorem 2. Every lookup
through it silently misses, and every future reader who trusts the type is misled. The same
reuse would also have wrapped constants, types, classes, locales and methods — none of which are
theorems — in a theorem-name type. A value must not misrepresent itself in its own type's terms;
that is the standard this datatype exists to meet.

**Its relationship to `Context_Callbacks.entry_name`** (`contrib/Isabelle_RPC/Tools/context.ML:47-55`,
`Fixed of Thm_Name.T | Member_of_Dynamic of string`) must be written on both, or someone will
delete one as a duplicate. They answer different questions over different populations. That one
asks "how is this **cached theorem** entry called **in the context being queried**" — theorems
only, and its member case carries no index because the live path recomputes it from the
collection's current content (`resolve_name`, `:198-214`). This one asks "how is **this entity, of
any kind,** named **in the record we are about to write**" — hence the sweep's snapshot index.
`member_entries` is the boundary: it maps `Fixed nm` to `Declared (Thm_Name.print nm)` and
`Member_of_Dynamic coll` to `Member (coll, i)`, taking `i` from the index
`process_dynamic_facts_into_cache` already returns beside the entry (`:1027`).

**One projection exported; the other two collapse into the write site.** The record's name and
its `from_collection` field each have exactly one consumer, and it is the same expression — the
record write inside `build_entries`' output map (`:845-856`, where `disp_name` is rendered
today). So they are not exported functions anybody else could grab wrongly (all the candidate
projections return indistinguishable strings, so the compiler cannot catch a mix-up); they are
one local `case` at that site, producing both values from one match:

```sml
val (disp_name, from_coll) =
  case nm of
    Declared n    => (n, NONE)
  | Member (c, i) => (c ^ "(" ^ string_of_int i ^ ")", SOME c)
```

The field and the name provably come from one match, so they can never disagree — and no other
site can call a projection it was not meant to have. Render the member name by hand-concatenation,
**not** `Thm_Name.print (c, i)`: the printer would produce the identical string, but routing the
invented pair through the theorem-name printer re-dresses it as the very thing it is not, at the
one site whose purpose is to keep the distinction. A future consumer with a genuinely new need
writes its own `case` — the compiler then forces it to answer for `Member` explicitly.

The one projection with scattered consumers is exported, with every consumer named:

```sml
fun space_name (Declared n)    = n
  | space_name (Member (c, _)) = c
  (* the carried name with no invented member index appended.  NOT always a
     name-space key as-is: a Declared fact name may carry a Thm_Name.print
     selection index, which fact-space consumers strip (Thm_Name.parse) before
     the lookup -- see serial_of. *)
```

| consumer | projection | why |
|---|---|---|
| the name list handed to `Locale_Instance.detect` (`:690`) | `space_name` | today's exact tokens (bare coll for members), so detection input is unchanged |
| `mk_constituents`' registry key (`:865`, branches at `:834-839`) | `space_name` | name-addressed kinds are never members, so the value is identical to today's |
| `serial_of` (`:1506-1527`) | `space_name` | a member takes its collection's serial — today's behaviour, now stated rather than falling out of string shape |
| `entry_ord`'s name tie-break (`:581`) | `space_name` | identical to today's value, so sort order is unchanged |

**The locale bypass needs no projection at all: the constructors are the answer.** Today it reads
`if Facts.is_dynamic pfacts name then [] else d` (`:698-699`) — a name-space query answering a
structural question ("is this entity a member, or the collection itself?"), run over entries of
**every** kind. For members the query is vacuous (true by construction), and for everything else
it holds only until names collide across name spaces: a locale carrying both a constant `x` and a
`named_theorems x` yields, under an interpretation `q`, a constant `q.x` and a dynamic fact
`q.x` — and the constant, which is precisely a locale-interpretation product, silently loses its
provenance to a lookup in the wrong space. Now that invented-ness is in the type, write the
comment at `:692-697` as code:

```sml
map2 (fn (entity, nm, _, _) => fn d =>
        case nm of
          Member _ => []
        | Declared _ =>
            (case entity of
               Universal_Key.Theorem_Collection _ => []
             | _ => d))
     raw detected
```

No fact-space query, no `pfacts` binding (`:685`; its only use is `:699` — the `pfacts` at
`:1049` is a different function's local). Verified population by population against every
producer feeding `build_entries` (static scans go through `Facts.dest_static`, so a dynamic name
cannot reach them; `Theorem_Collection` is constructed only by `named_theorems_entries`, `:1439`,
whose names are exactly the dynamic facts; a §2.4-renamed member is `Declared` + non-collection
and is detected under both tests, as intended): behaviour is identical everywhere **except** the
cross-space collision above, where today's silent provenance drop becomes correct detection. One
note for the file: `build_entries` is exported, so a comment should warn a future external caller
that a `Theorem_Collection` entity is bypassed by constructor, not by name.

**What this shape does NOT require.** No change to `Context_Callbacks.entry_name` the *type* —
but one comment in `contrib/Isabelle_RPC` must be rewritten: `bare_name`'s doc says "The
DB-storable name of an entry" (`context.ML:69-71`), which becomes false the moment
`member_entries` stops storing through it; reword it to `bare_name`'s remaining role, the live
name-filter key (`:1287`) and display fallback. No change to `Theory_Structure`: it goes on rendering the rule lists'
names, `serial_of` goes on parsing them in its `Declared` branch, and that parse keeps the comment
saying why (`the_entry` is keyed on the bare fact name; the index is not a name-space key —
`theory_structure.ML:258-259`). That round trip is a pre-existing shape this plan does not
repair — though §2.4 does **extend its population** (renamed members' stored names are
`Thm_Name.print` output that `serial_of` re-parses; see §2.4) — and restructuring it here would
be scope this change does not need.

**One invariant the type does not enforce**, so assert it where the value is built: a member index
is 1-based (`j + 1` at `:1110`). `Member (c, 0)` would render as `"c(0)"` — a fact selection that
can never resolve, since Isabelle's selection is 1-based — a value false in the datatype's own
terms (the `int` is defined as a 1-based sweep index). The assert guards that meaning; do **not**
"fix" the rendering to drop a 0 index instead (that is `Thm_Name.print`'s convention, and it would
produce the bare collection name §2.3 rules out showing). Nothing in `int` says any of this; a
guard at the construction site does.

**The field.** `from_collection`; ML `string option`; msgpack a string or nil; absent on
records written before the field existed. It holds the **full name** of the dynamic
collection the stored name was invented from. Its docstring on `Record` must state — as the
`position` field's already does for its own ambiguity (`semantics.py:274-275`) — that a decoded
`None` carries three readings: "not invented from a collection", "written before the field
existed", and "`migrate_from_collection.py` has not reached this record"; the three collapse to
the first only after that pass has completed and been verified (§3).

**The invariant.**

> `from_collection = SOME c` **if and only if** this enumeration adopted no static name for
> the member and therefore invented its name from collection `c`.

It states what the enumeration *did*, not what exists in the world: where §2.4 finds a name
but a guard rejects it, a static name exists and the field is still set. Only the
enumeration knows this for certain at the moment it decides, which is why ML supplies it and
nothing re-derives it later. It follows that the 4,524 records of §5 — which carry real
names — have `NONE`, and that a member §2.4 renames has `NONE` too.

**Consequence to accept.** The field records the provenance of the *name*, not the origin of
the *entity*. A member that has a real name is indistinguishable in the data from a static
fact, so the store cannot answer "which entities came from collection `c`". No field answers
that today and none is added.

**Where it travels.** Out of `build_entries` as a ninth component; onto the `interpret_file`
wire (`packTuple10` → `packTuple11`, `Tools/semantic_store.ML:378-383`, and the explicit
ten-component `entries:` type at `:402-412`); into `Entry`
(`Isabelle_Semantic_Embedding/semantic_interpretation.py:222`, built at `:1247`); into the
`Record` where the entry becomes one (`:373`); into the codec as field 14 (`semantics.py`
`_decode`/`_encode`); and on into the search site's export — see §2.3. **The wire slot is the
ninth of eleven, not the tail**: `build_entries` emits
`(kind, name, prop, position, uk, hint, prov, consts, from_collection)` and the widening maps at
`:1609-1611` / `attach` at `:1627-1633` append `digest` and `deps` **after** it — Python's
positional destructure in `_entries_of_wire` must match that order, not assume tail-append.

**It is normalised on the way in — like `name` where present, guarded like `position` when nil.**
`_entries_of_wire` runs every text field through `pretty_unicode` — `name=pretty_unicode(name)`,
`prop_str=pretty_unicode(prop)` (`semantic_interpretation.py:1249-1250`),
`prompt_extra=pretty_unicode(hint)` (`:1256`), with the one exemption spelled out at
`:1251-1253` — but unlike `name`, this field is nil on every non-member entry (the overwhelming
majority), and `pretty_unicode(None)` raises. Follow the `position` field's pattern at `:1254`:
`from_collection=(pretty_unicode(fc) if fc is not None else None)`. Where present it must go
through, or ML-written and pass-written records will hold two spellings of one collection:
the pass derives its value by slicing the **stored** name, which is already the unicode form.
Collections with symbols in their names do occur — `disjoint_\<G>_\<S>`, `\<V>\<^sub>B_simps`,
`\<T>_def`.

**Existing records get it once**, by a one-off pass. Call it `migrate_from_collection.py` and use
that name in every ordering sentence below, because "the backfill" would otherwise name two
different passes in adjacent paragraphs.

**The criterion, written once.** A record is selected when all four hold: its kind is neither
EXPERIENCE (`0x08`) nor METHOD (`0x07`); **its position is `None`**; its name matches
`^(.*)\((\d+)\)$`; and the base names a `THEOREM_COLLECTION` record. The field is set to that
base. Restricted to that population it is exact in both directions on the current corpus. It is
**not** exact over the whole store, which is why the kind exclusions are part of it: of the
16,368 positionless records, 6,768 are EXPERIENCE and 2 are the methods `Named_Simpsets.simp` and
`Named_Simpsets.simp_all`, which are legitimately positionless.

The position conjunct excludes the 4,524 records of §5, which got a name and a position in the
same write (`rename_dynamic_members.py:239-243`). **It does not, on its own, exclude a record
§2.4 renamed**, and the plan must not claim it does: the position sweep writes a position
*without* a name — `rec._replace(position=position)` (`semantics.py:813`), driven from a wire that
carries only `(uk, epos)` (`Tools/semantic_store.ML:1927`) — so once §2.4 ships, a member whose
name hint resolves can acquire a real position while its **stored** name is still `coll(i)`. The
conjunct would then skip exactly the record that most needs the field.

So the ordering is a real constraint, not one the conjunct removes: **no position sweep may run
from §2.4's release until `migrate_from_collection.py` has completed and its post-commit
verification has passed.** The window does not close when the pass *starts*: re-running is the
pass's resume mechanism (§3), so after an interrupted run the constraint is still live — a
position sweep in the gap would give a first-run-flagged record a real position, the resume's
position conjunct would then fail on it, and the resume — which writes nil on every non-match —
would **clear a correctly-set `SOME`**, silently, in the exact direction this plan exists to fix
(neither gate count catches it: the poisoned record fails the position conjunct in both). The
pass should also refuse to overwrite an existing `SOME` in field 14 with nil — abort loudly with
the offending keys — turning a violation of this window into a visible failure. Do **not** "fix"
any of this by widening `:1927` to carry the name: the position sweep is one-off code that has
already served its purpose, and rebuilding it to be structurally safe against a situation that
will not arise is work spent on the wrong thing. The constraint stays a runbook sentence — now a
checked one (see the gate's window-violation count in §3).

**The gate reuses this predicate; it does not restate it.** §3 requires a pre-write count that
must be zero, and it must share the conditions with the classifier, not carry a second copy. A
second copy has already drifted once in this document's own history, and the drift was live: an
experience record named `attempt(3)` satisfies a copy that forgot the kind exclusions, and would
abort a pass that should have run. "Share with one conjunct inverted" is not literally callable
on a four-conjunct boolean, so the factoring is fixed here: **the shared function evaluates the
two conjuncts every caller agrees on — the kind exclusions and the name regex — and returns the
parsed base name, or `None`**; the position test and collection-set membership are the
*callers'* tests, because those are exactly the two conjuncts whose polarity differs between
callers, and a polarity is each caller's meaning, stated at its call site: the classifier takes
position-absent and base-in-set; the gate's orphan count takes position-absent and
base-**not**-in-set; the gate's window-violation count takes position-**present** and
base-in-set (§3).

The criterion depends on the corpus, which is why it is used once over records that already
exist and never as a test at read time.

### 2.3 Render the invented form where results are shown to a person

A reader is shown `tendsto_intros(_)`. It is built from the field — `from_collection ^ "(_)"`
— not by editing the stored name, so no string parsing is involved and the record's own name
is never rewritten. `(_)` is chosen because an Isabelle fact selection takes a number
(`Pure/Isar/parse.ML:471-473`), so a citation of `coll(_)` fails loudly rather than resolving
to the wrong theorem, which a bare `coll` would do.

**The field reaches the display surface, and SEMANTIC_SEARCH_SITE_PLAN.md now carries it.** The
search site has no origin server: the browser talks to a Cloudflare Worker which reads turbopuffer
attributes, so the field has to be an attribute. It is — `from_collection  string` sits in that
plan's §6.1 **display** block, and its §8.1 export gained step 4a to copy it off the record. Two
constraints ride with it: it must be in the **first** export, because §8.2 makes every export a
fresh namespace and adding it later re-exports the whole corpus; and the schema is implemented
twice, in the Python export and in the JavaScript Worker, so it is a cross-repo change.

**Two consequences the rendering creates, both decided here** so the display layer inherits
answers rather than questions:

- **A pasted `coll(_)` must be normalised in the query, not routed to another field.** The Entity
  Name panel matches an adjacent subtoken sequence over `name_subtokens` (:74-77, :1424), and a
  pasted `coll(_)` tokenizes without the digits, so it matches nothing where today's `coll(123)`
  matches. **Strip one trailing `(_)` from an Entity Name condition before tokenizing**, as a named
  step in §5's tokenizer pipeline so both implementations share it and it gets a row in §5.5's
  shared test-vector file. The alternative — filtering member rows through `from_collection` — has
  no compilation: §6.3 compiles a name condition to exactly one form over `name_subtokens`
  (:1054, :1459),
  and the Worker emits one filter for the whole namespace, so it cannot branch per row. Making
  `from_collection` filterable instead would mean a fourth `pre_tokenized_array` in the first
  export and a rewrite of D22's `All` panel.
- **Rows that render identically are accepted and documented, not collapsed.** The response
  collapses on the `(name, expr)` pair, from values the export wrote off the stored name (:108,
  :150-152, :177-178). A scan found 168 groups holding 201 extra records sharing a
  `(kind, base, expr)` and will render as rows identical in both name and statement — but that scan
  was run on a development snapshot and grouped by the wrong key: the collapse key is `(name, expr)`
  and excludes kind (SEMANTIC_SEARCH_SITE_PLAN.md:108, :177-178). Re-measure on `cslh19`, grouped
  by `(base, expr)`, before quoting the number anywhere. The decision does not turn on it: a few
  hundred rows in 1.34M, the collapse happens in the Worker after ranking, and it is therefore reversible
  without re-exporting. If it is ever wanted, the second hash belongs at **export** time, over the
  rendered pair, computed where both halves are already in hand — never reconstructed in the
  Worker from a rendered string.

**Exactly one place: where a result is rendered for display.** Not in the data the search
site is built from, because there the name is not display-only — it feeds the identity hash
that collapses results onto one entity page and the subtoken array behind the name filter, so
rewriting it there would merge distinct records and change what the filter matches.

**And nowhere else.** Each exclusion below would break something specific:

- The text `document_text_of` produces for embedding — stale, undetectable vectors, as in
  §2.1. This is narrower than "anything `pretty_print` reaches": the `query` tool's
  display-only reuse of `pretty_print` is §2.1's third site and is fixed there.
- Isa-Mini/AoA's retrieval and citation path — there the displayed name is a handle, not a
  label: it is passed back to ML to resolve (`model.py:2347`), becomes `FactByName` "as the
  model writes it" (`:2443-2447`), and is re-resolved (`retrieval.py:574`). A member form
  there is unresolvable, whereas the live `coll(i)` §2.1 substitutes does resolve.
- The by-name lookup path (`model.py:2198-2201`), for the same reason.
- Any online read path in `Semantic_DB`, whose records are handed on for ML resolution.

### 2.4 Use the name the theorem already carries, where it has one

A member's theorem often carries a tag naming the fact it was declared as, and that name has
a real position; where it resolves, the member gets that name and that position, and no index
is appended. Where it does not, the name stays `coll(i)` and §2.2's field is set. It recovers
nothing for the 9,598 records already in the store — measured, and not a reason against it,
because its purpose is that future sweeps stop producing them.

**The change site is `process_dynamic_facts_into_cache`, at the point the member is stamped**
(`Tools/semantic_store.ML:1107-1110`): emit `Context_Callbacks.Fixed nm` where the name is
adopted, `Context_Callbacks.Member_of_Dynamic coll` where it is not. That type is unchanged by
this plan; the sweep's index stays where it already is, in the `int` component
`process_dynamic_facts_into_cache` returns beside each entry (`:1027`), and `member_entries`
combines the two into §2.2's `Member (coll, i)`. It must be there and not
in `member_entries`, because that one function feeds both the stored sweep (via
`member_entries`, `:1400`) and the AoA live-query path (via `make_entity_callbacks`,
`:1200-1207`, called as `make_entity_callbacks (Context.Proof ctxt) au` from
`Isa-Mini/Agent/agent_server.ML:1707`). Stamping there is what makes the stored name and the
live name the same value rather than two values that have to agree: `member_entries` maps
`Fixed nm` to `entity_name`'s `Declared (Thm_Name.print nm)` (§2.2's boundary mapping), and
`Context_Callbacks.resolve_name` returns `Thm_Name.print nm` for the same `Fixed` entry
(`contrib/Isabelle_RPC/Tools/context.ML:198`). Note what this adds: renamed members join the
population whose stored names `serial_of` re-parses with `Thm_Name.parse` — the print/parse
round trip is exact (`Pure/thm_name.ML`), but §2.4 is a new *producer* of parse-needing strings,
not a removal of one; say so here rather than let an audit of "who parses names" find an
undocumented sixth source.

**What it must do.** The whole step is one lookup, one selection and two rejections; the plan
below says which existing code each part is, because every one of them exists already.

- **Ask whether there is a hint at all with `Thm.has_name_hint`** (`Pure/more_thm.ML:656`), or
  `case try Thm.the_name_hint thm of NONE => …`, as `theory_structure.ML:252` already does. Do
  not string-compare against the `??.unknown` sentinel `get_name_hint` substitutes: §6 measures
  that branch as 97 % of all rejections, so it is the dominant path and it should not be spelled
  as a magic string.

- **Do the name-space lookup through one shared function, parameterised by the fact space.**
  The sequence "intern, fetch the entry, take its position" is written out at
  `Tools/semantic_store.ML:939-947` and twice more at `contrib/Isabelle_RPC/Tools/context.ML:1319-1326`
  and `:1549-1557`. Extract it once, beside `entry_def_pos`, which `Context_Callbacks` already
  exports for exactly this purpose (`context.ML:76-80`), and replace all three copies. The
  signature must spell the record out, because **`Name_Space.entry` is not an exported type**: the
  `NAME_SPACE` signature declares `the_entry`'s result inline
  (`Pure/General/name_space.ML:17-23`) and `type entry` exists only inside the structure body
  (`:109`), which the ascription at `:101` hides. `entry_def_pos` already carries the identical
  inline record one line away — so the record is about to be hand-copied twice in one signature,
  kept in step with Pure by hand. Declare it once instead:
  `type name_space_entry = {pos: Position.T, serial: serial, group: serial, suppress: bool list,
  theory_long_name: string, concealed: bool}` in `CONTEXT_CALLBACKS`, used by both
  `entry_def_pos` and the new
  `val entry_of_fact : Facts.T -> string -> name_space_entry option`. Extract the **lookup**, not "the guards":
  two of the three guards named in earlier drafts are already inside the `is_infra_thm` that runs
  three lines later (`infra_filter.ML:432-446`, whose first clauses are `Name_Space.is_concealed`
  and a `Long_Name.is_hidden (Name_Space.intern …)`), so a shared "guards" predicate would bake in
  a duplication *and* be strictly weaker than `is_infra_thm`, which also rejects a name whose
  extern form starts `??.`. Note that only **two** of the three guards earlier drafts named live at
  `:938-955`; there is no `??.unknown` test there, and there does not need to be — the previous
  bullet handles the absent hint at its source.

- **The fact space passed in is the global one** (`Global_Theory.facts_of thy`). This is not a
  fifth guard, it is which name space the lookup happens in: `local.h1` is simply not in the global
  space, so the lookup returns NONE with no test written anywhere. The fact space must therefore be
  a *parameter* of the extracted lookup, not a value it computes: the static path keeps passing the
  context's space — `Facts.space_of all_facts` with `all_facts = Context.cases Global_Theory.facts_of
  Proof_Context.facts_of context` (`:935-936`) — while the member path passes the global one. That
  difference is the whole guard, and it is why the member path's lookup is an independent call
  rather than a reuse of whatever the static path happened to resolve. §6 measured that the three
  guards of earlier drafts all pass on proof-local labels while the position check actively
  certifies them, so a guard-shaped answer here would have had to be discovered; a parameter-shaped
  one cannot go wrong.

- **Select the theorem the index names, using Pure's own convention.**
  `AList.lookup (op =) (Thm_Name.make_list (name, thms)) nm` validates the index and returns the
  selected theorem in one expression (`Pure/thm_name.ML`), instead of hand-writing "`i = 0` with a
  singleton list, or `1 ≤ i ≤ length thms`" for the sixth time in this tree. Use `Facts.lookup`,
  never `Facts.retrieve`: `retrieve` errors on an unknown fact and emits a position report
  (`Pure/facts.ML:199-211`), and a raise out of a per-theory future is fatal (`:1753-1757`).
  Reject `#dynamic = true`. Treat every miss as "keep the invented name", never as an error or a
  drop.

- **Verify the selected theorem's proposition equals the member's with structural equality on
  `Thm.prop_of`**, not `aconv`. The universal key's payload folds the `Abs` binder name into its
  digest (`Term_Digest.ML:110-112, 226-231`), so `=` is the equality the key respects; comparing
  the universal keys directly is equivalent and is what every dedup on this path uses. Measured:
  over 2,190 real pairs the two never disagreed (§6), so this costs nothing and closes the case
  where they would.

- **Re-apply the infrastructure filter under the adopted name — and hand it the BASE fact name,
  `#1 nm`, never the `Thm_Name.print` rendering.** The name-dependent clauses of `is_infra_thm`
  expect a name-space key: `"F(2)"` is not one, so `Name_Space.intern` falls back to
  `Long_Name.hidden` and `Facts.extern` to a `"??."` prefix — the printed form would trip the
  `is_hidden` and `??.`-extern clauses for **every** member adopted from a multi-theorem fact,
  silently (a hit here keeps `coll(i)`, it does not error), gutting §2.4 for exactly that
  population. The static path already passes the bare name (`:951`) and the codebase already
  warns about this trap (`:1453`, "bare name: name(i) would trip is_hidden"). The member path
  tests the filter with the collection's name (`:1114-1120`) while the static path tests the
  fact's own (`:951-955`), and `is_infra_thm` is name-dependent in six clauses
  (`infra_filter.ML:432-446`); without this re-check a member can be stored under a name the
  store excludes everywhere else. This is also where concealed, hidden and `??.` are enforced,
  which is why they need no bullet of their own. **The filter is not in scope where the name is stamped, so it must be passed in.**
  `fun entry (entity, uk) = …` at `:1107-1110` is called twice — for the Theorem face under
  `is_infra_thm (coll, thm')` at `:1114-1115`, and for the rule face at `:1116-1124`, where the
  applicable filter is bound only by the pattern `SOME (con, key_of, infra, needs_shape)` at
  `:1118`, so `infra` does not exist at `:1107`. Compute the candidate `(nm, pos, selected_thm)`
  once per member above `:1111` and give `entry` the filter as a parameter —
  `fun entry infra (entity, uk) = …` — passing `is_infra_thm` at `:1115` and the pattern-bound
  `infra` at `:1118`. `rule_kind_of` (`:1063-1078`) supplies `is_infra_induct_thm` for the induct
  and case-split faces, which is strictly stronger (`infra_filter.ML:452-454`), so **the two faces
  of one member can legitimately end up with different `entry_name`s** — one adopting the real
  name, the other keeping `coll(i)`. Say so where the code is written, because that asymmetry reads
  as a bug. **A hit falls back to the invented name; it is not a drop.** On the static path an
  `is_infra_thm` hit at `:951` means the entry is discarded, and an implementer extracting that
  sequence will carry the discard across by reflex — but here the member is a record the store
  already has, so a hit means "this real name is not usable, keep `coll(i)` and set the field", not
  "delete the member". Re-apply the same per-kind filter the member path already selects at
  `:1118`: `is_infra_thm` for the Theorem face, `is_infra_induct_thm` for the induct and case-split
  faces.

- **Carry the position in a new component, and say so.** `process_dynamic_facts_into_cache`
  returns `(cached_thm_entry * int * entity)` (`:1027`); the `int` is the sweep index and stays,
  so the position needs a component of its own — make it
  `(cached_thm_entry * int * Position.T * entity)`. Both consumers, `member_entries` (`:1400`) and
  `make_entity_callbacks` (`:1200-1207`), are compiler-caught. The value to put there is already in
  hand: `entry_of_fact` returned the name-space entry, whose `#pos` is a `Position.T`. Do **not**
  route it through `cached_thm_entry.pos` and do **not** convert anything — three position
  representations are in play and two of them are not interchangeable:
  `Context_Callbacks.def_pos` is (standardised absolute path, line, **symbol offset**)
  (`context.ML:41-46`), `Entity_Position.entity_position` is (portable symbolic path, line,
  **byte column**) (`entity_position.ML:9-11`), and `build_entries` wants neither — it takes a
  `Position.T` and hands it to `Entity_Position.of_positions` (`:842`), which calls
  `PIDE_State.absolutize_id_based_pos` and then reads the position's own accessors, which a
  position rebuilt from a flattened triple can no longer answer. In `member_entries`, derive the
  position it passes at `:1410` **by constructor**, not by trusting the stamp site:
  `Fixed _` → the carried `Position.T` component, `Member_of_Dynamic _` → `Position.none` — one
  `case` at the one consumer that writes records, so a future edit of the stamp site cannot
  silently attach a declaration site to an invented name (§1 declares that absence correct).

- **Stamp the cached entry's own position too, for the adopted-name case.** The `pos = ("", 0, 0)`
  hardcode is at `:1109` (`:1108` is the name stamp), and `("", 0, 0)` is documented as
  "position unknown" (`context.ML:217-219`) — which stops being true the moment the adopted
  name's name-space entry, `#pos` and all, is in hand three lines up. The live query path
  **does** serve this value: the cached pass returns `#pos entry` with every hit
  (`context.ML:1296-1299`) and Python answers definition fetches from it. So in the `Fixed`
  branch set `pos = Context_Callbacks.entry_def_pos e` — exactly what `process_facts_into_cache`
  stamps for every other `Fixed` entry (`:946-966`), making the population uniform (`Fixed` ⇒
  real `def_pos` whenever one is known) — and keep `("", 0, 0)` for `Member_of_Dynamic`, which
  remains honestly position-less. This is not "the same fact in two places": the cached `def_pos`
  and the tuple's `Position.T` are two projections of the one entry, written together at one
  site, and every static entry already carries both. The observable live change is strictly
  "definition unavailable" → "correct definition" for renamed members.

- **Make `member_entries` disjoint from the static entries by construction, not by list order.**
  Once a member carries a static fact's name, `serial_of` gives it that fact's serial and
  `entry_ord`'s three keys — serial, kind rank, name — all tie with the static rule entry's
  (`:574-583`, `:546-553`); the sort is stable and the dedup keeps the first, so the member would
  displace the positioned static entry. `member_entries` already owns the mechanism for this: it
  builds a `seen` table and drops any member whose universal key is already in it (`:1396-1398`).
  Seed that table from `deduped_thm_entries @ intro_entries @ elim_entries @ induct_entries @
  case_split_entries` instead of from `deduped_thm_entries` alone.

  **The `val member_entries` binding must move for that to compile.** `val` bindings in an SML
  `let` are sequential, and today `member_entries` binds at `:1394` while the four rule lists bind
  at `:1451`, `:1458`, `:1466` and `:1473` — the seed would name four identifiers that do not yet
  exist. Move the **definition** to just after `case_split_entries` (`:1477`); it depends only on
  `context`, the infra filters and `deduped_thm_entries`, all bound well before. Its **position in
  the concatenation** at `:1531-1536` does not move, and no longer matters — which is the point:
  seeding is a guarantee by construction, where relying on concatenation order would leave a
  positional dependency the next person to touch that list can silently break. Update the comment at `:1497-1504`, which currently reasons that the static
  fact's serial sorts first.

- **Let the renamed member take part in locale-instance detection.** The bypass at `:686-700`
  discards any detection for an entry whose carried name is a dynamic fact, and its comment says
  members are given the bare collection name precisely so that it fires for them. The reason is
  that detection's anti-misattribution gate is the name — an entry is attributed only when its
  fully qualified name ends with the qualifier-prefixed binding name — and a member's carried
  name is the collection's, which can never confirm, leaving only digest-only hits. Once the
  member carries its own qualified name that reason is gone: the gate works, and the entry is
  exactly the static fact it names. So the bypass correctly stops firing, no code changes, and
  the comment at `:692-697` must be rewritten — its "members … never carry provenance" becomes
  false. The collection entity itself keeps its bin name and stays bypassed.

**Three live-path consequences to settle before this ships.** They are behaviour changes, not
code:

- **Cross-theory accessibility.** Today a `Member_of_Dynamic` entry is re-resolved when a
  query moves to another theory and dropped if absent (`context.ML:199-214`, drop at
  `:1291-1295`). A `Fixed` name is emitted on the prep context's word. If the target theory
  does not import the name's theory, the model receives a name it cannot resolve.
- **Locale attribution across the rest of the batch.** The digest-only suppression is **per
  entry**, not per registration: `resolve` partitions one entry's provenances by `name_matches`
  against that same entry's own name and returns `[]` only when that entry has no confirmation
  (`locale_instance.ML:186-196`, signature comment at `:54-58`). So it does not propagate. The real
  cross-entry coupling is elsewhere: `base_set`, `middles` and `candidate_locales` are computed
  from the **whole batch's** names (`:93-95`, `:101-107`, `:118-120`), so changing one entry's name
  changes which locales are even considered for the others. That runs **both** ways — attributions
  can be lost as well as gained. Run one theory's detection before and after and diff the whole
  batch's attributions in both directions.

- **The label-uniqueness assert's fourth argument.** Its comment (`:1565-1568`) lists, among
  the four implicit arguments it replaces, "the Static/Dynamic fact partition (facts.ML)
  keeping a member's `coll(i)` name disjoint from a static `name(idx)` of the same kind". A
  renamed member ends that disjointness. No concrete colliding pair could be constructed —
  equal names imply the same selected theorem implies equal universal keys, which the dedup
  collapses first — but the assert aborts the entire `interpret'` run when it fires, so the
  argument has to be re-established rather than assumed.

**Two live-path changes that are improvements, recorded so nobody mistakes them for
regressions.** The live name filter tests `bare_name` (`context.ML:1287`) while the live pass
at `:1259` already filters on the fact's own name, so today the two disagree and this aligns
them; and the staleness drop no longer fires for a renamed member, which is correct because a
global fact name resolves regardless. A third, `is_local` being hardcoded `false`
(`:1297-1298`), only lied for proof-local names and is closed by the global-fact-space guard.

**Amend ENTITY_POSITION_PLAN.md §10 rule 1** (`:785-787`), which states flatly that a dynamic
collection member has no declaration site of its own. It becomes: none unless its name hint
resolves. A hinted name and position may belong to an ancestor theory; that is permitted by
§10 rule 3 (`:793-795`) and no current-theory restriction is applied.

## 3. Constraints an implementer must respect

**The store is the production store on `cslh19`**, as it stands after the 2026-08-18 repair (§5).
Every count a decision here rests on — §1's 9,598 of 1,343,793, §2.2's exactness claim, §5's
coverage census — is from that store, and is to be re-confirmed there before the pass runs. Nothing
is to be validated against a development snapshot: one that never had the entity-position sweep
applied has almost no positions at all, which silently inverts both §2.2's criterion and the gate
below.

That is also the pass's one **precondition**: run it only where `migrate_entity_positions._scan`
reports `reachable_short == 0`, read before the pass erases that signal. §2.2's criterion tests
`position is None`, so on a store whose position sweep never completed it would select most of the
corpus.

**The codec drops a 14th field unless both halves are changed.** `_decode` pads to 13 and
slices `vals[:13]` (`semantics.py:365-367`); `_encode` emits 13 (`:410-428`). Both need the
new count, or every decode-modify-encode round trip silently loses the field.

**Export the ritual, not just the numbers.** The codec destructures positionally with bare
literals (`semantics.py:365-367`, `:410-428`) and every migration pass redeclares its own
constants against them — `F_NAME, F_POS = 1, 12` in `rename_dynamic_members.py:72`, and again in
its siblings. Exporting the indices alone relocates the duplicated fact instead of removing it:
the next writer imports `F_NAME` and still hand-rolls the pad. Export what the passes actually
share — `unpack_fields(raw) -> list` (padding to the current field count) and
`pack_fields(vals) -> bytes`, next to `_decode`, plus the named indices. **The converted users
are: `rename_dynamic_members.py`'s write path (`:235-244`) and `migrate_from_collection.py`'s
own write path — no others.** Explicitly exempt, and never convert: every arity-deciding reader —
`migrate_entity_positions._scan` (`:107-110`) and this pass's own reached/not-reached audit —
which must keep reading `len(msgpack.unpackb(raw))` raw, because `unpack_fields`' padding
destroys exactly the tuple-length signal they exist to read. Do **not** reshape the wire
format itself: positional tail-append is right here, and a msgpack map would rewrite 1.34M
records.

**"Absent" is a statement about the msgpack tuple's length, not about the decoded value.**
`_decode` pads missing trailing fields with `None`, so a record written before the field existed
and a record the pass wrote `nil` onto both decode to `from_collection = None`. After the pass,
"this record was not reached" means **the stored tuple has fewer than 14 components** — not
"exactly 13". The store holds records of several arities: measured on the local snapshot, 1,109,130
have 12, 128,507 have 8, 114,982 have 6, 8,844 have 13 and 880 have 7, because `_decode` pads on
read while nothing pads on disk. Code must never read a decoded `None` as "not reached".

**The sentinel is defeasible, so `write_answer`'s threading must ship first.** `_encode` writes
every field the record has, so any ordinary decode-modify-encode promotes a record to the new
arity carrying a `nil` ML never supplied — `backfill_positions` (`:813`),
`_migrate_constituent_records` (`:1071`), `write_answer`, and the Phase-1 digest bump inside
`interpret_file` (`semantic_interpretation.py:931`) all do this. The last one cannot reach a member
record — theorem-alike entries carry no `semantic_digest`, so its guard skips them — so it affects
only the arity-based audit, not the field. Threading the field
through `write_answer` (below) before the pass runs is what keeps re-interpretation from
manufacturing false "reached" records.

**A re-interpretation clears it.** `write_answer` (`semantic_interpretation.py:372-379`)
builds a fresh `SemanticRecord`, so re-interpreting a member would drop the field while its
name is still an invented form. The field must be threaded there. The same path also rewrites
the record's *name* from the enumeration's current answer, which means re-interpreting one of
the 4,524 records of §5 reverts it to `coll(i)` unless §2.4 recovers its name.

**Archive the position-completeness scan before `migrate_from_collection.py` runs.**
`migrate_entity_positions._scan` decides "this record was reached by the position sweep" from
the record's msgpack arity — `if n >= 13`, with the in-code comment saying so
(`migrate_entity_positions.py:100-121`), pinned by `test_entity_position_backfill.py:167-183`.
A pass that pads every record to 14 makes `reachable_short` permanently 0, and nothing
else records which keys that sweep reached. Run the scan, archive its output, and note in the
plan file that the check is thereafter vacuous and needs an explicit marker.

**`migrate_from_collection.py` writes on every record it walks** — the collection name on a
match, `nil` otherwise — so that afterwards a tuple of fewer than 14 components means only "this
record was not reached". **"Every record" means every entity record, and the walk must say so in
code**: `semantics.lmdb` also holds theory-status records (msgpack **maps** under 16-byte keys)
and the 1-byte counter key, and `iter_items` yields them all. Every sibling whole-store walker
guards on key length (`migrate_entity_positions.py:105`: `if len(k) <= 16: continue`;
`snapshot_sync.py:802`); without that guard, the unpack-pad-put ritual applied to a status map
destroys its values silently (`list(dict)` keeps only the keys) and the post-commit field check
cannot notice. Carry the same guard — or walk `iter_entity_records` (`semantics.py:578-599`)
with its decode guard made *counting* instead of silent — and have the pass report five numbers:
walked / matched / nil-written / EXPERIENCE-skipped / undecodable, treating undecodable > 0 as a
loud warning in the report and in the post-commit verification.
Three constraints follow from walking the whole store, and none is optional.

**Batch the writes by generalising the method that already does this, not by copying it.**
`backfill_positions` (`semantics.py:774-815`) is the raw-put writer, and the written-down grant
for bypassing vector invalidation lives in its docstring — but it runs its entire entry list in
one `begin(write=True)`, because it was only ever driven per theory
(`migrate_entity_positions.py:16-17`). A single transaction rewriting ~1.34M records overruns
LMDB's dirty-page list and rolls the whole thing back after however long it ran, and it holds the
store's only write lock throughout. Rather than open-coding a fourth copy of "accumulate keys,
write in bounded batches, raw put", widen it: `backfill_field(field, entries, batch=_WRITE_BATCH)`
doing `rec._replace(**{field: value})` with a commit every `batch`, leaving `backfill_positions`
as a one-line wrapper for the ML wire. Put `_WRITE_BATCH` beside `SEMANTICS_MAP_SIZE`
(`semantics.py:146`). Leave `snapshot_sync`'s `_EXPORT_BATCH` (`:689`) alone: both constants
count **keys**, but the dirty-page cost per key differs by more than an order of magnitude
between the two loops, so folding them into one number couples two tunables — if they are ever
shared, a comment must say the unit is keys and name that asymmetry. The pass still collects
target keys in a read pass and closes the read transaction first — an open `iter_items` snapshot
pins old pages against reuse (`semantics.py:548-555`) — and checks map headroom before the first
write. **That check does not exist anywhere yet and is defined here** (no pass has ever done it;
"keep the headroom check" with no referent would make two implementers invent two): read
`env.info()` and assert `map_size == SEMANTICS_MAP_SIZE` and
`map_size - (last_pgno + 1) * psize >= ` the store's current live data size — the pass rewrites
every record once, so worst-case growth is on the order of one full copy of the data plus B-tree
churn — aborting with both numbers in the message.

**Refuse to run against an installed system-layer database.** `iter_items` yields the merged
view, and the read-modify-write pair materialises every system-resident record into the user
layer — the whole walked corpus, not 9,598 records. (`_raw_for_update`, `semantics.py:694-703`,
only reads; the copy-up is the caller's `txn.put`.) Detect with `validated_system_db()`
(`semantics.py:313-315`) and abort unconditionally, with no override flag.

**Do not write through `Semantic_DB.__setitem__`** (`semantics.py:601-621`), which invalidates
vectors unconditionally and would force a re-embed of the whole store for a field that is not
part of the embedded document. Use the raw put. Since `backfill_positions` becomes a wrapper, the
written-down grant moves with the code: put it on **`backfill_field`**, restated as a per-field
condition, and have that function **enforce** rather than document it — assert the field is not one
the embedded document is built from (`kind`, `name`, `expr`, `interpretation`, `goal_patterns`), or
take an explicit allow-list. A grant that is a docstring on a function nobody calls any more is not
a grant.

**Skip EXPERIENCE records** (kind byte `0x08`): their names are agent-chosen strings and may take
any shape. A skipped record is not walked, so it keeps whatever arity it had — 8 components in the
current corpus — which is still fewer than 14.

**Gate the pass before it writes, using §2.2's shared function — two counts, and the post-commit
verification after.** The factoring is §2.2's: the shared function evaluates the kind exclusions
and the name regex and returns the parsed base or `None`; the position test and collection-set
membership are the caller's, each polarity stated at its call site. Do not restate the shared
conditions — that is how an earlier draft of this document lost the kind exclusions and would
have aborted on an experience record named `attempt(3)`.

1. **Orphan count (pre-write, must be zero to proceed):** shared function returns a base +
   position **absent** + base names no `THEOREM_COLLECTION` record. It is the only thing that
   would catch the one structural false negative: a collection record is produced only in its
   declaring theory's sweep (`theory_structure.ML:107-128`) while members are produced wherever
   the collection is visible, so a member whose collection was never interpreted would be
   silently left unflagged forever.
2. **Window-violation count (pre-write, must be zero):** shared function returns a base +
   position **present** + base **in** the collection set. Non-zero means a position sweep ran
   inside §2.2's forbidden window (a §2.4-renamed member acquired a position while its stored
   name is still `coll(i)`); abort with the offending keys. This is what makes the runbook
   sentence a checked one — the failure it catches is otherwise per-record and silent forever,
   visible to neither the classifier nor the orphan count.
3. The post-commit verification of §3's closing paragraph, in a fresh read transaction.

Read the collection-name set through the same layered view the records come from, and complete
it before classifying anything — the two key families are unordered relative to each other, so
the pass is two-phase.

**Back up, quiesce the store, and verify after commit — through one shared function.** Four
one-off passes in this tree copy the same timestamped `env.copy(..., compact=True)` idiom —
`migrate_record_provenance.py:31`, `migrate_entity_positions.py:81`, `migrate_xor_thm_keys.py:35`,
`migrate_incremental_fields.py:53`, exactly those four — the tree calls it "the backup
convention", and the pass that most needed it did not have it. (`migrate_float32_to_q15.py` is
**not** a fifth: it deliberately demands a pre-existing external backup and refuses to run
without `--backup` — keep its contract, do not "convert" it.) Put the idiom in the package rather
than in any pass — `backup_store(path) -> str`, doing the timestamped compacting copy plus the
free-space check ENTITY_POSITION_PLAN.md:1155-1158 sizes by hand, the timestamp-suffix
formatting owned here for the first time (today the `.bak-%Y%m%d-%H%M%S` convention is spelled
inline five times — the four passes plus `semantic_embedding.py:1075` inside
`_rebuild_corrupt_store` — with no named owner; `backup_store` becomes it, and future spellings
point here) — and call it on
line one of `main`. **Its hard precondition goes in its docstring and here: it must run before
this process opens `semantics.lmdb` through the `Semantic_DB` singleton** — py-lmdb refuses to
open a path the process already holds (measured; the refusal does not depend on flags —
`migrate_entity_positions.py:72-76` documents the same constraint on the private precedent this
extracts). A caller that takes a pre-count first gets an `lmdb.Error`, and the fix is to reorder,
never to skip the backup. Refuse the larger temptation while you are there: these passes are
**not** one skeleton (two are directory renames, one drives Isabelle over RPC), so extract the
backup and nothing else. **Stop anything else reading or writing `semantics.lmdb` for the
duration — readers are not optional**: LMDB cannot recycle pages freed by the batched commits
while any older read transaction is registered, so a resident reader pins roughly one full copy
of the data under the 4 GiB `SEMANTICS_MAP_SIZE` ceiling, and a `lock=False` reader (the review
convention, `readonly=True, lock=False`) does not register at all and can observe pages being
reused under it. Before the first write batch, call `env.reader_check()` and assert
`env.readers()` is empty. Re-open in a **fresh** read transaction afterwards and verify the
edited records — the precedent read-back happens inside the still-uncommitted write transaction
(`rename_dynamic_members.py:245-247`), so it verifies the encoding, not the committed bytes. Re-running is the resume mechanism and is
idempotent, because the field is a function of the record's own name, its position and the
collection set — all three stable under re-running **while §2.2's no-position-sweep window
holds**; a sweep inside the window is exactly what changes the position input, which is why the
refuse-`SOME`→nil abort exists.

**Renaming a record must clear the field, and the one pass that renames cannot.**
`rename_dynamic_members.py` pads only to 13 elements and never touches index 13
(`:234-243`, `F_NAME, F_POS = 1, 12` at `:72`), so a second run — which §5 calls for — would
leave a real name flagged as an invented form, and §2.3 would then mask a legitimate name.
Either run it **before any record can carry the field at all** — that is, before §2.2's ML half is
released, not merely before the pass, because between the release and the pass new sweeps write
records that already carry it — or extend its pad to the new arity, set `nil` in the same put, and
extend the read-back assertion. Its vector drop must go through `invalidate_vectors` in either
case, not the open-coded `vt.delete` on the alphabetically first store (`:97-100`, `:249-253`;
`semantic_embedding.py:1130-1158`); that is wrong whenever more than one vector store exists,
independently of ordering.

**The wire change is lockstep.** The conda package ships the Isabelle and Python halves
together, but PyPI ships the Python half alone, so both channels must be released together.
Make the arity failure self-describing: on unpacking the entry tuple, raise a message naming
the expected and actual arity and saying the two halves are from different releases.

**`snapshot_sync.SCHEMA_VERSION` is not bumped.** It was not bumped for the 13th field
either; bumping it would make every installed client refuse the snapshot.

**One smell this change inherits rather than creates.** `build_entries`' output reaches **nine**
components, which is past what a tuple should carry. If the implementer wants to turn it into a
record, this is the moment — but it is a separate change and must not be smuggled in. (The other
candidate, a theorem name round-tripping through a string, is inherited **and extended**: §2.2's
`Declared of string` makes no claim about the string, so a name that already carries a selection
index sits in it honestly, `serial_of` goes on parsing such names as it does today, and §2.4
adds renamed members to the population it parses — see §2.4's stamping paragraph, which owns
that extension.)

`fact_base_name` (`:1169-1170`) is **not** on this list and must not be added: it matches
`Context_Callbacks.entry_name`, which this plan does not change, and its `Fixed` clause must keep
handing `is_declared_infra_thm` the bare `nm` rather than anything index-bearing.

**Sites coupled to `build_entries`' tuple arity**, which changes at both ends (four in, nine
out): `entry_ord`, which breaks ties with `string_ord` on the name component (`:574-583`) and is
applied to the pre-`build_entries` tuples at `:1537-1538` — give it `space_name`, which preserves
today's key exactly; the dedup filter at `:1542`; the label-uniqueness assert's destructuring
(`:1585`); the non-WIP widening map
(`:1609-1611`); `attach` in the WIP branch (`:1627-1633`); the widened ten-tuple at the
position backfill (`:1927`); and the wire type's **three** explicit spellings — the `entries:`
type in `make_interpret_file_cmd` (`:402-412`), the same inline type in the `SEMANTIC_STORE`
signature (`:61-65`), and `interpret_file_dry_run_cmd`'s annotation (`:425-433`) — plus
`build_entries`' own signature spec (`:174-179`). (`:1332` and `:1361`, which thread the name
from `raw_thm_entries_named` through `thm_entries_with_uks` and `best_thms`, sit **upstream** of
the `tag` wrap at `:1530` and do **not** change — they stay plain strings; they are named here
so nobody wraps them early and breaks their string operations.) All are compiler-caught
**except** `Test/Entity_Position_Test.thy:328`, `:329` and `:368`, in a
separate theory that nothing in this repo runs without an explicit `isabelle build`. `:328` is the
worst of the three because it **constructs** the input tuple —
`build_entries ctx [(entity, name, pos, uk, NONE)]` — so it needs `Declared name` (the §2.2
constructor; the entity there is a `Constant`, and wrapping it in any theorem-shaped value is
exactly what §2.2 forbids) as well as the
dropped fifth component. `:332`'s `entry_name = name` does **not** break: `build_entries`' output
name component stays a string.

**Tests that encode the arity**: on the Python side only `test_entity_position_codec.py`'s
`_wire_entry` (`:89-93`). `test_entity_position_backfill.py` does **not** break — its arities are
synthetic msgpack tuples and `_scan`'s `n >= 13` is not part of the codec — so do not "fix" it.
Plus the `.thy` lines above.
A new test should cover a collection with one member that has an invented name and one that
does not. §2.1 changes the **displayed** name at four sites; there is no golden-output suite
covering them, so its landing must include a before/after diff of the displayed names over a
fixed query set, with every changed line justified against §2.1's table.

## 4. Settled, and what is still to decide

**Settled: the field is stored, and ML supplies it.** Not derived at read time. The consumer
is the semantic-search front end, which serves live queries against a corpus that keeps
growing; applying a corpus-dependent test there would mean re-earning its correctness on every
future snapshot, and its failure mode is silent — a static bundle's stable `foo(3)` rendered
as an invented form. The enumeration knows the answer for certain at the moment it invents the
name, so that is where it is recorded. The costs in §3 are accepted.

**Settled: `migrate_from_collection.py` walks and writes every record.** The alternative — writing only on a
match — was considered and rejected: the invariant that a short tuple means "not
reached" is worth the whole-store pass, and the compatibility question is handled by the
tuple's length.

**Settled: §2.4 stays in this plan**, with every bullet in it treated as a prerequisite rather
than an improvement. Its measured cost is negligible (§6) and its code volume is small; three
of its bullets — the global-fact-space guard, carrying the position, and placing
`member_entries` after the rule lists — close defects that are measured, not hypothetical.

**Settled: §2.1 lands after §2.2.** It reads the field, so it ships once ML writes it, the two
release channels have gone out together, and `migrate_from_collection.py` has run. Shipping it earlier without
the condition was rejected: it would put an unconditional live-name override — correct on the
enumeration-fed rows of §2.1's table, where the live name always resolves — onto the three
conditional rows too, re-displaying the 4,524 repaired records as `coll(i)` at every by-name
site. A stopgap keyed on "the stored record has
no position" — which separates the two populations exactly on the current corpus — was also
considered and rejected, because it is a temporary mechanism that has to be remembered and
removed. If §2.2's release and `migrate_from_collection.py` turn out to be far off, that stopgap is the one thing
that would also repair the site that is broken today, and it can be reconsidered then.

**Settled: a member renamed by §2.4 carries locale provenance, like the static fact it now is.**
See §2.4's bullet on it. The alternative — keeping today's blanket exclusion — would require
knowing that an entry was once a member after it has been renamed, which is exactly the
information §2.2 deliberately does not keep.

**Settled, and done: SEMANTIC_SEARCH_SITE_PLAN.md now carries the field.** `from_collection` is
in its §6.1 schema, its §8.1 export gained step 4a, and its step 5 records that
`name_subtokens` keeps the raw name and the query-side tokenizer strips one trailing `(_)` from an
`Entity Name` condition, so `from_collection` stays display-only and is never filtered on. Nothing
else in this plan depends on that file.

**The order of work, settled.** Extend `rename_dynamic_members.py` and re-run it → ML writes the
field → thread it through `write_answer` → run and archive `migrate_entity_positions._scan` → run
`migrate_from_collection.py` and verify → export to the search site → §2.1's rule → §2.3's
rendering. The rename pass comes **first and is a hard prerequisite of the ML release**, because
§3 requires it either to run before any record can carry the field or to be extended to the new
arity. In this chosen order — before the release — the extensions it needs are `--dump` made
optional and the vector drop routed through `invalidate_vectors`; the pad to 14 plus the extended
read-back are required **only** in §3's other branch, if it ever runs after the release
(pre-release, padding to 14 would write explicit `nil`s on ~4,525 records and pre-promote them
past the "fewer than 14 = not reached" audit for no benefit). §2.1's Isa-Mini half lands with a
floor bump in the same commit: `contrib/Isa-Mini/pyproject.toml:49` must require the
`Isabelle_Semantic_Embedding` version that first ships `Record.from_collection`, or Isa-Mini
reads a field its installed dependency does not define. No position sweep may run from the ML
release until `migrate_from_collection.py` has completed and been verified (§2.2 — the window
covers interrupted-run resumes too). The export must come **after** the
pass: it copies `from_collection` straight off the record (SEMANTIC_SEARCH_SITE_PLAN.md §8.1
step 4a) and §8.2 makes every export a fresh namespace, so exporting first would publish
1.34M documents with the field empty and cost a full re-export to correct. Mirror the requirement
as a precondition on that plan's §8.1 completeness gate.

**Two things this document does not itself grant**, and they are the only open items:

1. **The raw-put grant.** §3 requires the pass to bypass `Semantic_DB.__setitem__`. The precedent
   grant is recorded in code, in `backfill_positions`' docstring (`semantics.py:794-805`), as "the
   one exception to the vector-layer self-sufficiency invariant, approved explicitly for this
   migration". No equivalent grant exists for this pass yet. Obtain it and record it on
   **`backfill_field`**, which is where the raw put will live.
2. **The three live-path verifications §2.4 names**, which prescribe a check rather than a
   procedure: cross-theory accessibility, the label-uniqueness assert's fourth argument, and the
   before/after diff of locale attributions.

   *Verification record (2026-08-19, fresh REPL on the HOL-Library heap, new code loaded from
   source; old code = the pre-change `semantic_store.ML` from git, shadow-loaded into the same
   session for the comparison):*

   - **Locale attributions, before/after, both directions:** enumerated `Topological_Spaces`,
     `Groups_Big` (locale interpretations) and `Limits` with both code versions and diffed every
     entry's stored provenance. Entry counts identical per theory (660 / 343 / 568);
     **provenance changed on zero entries in all three, in both directions**. The only
     differences were the intended renames themselves: 61 (`Topological_Spaces`) and 67
     (`Limits`) rule-face members of `continuous_intros`/`tendsto_intros` — same universal keys,
     invented `coll(i)` names before, adopted real names (with real positions) after; exactly
     the population §5 repaired by hand, now fixed at the source.
   - **The label-uniqueness assert's fourth argument, re-established:** equal labels need equal
     `(kind, name)`; a renamed member carries a static fact's name only because it selected that
     fact's own theorem (the structural proposition check), which makes the two entries'
     universal keys equal per face — and uk-equal entries are collapsed before the assert, by
     `member_entries`' seed over all five static lists and by the global keep-first. A static
     fact in an *ancestor* theory is not in this sweep's batch at all, so no cross-theory pair
     can reach the assert. Empirically, the assert ran clean over the three enumerations above,
     whose batches contained 128 renamed members.
   - **Cross-theory accessibility, settled:** an adopted `Fixed` name is generated in the prep
     context and resolved in that same proof context — the same property every static ancestor
     fact already has, so renamed members introduce no new accessibility class. The behaviour
     delta that remains is the recorded improvement: a member that left its collection after the
     prep snapshot is no longer dropped, because its global fact name still resolves.

## 5. What was already done to the store

Recorded because it changed production data and nothing else records it.

On 2026-08-18, after a reflink backup (`semantics.lmdb.pre-rename-20260817-235750` and the
vector store's twin, entry counts verified equal), **4,524 records were given a real name and a
real position** taken from data the store already held, and their vectors were dropped and
re-embedded (744,481 tokens). Every edit was read back; 0 problems. Report:
`~/rename_report.json` on `cslh19`; the pass was `rename_dynamic_members.py`.

Where the names came from: a theorem-alike key is `XOR(constituent hashes) ++ tag ++
thm128[:15]`, so records of one proposition differ only in the kind byte. Where a member's
proposition already had a positioned record under another kind — the theorem face, enumerated
statically in some other theory's sweep — that record's name and position were copied onto the
member face (4,519 records: 4,439 introduction rules, 80 elimination rules). Five more took a
positioned record that sat on the very same key.

Three consequences that matter for the work above. **The repair is not a fixpoint**: its scan
completed before its own writes, so one further record
(`Topological_Spaces.tendsto_intros(123)`) became repairable during the run and is still
unrepaired; a second run would find it — but note that the script's `--dump` argument is
required (`:92`) and takes a rekey dump database that this document does not name and that is
not in the repo, while the remaining record is a sibling case needing only the store, so
`--dump` has to become optional. **Store coverage afterwards**: 1,343,793 entity records,
98.78 % with a position; of the 16,368 without, 6,768 are EXPERIENCE records, 9,598 are the
population this plan is about, and 2 are the methods `Named_Simpsets.simp` and
`Named_Simpsets.simp_all`. **Those 4,524 records have `from_collection = NONE`**, by §2.2's
invariant, and nothing can tell from the data which collection they came from.

## 6. What was measured for §2.4

Measured on 2026-08-18 against a REPL on the `HOL-Library` heap; read-only. Recorded so nobody
re-measures it, and because three of §2.4's requirements exist only because of it.

**Yield.** In the `HOL-Library.Library` context, 28 non-infrastructure collections, 1,118
members, **756 accepted (67.6 %)**. The distribution is all-or-nothing, not an average: 12 of
26 non-empty collections at 100 %, 4 at 0 %. The 0 % ones are collections whose members are
synthesised on the fly — `tendsto_eq_intros` applies a rewrite to each `tendsto_intros` member
(`Topological_Spaces.thy:788-792`), `derivative_eq_intros` likewise (`Deriv.thy:61`) — so those
theorems have never been in the fact name space and no name exists to find.

**Why it fails.** Of 362 rejections, **352 (97.2 %) are the absent-hint marker**. Ten are
hidden names; concealed, proposition mismatch, and missing position rejected nothing. The
binding constraint is that no hint exists, not that the guards are strict.

**This does not extrapolate to `cslh19`, and the plan does not claim it does.** The probe ran on a
`HOL-Library` heap, the only one on the measuring machine, so it covers a small minority of the 137
collections the production store holds — and the largest bins there are package-generated ones
where a name hint is least likely to exist (`Record_Intf.icf_rec_unf`, `Nominal2_Base.eqvts_raw`,
`HeapLift.update_commute`, `Autoref_Id_Ops.autoref_itype`). The real yield on `cslh19` is
**unknown and lower than 67.6 %**. Settling it needs a REPL on an AFP heap against that store.

**The proof-context hazard.** Inside a `lemma` with `note h1[continuous_intros]` and the like,
four proof-local labels were accepted — `local.h1`, `local.cg`, `local.lg`, `local.h2` — passing
every guard: not the unknown marker, not concealed, `Long_Name.is_hidden` false because the name
genuinely is accessible there, proposition equal. `Name_Space.the_entry` returned
`file=#REPL line=1`, so a position check *certifies* them, and `Facts.extern` renders them
without a `??.` prefix. Only two tests catch them: the `local.` prefix, and absence from
`Global_Theory.facts_of`. This is why §2.4's global-fact-space guard is not optional.

**The two equalities.** Over 2,190 pairs where a hint resolved and matched, `aconv` and
structural `=` on `Thm.prop_of` never disagreed. Structural equality is adopted anyway, as it
costs nothing and is what the universal key respects.

**Cost.** About **1.3 µs per member**, roughly doubling the member-enumeration phase it sits
beside, about **1.4 ms added per prep pass** over 1,123 members. Measured with warm caches, and
not measured as a fraction of total prep cost, whose dominant term is
`Universal_Key.key_of_theorem'`. Cost is not an obstacle.

**Complementary coverage.** Indicative only — measured against a development snapshot, not
`cslh19`. Of 407 members that either route can name, **26 are ones only the store can name** — ten where the hint is a locale-local form
(`local.sup_continuous_const`) of a name the store holds correctly qualified
(`Order_Continuity.sup_continuous_const`), sixteen with no hint at all. Where both name a
member, 366 of 372 one-to-one rows agree (98.4 %); the single aligned disagreement is two
legitimate aliases for one proposition. This is the evidence behind §2.1's rule: §2.4 shrinks
the population for which the stored name beats the live one, but does not empty it.
