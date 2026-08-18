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

Three sites. The rule at each is the same and is stated once, at the end.

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
Bring it under the same rule, and add the **chosen** name — not `ref_name` — to
`bundle_member_names` at `:2203`, so the `suppress_def` match still works.

**The rule at all five: take the live name only when the stored name is an invented member
form**, which is exactly what §2.2's field decides. Otherwise keep the stored name. Without the
condition, the 4,524 records that already carry real names (§5) are shown to a model as
`tendsto_intros(37)` — the unstable string §1 calls the defect. Measurement backs this up: of the
members a name can be found for at all, roughly 6 % are ones the store knows and §2.4 cannot
recover (§6).

**Write the rule once, and write it as a record-to-record substitution, not as a predicate.**
`_apply_live_name` (`semantics.py:2046-2051`, applied at `:2057` and `:2114`) is already
record→record — `rec._replace(name=name) if name is not None else rec`. Keep that shape, add the
condition inside it, lift it out of its closure to module level, and have all five callers use it.
A boolean predicate instead would push `X if p(rec, live) else Y` into five places: five polarity
decisions to get right, and a second condition later would have to be added five times.

**Two of those callers are not member-specific, and the condition changes them.** `:2057` (inside
`_resolve`, for every scored candidate) and `:2114` (every reranked candidate) run on **every**
record of every kind, and `candidate_names` is filled for every entry the live enumeration
returned in both `Context` branches (`:1984-1985`, `:2000-2001`, `:2020`). Adding the condition
there flips every non-member record from the live, context-resolved name to the stored one. On
that path the name is a handle the agent will cite back, and the live one is the one guaranteed to
resolve in the querying context. **Keep those two unconditional** and apply the condition only at
the three by-name sites, unless someone first measures that the stored name resolves in the
querying context across the non-member population. Say which, in code, at the call site.

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
`Semantic_DB.query` has other callers (`semantics.py:1419`, `:2547`, `Isa-Mini`'s `desugar.py:119`),
so the new parameter defaults to `None` and they keep today's behaviour unchanged.

**Let ML hand Python the finished name.** Both the second and third sites otherwise have Python
rebuild `name(i)` from a string it was given. The rule for building that string is already owned by
ML and already implemented there: `key_of_theorems_tagged` composes it from `ref_at` and an `n > 1`
test in the same `local` block as `key_of_theorem` (`Isabelle_RPC/Tools/universal_key.ML`). Have
`key_of_theorem` return that same display name **as a new fifth component**, leaving `full_name`
and `is_global` untouched — replacing the fourth component would change what four other entity
kinds (18, 34, 50, 66) hand back and would break `is_global`, which must be computed from the bare
interned name. Only the kind-2 branch (`:1026-1027`) consumes the new component. Then
`universal_key_and_name_of` hands Python a string it never edits and the `parse_thm_xname` round
trip disappears from both sites.

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
    Declared of string        (* a name the name space declared; used verbatim *)
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

**Three total projections, and every consumer named.** Getting one wrong is silent, so the plan
names them rather than leaving the choice to whoever compiles first:

```sml
fun stored (Declared n)    = n
  | stored (Member (c, i)) = c ^ "(" ^ string_of_int i ^ ")"

fun from_collection (Declared _)    = NONE
  | from_collection (Member (c, _)) = SOME c

fun space_name (Declared n)    = n     (* the name to look up in a name space *)
  | space_name (Member (c, _)) = c
```

| consumer | projection | why |
|---|---|---|
| the name written to the record (`:851-856`) | `stored` | it wants that string |
| the new field (§2.2 below) | `from_collection` | the same value's other projection, so the two cannot disagree |
| the name list handed to `Locale_Instance.detect` (`:690`) | `space_name` | |
| the `Facts.is_dynamic` bypass (`:698-699`) | `space_name` | see below |
| `mk_constituents`' registry key (`:865`, branches at `:834-839`) | `space_name` | name-addressed kinds are never members, so the value is identical to today's |
| `serial_of` (`:1506-1527`) | `space_name` | a member takes its collection's serial — today's behaviour, now stated rather than falling out of string shape |
| `entry_ord`'s name tie-break (`:581`) | `space_name` | identical to today's value, so sort order is unchanged |

**The locale bypass gets better, not worse.** Today it reads
`if Facts.is_dynamic pfacts name then [] else d` (`:698-699`), and it works only because a member's
carried name *happens* to be the bare collection name — the comment at `:686-689` says members are
given that name precisely so the bypass keeps firing. That is a condition holding by coincidence,
and the next person to change what a member carries breaks it silently. With `space_name` it holds
by construction: `space_name` **is** "the name to look up in a name space", which is exactly what
`Facts.is_dynamic` asks. A member yields the bare collection name and is bypassed; the collection
entity itself carries the bin name and is bypassed (the comment notes a member-index-only test
would miss it — this one does not); everything else is not a dynamic fact and is detected normally.
One condition, resting on a definition rather than on a coincidence.

**What this shape does NOT require.** No change to `Context_Callbacks.entry_name`, and so no change
to `contrib/Isabelle_RPC`. No change to `Theory_Structure`: it goes on rendering the rule lists'
names, `serial_of` goes on parsing them in its `Declared` branch, and that parse keeps the comment
saying why (`the_entry` is keyed on the bare fact name; the index is not a name-space key —
`theory_structure.ML:258-259`). That round trip is a pre-existing shape this plan neither creates
nor repairs, and touching it here would be scope this change does not need.

**One invariant the type does not enforce**, so assert it where the value is built: a member index
is 1-based (`j + 1` at `:1109`). `Member (c, 0)` would render as the bare collection name, which
§2.3 rules out showing because a bare `coll` resolves to the wrong theorem. Nothing in `int` says
so; a guard at the construction site does.

**The field.** `from_collection`; ML `string option`; msgpack a string or nil; absent on
records written before the field existed. It holds the **full name** of the dynamic
collection the stored name was invented from.

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
`_decode`/`_encode`); and on into the search site's export — see §2.3.

