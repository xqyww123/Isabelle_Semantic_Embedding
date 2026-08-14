# Interface copy — isasearch

Draft 2, 2026-08-14. Every visitor-facing string, in one place, so that the
implementation copies rather than invents. Draft 1 went through the same four
readers that §13b used; draft 2 is the result. The findings that changed it are
recorded in §11 at the end, together with the ones that were rejected and why.

Nothing here may be paraphrased when it reaches the markup. Where a string is
locked by a decision, the decision is named beside it. Text in `«guillemets»` is
a substitution slot, never shipped as written.

## 0. The words this interface uses, and the ones it does not

| Use | Never use | Why |
|---|---|---|
| **panel** — one of the five blocks inside Syntactic filters (D22) | section, group, box | D22 already says "panel" |
| **condition** — one `contains`/`excludes` toggle with its text | row, filter, term, rule | "row" names a shape, not a thing |
| **search box** — the large input; **condition box** — the input inside a condition | the box, unqualified | draft 1 used "the box" for three different inputs |
| **query** — the text in the search box, and nothing else | description, search string, prompt, question | D40's locked hover already says "your query" |
| **search** — the action, and the unit that the daily limit counts | query, request, lookup | one action, one word |
| **entity expression** (short form **expression** where the Expression panel is on screen) | statement, term, formula, code | §1 of the plan |
| **the associated theories** | related theories, relevant theories | §1 of the plan, verbatim, always |
| **piece** — one unit of matching | token, subtoken, fragment | "token" and "subtoken" are internal |
| **part of a name** — a name's `_`- or `.`-delimited segment | piece, chunk, word | draft 1 used "piece" for both, in the one message where precision matters |
| **select** / **selected** for the Kind buttons | tick, ticked, chip | "tick" is British and low-frequency; "chip" is designer jargon |
| **theorems and derived rules** — the five theorem-like kinds together | theorem-alike, theorem-like | needed in three places that listed only some kinds |

The word **literally** does not appear: everyday English has turned it into an
intensifier, and it is false here — four transformations happen before a
condition is matched. **Run** does not appear as a noun. **Allowance**,
**authoritative** outside the locked sentence, **resets**, and **at once** in the
sense of *simultaneously* do not appear either.

Numbers are written without thousands separators — `1000`, `8000`. A comma is a
decimal point across most of continental Europe, and the audience is
international. The corpus size is written **`1 300 000`**, not `1.3 million`: a
decimal point groups thousands in several of the readers' languages.

**Three open naming choices** are marked `[DECIDE]`. Everything else is settled.

## 1. The landing page

The whole page is the search box, with the Syntactic filters panel group
collapsed beneath it.

> **isasearch**
>
> Search Isabelle/HOL and the Archive of Formal Proofs by describing what you
> want in English. Theorems and the rules that Isabelle derives from datatype,
> inductive and function definitions; constants, types, classes, locales, proof
> methods and named theorem sets — 1 300 000 entities in total.

Placeholder inside the search box:

> describe what you are looking for

Under the search box, two lines:

> A query is required. It puts the results in order; the syntactic filters
> decide which results can appear at all. Neither one works without the other.

> **Looking for a name you half-remember?** Type it into the search box and put
> it into an Entity Name condition as well. The condition finds every entity
> whose name contains it; the query decides the order.

*(The second line answers the one thing that made an Isabelle reader leave draft
1. It costs two lines and needs no change to the design — see §11.)*

## 2. The Syntactic filters panel group

Collapsed, nothing active:

> **Syntactic filters**

Collapsed, conditions active:

> **Syntactic filters** · «1 condition» / «3 conditions» · «4 of 11 kinds»

The kind part appears only when fewer than eleven kinds are selected. The
condition part is singular at one. Without both parts a visitor can leave the
group collapsed and never learn why the results are narrow.

Expanded, five panels in this order (D22): **Entity Name**, **Expression**,
**Theory Name**, **All**, **Kind**.

### 2.1 Panel labels and their hover text

