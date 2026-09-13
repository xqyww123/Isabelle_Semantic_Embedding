# How much time does alpha-normalisation cost?

## The short answer

Alpha-normalisation is cheap. Measured on the real system, over every constant of
`Main`:

* Normalising a term takes roughly **one fifth of the time it takes to hash that
  same term**. Concretely, over all 2,790 defining-axiom propositions of `Main`'s
  constants, `Semantic_Digest.normalize` costs **9.0 ms** while
  `Term_Digest.term128` on the same terms costs **37.2 ms**, and the composite
  `digest_term = term128 o normalize` costs **46.6 ms**. So normalisation is
  **19% of the cost of a digest** and the hashing is the other 81%.
* Inside the whole digest pass — `Semantic_Digest.semantics_of` over all 3,160
  constants of `Main`, which takes about **0.8 s** — normalisation accounts for
  **2.5% to 3.8%** of the total. That pass is dominated by things that have
  nothing to do with normalisation: resolving each constant in the theory,
  looking up its defining axioms, assembling the payload term and walking it for
  dependency edges.
* In absolute terms a single `normalize` call on a typical small proposition
  costs about **0.23 microseconds**. On the largest proposition in all of `Main`
  (3,019 term nodes) it costs **121 microseconds**, against **952 microseconds**
  to hash the same term.

In one sentence: the normalisation step is not a cost worth worrying about — it
is a small constant fraction of a hash that is itself a small fraction of the
digest pass.

## What was measured, and how

`Tools/semantic_digest.ML` defines

```
fun normalize t = #1 (norm_term t (Symtab.empty, 0))
fun digest_term t = Term_Digest.term128 (normalize t)
```

`normalize` is one recursive pass over a term that renames every `Free`, `Var`,
`TFree` and `TVar` by order of first occurrence (threading a `Symtab` and a
counter) and erases `Abs` binder names. It exists because `Term_Digest.term128`
hashes those names, so without normalisation a purely cosmetic rename would make
an entity look changed and buy a needless LLM re-interpretation.

`normalize` is exported through the `SEMANTIC_DIGEST` signature, so it could be
called directly; `digest_term` is not exported, so it was re-composed in the
probe as `Term_Digest.term128 o Semantic_Digest.normalize`, which is its literal
definition.

All timings were taken with `Timing.timing` (which reports wall, CPU and GC time
separately) inside a probe theory loaded through an Isa-REPL server on port 6704
against the `Semantic_Embedding` session heap. The probe theory and its outputs
live outside the repository, in the session scratch directory; nothing in the
repository was modified except this report, and no semantic store was opened.

Every timed loop folds a `Word` checksum derived from the result, so that the
work cannot be discarded. The checksums are printed alongside the times and are
reproduced below; identical checksums across repeated runs are the evidence that
each run really did the same work.

### Machine and environment

* Intel Core Ultra 7 165U, `nproc` = 14 logical CPUs, 62 GB RAM.
* Isabelle2025-2 (`contrib/Isabelle2025-2`), Poly/ML 5.9.2-2, the REPL's ML
  process started with `--gcthreads 8`.
* **Other Isabelle processes were running throughout.** `ss -ltnp | grep poly`
  showed a pre-existing `poly` listening on `127.0.0.1:51209` (pid 269133), and
  `ps -C poly` showed four other `poly` instances that predate this measurement
  (elapsed times of 1,300 s to 90,000 s), one of them holding 2.4 GB RSS at about
  0.9% CPU and another at 3-4% CPU, together with their Scala/Java halves. Load
  average was 0.67 at the start and 0.87 at the end. The machine was therefore
  lightly but *not* exclusively loaded. This matters for one number only — the
  differential measurement of normalisation's share of the full pass (section 2
  below), where the effect being measured is of the same order as the run-to-run
  noise.

## 1. Over all constants of `Main`

The population:

