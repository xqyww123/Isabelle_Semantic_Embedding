# The judge's bar — fixed 2026-08-14, before any finding was written

Written before the finder round returns, so that the standard cannot be adjusted
to fit whatever arrives. This is the §16.7 method fix: in the 2026-08-13 review
the bar was stated after the findings existed, the defender was told that killing
a true finding is worse than keeping a weak one, and consequently **none of 35
findings was deleted**. That review produced a list, not a decision.

## What a finding must clear to survive

A finding **survives** only if all four hold:

1. **It is about ambiguity, not about diligence.** The specification admits two
   readings, or the prose and the prototype disagree. "An implementer might forget
   to do X" is not a finding when §5, §16.2 or §16.5 already says to do X.
2. **Both readings are defensible from the frozen text.** Not "someone careless
   would write B" — someone competent, reading only §5 + D41 + the emitted assets,
   would have no way to prefer A.
3. **The divergence was demonstrated, not argued.** A concrete input, and both
   outputs, at least one of which was actually run. An unrun claim is dead.
4. **§16.5's test vectors, as currently specified, would not catch it.** If
   §16.2's table or §16.5's synthetic list already pins the case, the gate catches
   it and there is nothing to fix in the specification.

A finding that clears 1–4 is **actionable**: it names a sentence of §5 or D41 to
change, or a case to add to §16.5, before `isabelle_tokenizer.py` is written.

## What does not survive

- Restatements of a divergence §5 already documents and accepts.
- Style, naming, or "the prose could be clearer" without a demonstrated divergence.
- Hazards of the JavaScript port that D41's asset mechanism already removes —
  unless the finding shows the assets as specified in §16.4 are insufficient.
- Anything about §6.3 matching, ranking, or the interface. This review is §5 and
  D41 only.
- Duplicates. Two findings with the same root cause are one finding.

## The defender's deletion quota

The rebuttal round is instructed to delete **at least one third** of the findings
it receives, with a written justification for each deletion naming which of the
four criteria the finding fails. A rebuttal round that deletes nothing is
discarded and re-run — that is the failure the method fix exists to prevent.

If the defender genuinely believes fewer than one third should go, it must say so
explicitly and argue it, naming the quota it was given and why the findings resist
it. That is an acceptable outcome; silently passing everything through is not.