- **Entity Name** — *"The full name of the entity, which includes its theory:
  `Path_Connected.path_image_join`. You can type any part of the name that starts
  at a boundary, so `path_image_join`, `image_join` and `Path_Connected` all match
  that entity."* (D39)
- **Expression** — *"The expression that the result card prints: the proposition
  for a theorem or a derived rule, the type for a constant, and the source text of
  the declaration for a type, a class, a locale, a proof method or a named theorem
  set."*
- **Theory Name** — *"The associated theories. A constant, a type, a class, a
  locale, a proof method and a named theorem set each have exactly one theory,
  which is the theory whose source declares them. A theorem is matched instead
  against the theories of the constants that its statement uses."*
- **All** — *"Matches the condition against Entity Name, Expression and Theory
  Name together. `contains` needs the text in at least one of the three;
  `excludes` requires that it appears in none of them."* (D22, §6.3)
- **Kind** — *"If you select several kinds, the search returns entities of any of
  those kinds. Text conditions behave in the opposite way: a result must satisfy
  every one of them."* (D38)

### 2.2 The controls inside a panel

The toggle reads **contains** / **excludes**. The control that adds another
condition reads:

> add condition

### 2.3 The line under the All panel, always shown

> This condition matches text in Entity Name, Expression or Theory Name.

### 2.4 The note under Theory Name

Shown whenever the Theory Name panel is expanded, and additionally under the All
panel when a condition exists there and a theorem-like kind is selected (D15).

> A theorem is identified by its statement, not by the place where it is written,
> so isasearch does not filter a theorem by the theory that proves it. A Theory
> Name condition on a theorem matches every theory that declares a constant
> appearing in the theorem's statement. A theorem often has several such
> theories, and sometimes more than twenty.
>
> The theory that proves a theorem is the first part of its name, so you can
> search for it in **Entity Name** instead.