| quantity | value |
| --- | --- |
| constants of `Main` (`Name_Space.get_names` of `Consts.space_of (Sign.consts_of thy)`) | 3,160 |
| of those, constants with at least one own defining axiom | 2,689 |
| propositions collected (`Semantic_Digest.own_defining_axioms env name`, all of them) | 2,790 |
| total `size_of_term` over those propositions | 87,823 |
| mean `size_of_term` per proposition | 31 |

`Semantic_Digest.make_env` on `Main`, timed once on its own: **wall 0.001 s, CPU
0.001 s, GC 0.000 s**. Building the environment is free compared with everything
else here.

Three runs of each of the three variants, all over the same 2,790 propositions:

```
(a) normalize alone over all props:
  normalize run 1: wall=0.009s cpu=0.009s gc=0.000s  [checksum E4B]
  normalize run 2: wall=0.009s cpu=0.009s gc=0.000s  [checksum E4B]
  normalize run 3: wall=0.009s cpu=0.009s gc=0.000s  [checksum E4B]
(b) Term_Digest.term128 alone over the NON-normalised props:
  term128 run 1: wall=0.037s cpu=0.037s gc=0.000s  [checksum 16E15751]
  term128 run 2: wall=0.039s cpu=0.039s gc=0.000s  [checksum 16E15751]
  term128 run 3: wall=0.046s cpu=0.047s gc=0.005s  [checksum 16E15751]
(c) digest_term = term128 o normalize over all props:
  digest_term run 1: wall=0.055s cpu=0.055s gc=0.000s  [checksum 670B9002]
  digest_term run 2: wall=0.052s cpu=0.053s gc=0.005s  [checksum 670B9002]
  digest_term run 3: wall=0.047s cpu=0.047s gc=0.000s  [checksum 670B9002]
```

Wall and CPU time agree to within a millisecond everywhere: this is single-
threaded work with no waiting. GC time is zero or 5 ms.

Derived from the fastest of the three runs in each group (the per-item figures
are computed from the full-precision time, not from the three-decimal string):

| variant | best wall | per proposition | per constant |
| --- | --- | --- | --- |
| (a) `normalize` alone | 9.05 ms | 3.244 us | 2.865 us |
| (b) `term128` alone, non-normalised terms | 37.20 ms | 13.333 us | 11.772 us |
| (c) `digest_term` (both) | 46.57 ms | 16.691 us | 14.736 us |

Reading these three numbers together: (a) + (b) = 46.25 ms against a measured
(c) of 46.57 ms, so the composite costs almost exactly the sum of its parts and
there is no hidden interaction. **Normalisation is 19.4% of `digest_term` and
24.3% of the bare hash.**

## 2. The share of normalisation in the full digest pass

The full pass is `Semantic_Digest.semantics_of env (Universal_Key.Constant name)`
for every one of the 3,160 constants. Note that this calls `normalize` **once per
constant**, on one assembled payload term, not once per proposition — an
instrumented copy of the module counted exactly 3,160 `normalize` calls per pass,
on terms whose `size_of_term` sums to 104,199 (mean 33 nodes per payload).

Timed three times:

```
(2) full Semantic_Digest.semantics_of (Constant n) over all constants of Main:
  semantics_of run 1: wall=0.806s cpu=0.808s gc=0.012s  [checksum 3E73D219]
  semantics_of run 2: wall=0.857s cpu=0.860s gc=0.012s  [checksum 3E73D219]
  semantics_of run 3: wall=0.816s cpu=0.820s gc=0.015s  [checksum 3E73D219]
```

Best wall 0.806 s, i.e. **255.0 us per constant**. Scaling the section-1
measurement of pure `normalize` from 87,823 nodes to the 104,199 nodes the pass
actually normalises gives an expected pure traversal cost of about **10.7 ms, or
1.3% of the pass**.