**It is normalised on the way in, exactly like `name`.** `_entries_of_wire` runs every text field
through `pretty_unicode` — `name=pretty_unicode(name)`, `prop_str=pretty_unicode(prop)`
(`semantic_interpretation.py:1249-1250`), `prompt_extra=pretty_unicode(hint)` (`:1256`), with the
one exemption spelled out at `:1251-1253`. `from_collection` is an Isabelle fact name and must go
through it too, or ML-written and pass-written records will hold two spellings of one collection:
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
between §2.4's release and this pass.** Do **not** "fix" this by widening `:1927` to carry the
name: the position sweep is one-off code that has already served its purpose, and rebuilding it to
be structurally safe against a situation that will not arise is work spent on the wrong thing. The
constraint is one sentence in a runbook; keep it there.

**The gate reuses this predicate; it does not restate it.** §3 requires a pre-write count that
must be zero, and it must call the same function, not a second copy of the conditions. A second
copy has already drifted once in this document's own history, and the drift was live: an
experience record named `attempt(3)` satisfies a copy that forgot the kind exclusions, and would
abort a pass that should have run.

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
  Name panel matches an adjacent subtoken sequence over `name_subtokens` (:1143, :1172), and a
  pasted `coll(_)` tokenizes without the digits, so it matches nothing where today's `coll(123)`
  matches. **Strip one trailing `(_)` from an Entity Name condition before tokenizing**, as a named
  step in §5's tokenizer pipeline so both implementations share it and it gets a row in §5.5's
  shared test-vector file. The alternative — filtering member rows through `from_collection` — has
  no compilation: §6.3 compiles a name condition to exactly one form over `name_subtokens` (:1185),
  and the Worker emits one filter for the whole namespace, so it cannot branch per row. Making
  `from_collection` filterable instead would mean a fourth `pre_tokenized_array` in the first
  export and a rewrite of D22's `All` panel.
- **Rows that render identically are accepted and documented, not collapsed.** The response
  collapses on a hash of `(name, expr)` computed from the stored name at export (:1124-1127,
  :1419-1421). A scan found 168 groups holding 201 extra records sharing a
  `(kind, base, expr)` and will render as rows identical in both name and statement — but that scan
  was run on a development snapshot and grouped by the wrong key: the collapse key is `(name, expr)`
  and excludes kind (SEMANTIC_SEARCH_SITE_PLAN.md:1121-1127, :1136). Re-measure on `cslh19`, grouped
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
`Fixed nm` to `entry_name`'s `Named`, and `Context_Callbacks.resolve_name` returns
`Thm_Name.print nm` for the same constructor (`contrib/Isabelle_RPC/Tools/context.ML:198`).

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
  (`:109`), which the ascription at `:101` hides. `entry_def_pos` already carries the workaround one
  line away, so copy its shape —
  `val entry_of_fact : Facts.T -> string -> {pos: Position.T, serial: serial, group: serial,
  suppress: bool list, theory_long_name: string, concealed: bool} option`. Extract the **lookup**, not "the guards":
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

