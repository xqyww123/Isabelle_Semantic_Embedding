# Interface copy — isasearch

Draft 4, 2026-08-19. Every visitor-facing string, in one place, so that the
implementation copies rather than invents.

Drafts 1, 2 and 3 each went to the readers that §13b of the plan established.
Draft 1 was rejected by four of four, draft 2 by three of three, and draft 3 by
four of four. §12 records what each round changed and what was rejected, so that
nothing is re-litigated. **Draft 4 has not yet been read**, and by the standing
rule — the user's approval of this file is conditional on the readers accepting
it — it is not approved until it has been.

Nothing here may be paraphrased when it reaches the markup. Where a string is
locked by a decision, the decision is named beside it. Text in `«guillemets»` is
a substitution slot, never shipped as written.

## 0. The matching rule, stated once

Draft 2 stated this rule four times in three incompatible ways, and both
reviewers independently made it their top finding. It is stated **here**, and
every place in the interface that needs it uses this wording without variation.

isasearch divides a name into **parts**. The dividers are `_`, `.`, the question
mark, and the subscript and superscript marks; a divider is thrown away and can
never be matched itself. Every **other** character that is not a letter or a digit —
a hyphen, a bracket, an operator — is a part on its own and can be matched. A
condition matches when its parts appear **as whole parts, in the order given, with
nothing between them**.

Two consequences of the first two sentences that every screen must respect, because
draft 3 broke both. A condition that consists only of dividers has no parts left and
is rejected. A condition that mixes dividers with other characters is **not**
rejected: it is reduced to the parts that survive, and the search then runs on the
reduction, so `_ + _` searches for `+`. §4.6 is the notice that says so.

Measured consequences, all verified against the corpus on 2026-08-14, and the
worked examples in the interface are drawn from this list:

| Condition | `Path_Connected.path_image_join` | why |
|---|---|---|
| `path` | matches | a whole part |
| `image_join` | matches | two whole parts, adjacent, in order |
| `Path_Connected` | matches | likewise |
| `Connected.path` | matches | the `.` divides, the two parts are adjacent |
| `join_path` | no | right parts, wrong order |
| `Path` vs `path` | different | upper and lower case are distinct |

| Condition | `sorted_wrt` | why |
|---|---|---|
| `sorted` | matches | a whole part |
| `sort` | **no** | only whole parts match, never a fragment of one |
| `orted` | no | likewise |

**`sort` not matching `sorted_wrt` is the fact that draft 2 got wrong.** It said a
condition may be "any part of the name that starts at a boundary", which promises
prefix matching that does not exist. Nothing in the interface may imply it.

## 1. The words this interface uses, and the ones it does not

| Use | Never use | Why |
|---|---|---|
| **panel** — one of the five blocks inside Syntactic filters (D22) | section, group, box | D22 says "panel" |
| **panel heading** — the panel's title | label | "label" is needed for the kind |
| **kind label** — the badge on a card | badge, tag, chip | one word for one thing |
| **condition** — one entry in Entity Name, Expression, Theory Name or All. **A kind selection is not a condition.** | row, filter, term, rule | draft 2 wrote "every condition" of a rule that excludes kinds |
| **search box** — the large input; **condition box** — the input inside a condition | the box, unqualified | draft 1 used "the box" for three inputs |
| **query** — the text in the search box | description, search string, prompt | D40's locked hover says "your query" |
| **search** — the action, and the unit the daily limit counts | query, request, lookup | one action, one word |
| **part** — one unit of matching, per §0 | piece, fragment, token, subtoken | draft 2 used "part" and "piece" for one thing |
| **entity expression**, short form **expression** near the Expression panel | statement, term, formula | §1 of the plan |
| **the associated theories** | related theories, relevant theories | §1 of the plan, verbatim |
| **derived rule** — an Introduction rule, an Elimination rule, an Induction rule or a Case split; **defined at first use, every time** | theorem-alike, theorem-like | draft 2 used two undefined collective terms |
| **select** / **selected** for the Kind buttons | tick, chip | "tick" is British and low-frequency |

Absent by decision: **literally**; **run** as a noun; **allowance**; **resets**;
**authoritative** outside D30's locked first sentence; **carry** in the sense of
*display*; **at once** in the sense of *simultaneously*.

