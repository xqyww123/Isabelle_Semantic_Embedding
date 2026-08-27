# DeepSeek interpretation driver — implementation plan, rev 2 (route B)

Status: **APPROVED by the owner, 2026-08-27** (every ruling recorded in §1.1).
Rev 1 was reviewed by a 2-turn adversarial debate (two Opus 5 reviewers,
correctness lens + elegance lens); rev 2 folds in every surviving finding.
§8 records what was rejected so it does not get re-proposed.

This document is written to be executed AFTER a context compaction: it
contains every ruling, every measured fact, and the exact target shape of
every edit. No open design questions remain except the ones §7 explicitly
routes back to the owner.

## 1. Goal

Add a third interpretation-agent backend, `DeepSeek`, that runs the
deformalization agent on **deepseek-v4-pro**: the **unmodified Claude Code
CLI** pointed at DeepSeek's Anthropic-compatible endpoint
(`https://api.deepseek.com/anthropic`) — DeepSeek ships no agent CLI of its
own; this endpoint is its documented route to agentic tooling.  The owner's
hard requirement: the semantic DB must record the data as produced by
`driver="DeepSeek"`, `model="deepseek-v4-pro"`, at DeepSeek prices — never as
a Claude model, never at Claude prices, and never silently otherwise.

Rejected alternatives (owner-ruled, do not reopen): a raw chat-completions
tool-call loop ("route A" — thinner agent environment, second quality
variable); OpenCode as host ("route C" — new medium driver + npm dep).
Route B's thesis: the whole ClaudeCode pipeline (skills, five MCP tools,
hooks, classification) is reused, so **the only variable is the model**.
Several rev-2 decisions below (aux-model pinning, refusal guard) exist to
keep that thesis true.

### 1.1 Owner rulings ledger (all 2026-08-27)