- **Re-apply the infrastructure filter under the adopted name.** The member path tests the filter
  with the collection's name (`:1114-1120`) while the static path tests the fact's own
  (`:951-955`), and `is_infra_thm` is name-dependent in six clauses (`infra_filter.ML:432-446`);
  without this a member can be stored under a name the store excludes everywhere else. This is
  also where concealed, hidden and `??.` are enforced, which is why they need no bullet of their
  own. **The filter is not in scope where the name is stamped, so it must be passed in.**
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
  position rebuilt from a flattened triple can no longer answer. `member_entries` passes the new
  component at `:1410` in place of `Position.none`; a member with no adopted name passes
  `Position.none`, correctly. (The `pos = ("", 0, 0)` hardcode is at `:1109`; `:1108` is the name
  stamp. `cached_thm_entry.pos` stays `("", 0, 0)`: the live query path does not use a position,
  and giving it one would put the same fact in two places.)

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
`pack_fields(vals) -> bytes`, next to `_decode`, plus the named indices — and name in this plan
which existing readers get converted, because otherwise none will be. Do **not** reshape the wire
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

**Archive the position-completeness scan before the backfill runs.**
`migrate_entity_positions._scan` decides "this record was reached by the position sweep" from
the record's msgpack arity — `if n >= 13`, with the in-code comment saying so
(`migrate_entity_positions.py:100-121`), pinned by `test_entity_position_backfill.py:167-183`.
A backfill that pads every record to 14 makes `reachable_short` permanently 0, and nothing
else records which keys that sweep reached. Run the scan, archive its output, and note in the
plan file that the check is thereafter vacuous and needs an explicit marker.

**The backfill writes on every record it walks** — the collection name on a match, `nil`
otherwise — so that afterwards a tuple of fewer than 14 components means only "this record was
not reached".
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
(`semantics.py:146`) so it and `snapshot_sync`'s `_EXPORT_BATCH` (`:689`) stop being two numbers.
The pass still collects target keys in a read pass and closes the read transaction first — an open
`iter_items` snapshot pins old pages against reuse (`semantics.py:548-555`) — and still checks map
headroom before starting.

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

**Gate the pass before it writes, using §2.2's predicate itself.** Count the records that
satisfy every conjunct of §2.2's criterion *except* the collection-record one — kind neither
EXPERIENCE nor METHOD, no position, name matching `^(.*)\((\d+)\)$` — and whose base names no
`THEOREM_COLLECTION` record; abort if non-zero. Call the same function §2.2 defines, with that one
conjunct inverted; do not restate the conditions, which is how an earlier draft of this document
lost the kind exclusions and would have aborted on an experience record named `attempt(3)`. The
count should be zero on the current corpus, and it is the only thing that would catch the one
structural false negative: a collection record is produced only in its declaring theory's sweep
(`theory_structure.ML:107-128`) while members are produced wherever the collection is visible, so
a member whose collection was never interpreted would be silently left unflagged forever. Read the
collection-name set through the same layered view the records come from, and complete it before
classifying anything — the two key families are unordered relative to each other, so the pass is
two-phase.

**Back up, stop other writers, and verify after commit — through one shared function.** Five
one-off passes in this tree copy the same timestamped `env.copy(..., compact=True)` idiom
(`migrate_record_provenance.py:27-31`, `migrate_entity_positions.py:36-39`, and three siblings),
the tree calls it "the backup convention", and the pass that most needed it did not have it. Put
it in the package rather than in any pass — `backup_store(path) -> str`, doing the timestamped
compacting copy plus the free-space check ENTITY_POSITION_PLAN.md:1155-1158 sizes by hand — and
call it on line one of `main`. Refuse the larger temptation while you are there: these passes are
**not** one skeleton (two are directory renames, one drives Isabelle over RPC), so extract the
backup and nothing else. Stop anything else writing `semantics.lmdb` for the duration; re-open in
a **fresh** read transaction afterwards and verify the edited records — the precedent read-back
happens inside the still-uncommitted write transaction (`rename_dynamic_members.py:245-247`), so
it verifies the encoding, not the committed bytes. Re-running is the resume mechanism and is
idempotent, because the field is a function of the record's own name, its position and the
collection set — all three stable under re-running.

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
candidate, a theorem name round-tripping through a string, is *removed* by §2.2 rather than
inherited: §2.2's `Declared of string` makes no claim about the string, so a name that already
carries a selection index sits in it honestly, and `serial_of` goes on parsing it exactly as it
does today.)