Numbers of four digits or more are grouped with a **non-breaking thin space** —
`1 000`, `8 000`, `1 362 163`. A comma is a decimal point across most of
continental Europe, and draft 2 mixed bare `1000` with spaced `1 300 000`. Digits
throughout, never words: `11 kinds`, not "eleven kinds".

**Nothing in this file is open.** The four labelling choices raised by draft 2
were settled by the user on 2026-08-14; §11 records them.

## 2. The landing page

The whole page is the search box, with the Syntactic filters panel group
collapsed beneath it.

> **isasearch**
>
> Search Isabelle/HOL and the Archive of Formal Proofs by describing what you
> want in English. The index covers theorems, together with the rules that Isabelle
> derives from `datatype`, `inductive` and `function` definitions. It also covers
> constants, types, classes, locales, proof methods and named theorems. In total it
> holds «1 362 163» entities.

The count is a substitution slot, filled by the export and matching the footer's
build date. It is exact, not rounded: measured on `cslh19` on 2026-08-19, the
authoritative store holds 1 343 793 entity records, of which 1 337 025 are
exportable — the difference being the 6 768 `EXPERIENCE` records, which are never
published. A search tool may not be vague about how much it covers, because the
absence of a result is its main output.

Placeholder inside the search box:

> describe what you are looking for

Under the search box, two lines:

> A query is required. It puts the results in order, and only the first «200»
> appear. The syntactic filters are optional: they decide which entities are
> eligible to be ordered at all. The filters do not affect the order.

> **Do you remember only part of a name?** Type the part you remember into the
> search box, and type it into an Entity Name condition as well. A condition keeps
> only those entities whose names contain what you typed, matched as **whole parts**
> — `sorted` finds `sorted_wrt`, but `sort` finds nothing — so type a whole
> underscore-separated or dot-separated piece, and check the capitals.

*(Draft 2 said "Neither one works without the other", which tells a first-time
visitor that a filter is mandatory. It is not: the default state has no
condition and all 11 kinds selected. Both reviewers made this their second
finding.)*

## 3. The Syntactic filters panel group

Collapsed, nothing active:

> **Syntactic filters**

Collapsed, with anything active — the two parts appear independently, so that a
visitor who narrowed only the kinds still sees why the results are narrow:

> **Syntactic filters** · «1 condition» / «3 conditions» · «4 of 11 kinds»

Expanded, five panels in this order (D22): **Entity Name**, **Expression**,
**Theory Name**, **All**, **Kind**.

### 3.1 Panel headings and their hover text

- **Entity Name** — *"The full name of the entity, which begins with the theory
  that declares it: `Path_Connected.path_image_join`. The name has no session
  prefix, so type `Path_Connected`, not `HOL-Analysis.Path_Connected`."* (D39)
- **Expression** — *"The expression that the result card prints: the proposition
  for a theorem or a derived rule, the type for a constant, and the declaration as
  it is written in the source for a type, a class, a locale, a proof method or
  named theorems."*
- **Theory Name** — *"The associated theories, written with their session:
  `HOL-Analysis.Path_Connected`. A constant, a type, a class, a locale, a proof
  method and named theorems each have exactly one such theory. A theorem is
  matched against a different set — see the note below the panel."*
- **All** — *"Matches the condition against Entity Name, Expression and Theory
  Name together. `contains` matches when the text appears in at least one of the
  three; `excludes` matches only when it appears in none of them."* (D22, §6.3 of
  the plan)
- **Kind** — *"If you select several kinds, the search returns entities of any of
  those kinds. Conditions behave in the opposite way: a result must satisfy every
  one of them."* (D38)

### 3.2 The controls inside a panel

The toggle reads **contains** / **excludes** (D22). The control that adds another
condition reads:

> add condition

### 3.3 The line under the All panel, always shown

> This condition matches text in Entity Name, Expression or Theory Name.

### 3.4 The note under Theory Name

**The trigger is the user's, settled 2026-08-19**: the note appears when the Kind
selection includes Theorem or a derived rule **and** the Theory Name panel carries a
condition — not merely when the panel is open. The same two conditions govern it
under the All panel, since an All condition reaches Theory Name and so carries the
same surprise. A note that is always on screen is a note nobody reads; this one
appears exactly when it applies.

