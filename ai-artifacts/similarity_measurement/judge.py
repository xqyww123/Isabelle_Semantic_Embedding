"""Candidate rule 4: an LLM judge as the comparator instead of embedding distance.

Reuses the client the AoA `Codex-API` driver already uses -- `openai.AsyncOpenAI`
pointed at AOA_CODEX_API_BASE_URL with AOA_CODEX_API_KEY (the local auth2api
proxy in front of the ChatGPT subscription; see
Isa-Mini/IsaMini/AoA/driver_openai_api.py:APIDriver_OpenAICodex). No new API
plumbing: same env vars, same SDK, same Responses endpoint.

Run with `isabelle env python3 judge.py` so the settings variables are present.
Results are appended to judge_phase2.json and re-runs skip what is already there.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "judge_phase2.json")
MODEL = "gpt-5.6-sol"
CONCURRENCY = 4

# Which run pairs to judge, per entity.  Four no-change pairs inside the
# unchanged content, two inside modified content (so the judge is also tested on
# the modified text), and one change pair per modified content, each against a
# different unchanged run so the A-side variation is sampled too.
PAIRS_TO_JUDGE = [
    ("Sim_Measure_A1", "Sim_Measure_A2"),
    ("Sim_Measure_A3", "Sim_Measure_A4"),
    ("Sim_Measure_A2", "Sim_Measure_A5"),
    ("Sim_Measure_A1", "Sim_Measure_A4"),
    ("Sim_Measure_B", "Sim_Measure_B1b"),
    ("Sim_Measure_B2", "Sim_Measure_B2b"),
    ("Sim_Measure_A1", "Sim_Measure_B"),
    ("Sim_Measure_A2", "Sim_Measure_B2"),
    ("Sim_Measure_A3", "Sim_Measure_B3"),
    ("Sim_Measure_A4", "Sim_Measure_B4"),
]

PROMPT = """You compare two English descriptions of the same named entity from an \
Isabelle/HOL theory (a constant, a lemma, a type, or a locale). The two descriptions \
were written independently and may differ in wording.

Decide ONE thing: do the two descriptions describe the SAME mathematical object and \
assert the SAME thing? Wording, level of detail, examples and asides do not matter -- \
only whether the mathematical content is the same. If one description states a \
different value, a different condition, a different formula, a different assumption, \
or a different logical direction from the other, they are NOT the same.

Entity: {label}

Description 1:
{t1}

Description 2:
{t2}

Answer with a single JSON object and nothing else:
{{"same": true or false, "why": "<one sentence>"}}"""


def parse_answer(text: str) -> dict:
    """Pull the JSON object out of the reply.  A model that wrapped it in prose
    or a fence still round-trips; anything else is recorded as unparsable rather
    than guessed at."""
    t = text.strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return {"same": None, "why": "", "raw": t[:400]}
    try:
        obj = json.loads(t[a:b + 1])
    except Exception:
        return {"same": None, "why": "", "raw": t[:400]}
    same = obj.get("same")
    if not isinstance(same, bool):
        return {"same": None, "why": str(obj.get("why", ""))[:400], "raw": t[:400]}
    return {"same": same, "why": str(obj.get("why", ""))[:400]}


async def main() -> None:
    import openai

    with open(os.path.join(HERE, "pairs_phase2.json")) as f:
        data = json.load(f)
    ents = {(e["entity"], e["kind"]): e for e in data["entities"]}
    meta_pairs = {(p["entity"], p["kind"], p["g1"], p["g2"]): p
                  for p in data["pairs"]}

    done, retry = {}, set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            for r in json.load(f)["judgements"]:
                done[(r["entity"], r["kind"], r["g1"], r["g2"])] = r
        # A recorded FAILURE is not a result: keep it in `done` so the output
        # file stays complete, but leave it in the to-do list so a re-run
        # retries it (the 429s below need a slower, longer backoff).
        retry = {k for k, r in done.items() if r.get("same") is None}
        print(f"resuming: {len(done)} judgements already recorded", flush=True)

    todo = []
    for (entity, kind), e in ents.items():
        for g1, g2 in PAIRS_TO_JUDGE:
            k = (entity, kind, g1, g2)
            if k in done and k not in retry:
                continue
            meta = meta_pairs.get(k)
            if meta is None or meta["shared_key"]:
                continue          # not two independent interpretations
            todo.append((k, e, meta))
    print(f"{len(todo)} judgements to make with {MODEL}", flush=True)
    if not todo:
        return

    client = openai.AsyncOpenAI(base_url=os.environ["AOA_CODEX_API_BASE_URL"],
                                api_key=os.environ["AOA_CODEX_API_KEY"])
    sem = asyncio.Semaphore(CONCURRENCY)
    counter = {"n": 0, "in": 0, "out": 0}

    async def one(k, e, meta):
        entity, kind, g1, g2 = k
        prompt = PROMPT.format(label=f"{kind} {entity}",
                               t1=e["runs"][g1]["interpretation"],
                               t2=e["runs"][g2]["interpretation"])
        msg = [{"role": "user",
                "content": [{"type": "input_text", "text": prompt}]}]
        async with sem:
            for attempt in range(8):
                try:
                    r = await client.responses.create(
                        model=MODEL, input=msg, reasoning={"effort": "low"})
                    break
                except Exception as exc:
                    if attempt == 7:
                        return {"entity": entity, "kind": kind, "g1": g1, "g2": g2,
                                "relation": meta["relation"], "class": meta["class"],
                                "grade": meta["grade"], "root": meta["root"],
                                "same": None, "why": "",
                                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                    await asyncio.sleep(5 * (attempt + 1))
        ans = parse_answer(r.output_text or "")
        u = getattr(r, "usage", None)
        if u is not None:
            counter["in"] += getattr(u, "input_tokens", 0) or 0
            counter["out"] += getattr(u, "output_tokens", 0) or 0
        counter["n"] += 1
        if counter["n"] % 50 == 0:
            print(f"  {counter['n']}/{len(todo)}", flush=True)
        return {"entity": entity, "kind": kind, "g1": g1, "g2": g2,
                "relation": meta["relation"], "class": meta["class"],
                "grade": meta["grade"], "root": meta["root"], **ans}

    results = await asyncio.gather(*(one(k, e, m) for k, e, m in todo))
    for r in results:
        done[(r["entity"], r["kind"], r["g1"], r["g2"])] = r
    with open(OUT, "w") as f:
        json.dump({"model": MODEL, "prompt": PROMPT,
                   "tokens": {"input": counter["in"], "output": counter["out"]},
                   "judgements": list(done.values())}, f, ensure_ascii=False)
    bad = sum(1 for r in done.values() if r.get("same") is None)
    print(f"wrote {OUT}: {len(done)} judgements, {bad} unparsable/errored, "
          f"tokens in={counter['in']} out={counter['out']}", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