`fact_base_name` (`:1169-1170`) is **not** on this list and must not be added: it matches
`Context_Callbacks.entry_name`, which this plan does not change, and its `Fixed` clause must keep
handing `is_declared_infra_thm` the bare `nm` rather than anything index-bearing.

**Sites coupled to `build_entries`' tuple arity**, which changes at both ends (four in, nine
out): `entry_ord`, which breaks ties with `string_ord` on the name component (`:574-583`) and is
applied to the pre-`build_entries` tuples at `:1537-1538` — give it `space_name`, which preserves
today's key exactly; `:1332` and `:1361`, which thread the name from `raw_thm_entries_named` through
`thm_entries_with_uks` and `best_thms`; the dedup filter at `:1542`; the label-uniqueness assert's destructuring
(`:1585`), the non-WIP widening map
(`:1609-1611`), `attach` in the WIP branch (`:1627-1633`), the widened ten-tuple at the
position backfill (`:1927`), and the explicit `entries:` type in `make_interpret_file_cmd`
(`:402-412`). All are compiler-caught **except** `Test/Entity_Position_Test.thy:328`, `:329` and `:368`, in a
separate theory that nothing in this repo runs without an explicit `isabelle build`. `:328` is the
worst of the three because it **constructs** the input tuple —
`build_entries ctx [(entity, name, pos, uk, NONE)]` — so it needs `Fixed (name, 0)` as well as the
dropped fifth component. `:332`'s `entry_name = name` does **not** break: `build_entries`' output
name component stays a string.

**Tests that encode the arity**: on the Python side only `test_entity_position_codec.py`'s
`_wire_entry` (`:89-93`). `test_entity_position_backfill.py` does **not** break — its arities are
synthetic msgpack tuples and `_scan`'s `n >= 13` is not part of the codec — so do not "fix" it.
Plus the `.thy` lines above.
A new test should cover a collection with one member that has an invented name and one that
does not.

## 4. Settled, and what is still to decide

**Settled: the field is stored, and ML supplies it.** Not derived at read time. The consumer
is the semantic-search front end, which serves live queries against a corpus that keeps
growing; applying a corpus-dependent test there would mean re-earning its correctness on every
future snapshot, and its failure mode is silent — a static bundle's stable `foo(3)` rendered
as an invented form. The enumeration knows the answer for certain at the moment it invents the
name, so that is where it is recorded. The costs in §3 are accepted.

**Settled: the backfill walks and writes every record.** The alternative — writing only on a
match — was considered and rejected: the invariant that a short tuple means "not
reached" is worth the whole-store pass, and the compatibility question is handled by the
tuple's length.

**Settled: §2.4 stays in this plan**, with every bullet in it treated as a prerequisite rather
than an improvement. Its measured cost is negligible (§6) and its code volume is small; three
of its bullets — the global-fact-space guard, carrying the position, and placing
`member_entries` after the rule lists — close defects that are measured, not hypothetical.

**Settled: §2.1 lands after §2.2.** It reads the field, so it ships once ML writes it, the two
release channels have gone out together, and the backfill has run. Shipping it earlier without
the condition was rejected: it would widen a known defect from the one site that has it today
(`_apply_live_name`'s unconditional override) to four. A stopgap keyed on "the stored record has
no position" — which separates the two populations exactly on the current corpus — was also
considered and rejected, because it is a temporary mechanism that has to be remembered and
removed. If §2.2's release and backfill turn out to be far off, that stopgap is the one thing
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
arity; the extension it needs in either case is the pad to 14, `--dump` made optional, and the
vector drop routed through `invalidate_vectors`. No position sweep may run between the ML release
and `migrate_from_collection.py` (§2.2). The export must come **after** the
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