> **Theory Name conditions work differently on theorems.** A Theory Name condition
> on a theorem matches every theory that declares a constant appearing in the
> theorem's statement. That is a different question from "where was this theorem
> proved", although the two usually overlap: a theorem matches its own theory when
> its statement uses a constant from it, and matches many others besides. A theorem
> often has several such theories, and sometimes more than twenty.
>
> To search for the theory that proves a theorem, use an **Entity Name** condition
> instead: an entity's name begins with the name of the theory that proves it, up to
> the first dot, so a condition of `Path_Connected` finds theorems proved in
> `Path_Connected`. Write the theory's own name without the session prefix. Such a
> condition also matches any entity whose name mentions `Path_Connected` anywhere
> else.

*(Draft 1 said "isasearch does not record which theory declares a theorem", which
is false about Isabelle and contradicts the source link on the same card. Draft 2
replaced it with "A theorem is identified by its statement, not by the place
where it is written", which the Isabelle reader rejected for the same reason —
that is true of this index, not of Isabelle, and it was doing the work of
justifying a design choice that can simply be stated. Draft 3 states only the
behaviour. §12.)*

### 3.5 The lines at the foot of the panel group, always shown

> **How a condition is matched.** isasearch cuts a name into parts at `_`, `.`, the
> question mark, and the subscript and superscript marks. Those five are separators:
> they are thrown away and cannot be matched. Every other character that is not a
> letter or a digit — an operator or a bracket, such as `+` or `⟦` — is a part on
> its own and can be matched. A condition matches when its parts appear as whole
> parts, in the order you typed them, with nothing between them. So `sorted` matches
> `sorted_wrt` and `image_join` matches `Path_Connected.path_image_join`; `sort`
> matches neither, because isasearch matches only whole parts and never a fragment
> of one. Upper and lower case are different: `Path` and `path` do not match each
> other. Spacing is ignored — `x + y` and `x+y` are the same condition.
>
> **How conditions combine.** A result must satisfy every condition. `excludes`
> reverses one condition: the result must not contain that text. Kind selections are
> not conditions and behave in the opposite way — a result appears if its kind is
> one of the kinds you select.

### 3.6 The Kind buttons

Eleven buttons, all selected by default (D29):

> Theorem · Named theorems · Constant · Type · Class · Locale · Proof method ·
> Introduction rule · Elimination rule · Induction rule · Case split

Hover on **Named theorems**: *"A `named_theorems` declaration, such as
`approximation_preproc`."*
Hover on **Introduction rule**: *"A theorem that is also an introduction rule is a
single entity with both kind labels, shown on one result card. Select only this
button to find the entities that have this label."*
Hover on **Case split**: *"A case rule: one case for each constructor of a
datatype, or for each introduction rule of an inductive definition. A rule whose
name ends in `.split`, such as `option.split`, has the kind Theorem here."*

When no kind is selected. All eleven are selected when the page loads, so this state
is reachable only by clearing them, and the message says so rather than reading as
though the site had started switched off:

> You have cleared every kind, so no result can appear. Select at least one.

## 4. The result cards

### 4.1 The card

Entity name, kind labels, the entity expression in monospace, the similarity, a
copy control, and the English explanation collapsed (D40: no "AI" label on the
collapsed line).

Copy control hover:

> Copy the expression

For two seconds after use:

> Copied

If the copy fails:

> Could not copy. Select the expression and copy it yourself.

Similarity hover — **locked by D40, do not edit**:

> Cosine similarity between your query and this entity, computed with
> Qwen3-Embedding-8B. The result order also accounts for keyword matching, so a
> lower score can appear higher up.

### 4.2 The expanded explanation

The first sentence is **locked by D30**. The second is D30's, amended by the user
on 2026-08-14. The third is required by D40.

> Written by a language model from the formal statement, not by the theory's
> authors. It may be imprecise or wrong. Where the explanation and the statement
> disagree, the statement is the correct one. isasearch searches this text as
> well, so an entity with a poor explanation may rank lower than it deserves.

No explanation:

> No explanation was generated for this entity. Its name and its expression still
> place it in the results, but the search box works best against an explanation, so
> this entity is harder to reach by describing it.

### 4.3 The theory line

A constant, a type, a class, a locale, a proof method and named theorems always
show their one theory. A theorem and a derived rule show no theory line, unless a
condition reaches the Theory Name field — directly, or through the All panel
(D26). Then:

> a constant in this statement comes from HOL-Analysis.Path_Connected

Hover:

> Your condition matched this theory. It is one of the «23» theories that declare
> the constants in this statement. The theory where the theorem was proved is
> usually in that set too, because a statement normally uses constants from its own
> theory — but isasearch does not mark which one it is, so a match here does not
> tell you where the theorem was proved. The entity page lists all «23».

An `excludes` condition never produces this line: nothing was matched.

*(Draft 2 printed "a constant here comes from …", where "here" has no referent on
a card, and its hover claimed a "Theory Name condition" matched, which is false
when the condition sits in All and meaningless when it excludes.)*

### 4.4 The source link

Present on about four cards in five (D42, coverage 80.2 %). The file and line are a
substitution slot like every other run-time value; draft 3 wrote them bare, which
reads as a claim about a real line of a real file and was challenged as such:

> «Path_Connected.thy»:«1204»

Hover:

> The command that produced this entity. Many entities come from a command such
> as `datatype` or `fun` rather than from an explicit declaration, so the line
> number refers to that command.

Absent form, in place of the link, never a dead link and never blank:

> source position not recorded

Hover on the absent form:

> Some commands do not report a position, so isasearch cannot provide a link.

### 4.5 Under the list

> Showing results 1 to 20

Twenty results or fewer, so there is no second page:

> Showing all «7» results

Controls at the foot of the list. The previous control is absent on the first
page; the next control is absent on the last:

> previous 20 · next 20

At the end of the results, **only when the 200-match limit was reached**:

> No more results. isasearch ranks every entity that satisfies your conditions
> and returns the best 200. If what you want is not among them, add a condition
> to narrow the search.

At the end of a list shorter than that:

> These are all the entities that satisfy your conditions. To see more, remove a
> condition or select more kinds.

*(No total. D29 removes the count: the fused result set is truncated at 200, so a
total would be a number the site cannot honestly produce. Draft 2 showed the
200-limit advice unconditionally, telling a visitor looking at 7 results to
narrow the search.)*

### 4.6 A condition matched more loosely than it looks

**New in draft 4, and it covers a state that had no text at all.** A condition
containing separators is not rejected; it is reduced to the parts that survive, and
the search then succeeds against the reduction. The reader's own report of this was
that the site teaches "this will find nothing" while the truth is "this will find
thousands of the wrong things, silently". Shown as a notice directly above the
result list whenever the parts of a condition are fewer than the things the visitor
typed:

> **«Expression `_ + _`» was read as «`+`»**
>
> `_`, `.`, the question mark and the subscript and superscript marks separate the
> parts of a name; they are never matched themselves. The results below are for
> what remains.
>
> *[button]* Edit this condition

If nothing at all remains, §5.6 applies instead — that condition is rejected rather
than reduced.

## 5. Empty states

### 5.1 An Expression condition matched nothing

Generic: shown for whatever the visitor typed, so nothing on it assumes what they
meant. The worked case is separated from their own input by its own heading,
which draft 2 failed to do — it labelled the visitor's own quoted condition "For
example".

> **Nothing contains that text**
>
> An Expression condition matches text, not patterns. It has no variables: `?n`
> searches for the name `n`.
>
> **Your condition**
> «?n + ?m = ?m + ?n»
> isasearch removes the question marks — from your condition and from the text it
> searches — and then looks for «7» parts, one directly after another, in this
> order: «`n` `+` `m` `=` `m` `+` `n`».
>
> **Why this usually happens**
> A condition fixes the variable names, but a statement is displayed with the
> variable names that its own author chose. `?n + ?m = ?m + ?n` finds nothing, even
> though the theorem that it describes is in the index:
> `Groups.ab_semigroup_add_class.add.commute` is printed as `?a + ?b = ?b + ?a`.
> The variable names are the only difference.
>
> **What to do instead**
> Describe the statement in the search box — *addition is commutative* — and use
> an Expression condition only for a name that must appear, such as `sorted_wrt`
> or `continuous_on`.
>
> *[button]* Remove this condition and search again

For an `excludes` condition, the whole page is replaced:

> **Everything that remains contains that text**
>
> **Your condition**
> excludes «⟹»
> Every entity that satisfies your other conditions contains it, so none is left.
>
> **Why this usually happens**
> Operators are common. `⟹` alone appears in «45 %» of all statements, and your
> other conditions have already narrowed the results to a set in which every
> remaining entity uses it.
>
> **What to do instead**
> Exclude a name rather than an operator. Excluding an operator removes a large
> part of the index at once, and it cannot be undone by the search box: the query
> orders results, it cannot remove them.
>
> *[button]* Remove this condition and search again