| # | Ruling |
|---|---|
| R1 | Route B approved; dedicated wrapper for provenance is a hard requirement. |
| R2 | Pricing: **static PEAK rates** in the config; recorded dollars are an upper bound (off-peak is half). No time-of-day logic. |
| R3 | Accept the `DeepSeek.V4-pro` / `DeepSeek.V4-flash` shorthand (AoA's vocabulary) via the `canonical_model` hook (§3.3) — relaxes rev 1's "no alias mapping". |
| R4 | Fix AoA's stale DeepSeek price table (`contrib/Isa-Mini`) in passing (§3.5). |
| R5 | The base-class refactor to methods + class-attribute wording + `status_messages` property + keyword cost hook: approved. |
| R6 | Auxiliary models pinned to **`self.model`** (v4-pro), not flash: approved. |
| R7 | Hijack-class env vars: **refuse to start** (FatalAgentError), not scrub: approved. |
| R8 | Context window: **384_000** (AoA's practical cap; real model window is 1M — see F11): approved. If the owner later wants 1M it is a one-line table change. |
| R9 | Base-class sentinels (dual cost log; model-echo mismatch warning): approved. |
| R10 | Fix the pre-existing red test baseline via the stub restructure (§3.6): approved. |
| R11 | **NEVER disable adaptive thinking for DeepSeek without an explicit owner ruling** — if the multi-turn smoke hits thinking-related 400s, STOP and report; do not flip `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING`/`CLAUDE_CODE_DISABLE_THINKING` on your own. |

## 2. Measured facts

F1–F7 were probed 2026-08-27 against the live endpoint (probe scripts:
scratchpad `deepseek_probe/probe_sdk.py`, `probe_opts.py`); F8–F14 come from
the adversarial review (CLI binary 2.1.247 at
`/home/qiyuan/.local/share/claude/versions/2.1.247`, and repo evidence).

- **F1 — model names.** The endpoint accepts the real name `deepseek-v4-pro`
  and echoes it in the response `model` field (SDK: `AssistantMessage.model ==
  "deepseek-v4-pro"`).  No claude-alias needed.
- **F2 — no silent substitution.** A bogus model name is a hard
  `invalid_request_error` naming the three supported models
  (`deepseek-v4-pro`, `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`).
  NB at pipeline level this arrives as HTTP 400 → `PoisonedSessionError` → 8
  recycles → a misleading fatal; `pricing_of` failing first is the real typo
  guard (see §3.2 note on the 400 branch).
- **F3 — the SDK chain works.** claude-agent-sdk 0.2.97 + env overrides ran
  end-to-end: in-process SDK MCP tool called with correct args, PreToolUse
  hook honored, `thinking=adaptive` + `effort="high"` accepted, Bash works.
  NOT covered by F3: skill loading, compaction (must be in the smoke, §5).
- **F4 — the CLI's dollar figure is wrong here.** Probe
  `total_cost_usd=$0.142204` vs ≈$0.0015 at DeepSeek prices (~100x).  The CLI
  prices at Anthropic list prices; the wrapper must reprice from tokens.
- **F5 — usage convention is Anthropic-EXCLUSIVE.** Identical prompt twice:
  first `input=1289, cache_read=0`; second `input=9, cache_read=1280`.
  `input_tokens` EXCLUDES cache reads.  DeepSeek's prefix cache is automatic
  (`cache_control` ignored), reports as `cache_read_input_tokens`;
  `cache_creation_input_tokens` was always 0 (cache writes are just
  miss-priced input on this endpoint).
- **F6 — auth.** `DEEPSEEK_API_KEY` is exported by `secret.sh`.  With the env
  key set the CLI never consults the local login.  Verified: neither
  `secret.sh` nor the ambient env carries any hijack-class var from F10, so
  the §3.2 refusal guard fires on nothing today.
- **F7 — prices** (official page re-read twice on 2026-08-27; per 1M, PEAK):
  v4-pro miss $1.32 / hit $0.044 / out $3.96; v4-flash miss $0.44 / hit
  $0.014 / out $1.32.  Off-peak = half (weekday UTC 01:00–04:00 and
  06:00–10:00 windows are peak per the page).  Owner ruling R2: record peak.
- **F8 — unknown-model window clamp.** The CLI does not recognize
  `deepseek-v4-pro` and clamps auto-compact to a window it ASSUMES ("…is not
  a model this version of Claude Code recognizes, so auto-compact will keep
  this session within N tokens…  set CLAUDE_CODE_MAX_CONTEXT_TOKENS to its
  real window…").  Extracted threshold algorithm: threshold =
  `min(window − round(window·fraction), window − 13000)` where `fraction` is
  a remote-config table lookup (per windowSize, [0,1)); i.e. **at most
  window − 13,000**, possibly lower.  With R8's 384_000 the compaction
  trigger is ≤ 371,000 tokens; the smoke run must log the effective value
  (the SDK's `autocompact_state` event reports `effective_window` and
  `threshold`).
  AMENDED by the smoke run (§9.3): `CLAUDE_CODE_MAX_CONTEXT_TOKENS` only
  DECLARES the window; for an unrecognised model the CLI leaves
  threshold-triggered compaction unenforced.  The enforcement knob is a
  second env var, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which the driver also
  pins.
- **F9 — env merge semantics.** `subprocess_cli.py:430-436` builds
  `{**os.environ, ..., **options.env}`: `ClaudeAgentOptions.env` can ADD or
  OVERRIDE but can NEVER REMOVE an inherited key, and whether the CLI treats
  `""` as unset is unverified.  Hence R7's refuse-not-scrub.
- **F10 — the CLI's routing/credential/model env surface** (all names
  verified present in the binary):
  hijack-class (no valid DeepSeek value → refuse): `ANTHROPIC_AUTH_TOKEN`,
  `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_CUSTOM_HEADERS`,
  `ANTHROPIC_UNIX_SOCKET`, `CLAUDE_CODE_USE_BEDROCK`,
  `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`,
  `CLAUDE_CODE_USE_GATEWAY`, `CLAUDE_CODE_USE_MANTLE`,
  `CLAUDE_CODE_API_BASE_URL`;
  model-selection (valid value exists → pin): `ANTHROPIC_MODEL`,
  `ANTHROPIC_SMALL_FAST_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`,
  `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`,
  `ANTHROPIC_DEFAULT_FABLE_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`,
  `CLAUDE_CODE_BG_CLASSIFIER_MODEL`, `CLAUDE_CONTEXT_COLLAPSE_MODEL`,
  `CLAUDE_CODE_AUTO_MODE_MODEL`.
  Whether every aux path fires in headless SDK use is UNMEASURED — pinning is
  cheap defense, not a probed fact; do not claim otherwise in comments.
- **F11 — context length.** Official page: **1M context for both v4-pro and
  v4-flash** (it lists 384K as maximum OUTPUT).  384_000 as our window value
  is AoA's practical cap (`driver_openai_api.py` ≈:1283: "V4 flash & pro both
  support up to 1M; 384K is a practical default"), adopted by ruling R8.
- **F12 — thinking + tool calls.** AoA's OpenAI-endpoint note warns DeepSeek
  V4 thinking 400s on multi-turn tool calls unless CoT is re-sent.  On THIS
  endpoint the Anthropic protocol itself re-sends thinking blocks with tool
  results, and both probes already exercised tool_use → tool result →
  continuation successfully with adaptive thinking on.  Risk downgraded to
  "confirm with a longer multi-tool smoke"; if it does bite, R11 applies
  (stop and ask — never disable thinking unilaterally).
- **F13 — dev machine config.** `~/.isabelle/Isabelle2025-2/etc/interpretation_config`
  exists (2026-07-27), has only gpt-* entries; the template only seeds
  MISSING files, and `User_Config.load` caches per process.  Smoke pre-flight
  must append the deepseek blocks there; any long-lived RPC host must be
  restarted to see them.
- **F14 — AoA's price table is stale.** `contrib/Isa-Mini/IsaMini/AoA/
  language_model_driver.py` (read 2026-06-06) prices v4-pro at 0.435/0.87
  per-M with hit = miss/120, and its comment argues those numbers are
  current.  Off by 3.0x input / 4.6x output / 12.1x cache-hit vs F7.
  Ruling R4: fix in passing (§3.5).
- **F15 — test baseline (measured 2026-08-27).**
  `pytest test_interpretation_error_classifier.py test_interpretation_driver.py`
  → **7 failed, 23 passed**.  All 7 failures are in the classifier file,
  pre-existing (`_StubTask` lacks `.model`, which `_handle_message` reads on
  every AssistantMessage).  Green target after §3.6: **0 failed, 30+ passed**
  (new DeepSeek tests add to the count).

## 3. Design (rev 2)

Files touched, all under `contrib/Semantic_Embedding` except §3.5:
`Isabelle_Semantic_Embedding/interpretation_driver/claude_code.py` (§3.1),
new `.../interpretation_driver/deep_seek.py` (§3.2),
`.../interpretation_driver/__init__.py` + `.../semantic_interpretation.py`
(§3.3), `.../interpretation_config_template.yaml` + `.../interpretation_driver/config.py`
+ `README.md` (§3.4), `contrib/Isa-Mini/IsaMini/AoA/language_model_driver.py`
(§3.5), `test_interpretation_error_classifier.py` +
`test_interpretation_driver.py` + new `test_deepseek_driver.py` (§3.6).

### 3.1 `claude_code.py`: the classifier becomes methods; wording and cost become extension points

ClaudeCode behavior must stay observably identical (the §3.6 passthrough test
pins it).  Changes:

1. **Methods, not driver-first functions** (ruling R5; the codex.py
   convention: pure → module function, driver-dependent → method).
   `_handle_message(self, message)`, `_raise_for_agent_error(self, err,
   result_msg, model_text="")` and the usage/cost recorder move into
   `ClaudeCodeDriver`; the cost recorder is renamed **`_record_turn_cost`**
   (codex.py's existing name for the same concept — do NOT keep the name
   `_accumulate_usage`, which collides with the module-level
   `accumulate_usage` it calls).  `run_turn` calls
   `self._handle_message(message)`.  Stay module-level (pure):
   `_log_message`, `_model_error_text`, `_deny`, `_permission_control`,
   `_TOOL_WHITELIST`.
2. **Wording as class attributes.**  The three `_MSG_*` module constants move
   into the class as `MSG_AUTH_FAILED`, `MSG_BILLING`, `MSG_INVALID_REQUEST`
   (strings unchanged; their explanatory comments move with them; plain
   comments, not `#:` — rejected in review).  Add to the class docstring:
   "SUBCLASSED by deep_seek.py, which points the same CLI at another vendor's
   Anthropic-compatible endpoint.  Anything added here that is true only of
   Anthropic's own API must become one of the extension points below."
3. **`status_messages` — a PROPERTY, never a class-body dict** (a class-body
   dict literal would freeze THIS class's strings at definition time, so a
   subclass overriding `MSG_AUTH_FAILED` would silently keep the base
   wording on the inference path while the enum path — the tested one — looks
   right):

   ```python
   @property
   def status_messages(self) -> dict[int, str]:
       """HTTP statuses this backend can NAME on the inference path (no SDK
       error enum: we are reading the api_retry trail and the terminal
       ResultMessage).  A status absent here falls into the loud
       unrecognised bucket, deliberately.  A property, not a class-body
       dict: a dict literal would freeze the base wording and defeat a
       subclass's MSG_* override."""
       return {401: self.MSG_AUTH_FAILED}
   ```

   In `_raise_for_agent_error`, the current line
   `if status == 401 or 401 in statuses or "authentication_failed" in kinds:
   fatal(_MSG_AUTH_FAILED)` becomes: look up
   `{status} | statuses` in `self.status_messages` (first hit wins →
   `fatal(...)`); the `"authentication_failed" in kinds` check stays as-is
   (kind strings are SDK vocabulary, not vendor statuses — no second table).
   The lookup runs BEFORE nothing it doesn't already; ClaudeCode's table has
   exactly the 401 entry, so behavior is unchanged.  Also annotate the
   400 → PoisonedSessionError branch in `_handle_message`: "a backend where
   400 can also mean 'malformed request, not poisoned transcript' would need
   a discriminator here; none is known for DeepSeek yet — the smoke decides"
   (review finding; no code change beyond the comment).
4. **The cost hook — keyword currency** (the SDK usage-dict keys stay in
   exactly one place, `_record_turn_cost`):

   ```python
   def _turn_cost_usd(self, *, input_tokens: int, cache_creation_tokens: int,
                      cache_read_tokens: int, output_tokens: int,
                      reported_usd: float) -> float:
       """Dollars for one turn.  The CLI's own figure is correct for the
       Anthropic API it was built for; a subclass that redirects the CLI to
       another vendor's endpoint must reprice the tokens itself (the CLI
       would price them at Anthropic list prices)."""
       return reported_usd
   ```

   `_record_turn_cost` destructures `message.usage` once (as today), computes
   `cost = self._turn_cost_usd(input_tokens=d_in, cache_creation_tokens=d_cw,
   cache_read_tokens=d_cr, output_tokens=d_out,
   reported_usd=message.total_cost_usd or 0.0)`, and (ruling R9, sentinel a)
   logs BOTH figures — the collapse of the ~100x gap toward 1x is the alarm
   that traffic reached Anthropic:

   ```python
   _log.info("turn usage: %s, cost: $%.6f (CLI reported $%.6f)",
             message.usage, cost, message.total_cost_usd or 0.0)
   ```

   ("turn", not "round" — terminology consistency with run_turn/codex.py.)
5. **Model-echo assertion** (ruling R9, sentinel b; base class, vendor-
   agnostic).  The backfill branch in `_handle_message` becomes:

   ```python
   if isinstance(message.model, str) and message.model:
       if not self.task.model:
           self.task.model = message.model          # CLI chose it; record it
       elif message.model != self.task.model and not self._model_mismatch_warned:
           self._model_mismatch_warned = True       # once per session
           _log.warning("the endpoint answered with model %r, not the "
                        "configured %r -- check ANTHROPIC_BASE_URL and the "
                        "ambient environment", message.model, self.task.model)
   ```

   WARN only, never raise (a dated slug or aux-model echo must not kill a
   cone).  `self._model_mismatch_warned = False` in `__init__`.
   On the ClaudeCode path `task.model` starts empty → first branch runs
   exactly as today.

### 3.2 New `interpretation_driver/deep_seek.py`

(`"DeepSeek"` → module basename `deep_seek` under the existing rule.)
Complete target shape — module docstring should carry F1/F4/F5/F8's essence
and the probe date:

```python
_BASE_URL = "https://api.deepseek.com/anthropic"
# Deliberately NOT honoring $DEEPSEEK_BASE_URL: in this repo that variable
# already means AoA's OpenAI-compatible endpoint (/beta), which speaks a
# different protocol.  One name may not mean two incompatible endpoints.

#: env vars that would redirect the CLI's traffic or credentials past
#: ANTHROPIC_BASE_URL.  options.env can override but never REMOVE an
#: inherited variable, and ""-means-unset is unverified -- so a set one is
#: refused, not scrubbed (the failure it prevents: Claude traffic recorded
#: as driver="DeepSeek" at DeepSeek prices, silently).
_HIJACK_ENV = (
    "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_UNIX_SOCKET",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_GATEWAY",
    "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_API_BASE_URL",
)

@register_interpretation_driver("DeepSeek")
class DeepSeekDriver(ClaudeCodeDriver):
    DEFAULT_MODEL = "deepseek-v4-pro"

    #: real windows for models the CLI does not recognize (it would otherwise
    #: clamp auto-compact to a GUESSED window -- systematic premature
    #: compaction).  The models serve 1M; 384K is the practical cap AoA
    #: settled on (driver_openai_api.py), owner-ruled here (R8).
    CONTEXT_WINDOW = {"deepseek-v4-pro": 384_000,
                      "deepseek-v4-flash": 384_000,
                      "deepseek-v4-flash-vision-exp": 384_000}

    MSG_AUTH_FAILED = (
        "Semantic interpretation failed: DeepSeek rejected the API key. "
        "Check DEEPSEEK_API_KEY in the environment, then retry.")
    MSG_BILLING = (
        "Semantic interpretation failed: the DeepSeek account has a billing "
        "problem (out of balance?). Top it up, then retry.")
    MSG_INVALID_REQUEST = (
        "Semantic interpretation failed: DeepSeek rejected the request as "
        "invalid. Most often this is the model name in the driver spec -- "
        "DeepSeek serves deepseek-v4-pro, deepseek-v4-flash and "
        "deepseek-v4-flash-vision-exp. If the model name is right, this is "
        "a bug - please report it with the RPC host log.")

    @property
    def status_messages(self):
        # 402 (out of balance) is DeepSeek's most likely operational failure;
        # whether the adapter actually surfaces it as a status is unverified
        # -- if it does not, the unrecognised bucket still catches it loudly.
        return {**super().status_messages, 402: self.MSG_BILLING}

    @classmethod
    def canonical_model(cls, model: str) -> str:
        # AoA's documented shorthand for the same driver name
        # (driver_openai_api.py): DeepSeek.V4-pro / DeepSeek.V4-flash.
        # Normalised HERE -- before the task exists -- so task.model, the
        # priced name and the name on the wire are one string (§3.3).
        arg = (model or "v4-pro").strip().lower()
        return f"deepseek-{arg}" if arg in ("v4-pro", "v4-flash") else arg

    def __init__(self, **kw):
        super().__init__(**kw)
        self._api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self._api_key:
            raise FatalAgentError(
                "Semantic interpretation failed: DEEPSEEK_API_KEY is not set "
                "in the environment, so the DeepSeek backend cannot "
                "authenticate. Export it, then retry.")
        hijacked = [v for v in _HIJACK_ENV if os.environ.get(v)]
        if hijacked:
            raise FatalAgentError(
                "Semantic interpretation failed: the environment sets "
                f"{', '.join(hijacked)}, which would redirect the Claude Code "
                "CLI's traffic or credentials away from DeepSeek while the "
                "database still records DeepSeek provenance. Unset them for "
                "this process, then retry.")
        # Both resolved before anything is spent, as the configuration errors
        # they are (the codex.py precedent for pricing).
        try:
            self._pricing = pricing_of(self.model)
        except MissingPricing as e:
            raise FatalAgentError(str(e)) from e
        window = self.CONTEXT_WINDOW.get(self.model)
        if window is None:
            raise FatalAgentError(
                f"Semantic interpretation failed: no context window is "
                f"curated for model {self.model!r} (deep_seek.py "
                f"CONTEXT_WINDOW). Add it, then retry.")
        self._context_window = window

    def _options(self):
        opts = super()._options()
        opts.env.update({
            "ANTHROPIC_BASE_URL": _BASE_URL,
            "ANTHROPIC_API_KEY": self._api_key,
            # --model pins only the MAIN loop.  Every other model the CLI may
            # reach for is pinned to the SAME model (owner ruling R6): the
            # CLI's built-in fallbacks are Claude names this endpoint
            # hard-rejects (F2), and a weaker model writing the compaction
            # summary would be a second quality variable.  Whether each aux
            # path fires headless is unmeasured (F10) -- pinning makes the
            # answer not matter.
            "ANTHROPIC_MODEL": self.model,
            "ANTHROPIC_SMALL_FAST_MODEL": self.model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": self.model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": self.model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": self.model,
            "ANTHROPIC_DEFAULT_FABLE_MODEL": self.model,
            "CLAUDE_CODE_SUBAGENT_MODEL": self.model,
            "CLAUDE_CODE_BG_CLASSIFIER_MODEL": self.model,
            "CLAUDE_CONTEXT_COLLAPSE_MODEL": self.model,
            "CLAUDE_CODE_AUTO_MODE_MODEL": self.model,
            # The CLI does not recognise this model and would clamp
            # auto-compact to a window it ASSUMES; this variable is its own
            # documented remedy (F8).  Trigger lands at <= window - 13000.
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(self._context_window),
        })
        return opts

    def _turn_cost_usd(self, *, input_tokens, cache_creation_tokens,
                       cache_read_tokens, output_tokens, reported_usd):
        # reported_usd is the CLI's Anthropic-priced figure -- ignored
        # (measured ~100x too high, F4).  Pricing.cost wants the INCLUSIVE
        # input count; this endpoint's input_tokens EXCLUDES cache reads
        # (F5), and a cache write here is just miss-priced input, so both
        # join the sum.
        return self._pricing.cost(
            input_tokens=input_tokens + cache_creation_tokens + cache_read_tokens,
            cached_input_tokens=cache_read_tokens,
            output_tokens=output_tokens)
```

Inherited unchanged, deliberately: `REPORTS_CONTEXT_RESET = True` (PreCompact
is CLI-local; smoke must confirm it fires, §5), tool whitelist, permission
hook, `AGENT_DIR` cwd, MCP server, `MAX_MCP_OUTPUT_TOKENS` (the env update
must not clobber it — pinned by a §3.6 test).  There is NO
`self.task.model = ...` line anywhere (rev 1's was dead code with a false
comment; under `canonical_model` it would actively mask a provenance bug).

### 3.3 `canonical_model`: normalize before the task exists

The one edit outside the driver package (owner ruling R3).  Rationale: a
`__init__`-time alias map would leave `task.model = "V4-pro"` in the DB while
the API serves `deepseek-v4-pro` — the task's model is fixed BEFORE the
driver is constructed (`interpret_file` → `InterpretationTask(...)` →
`_run_agent` → `make_driver()`), and the `_handle_message` backfill is
guarded on `not task.model`, so nothing would repair it.

1. `interpretation_driver/__init__.py`, on the ABC:

   ```python
   @classmethod
   def canonical_model(cls, model: str) -> str:
       """The model name to run AND to record.  Normalising here -- before
       the task is built -- is what keeps task.model, the priced name and
       the name sent to the API one string.  The base rule is just the
       default; a driver with user-facing shorthands overrides it."""
       return model or cls.DEFAULT_MODEL
   ```

2. `semantic_interpretation.py` (interpret_file's resolution, currently
   `model = model or driver_cls.DEFAULT_MODEL` at ≈:1111):

   ```python
   model = driver_cls.canonical_model(model)
   ```

Side benefits: `pricing_of` sees the canonical name; the user-facing report
names the real model; `DEFAULT_MODEL` stops being expressed twice.

### 3.4 Price table + falsified docs

**`interpretation_config_template.yaml`** — append under `models:`, with its
own "what the recorded dollars mean" block (mirroring the Codex one):

```yaml
  # ---------------------------------------------------------------------
  # WHAT THE RECORDED DOLLARS MEAN FOR DEEPSEEK (the "DeepSeek" driver: the
  # Claude Code CLI on DeepSeek's Anthropic-compatible endpoint).  These are
  # the PEAK list rates, read 2026-08-27 from
  # https://api-docs.deepseek.com/quick_start/pricing -- DeepSeek halves
  # them in off-peak windows, so the recorded dollars are an UPPER BOUND of
  # the bill (owner ruling: static peak, no time-of-day logic).  The CLI's
  # own dollar figure is ignored for this backend (it prices at Anthropic
  # rates, measured ~100x too high).  AoA keeps an independent DeepSeek
  # price table: contrib/Isa-Mini/IsaMini/AoA/language_model_driver.py --
  # update both when prices move.
  # deepseek-v4-flash-vision-exp is deliberately absent: unpriced here
  # until someone needs it, so a run on it fails loudly instead of free.
  deepseek-v4-pro:
    pricing:
      input: 1.32e-6         # $1.32 / 1M (cache miss, peak)
      cached_input: 4.4e-8   # $0.044 / 1M (cache hit, peak)
      output: 3.96e-6        # $3.96 / 1M (peak)
  deepseek-v4-flash:
    pricing:
      input: 4.4e-7          # $0.44 / 1M (cache miss, peak)
      cached_input: 1.4e-8   # $0.014 / 1M (cache hit, peak)
      output: 1.32e-6        # $1.32 / 1M (peak)
```

**Falsified/stale docs to fix in the same commit:**
- `config.py` module docstring ("A backend that reports its own dollar cost
  (Claude Code does) never comes here") → "A backend whose reported dollars
  are correct for the endpoint it actually talked to needs no entry here;
  the Claude Code CLI's figure is correct only against Anthropic's own API."
- Template header's same sentence (≈line 7-8): same reword.
- `README.md:63` ("`ClaudeCode` is currently the only backend; a Codex-based
  one is under development" — already false re Codex): reword to name the
  three backends and the `interpretation_driver` spec syntax
  (`ClaudeCode`, `Codex[.model]`, `DeepSeek[.model|.V4-pro|.V4-flash]`).

### 3.5 AoA's stale price table (`contrib/Isa-Mini`, owner ruling R4)

In `contrib/Isa-Mini/IsaMini/AoA/language_model_driver.py` (≈:85-100): read
the section first; then (a) replace the three `deepseek-v4-pro` numbers with
F7's peak rates and the `deepseek-v4-flash` row likewise (keep that table's
own key names, e.g. `cached`); (b) REWRITE the comment — it currently asserts
currency ("official … fetched 2026-06-06" + a paragraph rejecting a competing
figure) and must not survive pointing at dead numbers.  New comment: read
2026-08-27, peak rates, off-peak = half, plus a pointer to
`contrib/Semantic_Embedding/.../interpretation_config_template.yaml` as the
sibling table.  Separate commit in the Isa-Mini submodule (another
workstream's tree — touch ONLY this table + comment).  Check whether AoA's
cost math expects the same per-token units (it does — `0.435e-6` style).

### 3.6 Tests

**Baseline (F15): 7 failed / 23 passed.  Target: 0 failed.**

1. `test_interpretation_error_classifier.py` — restructure `_StubTask` to
   SUBCLASS the real `InterpretationTask`, the way
   `test_interpretation_driver.py`'s `_RecordingTask` already does
   (constructing with `connection=None` is safe: `__init__` only stores it;
   `__enter__`/`__exit__` are no-ops).  Override `write_cost` to count
   flushes.  This fixes the 7 pre-existing failures structurally (ruling
   R10): no future `InterpretationTask` field can silently red the suite
   again.  Delete the stub's false justifying docstring.  All
   `_handle_message(task, msg)` call sites become
   `_driver(task)._handle_message(msg)` with

   ```python
   def _driver(task):
       return ClaudeCodeDriver(model="m", system_prompt="s", tools=[],
                               task=task, on_context_reset=lambda: None)
   ```

2. Same file — add the passthrough assertion that pins "ClaudeCode is
   bit-for-bit unchanged": a successful `ResultMessage(total_cost_usd=0.1,
   usage={...})` through a real driver leaves `task.total_cost_usd == 0.1`,
   the four token counters matching, `cost_writes == 1`.
3. `test_interpretation_driver.py` ≈:341 — the backfill test: wrap in the
   same `_driver(...)`; add the mismatch-warning case (model set +
   different echo → one warning, not an exception, and warned only once).
4. New `test_deepseek_driver.py` (monkeypatch `deep_seek.pricing_of`; no
   network):
   - canonical_model: `""` → `deepseek-v4-pro`; `"V4-pro"`/`"v4-flash"` →
     canonical names; unknown strings pass through untouched;
   - missing `DEEPSEEK_API_KEY` → FatalAgentError naming the variable
     (monkeypatch.delenv — secret.sh exports it in dev shells);
   - refusal guard: setting e.g. `ANTHROPIC_AUTH_TOKEN` →
     FatalAgentError naming it;
   - `_options().env`: carries base URL + key + all ten model pins to
     `self.model` + `CLAUDE_CODE_MAX_CONTEXT_TOKENS == "384000"`, AND the
     inherited `MAX_MCP_OUTPUT_TOKENS` survives;
   - cost: F5's probe shape (`input=9, cache_read=1280, out=16`) →
     `9·miss + 1280·hit + 16·out`, and `reported_usd=0.142204` does not
     leak through;
   - `MissingPricing` at construction surfaces as FatalAgentError;
   - uncurated model (in pricing, absent from CONTEXT_WINDOW) →
     FatalAgentError naming CONTEXT_WINDOW;
   - `status_messages` includes 402 with the DeepSeek billing wording and
     401 with the DeepSeek auth wording (the property-not-dict trap test).

### 3.7 What is deliberately NOT in scope

- No prompt/skill/tool-name/batching/retry changes.
- No time-of-day pricing (R2).
- No `DEEPSEEK_BASE_URL` support (name collision with AoA's OpenAI-endpoint
  semantics — rejected in review).
- No claude-alias mapping (F1 made it dead).
- No disabling of adaptive thinking, ever, without an owner ruling (R11).
- No change to `_run_agent`'s unbounded recursive RateLimitError retry
  (`semantic_interpretation.py` ≈:809-810) — real pre-existing defect,
  recorded as a SEPARATE item for the owner, not this plan's.
- No switch of any running collection (the D16 backfill) to DeepSeek —
  separate decision after a quality comparison the owner has not yet
  commissioned.

## 4. Execution order (post-compact checklist)

1. §3.1 claude_code.py refactor (+ §3.3's two small edits).
2. §3.2 deep_seek.py.
3. §3.4 template + config.py + README.
4. §3.6 tests; run
   `pytest test_interpretation_error_classifier.py test_interpretation_driver.py test_deepseek_driver.py -q`
   → expect 0 failed.  Then the FULL Semantic_Embedding suite; compare
   against the session's known pre-existing-failure set before blaming new
   code.
5. §3.5 AoA table (separate Isa-Mini commit).
6. Dev-machine pre-flight (F13): append the two deepseek blocks to
   `~/.isabelle/Isabelle2025-2/etc/interpretation_config`.
7. Live smoke (§5).  Fix what it finds (within this plan's rulings; R11
   gates the thinking knob).
8. Report results to the owner; commits in the two submodules + superproject
   bump; push ONLY when the owner says so (origin only).  phi-system stays
   unpushed (standing ruling).

## 5. Live smoke checklist (before sign-off; spend is sanctioned, keep it small)

Driven through the real `DeepSeekDriver` (stub task + probe MCP tools is
fine for a/b/c; d needs the real pipeline or a long scripted turn):

a. **Multi-turn multi-tool run** (≥3 tool calls with continuations): confirms
   F12 at depth — thinking + tool-call turns do not 400.  If they DO:
   STOP, report to the owner (R11).
b. **One Skill invocation** (never probed — F3 gap).
c. **Refusal guard**: with a dummy `ANTHROPIC_AUTH_TOKEN` planted, the driver
   refuses with the right message (then unset it).
d. **A compaction crossing**: drive past the threshold; assert
   `on_context_reset` fired ≥ once (else flip `REPORTS_CONTEXT_RESET` to
   False for this driver — the safe polarity) and record the CLI's effective
   window/threshold numbers (expect ≤ 371,000 for the 384_000 window).
e. Verify the dual cost log shows the ~100x gap, and provenance
   (`b"driver"`, `b"model"`) in the written records says
   `DeepSeek` / `deepseek-v4-pro`.

## 6. Review record (2-turn adversarial debate, two Opus 5 reviewers, 2026-08-27)

Surviving findings are all folded into §3 above.  Signature discoveries:
correctness reviewer — unknown-model window clamp (F8), env merge semantics
(F9), thinking/tool-call 400 risk (F12, downgraded by probe evidence), the
already-red baseline (F15), the provenance-corrupting alias-map variant
(fixed as §3.3); elegance reviewer — methods-not-driver-first-functions,
status_messages-as-property trap, keyword cost hook, AoA vocabulary gap,
AoA stale prices (F14), stub-subclassing (§3.6.1).

## 7. Open items routed to the owner (not blocking implementation)

- If smoke step (a) 400s: thinking-knob decision (R11).
- If smoke step (d) shows compaction/PreCompact broken on this endpoint:
  REPORTS_CONTEXT_RESET flip is pre-authorized (safe polarity), but report it.
- The `_run_agent` rate-limit retry defect (§3.7) — separate fix, needs its
  own approval.
- Whether DeepSeek takes over any collection work (quality pilot first).

## 8. Rejected in review (do not re-propose)

- Shared `pricing_or_fatal` helper in config.py — creates the import cycle
  the driver package's `__init__` exists to prevent; 4-line duplication is
  cheaper.  (The deep_seek.py block must reference codex.py's twin in a
  comment for discoverability.)
- `#:` Sphinx doc-comments on MSG_* — convention creep.
- Honoring `DEEPSEEK_BASE_URL` — same name, incompatible endpoint semantics
  vs AoA.
- Raising (not warning) on model-echo mismatch — cosmetic slug differences
  would kill cones.
- Pinning aux models to v4-flash — second quality variable (R6 went to
  self.model).
- `STATUS_MESSAGES` as a class-body dict — freezes base wording (→ property).
- Time-of-day pricing (R2), route A, route C (owner-ruled earlier).

## 9. Execution record (2026-08-27, post-compaction session)

Executed §4 in order; every step done.  Deviations and findings:

1. **§3.1/§3.2/§3.3/§3.4 landed as written.**  Tests: baseline 7 failed /
   23 passed → **41 passed, 0 failed** across the three driver test files.
   Full suite: 3 failed + 3 errors, all pre-existing and off this plan's
   footprint (async-plugin config in `test_config_resolution.py`, the
   network-dependent `test_fireworks_qwen`, and the REPL-dependent callback
   tests).
2. **§3.5 (AoA table)** replaced with F7's peak rates + rewritten comment +
   cross-pointer; §3.4's template block points back at it.
3. **Smoke (§5) — all five items pass**, with one discovery:
   - (a) multi-turn multi-tool (Bash → MCP query → Bash → Skill → reply),
     adaptive thinking on: no thinking-related 400s (F12 confirmed at depth;
     R11 gate never engaged).
   - (b) Skill loading works (the agent read `isabelle-datatype` and quoted
     its first heading).
   - (c) refusal guard fires on a planted `ANTHROPIC_AUTH_TOKEN`, naming it.
   - (d) **the discovery**: with only `CLAUDE_CODE_MAX_CONTEXT_TOKENS` set,
     8 turns grew far past a 30_000 test window and compaction NEVER fired —
     the CLI treats the declared window of an unrecognised model as
     unenforced ("this session can grow past it. To enforce it, set
     CLAUDE_CODE_AUTO_COMPACT_WINDOW=…" — its own notice text; the
     `autocompact_state` schema likewise carries an `enforced` flag that is
     False when the CLI defers to the API's prompt-too-long).  With
     `CLAUDE_CODE_AUTO_COMPACT_WINDOW` also pinned (now in `_options`),
     auto-compact fired (`trigger: "auto"`, pre 68,473 → post 5,618 tokens,
     summary written by deepseek-v4-pro) and PreCompact reached
     `on_context_reset` exactly once — so `REPORTS_CONTEXT_RESET = True`
     stays correct, no polarity flip needed.  NB the trigger ran later than
     the naive threshold (68K observed on a 30K window): the check runs at
     turn boundaries against lagging usage estimates.  Harmless here — the
     endpoint serves 1M, so late-by-a-turn still has ~600K headroom over the
     384K window.
   - (e) dual cost log shows the repricing ($0.055758 vs CLI-reported
     $0.268063 on a cache-heavy turn — the ~100x figure of F4 was for a
     cache-miss-dominated probe; both consistent), and a REAL `write_cost`
     into a throwaway `SEMANTIC_DB_DIR` recorded
     `driver='DeepSeek' model='deepseek-v4-pro'` with the repriced dollars.
4. **Dev-machine pre-flight (F13)** done: both deepseek blocks appended to
   `~/.isabelle/Isabelle2025-2/etc/interpretation_config` (YAML re-parsed to
   verify).
5. Smoke scripts: scratchpad `deepseek_smoke/smoke1.py` / `smoke2.py`.

## 10. Implementation review (2-turn adversarial debate, two Opus 5 reviewers, 2026-08-27)

Reviewed commit `11c5b77` + Isa-Mini `2324fc5`: one correctness lens, one
elegance lens, each attacking the other's findings in turn 2.  **No blocker.**
Both confirmed the ClaudeCode path is behaviourally intact and that no
reachable flow writes a wrong driver/model/dollar figure.

### 10.1 Culled in cross-examination (do not re-raise)

- "A DeepSeek throttle would be misread as fatal" — REFUTED: the CLI maps
  HTTP 429 to the `rate_limit` enum vendor-agnostically; the two English text
  checks are a fallback, not the only route.
- An `_env()` hook mirroring `status_messages` — the property it would make
  structural already is (`_options` builds a fresh env dict per call, and
  `update` cannot remove a key it does not name).
- Restating `REPORTS_CONTEXT_RESET` in deep_seek.py — §3.2 rules it inherited
  unchanged; the measurement belongs here, not duplicated in code.
- Adding the CLI's federated-credential vars to `_HIJACK_ENV` — their profile
  still reads the pinned `ANTHROPIC_BASE_URL`, so they can only fail loudly;
  refuse-to-start is too heavy. Recorded as a decision in the code comment.
- A subclass test for the 400 branch — records the cost of the §3.1.3
  comment-only ruling; no code should change. See §7.

### 10.2 Owner rulings from this round (2026-08-27)

| # | Ruling |
|---|---|
| R12 | **OD-3 adopted**: the model-echo sentinel is replaced by a check of the terminal message's per-model usage (`ResultMessage.model_usage`) against a new `billable_models` extension point — it names EVERY model that billed, including the auxiliary paths the env pins defend, which a single model echo structurally cannot see. Probed 2026-08-27: DeepSeek's adapter populates it. Supersedes R9's sentinel (b). |
| R13 | **OD-1 declined**: `CONTEXT_WINDOW` stays a per-model table (it is a refusal gate; R8 set the value, not the shape). |
| R14 | **OD-2 accepted**: `deepseek-v4-flash-vision-exp` dropped from `CONTEXT_WINDOW` so the window table and the price table describe one model set; `MSG_INVALID_REQUEST` now names only the two models this backend runs. |
| R15 | **OD-4 declined**: the two quota/throttle text checks stay hard-wired; the base docstring is narrowed to what the file honours instead of growing a fourth extension point. |

### 10.3 Fixes landed

Behaviour:
1. `canonical_model` is applied at BOTH doors — `interpret_file`'s resolution
   and `InterpretationDriver.__init__` — and the base rule became
   `(model or "").strip() or cls.DEFAULT_MODEL`, so a whitespace model half
   (`"DeepSeek. "`) is "not set" rather than a nameless model, and the
   function is idempotent (the precondition for applying it twice).
   DeepSeek's override now expands shorthands on top of `super()`, so the
   default is stated once.
2. `_raise_for_agent_error` consults the terminal `api_error_status` BEFORE
   the retry trail, and scans the trail in the table's own order — a run that
   ends out of balance after a transient 401 no longer says "check your key".
3. `model_not_found` (the CLI's 404) joins the `invalid_request` branch, so it
   reaches `MSG_INVALID_REQUEST` instead of the unrecognised bucket.
4. R12's sentinel: `billable_models` (None on the base = unconstrained,
   `{self.model}` on DeepSeek) checked against `model_usage` in
   `_record_turn_cost`, warning once per process per unexpected name.
5. `ANTHROPIC_DEFAULT_MODEL` added to the pins — it is in the CLI's own
   model-env group and was the one selector left unpinned; the ten literal
   lines became a module constant `_AUX_MODEL_ENV` beside `_HIJACK_ENV`.
6. R14's model-set alignment (see above).
7. `_resolve_driver_and_model` extracted in `semantic_interpretation.py`: the
   resolution seam is now testable without LMDB.

Tests (26 in the DeepSeek file, 92 across the four driver files, 0 failed;
full suite 342 passed with the session's known pre-existing failures):
the shipped price table is now asserted exactly (a wrong digit had been
invisible — mirroring codex's `> 0` assertion would NOT have caught it); the
hijack guard is parametrised over all ten names; the repricing test carries a
non-zero cache-creation count; the sentinel is tested on both backends; the
window table is checked against the CLI's enforceable range; resolution is
tested end to end.

Comments/docs corrected against measurement:
- the pre-smoke "guessed window → premature compaction" story removed from
  three sites (the measured behaviour is the opposite polarity: nothing
  compacts until the enforcement knob is set);
- the "~100x" alarm ratio replaced everywhere by the measured range (4.8x on
  a cache-heavy turn, ~100x cache-miss-dominated; **near 1.0 is the alarm**);
- the CLI clamps `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 100_000..1_000_000
  (binary constants) — now recorded on `CONTEXT_WINDOW`, and asserted;
- both env lists carry their provenance ("read out of CLI 2.1.247");
- `status_messages` documents that every entry is FATAL;
- the base class docstring names the three things a third backend must
  revisit rather than promising they are extension points;
- two dangling references to the removed `_accumulate_usage`, and the
  "round"/"turn" split, fixed.

### 10.4 Correction to §9.3(d)

The compaction smoke ran with a 30_000 test window, which is BELOW the CLI's
enforced minimum of 100_000, so the effective enforcement window was clamped
and the run did not exercise the branch production takes.  The trigger
observed at 68,473 tokens is therefore not evidence about the 384_000
configuration, and §9.3(d)'s "lagging usage estimates" explanation is
unconfirmed.  What the smoke DID establish stands: without
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` nothing compacts at all, with it
auto-compact fires and PreCompact reaches `on_context_reset`.

### 10.5 Live re-verification after the fixes (2026-08-27)

One real turn through the changed driver: `DeepSeek.V4-pro` resolved through
`_resolve_driver_and_model` to `deepseek-v4-pro`, tool call served, sentinel
silent (only the pinned model billed — the eleven pins held), cost repriced
($0.047258 vs the CLI's $0.196463), and the real `write_cost` recorded
`driver='DeepSeek' model='deepseek-v4-pro'`.