*(Draft 1 said "isasearch does not record which theory declares a theorem". Every
reader rejected it: it is false about Isabelle, it contradicts the source link on
the same card, and the theory is visibly present in the entity's own name. §11.)*

### 2.5 The lines at the foot of the panel group, always shown

> **How conditions are matched.** isasearch splits a name into parts at `_`, `.`
> and any punctuation, and a condition has to start at one of those boundaries:
> `sorted` matches `sorted_wrt`, and `Analysis` matches `HOL-Analysis.Filter`, but
> `orted` starts in the middle of a part and matches nothing. Upper and lower case
> are different: `Path` and `path` do not match each other. Spacing does not
> matter — `?a + ?b` and `?a+?b` are the same condition.
>
> **How conditions combine.** A result has to satisfy every condition. `excludes`
> reverses one condition: the result must not contain that text. The Kind buttons
> work the other way — a result may be any of the kinds you select.

*(Draft 1 said "matched against the printed text… Case-sensitive", stated the
boundary rule only on an error page that most visitors never reach, never
mentioned `-`, never explained `excludes` at all, and left spacing unanswered.)*

### 2.6 The Kind buttons

Eleven buttons, all selected by default (D29):

> Theorem · Named theorems `[DECIDE 1]` · Constant · Type · Class · Locale ·
> Proof method `[DECIDE 2]` · Introduction rule · Elimination rule · Induction
> rule · Case split `[DECIDE 3]`

Hover on **Named theorems**: *"A `named_theorems` declaration — a name that later
proofs add theorems to, such as `approximation_preproc`."*
Hover on **Introduction rule**: *"A theorem that also serves as an introduction
rule is one entity with both labels, and one result card carrying both. Selecting
only this button finds the entities that carry it."*

When no kind is selected:

> No kind is selected, so no result can appear. Select at least one.

## 3. The result cards

### 3.1 The card

Entity name, kind labels, the entity expression in monospace, the similarity, a
copy control, and the English explanation collapsed (D40: no "AI" label on the
collapsed line).

Copy control hover:

> Copy the expression

For two seconds after use:

> Copied

Similarity hover — **locked by D30 and D40, do not edit**:

> Cosine similarity between your query and this entity, computed with
> Qwen3-Embedding-8B. The result order also accounts for keyword matching, so a
> lower score can appear higher up.

### 3.2 The expanded explanation

The first two sentences are **locked by D30**. The third is required by D40.
`[DECIDE 4]` below asks whether the second sentence may change.

> Written by a language model from the formal statement, not by the theory's
> authors. It may be imprecise or wrong; the statement above is authoritative.
> isasearch searches this text as well, so a poor explanation can push an entity
> down the result list.

No explanation:

> No explanation was generated for this entity. You can still find it by its name
> and by its expression, and its position in the results is decided by those.

### 3.3 The theory line

A constant, a type, a class, a locale, a proof method and a named theorem set
always show their one theory. A theorem shows no theory line, unless a Theory
Name condition is active (D26), in which case:

> a constant here comes from HOL-Analysis.Path_Connected

Hover:

> Your Theory Name condition matched this theory. It is one of the «23» theories
> that declare the constants in this statement, not the theory that proves the
> theorem. The entity page lists all of them.

*(Draft 1 printed a bare "matches HOL-Analysis.Path_Connected", which two readers
independently read as "this theorem lives in Path_Connected" — the one belief the
rest of the page works to prevent.)*

### 3.4 The source link

Present on about four cards in five (D42, coverage 80.2 %):

> Path_Connected.thy:1204

Hover:

> The command that produced this entity. Many entities come from a command such
> as `datatype` or `fun` rather than from an explicit declaration, so the line
> number points at that command.

Absent form, in place of the link, never a dead link and never blank:

> source position not recorded

### 3.5 Under the list

> Showing 1–20

Fewer than twenty results:

> Showing all «7» results

*(No total. D29 removes the count: the fused result set is truncated at 200, so a
total would be a number that the site cannot honestly produce.)*

Controls at the foot of the list — **both**, and the previous control is absent
on the first page:

> previous 20 · next 20

At the end:

> No more results. isasearch returns the 200 best matches for a query; if what
> you want is not among them, add a condition to narrow the search.

## 4. Empty states

### 4.1 An Expression condition matched nothing

This page is generic: it is shown for whatever the visitor typed, so nothing on
it may assume what they meant. The worked example is labelled as an example.

> **Nothing contains that text**
>
> The Expression panel matches text, not patterns. It has no variables: `?n`
> searches for the name `n`.
>
> **Your condition**
> «?n + ?m = ?m + ?n»
> isasearch removes the question marks — from your condition and from the text
> that it searches — and then looks for «7» pieces in adjacent positions, in this
> order: «`n` `+` `m` `=` `m` `+` `n`».
>
> **For example**, `?n + ?m = ?m + ?n` finds nothing, although the theorem it
> describes is in the index: `Groups.ab_semigroup_add_class.add.commute` is
> printed as `?a + ?b = ?b + ?a`. A condition that names the variables `n` and
> `m` cannot match a statement that is printed with `a` and `b`. The variable
> names are the only difference.
>
> **What to do instead**
> Describe the statement in the search box — *addition is commutative* — and use
> the Expression panel only for a name that must appear, such as `sorted_wrt` or
> `continuous_on`.
>
> *[button]* Remove this condition and search again

For an `excludes` condition, the first two blocks change and the rest is
unchanged:

> **Every entity contains that text**
>
> This condition excludes «`⟹`», and every remaining result contains it, so
> nothing is left. Excluding a very common operator removes almost everything;
> exclude a name instead.

The reference block beneath, always shown:

> **What the Expression panel matches**
>
> ✓ Names and operators, as the card prints them: `continuous_on`, `sorted_wrt`,
>   `⟦`
> ✓ Part of a name, starting at a boundary: `sorted` matches `sorted_wrt`
> ✓ Isabelle's ASCII form. `\<Longrightarrow>` is always understood as `⟹`.
>   Abbreviations such as `==>` are converted inside the box while you type,
>   whenever the abbreviation has only one meaning.
>
> ✗ Variables and unification: `?f ?x`, `_ + _`
> ✗ Regular expressions and wildcards: `.*`, `cont*`
> ✗ Question marks, `_`, `.` and the subscript and superscript marks, which are
>   all removed before matching. A subscripted name such as `f⇩1` is therefore
>   found by `f`.
>
> To search by the structure of a term you need Isabelle itself: `find_theorems`
> and `find_consts` do that, inside a session.

### 4.2 The conditions matched nothing between them

Each active condition appears with its own removal control, and an `excludes`
condition prints as `excludes`.

> **No entity satisfies all of these conditions**
>
> A result has to satisfy every text condition. These are active:
>
> - Expression contains `sorted_wrt` — *[remove]*
> - Entity Name excludes `List` — *[remove]*
> - Theory Name contains `HOL-Analysis` — *[remove]*
>
> Try removing one. Your query is not the cause: it puts results in order and
> never removes any.

Appended whenever fewer than eleven kinds are selected:

> «4» of the 11 kinds are selected, which also restricts the results.

When the Kind selection alone is the cause:

> No entity of the kinds you selected satisfies these conditions. Selecting more
> kinds widens the search; with all eleven selected, the kind no longer restricts
> anything.

### 4.3 A condition with nothing to match

> Nothing in this condition can be matched. `_` and `.` separate the parts of a
> name, and question marks and the subscript and superscript marks are removed
> before matching. If a condition contains only these characters, no text remains.
> Add a name or an operator, or remove the condition.

### 4.4 The search box is empty

> Enter a query. The syntactic filters narrow the results; they cannot search
> without one.

## 5. While searching, and when it fails

> Searching…

> The search did not complete. Try again. If it continues to fail, the problem is
> with the site and not with your query.

> No connection to the site.

## 6. Limits

Numbers locked by D29 and D35. Wording is not. Both address limits count per
network address, and both messages say so, because a visitor behind a shared
address needs to know that waiting alone may not help.

Too many searches within a few seconds (5 per 10 seconds per address):

> Too many searches from your network. Wait a few seconds and try again.

The daily limit is reached (1000 per address per UTC day):

> Your network has reached the limit of 1000 searches for today. You can search
> again after 00:00 UTC.

The whole site is above its limit (10000 per hour):

> isasearch is busy. Try again in a moment.

The query is too long:

> The text in the search box is too long. The limit is 8000 characters.

One condition is too long:

> This condition is too long. The limit is 512 characters.

## 7. The entity page

The heading is the entity name alone. Under it, the same content as a card,
uncollapsed and full width, and then:

> **Associated theories**

For a constant, a type, a class, a locale, a proof method or a named theorem set,
one theory. For a theorem or a derived rule, the complete list, untruncated
(D26), under this line:

> These are the theories that declare the constants appearing in this statement.
> isasearch does not filter a theorem by the theory that proves it — that theory
> is the first part of the name above.

Then, when a position is recorded:

> **Source**
> This entity was produced by the command at Path_Connected.thy:1204.

and when none is recorded:

> **Source**
> The source position of this entity was not recorded.

Then:

> **Nearest entities**
> The ten entities closest to this one by the same similarity measure that ranks
> search results.

When the entity has no vector:

> Nearest entities are not available for this entity.

An entity page that does not exist:

> No entity has this address. It may have been removed when the index was
> rebuilt. *[link]* Search instead

## 8. The footer, on every page

> isasearch · Isabelle release 2025-2 · AFP snapshot 2026-05-13 · index built
> «2026-08-20» · [about] · [source]

*(The build date is load-bearing: the absence of a result is this product's main
output, and no one can interpret it without knowing what was indexed. §15.2.)*

## 9. Deliberately unwritten

- **Whether the filters persist between visits.** They do not. Saying so on a
  page that a visitor reads twenty times a day costs a line and helps no one.
- **What the copy control copies.** The expression as printed, in Unicode,
  without the name. The hover in §3.1 is the whole answer.
- **What a locale, a session or a proof method is.** The audience is Isabelle
  users (settled 2026-08-14). What this interface has to explain is this index,
  not the prover.

## 10. Naming choices for the user

- **`[DECIDE 1]` `Collection` → `Named theorems`.** Measured: all 994 records of
  this kind are `named_theorems` declarations — `Approximation.approximation_preproc`,
  `DFS.invar_holds_intros`, `Finiteness.finite`. Not `lemmas` bundles, and not
  attributes such as `simp`. "Named theorems" is Isabelle's own word for exactly
  this, and it is the only label of the three that a reader can act on. Draft 1
  proposed `Theorem collection`; the measurement makes `Named theorems` better.
- **`[DECIDE 2]` `Method` → `Proof method`.** The landing page says "proof
  methods" and the button says "Method"; and "Method" alone reads as a
  programming-language method.
- **`[DECIDE 3]` `Case split` → keep, or rename.** The kind is
  `CASE_SPLIT_RULE`, 10504 records. An Isabelle reader reported that the label
  does not distinguish `option.split`-style split rules from `nat.cases`-style
  case rules, and said they use the two differently. Keeping the label costs
  nothing if a hover says which one it is — but nobody has yet measured which of
  the two is in there. Recommendation: keep the label, measure before writing the
  hover.
- **`[DECIDE 4]` the word `authoritative`, locked by D30.** Two consecutive
  rounds of reader testing named this the single worst line on the site. In
  everyday English "authoritative" means *sounds expert*, so the sentence can be
  read as praising the explanation rather than as ranking the statement above it
  — the exact opposite of its purpose, in the one sentence that guards against
  trusting machine-written text about a formal statement. The proposed
  replacement keeps the meaning and the register: *"It may be imprecise or wrong.
  Where the explanation and the statement disagree, the statement is the correct
  one."* This needs an amendment to D30.

## 11. What the readers changed, and what they did not

Four readers received draft 1 and only draft 1: an Isabelle user, a Lean/Coq
user, an assessment for non-native English readers, and a hostile copy reviewer.
All four returned "not fit to ship". Their material findings:

**Accepted, and fixed above.** The theorem/theory story contradicted itself in
three places at once — the note said that isasearch does not record a theorem's
theory, while the card showed a `.thy` source line and the Entity Name hover
showed the theory inside the name. The `excludes` toggle appeared on every
condition and no sentence anywhere explained it, including in the two empty
states, which both assumed `contains`. The boundary rule lived only on an error
page, never mentioned `-`, and therefore implied that `Analysis` cannot match
`HOL-Analysis.Filter`; it can, and the rule now sits in the always-visible
footer. Whitespace and subscripts were unanswered. `simp` was offered as a named
theorem set and is not one. The Introduction rule hover said "you see both",
which contradicts D38's grouping — the two records collapse into one card with
two labels. The empty-state page promised to name the theorem the visitor meant,
which is impossible in general. `Showing 1–20` had no way back to results 1–20.
Eight further states had no copy at all. And the whole file went through the
non-native reader's list: sentence-initial participles, dropped relative
pronouns, phrasal verbs, "tick", "allowance", "at once", `1.3 million`.

**Rejected.** The Lean/Coq reader could not resolve *locale*, *session*,
*jEdit*, `simp` or `intro` — out of scope by the user's decision of 2026-08-14
that readers who do not know Isabelle are not customers. The same reader asked
for term-structure search: D2, and the page says so. The Isabelle reader asked
that the required query be dropped so that filters can search alone: that is D7,
and their actual need — a half-remembered name — is fully served by an Entity
Name condition, which draft 1 simply never mentioned. §1 now does. The Isabelle
reader also called `Introduction rule` a role rather than an entity, which is
true of Isabelle and not of this index (D38, settled).

**Left standing as design, not copy.** Two readers independently judged that a
Theory Name condition on a theorem will systematically mislead, because 99 % of
theorem statements mention something from `HOL` and a condition naming one
theory returns theorems proved in many others. That is D14, taken on measured
evidence that the alternatives are worse (§7.2). The copy above now labels the
matched theory for what it is and points at Entity Name for the other question,
which is as far as wording can go.