The reference block beneath, on both variants:

> **What an Expression condition matches**
>
> ✓ Names and operators, as the card displays them: `continuous_on`, `sorted_wrt`,
>   `⟦`
> ✓ Whole parts of a name, in the order you typed them: `sorted` matches
>   `sorted_wrt`; `sort` matches nothing, because only whole parts are matched,
>   never a fragment of one
> ✓ Isabelle's ASCII form, for every symbol that Isabelle displays as a character:
>   `\<Longrightarrow>` is understood as `⟹`. Abbreviations such as `==>` are
>   converted inside the condition box while you type; an abbreviation that has more
>   than one meaning is not converted, so type the `\<…>` form for those. A few
>   markup escapes, such as `\<^named_theorems>`, have no character of their own and
>   are matched exactly as you typed them.
>
> ✗ Patterns of any kind. **These are not rejected — they are reduced**, which is
>   worse, because the search then succeeds and returns the wrong entities:
>   - `_` and `.` are separators, so `_ + _` becomes the single part `+` and
>     matches every statement that contains a plus sign;
>   - `.*` becomes `*` and matches a literal multiplication sign;
>   - `cont*` loses nothing, but it is read as the two parts `cont` `*`, which
>     almost nothing contains: a star is an ordinary character here, not a wildcard.
>   isasearch says so above the results **when a separator was dropped**. When
>   nothing is dropped — as with `cont*` — there is nothing to report and no notice
>   appears, so the absence of a notice does not mean your condition was taken as
>   you meant it.
> ✗ Question marks, `_`, `.` and the subscript and superscript marks are separators
>   and are never matched themselves. A subscripted name such as `f⇩1` is therefore
>   found by `f`, and **not** by `f1`.
>
> To search by the structure of a term, use Isabelle: `find_theorems` and
> `find_consts` search structurally inside a session. The search box here ranks by
> meaning, not by shape, so describing the term will find related statements but
> cannot match a pattern.

### 5.2 The conditions matched nothing between them

Shown when two or more conditions are active. Each appears with its own removal
control, and an `excludes` condition prints as `excludes`.

> **No entity satisfies all of these conditions**
>
> A result must satisfy every condition. These are active:
>
> - Expression contains `sorted_wrt` — *[remove]*
> - Entity Name excludes `List` — *[remove]*
> - Theory Name contains `HOL-Analysis` — *[remove]*
>
> Try removing one. Your query is not the cause: the conditions decide which
> entities are eligible, and none is. The query only puts eligible entities in
> order.

Appended whenever fewer than 11 kinds are selected:

> «4» of the 11 kinds are selected, and that also restricts the results.

### 5.3 One condition matched nothing

Shown when exactly one condition is active and it is not an Expression condition
(an Expression condition gets §5.1, which can explain the pattern mistake).

> **Nothing satisfies this condition**
>
> «Entity Name contains `Path_Connectd`»
>
> A condition matches whole parts of a name, in the order you typed them, and
> upper and lower case are different. Check the spelling and the capitals. If you
> are unsure of the whole name, type **fewer parts** of it — `Path` rather than
> `Path_Connectd`. Typing a shorter piece of one part does not help, because only
> whole parts are matched.
>
> *[button]* Remove this condition and search again

### 5.4 The kind selection alone is the cause

Shown when no condition is active. The removal controls of §5.2 are absent,
because there is nothing to remove.

> No entity of the kinds you selected is eligible. Selecting more kinds returns
> more results; if you select all 11, the kind selection no longer restricts
> anything.

### 5.5 — deleted in draft 4

There is no such state. Two legs each fetch 200 rows and the fused list is truncated
to 200 (plan §6.6); there is no relevance floor anywhere, and D7 rejects an empty
query. So with nothing narrowing, a non-empty index always returns 200 results, and
the screen this section used to hold described a state the system cannot reach. A
genuine backend failure is §6's territory, which already covers it.

### 5.6 A condition with nothing to match

> Nothing in this condition can be matched. `_`, `.`, the question mark and the
> subscript and superscript marks divide a name into parts and are not matched
> themselves, so a condition made only of them has no text remaining. Add a name or an
> operator, or remove the condition.

### 5.7 The search box is empty

> Enter a query. The syntactic filters do nothing but narrow the results; they
> cannot search by themselves.

