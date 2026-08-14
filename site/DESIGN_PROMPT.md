Design the web UI for a semantic search engine over the Isabelle/HOL theorem prover
and its Archive of Formal Proofs (AFP). Think Hoogle (Haskell), loogle (Lean), or
Lean Finder — a reference tool that working researchers keep open in a tab.

## Who uses it

Formal-methods researchers and Isabelle users, worldwide, mostly on desktop.
They are technical, impatient, and here to find one specific lemma or constant.
They are NOT here to browse. Speed of scanning results matters more than beauty.

## What it searches

1.35 million Isabelle entities — theorems, constants, types, type classes,
locales, proof methods, and derived rules. Each carries a machine-generated
English explanation. UI language is English.

## The search inputs

ONE large search box, always visible, holding a natural-language query
("theorems about continuity of paths"). It is required — searching with filters
alone is not supported, and the landing page is essentially this box alone.

Below it, a collapsed disclosure labelled "Syntactic filters" containing FOUR
condition sections plus one chip group, in this order:

  - "Entity Name"   — matches the entity's own name
  - "Expression"    — matches the printed expression
  - "Theory Name"   — matches the theories the entity is associated with
  - "All"           — matches any of the three above
  - "Kind" — multi-select chips: Theorem, Constant, Type, Class, Locale,
    Method, Collection, Introduction rule, Elimination rule, Induction rule,
    Case split.

Each of the four condition sections is a REPEATABLE LIST OF SINGLE-LINE ROWS.
Every row is one condition and carries its own contains/excludes toggle, its
own text input, and a remove button, with an "add condition" affordance below
the list. Conditions are combined with AND.

A condition may freely contain spaces and any punctuation — `sorted_wrt R xs`,
`-->`, `⟦?P; ?Q⟧` are each ONE condition. There is no escaping and no inline
operator syntax; do not design one.

The disclosure shows a compact summary when collapsed but non-empty
(e.g. "3 conditions active"), so filter state is never hidden from the user.

## The result list

Results are ranked by semantic similarity to the natural-language query; the
syntactic filters only narrow the candidate set. Show a similarity score.

Design a result card that stays scannable at 20+ per screen. Each card carries:

  - entity name — the primary handle; this is what users scan for
  - one or more kind badges — an entity can be several kinds at once
  - the theory or theories it relates to (see the note on multiplicity below)
  - the entity expression — mathematical notation, monospace, length varies wildly
  - a similarity score
  - a copy-to-clipboard affordance for the expression
  - the English explanation, collapsed by default, expandable in place

**Theory multiplicity, and when to say nothing.** A constant, type, class,
locale or method belongs to exactly one theory: show it, always. A theorem
belongs to none — it relates instead to every theory whose constants appear in
its statement, on average seven of them and sometimes forty, and the
alphabetically first of those is a base logic (`HOL.*`, `Pure`) more than half
the time. So a theorem card shows NO theory line at all by default.

The exception is when a theory condition is active. Then the user needs to know
why this theorem came back, so the card shows the theory (or theories) that
matched the condition, marked as such, with no "+N more" — the matched set is
the answer, not a truncation of a longer list.

The complete list always lives on the entity page, untruncated.