To measure the share directly rather than by scaling, two further copies of
`Tools/semantic_digest.ML` were loaded into the probe theory by `ML_file` (both
copies live in the scratch directory; the repository file was not touched):

* **B, the control**: byte-identical except that the signature and structure were
  renamed, so that any difference between `ML_file`-compiled code and the
  heap-compiled shipped module would show up as B versus the shipped module
  rather than contaminating the comparison.
* **C, the experiment**: the same copy with the single line
  `fun normalize t = #1 (norm_term t (Symtab.empty, 0))` replaced by
  `fun normalize t = t`.

B reproduced the shipped module's checksum exactly (`3E73D219`), confirming the
control is behaviourally identical; C produced a different checksum
(`604A6A3F`), confirming that normalisation really was disabled and really does
change the digests.

First measurement, three runs of each variant in sequential blocks:

```
best wall: A heap = 771.039 ms, B copy = 772.388 ms, C no-norm = 743.106 ms
normalisation cost inside the full pass (B - C) = 29.282 ms = 3.791% of B
per constant: B 244.427 us, C 235.160 us, difference 9.266 us
```

Because 29 ms out of 770 ms is close to the run-to-run spread, the comparison was
repeated with the two variants interleaved round by round (so that any drift in
background load affects both equally), nine rounds after a discarded warm-up
round. That run happened under slightly heavier background load, which is visible
in the larger absolute times:

```
  round 1: B = 832.755 ms, C = 789.339 ms, B-C =  43.416 ms
  round 2: B = 822.206 ms, C = 830.039 ms, B-C =  -7.833 ms
  round 3: B = 857.489 ms, C = 825.649 ms, B-C =  31.840 ms
  round 4: B = 825.210 ms, C = 809.358 ms, B-C =  15.852 ms
  round 5: B = 858.825 ms, C = 840.409 ms, B-C =  18.416 ms
  round 6: B = 862.379 ms, C = 828.412 ms, B-C =  33.967 ms
  round 7: B = 849.022 ms, C = 816.221 ms, B-C =  32.801 ms
  round 8: B = 814.291 ms, C = 830.211 ms, B-C = -15.920 ms
  round 9: B = 844.850 ms, C = 806.606 ms, B-C =  38.244 ms

B: min 814.291 ms, mean 840.781 ms
C: min 789.339 ms, mean 819.583 ms
min(B) - min(C)   = 24.952 ms  (3.064% of min(B))
mean(B) - mean(C) = 21.198 ms  (2.521% of mean(B))
mean(B-C) per constant: 6.708 us
```