## 6. While searching, and when it fails

> Searching…

> The search did not finish. Try again. If it continues to fail, the problem is
> with the site and not with your query.

> No connection to the site.

## 7. Limits

Numbers locked by D29 and D35. Both address limits count per network address, and
both messages say so, because a visitor behind a shared address needs to know
that waiting alone may not be enough.

Too many searches within a few seconds (5 per 10 seconds per address):

> Too many searches from your network. Wait a few seconds and try again.

The daily limit is reached (1 000 per address per UTC day). One search is one press
of the search button: turning a page of results costs nothing, because all «200» are
fetched at once (D29), and editing a condition costs nothing until you search again.
The message says so, because a visitor who cannot budget against the limit will
assume the worst:

> Your network has reached the limit of 1 000 searches for today. You can search
> again after 00:00 UTC. Turning a page of results does not count. This limit counts
> every search from an address, so an address shared by many people reaches it
> faster than one used by a single person.

The whole site is above its limit (10 000 per hour):

> isasearch is busy. Try again in a moment.

The query is too long:

> The text in the search box is too long. The limit is 8 000 characters.

One condition is too long:

> This condition is too long. The limit is 512 characters.

## 8. The entity page

The heading is the entity name alone. Under it, the same content as a card,
uncollapsed and full width, and then:

> **Associated theories**

For a constant, a type, a class, a locale, a proof method or named theorems, one
theory. For a theorem or a derived rule, the complete list, untruncated (D26),
under this line:

> These are the theories that declare the constants appearing in this statement.
> About five times in six the theory where the theorem was proved is among them,
> because a statement normally uses constants from its own theory; the rest of the
> time it is absent. isasearch does not mark it either way. Its name is at the start
> of the entity name above, up to the first dot.

Then, when a source position is recorded:

> **Source**
> This entity was produced by the command at Path_Connected.thy:1204.

and when none is recorded:

> **Source**
> No source position was recorded for this entity. Some commands do not report
> one.

Then:

> **Nearest entities**
> The ten entities closest to this one, compared with each other by the same
> measure that compares a query with an entity on the result cards. There is no
> query here, so keyword matching is not used.

When the entity has no vector:

> Nearest entities are not available for this entity.

An entity page that does not exist:

> No entity was found at this web address. The entity may have been removed when the
> index was rebuilt. *[link]* Search instead

## 9. The footer, on every page

> isasearch · built for Isabelle release 2025-2 · AFP snapshot 2026-05-13 · index built
> «2026-08-20» · [about] · [source]

*(The build date is load-bearing: the absence of a result is this product's main
output, and no one can interpret it without knowing what was indexed. §15.2 of
the plan. "version" rather than "release" because `2025-2` sits between two ISO
dates and otherwise reads as February 2025.)*

## 10. Deliberately unwritten

- **Whether the filters persist between visits.** They do not. Saying so on a page
  a visitor reads twenty times a day costs a line and helps no one.
- **What the copy control copies.** The expression as printed, in Unicode, without
  the name. The hover in §4.1 is the whole answer.
- **What a locale, a session or a proof method is.** The audience is Isabelle
  users (settled 2026-08-14). What this interface must explain is this index, not
  the prover.

## 11. The four labelling choices, settled 2026-08-14

- **`Collection` → `Named theorems`.** Measured: all 994 records of this kind are
  `named_theorems` declarations — `Approximation.approximation_preproc`,
  `DFS.invar_holds_intros`, `Finiteness.finite`. Not `lemmas` bundles, and not
  attributes such as `simp`.
- **`Method` → `Proof method`.** The landing page said "proof methods" and the
  button said "Method"; and "Method" alone reads as a programming-language method.
- **`Case split` — kept, hover measured.** Over all 10 504 records of the kind the
  final name segment is `cases` 3 659 times and `exhaust` 2 472, and exactly one
  contains `split`; separately, the 1 602 entities whose name ends in `.split` are
  classified `THEOREM`. The `.cases` records come from `inductive` definitions and
  the `.exhaust` records from datatypes, which is why §3.6's hover names both
  sources and no specific lemma. Draft 2's hover said "such as `list.cases`",
  which the Isabelle reader rejected: after the BNF transition `list.exhaust` is
  the datatype case rule.