Use these REAL examples so the layout is tested against authentic content. Note
the notation, the length variance, the very long dotted names, and the
multi-theory case:

  ── Theorem ────────────────── (a theory condition is active) ─
  Error_Function.continuous_on_linepath'
  matches HOL-Analysis.Path_Connected
  ⟦continuous_on ?A ?f; continuous_on ?A ?g; continuous_on ?A ?h⟧
    ⟹ continuous_on ?A (λx. linepath (?f x) (?g x) (?h x))
  "If functions f, g, and h are each continuous on a set A, then
   x ↦ linepath (f x) (g x) (h x) is continuous on A. …"

  ── Theorem ─────────────────── (no theory condition active) ──
  Stochastic_Processes.proc_source.finite_measure_cut_measurable
  ?Q ∈ sets (?N ⨂⇩M proc_source ?X)
    ⟹ (λx. emeasure (proc_source ?X) (Pair x -` ?Q)) ∈ borel_measurable ?N

  ── Constant ─────────────────────────────────────────────────
  Strong_Late_Sim.derivative
  Pi_Calculus.Strong_Late_Sim
  pi ⇒ pi ⇒ subject ⇒ name ⇒ (pi × pi) set ⇒ bool

  ── Theorem ──────────────────────────────────────────────────
  MC.no_infinite_subset_chain2
  HOL.Finite_Set  (+6 more)
  ⟦finite UNIV; mono ?τ; ∀i. (?τ ^^ (i + 1)) UNIV ⊂ (?τ ^^ i) UNIV⟧ ⟹ False

  ── Theorem · Introduction rule ──────────────────────────────
  Multi_Interval_Preliminaries.max_last_sorted_wrt_upper
  Interval_Analysis.Multi_Interval_Preliminaries  (+5 more)
  ⟦?XS ≠ []; sorted_wrt_upper ?XS⟧ ⟹ Max (set (map upper ?XS)) = upper (last ?XS)

## The entity page

Every entity also has a permanent, shareable URL. Design that page too: the same
content as a card but full-width and uncollapsed, plus

  - the source location, phrased as "generated by the command at
    Path_Connected.thy:1204", with a link out to the source. The wording matters:
    many entities are machine-derived and the line points at the command that
    produced them, not at a hand-written declaration.
  - the complete list of related theories, not truncated
  - "Related entities" — the ten semantically nearest entities, as links

These pages are indexed by search engines and are often the first thing a
visitor sees, so each must read well standing alone, with the entity name as the
visual anchor.

## Hard constraints

**Mathematical notation is the content.** Symbols like ⟹ ⟦ ⟧ ⨂⇩M λ ∀ ⊂ ↦ ⇒ ×
∈ ≠ 𝔍 ℭ and subscripts appear constantly. Expressions must be monospace, must
never be truncated mid-symbol, and long ones must wrap or scroll gracefully
inside the card without breaking the layout. Some expressions run to thousands
of characters — design the overflow behaviour explicitly rather than leaving it
to chance.

**Users must be able to type these symbols.** Provide an input affordance: a
clickable palette of roughly twenty common symbols, plus a hint that ASCII
escapes (`\<Longrightarrow>`) and abbreviations (`==>`) are accepted and
converted as you type.

**One piece of user education is mandatory.** The syntactic filters are LITERAL
text matching, not pattern matching with variables. Users will type `?P ⟹ ?Q`
expecting wildcards and get zero results. Design an empty state that says this
specifically — a generic "no results found" is a failure here.

**A rejected-condition state.** A condition that consists only of separator
characters — a lone `_`, a lone `.`, a lone subscript marker — carries nothing
to match on and is rejected rather than silently ignored. Design how the
offending line is marked and what it says.

**The theory filter means two things, and must say so.** A constant, type,
class, locale or method has one declaring theory. A theorem has none — it is
matched instead against the theories of the constants its statement uses, on
average seven of them. Design an inline notice under "Theory Name" that states
this, shown only when it can bite: a theorem-like kind is selected AND a
condition reaches the theory field (directly or through "All").

**Machine-generated disclosure.** The English explanations come from a language
model. Say so honestly and visibly, not buried in a footer.

**Themes.** Light and dark, both first-class.

**Responsive** down to tablet; phone is a nice-to-have, not a requirement.

**No framework assumptions.** The markup will be server-rendered; do not design
anything that presupposes a particular client-side framework.

## Aesthetic direction

Dense, quiet, typographic. Closer to a well-set reference manual or a good API
doc than to a consumer product. Restrained colour, used for meaning — kind
badges, match highlighting — rather than decoration. Generous monospace. No hero
section, no marketing copy, no illustrations. The search box is the entire
landing page.

## Deliverables

1. Landing / empty state
2. Results page with filters collapsed
3. Results page with filters expanded, showing two conditions in Expression
   (one contains, one excludes) and one in Theory Name
4. The "literal matching, no wildcards" empty state
5. An entity page
6. Dark theme for at least the results page