Two of the nine rounds came out negative, which is the honest signal that the
effect (about 25 ms) is only a little larger than the noise (about 40 ms of
spread in each variant's own times on this shared machine). Taking the three
estimates together — 29.3 ms / 3.79% from the blocked run, 25.0 ms / 3.06% from
the interleaved minima, 21.2 ms / 2.52% from the interleaved means — the
defensible statement is: **normalisation accounts for roughly 2.5% to 4% of the
full `semantics_of` pass, that is about 20-30 ms out of some 800 ms.**

That all-in figure is about twice the 1.3% predicted from the pure traversal
cost, and the gap has a straightforward explanation that is worth stating
because it is a real cost: `normalize` allocates a fresh copy of every term it
walks, so the pass with normalisation on does noticeably more allocation and
hence more GC work than the pass with it off. (A second, much smaller effect
pushes the other way: the normalised names `z0`, `'z1` are typically a character
longer than the originals they replace, so variant C's hashing is if anything
marginally cheaper than B's, which would make B-C slightly *understate* the
cost.) Either way, both the pure-traversal estimate and the end-to-end
differential land in the low single-digit percent.

## 3. The worst single case

The largest single proposition among all the defining axioms of `Main`'s
constants belongs to the constant **`Enum.random_aux_finite_5`**, with
`size_of_term = 3019`.

```
  single normalize call: wall=0.000s cpu=0.000s gc=0.000s
  1000 normalize calls: wall=0.121s cpu=0.121s gc=0.000s
      => 121.028 us per call
  1000 term128 calls (non-normalised): wall=0.952s cpu=0.962s gc=0.038s
      => 951.992 us per call
```

A single call is below the resolution of `Timing`'s three-decimal display, hence
the 1,000-iteration loops. Normalising the worst term in `Main` costs **121
microseconds**; hashing the same term costs **952 microseconds**. So in the worst
case normalisation is an even smaller share of the digest than on average —
**11.3% of the 1,073 microseconds the two steps take together** — because the
hasher's per-node work grows faster than the normaliser's on a term this large.

Per term node, this large term normalises at about 40 ns/node, against about
103 ns/node for the 2,790-proposition aggregate in section 1. The difference is
per-call fixed overhead: every call starts a fresh empty `Symtab`, and that cost
is amortised over 3,019 nodes here against 31 nodes in the average case.

## 4. Micro-benchmark: the simps of a small `fun`

The probe theory defines

```
fun h :: "nat ⇒ bool ⇒ nat" where
  "h x True = x"
| "h y False = y"
```

and takes `h.simps` via `Global_Theory.get_thms thy "h.simps"` and
`Thm.prop_of`. That is 2 propositions, each of `size_of_term` 6. Each variant was
run for 10,000 sweeps of both propositions (i.e. 20,000 individual calls), twice:

```
  normalize   x10000 sweeps: wall=0.005s  => 0.456 us per sweep, 0.228 us per prop
  normalize   x10000 sweeps: wall=0.005s  => 0.480 us per sweep, 0.240 us per prop
  term128     x10000 sweeps: wall=0.025s  => 2.455 us per sweep, 1.227 us per prop
  term128     x10000 sweeps: wall=0.024s  => 2.435 us per sweep, 1.218 us per prop
  digest_term x10000 sweeps: wall=0.032s  => 3.178 us per sweep, 1.589 us per prop
  digest_term x10000 sweeps: wall=0.029s  => 2.903 us per sweep, 1.452 us per prop
```

So for a genuinely small `fun` equation: **normalisation costs about 0.23
microseconds per proposition**, hashing about 1.22 microseconds, and the two
together about 1.5 microseconds. Normalisation is about **15% of `digest_term`**
at this size — the same picture as at every other size measured.

## Summary table

| what | time | normalisation's share |
| --- | --- | --- |
| one small `fun` equation (6 nodes) | normalize 0.23 us, term128 1.22 us, digest_term 1.5 us | ~15% of `digest_term` |
| all 2,790 defining-axiom props of `Main` (87,823 nodes) | normalize 9.05 ms, term128 37.2 ms, digest_term 46.6 ms | 19.4% of `digest_term` |
| the largest single prop, `Enum.random_aux_finite_5` (3,019 nodes) | normalize 121 us, term128 952 us | 11.3% of the two combined |
| full `semantics_of` over all 3,160 constants of `Main` | 0.77-0.86 s, i.e. ~255 us per constant | 2.5%-4% of the pass (~20-30 ms) |
| `make_env` on `Main`, once | 0.001 s | n/a |

## Caveats

* The machine was shared with several other, pre-existing Isabelle processes
  throughout. The section-1, section-3 and section-4 numbers are robust to that
  (they are ratios within a single run, and repeated runs agree closely); the
  section-2 differential is not, which is why it is given as a range across three
  estimates rather than a single figure.
* Section 1 measures `normalize` and `term128` over the raw defining-axiom
  propositions. The real pass normalises one assembled payload term per entity
  instead, which is why section 2 reports the payload count (3,160 calls,
  104,199 nodes) separately rather than reusing the section-1 totals.
* Only constants were measured, and only those of `Main`. Types, classes and
  locales go through the same `digest_term`, so the per-term ratios carry over,
  but their per-entity costs were not measured.