- **`authoritative` — D30's second sentence amended.** Two consecutive rounds of
  reader testing named it the worst word on the site: its everyday sense is
  *sounds expert*, which reverses the sentence's purpose in the one place
  guarding against trusting machine-written prose about a formal statement.

## 12. What three rounds of reading changed

**Round 1 — four readers, four rejections.** Five statements were false: that
theorems have no declaring theory; that a condition matches "an adjacent run of
Isabelle tokens" (`sorted_wrt` is one token); that the filter "does not match
inside a name" with an example that refutes it; that conditions are matched
"literally"; and `sledgehammer` offered as a search tool. The empty state was
built on `?P ⟹ ?Q`, which matches 60 entities, and suggested `⟹`, which is in
about 45 % of them. The `excludes` toggle was unexplained; the boundary rule lived
only on an error page; eight states had no copy.

**Round 2 — three readers, three rejections.** The matching rule was stated four
times in three incompatible ways, and the version most visitors would read
promised prefix matching that does not exist — `sort` does not find `sorted_wrt`.
"Neither one works without the other" made the optional filters look mandatory.
"Your query never removes any" contradicted the 200-match limit. Draft 2 invented
a theory, `HOL-Analysis.Filter`, for the one example that teaches the rule; and it
told visitors to search for a theory in Entity Name without saying that entity
names carry no session prefix, so the name they would copy matches nothing. The
`excludes` empty state kept advice written for the opposite case, and the
end-of-list advice told visitors with 7 results to narrow their search.

**Round 3 — four readers, four rejections (draft 3).** The matching rule was still
stated five times, and three of the five dropped the adjacency clause — the same
defect that sank draft 2, moved rather than fixed. "A query cannot narrow the
results" was contradicted by the 200-result cap that the site itself describes; all
four readers found it independently. The three `✗` examples were the worst finding:
`_ + _`, `.*` and `cont*` are not rejected but **reduced** — `_` and `.` are
separators, so `_ + _` searches for `+` and returns thousands of unrelated entities
— so the copy taught the opposite of the real failure mode, and no screen covered
it. §4.6 is new and covers it. "The theory is the first part of the entity name" was
false under this file's own definition of *part*: the first part of
`Path_Connected.path_image_join` is `Path`. The `⟹` explanation refuted itself —
45 % is not "most statements", and removing 45 % is not "removes almost everything".
"Try a shorter part of it" was the one repair the matching rule forbids. §5.5
described a state the system cannot reach and is deleted. The non-native reader
found `left` used in four senses on one page, `and its kind` colliding with this
file's own defined term *kind*, and a garden path in the sentence that teaches the
central lesson of §5.1.

**One reader finding was rejected as wrong.** The Isabelle reader did not believe
`\<^named_theorems>` is a real Isabelle symbol. It is: `etc/symbols` line 466,
`\<^named_theorems>  argument: cartouche`. The sentence stands.

**Rejected across both rounds.** *Locale*, *session*, *jEdit*, `simp` and `intro`
left unexplained — out of scope by the user's decision of 2026-08-14 that readers
who do not know Isabelle are not customers. Term-structure search — D2, and the
interface says so. Dropping the required query so filters can search alone — D7;
the underlying need, a half-remembered name, is served by an Entity Name
condition, which §2 now says. Renaming the `contains` toggle, proposed on the
ground that the word promises substring matching — D22 fixes the control model,
and the rule is now stated where a visitor first meets it, which is the cheaper
of the two fixes.

**Left standing as design, not copy.** Two readers judged that a Theory Name
condition on a theorem will systematically mislead, since 99 % of theorem
statements mention something from `HOL`. That is D14, taken on measured evidence
that both alternatives are worse (§7.2 of the plan). The 200-match limit and the
per-network daily limit were both called out as leaving a user with no move; they
are D29 and D35.

## 13. Why the two name forms differ

§3.1's Entity Name hover tells visitors that an entity name is qualified by the
theory's base name and carries no session prefix — `Path_Connected.path_image_join`
— while the Theory Name panel takes the session-qualified form,
`HOL-Analysis.Path_Connected`. That is not an inconsistency to fix: an Isabelle
fact's long name is theory-qualified, and the theory field holds theory long
names, which are session-qualified. The interface states both, because a visitor
copying a theory off a card into Entity Name would otherwise match nothing.

D39 was first written with `HOL-Analysis.Path_Connected.path_image_join` as its
worked example, which is not a name that exists; it has been corrected in the
plan.
