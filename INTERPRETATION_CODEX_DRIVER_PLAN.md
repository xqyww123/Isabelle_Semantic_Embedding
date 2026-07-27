# Interpretation Codex Driver Plan

给 interpretation（deformalization）子系统增加一个 **Codex driver**，走官方 Codex
Python SDK，使其可以用 ChatGPT 订阅额度跑大规模 interpretation，而不只是 Claude Code
Agent SDK。

**已确认的约束与决策**

| 项 | 决定 |
|---|---|
| 目的 | **降本**：批量跑 AFP 级别的 interpretation，用 ChatGPT 订阅额度替代 Claude 额度 |
| 与 AoA 的关系 | 只借鉴设计，**不 import、不修改 `contrib/Isa-Mini` 任何代码**（它已硬依赖本项目，反向 import 成环） |
| 接入方式 | **官方 Python SDK**（`openai-codex`），不手工 spawn CLI |
| 两个 driver 写同一个语义库 | **接受**。不做 entity 级留痕、不做物理隔离 |
| `_BATCH_SIZE = 20` | 保持模块级常量，两个 driver 通用 |
| 文件读取路径 | **不限制** |
| ML config 解析 | 在 ML 入口解析一次、当数据往下传（修法 A，§4.9），支持 `.thy` 里 `declare` 逐 theory 切 driver；**不再需要** `Config.lookup` callback |
| 系统提示词 / CODEX_HOME | `base_instructions` 替换为默认（§4.6，步骤 7 复核）；标准用法直接用真实 `~/.codex`（§4.6） |
| 压缩去重 | codex 路径 `dedup=False`（压缩信号全死，§4.7） |
| 步骤 1 纯重构 | 单独提交，跑完回归再动后面 |

> 演进：v1 裸 OpenAI API（要手写 Read/Grep + 自做压缩 + 自管历史）→ v2 手工 spawn
> `codex exec` + 解析 JSONL（照抄 AoA）→ v3 官方 Python SDK → v4 = v3 经四路并行实测 +
> 登录后实地验证校正（推翻 v3 六处，详见 §1.2）→ **v5（本文）= v4 经第二轮对抗评审
> （6 条：错误分类 RootModel、ML config 修法 A、MCP 结果翻译、健康检查、单例 server、
> 打包，详见 §6）+ 再一轮实地验证**（`base_instructions` 替换后 shell/MCP 均正常，定为
> 默认，§4.6）+ CODEX_HOME 定为标准用法（直接用真实 `~/.codex`，§4.6）。

---

## 1. Codex Python SDK 事实清单

包：`openai-codex` 0.144.4（PyPI），来自 `github.com/openai/codex` 的 `sdk/python`。
依赖 `pydantic>=2.12` 和 `openai-codex-cli-bin==0.144.4`。
架构：SDK 拉起 `codex app-server` 子进程，走 stdio 上的类型化 JSON-RPC。

### 1.1 已实测（四个并行 agent + 一轮登录后实地验证，全部零额度消耗）

> **Provenance 图例**（第二轮评审的元教训：不少"事实"是在比陈述更窄的路径上测得的）。
> 每条按最强证据标注：
> `[源]` 读 SDK/协议源码得出（最强，与运行时无关）；
> `[抓包]` localhost 拦截真实请求体；
> `[会话]` 统计用户既有 rollout 记录；
> `[实测]` 登录后跑真实 turn 观察；
> `[推断]` 由源码/schema 推出、未实跑 —— **这类等同 §1.3，实现前当假设对待**。
> ⚠️ 标注还写明**测的是哪条路径**（同步/异步 client、进程级/线程级、哪个 server 实现），
> 因为多处结论是在与最终代码不同的路径上取得的。

**运行时 / 打包**

- `[源+实测]` SDK **只用自带的 0.144.4 二进制，从不查 PATH**。`resolve_codex_bin`
  （`client.py:176-186`）只有两个分支：`config.codex_bin`，否则
  `codex_cli_bin.bundled_codex_path()`；全包无 `shutil.which`。读 `/proc/<pid>/exe` 实证。
  系统的 `/usr/bin/codex` 0.141.0 不参与。
- `[源]` SDK 会把自带的 `codex-path`（含 vendored `rg`）**前插**进子进程 PATH
  （`client.py:248,257`）。
- `[源+实测]` 默认 `env = os.environ.copy()` 且不设 `CODEX_HOME`（`client.py:254`），
  子进程落到用户的真实 `~/.codex`。`CodexConfig(codex_bin=..., env={"CODEX_HOME": ...})`
  两个旋钮都实证可用，`env` 是**合并**到 `os.environ` 副本而非替换。
- `[推断]` 0.141.0 与 0.144.4 **schema 一致**（`state_5` / `logs_2` / `goals_1` /
  `memories_1` 同集，与磁盘现状一致），无跃迁。⚠️ 静态比对，未实跑确认 `migrate_*`
  在真库上 no-op。但我们用标准用法直接用真实 `~/.codex`（§4.6），该 store 本就由 codex
  自身管理，schema 迁移是它自己的事——非我们引入的风险。

**MCP 注册（原承重点，已解决）**

两条通路都实测可用。推荐 per-thread：

```python
thread = await codex.thread_start(
    sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all,
    config={"mcp_servers": {"isabelle_semantics": {
        "url": "http://127.0.0.1:<port>/mcp",
        "enabled": True,
        "default_tools_approval_mode": "approve",
    }}})
```

`ThreadStartParams.config` 是 free-form overlay（`additionalProperties: true`），嵌套键
snake_case，与 `config.toml` 同构。另一条是 `CodexConfig(config_overrides=('mcp_servers.x.url="…"',))`
——进程级、值按 TOML 解析故字符串要内嵌引号、要重启 client，不如前者。

- `[实测]` 证据：`mcpServerStatus/list` 返回 `{'probe': ['add_two_numbers']}` 含完整
  schema；服务端日志有完整握手（`POST /mcp` initialize → `GET /mcp` SSE →
  `ListToolsRequest`）；`mcpServer/tool/call` 拿回 `{"content":[{"type":"text","text":"42"}],
  "structuredContent":{"result":42},"isError":false}`。⚠️ **测的是 FastMCP + 标量返回**，
  不是我们的 `mcp.server.lowlevel.Server` + `ToolCall_ret`——结果翻译问题正因此漏到 v4，
  见 §4.2。
- `[实测]` **模型确实看得见并会调用这些工具**：流里出现 `McpToolCallThreadItem`，
  参数正确、结果被采纳。⚠️ 但 codex 手里有 shell，凡是 shell 能解决的它会优先用 shell
  ——首次实测用 `add_two_numbers` 就被它拿 `expr 17 + 25` 绕过去了。我们的 5 个工具都属于
  "除调用外无从得知"的类别，故不受影响。
- `[实测]` **`default_tools_approval_mode="approve"` 是必需的**（A/B）。省略它则每次 MCP
  调用被自动拒绝（`"user rejected MCP tool call"`），模型重试一次后放弃；而且**更贵**——
  失败轮 51742 token vs 成功轮 38428。
- `[源]` **`mcpServerStatus/list` 是零额度的注册健康检查**。⚠️ 更正（评审）：SDK 无便捷
  方法，但**有生成的 response model + 公开泛型 `request()`**；`_request_raw` 只存在于
  **同步 `CodexClient`**（`client.py:318,323`），异步 driver 必须用
  `await codex._client.request(method, params, response_model=...)` 并带 `threadId`
  （MCP 是 per-thread overlay）。详见 §4.2 健康检查。
  ⚠️ 上一轮探针用 `_request_raw` 是在**同步** client 上、且**未带 `threadId`**验的——
  两个前提都不适用于最终的异步 + per-thread 代码，别据此以为异步侧也这么调。
- HTTP server 下合法键（`--strict-config` 反推）：`url` / `enabled` /
  `default_tools_approval_mode` / `bearer_token_env_var` / `http_headers` /
  `startup_timeout_sec` / `tool_timeout_sec` / `enabled_tools` / `disabled_tools`。
  `default_tools_approval_mode` 枚举为 `auto` / `prompt` / `writes` / `approve`。

**提示词注入（线级抓包证据）**

| thread_start | `instructions` 长度 | 内容 |
|---|---|---|
| 不传 | 20751 | `"You are a coding agent running in the Codex CLI, …"` |
| `base_instructions="…34 chars…"` | **34** | 仅我们那句 |

- `[抓包]` `base_instructions` = **彻底替换**内置系统提示词，等价于 CLI 的
  `model_instructions_file`。被替换掉的是 20.7 KB 关于**怎么用工具、输出风格、规划纪律、
  提权礼节**的散文。存活的是：`tools` 数组本身、developer message 全部（权限/沙箱说明、
  `<skills_instructions>`、`<environment_context>`）。
- `[抓包]` `developer_instructions` = **叠加**。不动 `instructions`，插进 developer message
  的权限块与 `<skills_instructions>` 之间。
- `[实测]` **完全替换后 shell 照用**：一个 turn 里，`base_instructions` 替换掉整个内置提示词，
  模型仍自发 `zsh -lc 'cat …'` 读到 cwd 外的文件并返回准确内容；与 `developer_instructions`
  对照组产出**逐字节相同**。即被替换的那 20.7 KB 散文不是用 shell 读文件的必要条件。
- `[实测]` **替换 + 我们的 MCP 工具共存**（生产真实配置）：同一 `thread_start` 里
  `base_instructions` 替换 **且** config overlay 注册 MCP，`mcpServerStatus/list` 在该 thread 下
  列出工具，模型真调 `McpToolCallThreadItem` 并采纳结果。两条通路独立，已证共存。
- `[实测]` ⚠️ **read_only 挡不住模型绕开工具**：若答案在磁盘上够得着，模型会 `cat` 源码甚至
  in-process import 去读，而非调工具。对我们**无害**——5 个工具查的是活 RPC 状态 + 语义 DB，
  磁盘上没有对应文件可 `cat`；theory 源码在盘上是**该被 shell 读的输入**、不是工具的替代品。

**Skills**

- `[抓包]` `SkillInput(name, path)` **逐字注入完整 SKILL.md 正文**，包成
  `<skill><name>…</name><path>…</path>…</skill>` 的 **user** 消息，且被**提到输入列表末尾**
  （传 `[SkillInput, TextInput]` 得到 `…, user:"marker", user:"<skill>…"`）。
- `[抓包]` ⚠️ **解析按路径、不按名字**；`name` 是装饰品，会被解析出的 metadata 覆盖。
- `[抓包]` ⚠️ **未注册根目录下的路径静默丢弃**——无报错、无通知、无日志，turn 照跑但
  skill 不在。
- 可用根目录：`$CODEX_HOME/skills/`、**`<cwd>/.codex/skills/`（自动发现，scope=repo）**、
  以及 `skills/extraRoots/set` 注册的任意目录（⚠️ SDK 未暴露，需 `_request_raw`；
  且注册后该目录下**所有** skill 会永久出现在每轮系统提示词里，无法只注册不广播）。
- 已注册的 skill **本来就会**经 `<skills_instructions>` 广告给模型（名称+描述+路径+"去读它"），
  所以 `build_prompt:425` 的 "Load the skills …" 原样即可工作；`SkillInput` 只是额外强制灌入。

**压缩**

- `[会话]` 自动压缩**确实会发生**：用户 `~/.codex/sessions/` 里 4 次真实压缩（上下文用到
  85.8% / 87.3% / 90.6% / 97.5% 时），前置都是普通用户消息而非 `/compact`。
- `[实测]` ❌ **但 `thread/compacted` 通知根本不会被发出** —— 实测否定。把
  `model_auto_compact_token_limit` 压到 14000 逼出真实压缩（rollout 里 `compacted` +
  `context_compacted` 记录俱在），插桩在 `MessageRouter.route_notification`
  （在任何路由决策**之前**、可见每一条通知）的 tracer 全程只见到：
  `account/rateLimits/updated` / `item/started` / `item/completed` /
  `mcpServer/startupStatus/updated` / `remoteControl/status/changed` / `thread/started` /
  `thread/status/changed` / `thread/tokenUsage/updated` / `turn/started` / `turn/completed`。
  **没有 `thread/compacted`**；pending buffer 也是空的。显式 `compact()` 同样不发。
  该方法存在于 v2 schema 与 SDK 的 `notification_registry`，但 0.144.4 的 app-server
  从不发送它。
- 显式 `await thread.compact()` 另外还坏在：它在服务端开一个**新 turn**，而
  `ThreadCompactStartResponse` 是**空模型**（`v2_all.py:4070-4071`），SDK 拿不到 turn id，
  其 `turn/started` / `item/*` / `turn/completed` 全掉进无人读取的 `_pending_turn_notifications`。
- `[实测]` ❌ **`PreCompact` 钩子经纯 SDK 配置（`config_overrides`，不碰磁盘 config.toml、
  不新开 CODEX_HOME）也不触发。** 钩子能注册（`hooks/list` 见 `event=preCompact, enabled=True`），
  但 headless app-server 把 SDK 注入的钩子恒判 `trustStatus=untrusted, source=sessionFlags`，
  `bypass_hook_trust=true` 不被认；13 次自动压缩零执行，`SessionStart`/`Stop`/`PreToolUse`
  session-flag 钩子同样全不触发。唯一未测的受信变体（on-disk config.toml）需隔离 CODEX_HOME
  或写用户真实 `~/.codex`——两者皆脏且违背标准用法决定，不追。
- `[实测]` ✅ **唯一可用的压缩替代信号**（只观察到一次）：压缩时流里多出一条
  `thread/tokenUsage/updated`，其中 `usage.last` 变化而 `usage.total` **不前进**。实测 turn 3：
  `last.total=12471, cum.total=32376`（与 turn 2 末相同），随后真实请求才是
  `last.total=20352, cum.total=52728`。该事件与 rollout 的 `compacted` 记录时点吻合。
- 阈值可调：`model_auto_compact_token_limit` / `model_auto_compact_token_limit_scope`
  （`total` | `body_after_prefix`），可经 `thread_start(config=...)` 传。
  **未找到关闭开关。** 模型目录里 `effective_context_window_percent = 95`。

**用量** `[会话统计 + 实测复核]`（72 个真实会话 / 1477 样本 / 2954 条 breakdown 上统计,
且带 MCP 工具调用的 turn 上实地复核过差分规则）

`ThreadTokenUsage`（`v2_all.py:7482`）是**容器**，不是四字段结构：

```
ThreadTokenUsage { last: TokenUsageBreakdown, total: TokenUsageBreakdown, model_context_window }
TokenUsageBreakdown { input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens }
```

- `input_tokens` **含** `cached_input_tokens`（`input+output==total` 在 2924/2954 条成立；
  `cached>input` 零次）。
- `reasoning_output_tokens` **含**在 `output_tokens` 里（`reasoning>output` 零次）。
- ⚠️ **`usage.last` 是"每次模型请求"，不是"每轮"**。一个 turn 里每次工具调用都会再发一次
  请求，`.last` 只是最后一次。实测单轮内：`total` 走 13687 → 27965 → 43754 → 65125，
  而对应的 `.last` 分别是 13687 / 14278 / 15789 / 21371。
- ✅ **正确的每轮成本 = `usage.total` 的前后差**。
- ⚠️ `usage.total` 累计的是每次请求的**全量重发前缀**（某会话累计 1680 万 token 对 17 万
  上下文）。**对计费正确，绝不可当上下文占用量。**
- ⚠️ 30 条记录四分量全零但 `total_tokens` 非零 —— 别假设 `input+output==total` 恒成立。

**错误分类** `[源]`（全部读 SDK/协议源码得出，**无一在真实故障上跑过**——见 §1.3）

- 异常层次：`CodexError` → `TransportClosedError` / `JsonRpcError` → `CodexRpcError` →
  {`ParseError`, `InvalidRequestError`, `MethodNotFoundError`, `InvalidParamsError`,
  `InternalRpcError`, `ServerBusyError` → `RetryLimitExceededError`}。
- `is_retryable_error()`（`errors.py:112-121`）**只**对 `ServerBusyError` /
  `RetryLimitExceededError` / `.data` 满足 `_is_server_overloaded` 的返回 True。
  auth、quota、`TransportClosedError` **全为 False**。
- `retry_on_overload`（`retry.py:12-41`，3 次、0.25s→2.0s 指数退避、±20% 抖动）
  **opt-in，SDK 内部无任何自动调用点**——约 20 个内部操作全走裸 `request`，
  `request_with_retry_on_overload` 无内部调用者。**不会与我们的重试叠乘**（只要我们不主动调）。
- ⚠️ **但类型化异常分不出我们要的五桶**，两处独立的信息丢失：
  1. **失败 turn 丢弃类型化错误**。`_run.py:60-65`：
     ```python
     if turn.error is not None and turn.error.message:
         raise RuntimeError(turn.error.message)   # 裸 RuntimeError，只剩字符串
     ```
     `turn.error.codex_error_info` 被丢弃。而协议里本有精确枚举 `CodexErrorInfoValue`
     （`v2_all.py:379-390`）：`usageLimitExceeded` / `unauthorized` / `serverOverloaded` /
     `badRequest` / `contextWindowExceeded` / `sessionBudgetExceeded` / …，以及
     `RateLimitReachedType`（`v2_all.py:2908-2913`）区分
     `workspace_owner_credits_depleted`（计费）与 `workspace_member_usage_limit_reached`（额度）。
  2. **`_is_server_overloaded` 有大小写 bug**（`errors.py:61-83`）：拿 snake_case
     `"server_overloaded"` 比对，但协议发 camelCase `"serverOverloaded"`（同函数里检查键名
     用的却是 camelCase 的 `codexErrorInfo`）。于是真正的服务端过载被判成不可重试。
- ⚠️ 走 `thread.run()` 时 **`TurnResult.status` 永不为 `failed`、`.error` 恒为 `None`**
  ——`_collect_turn_result` 在构造结果前先调 `_raise_for_failed_turn`（`_run.py:87`/`:123`）。
- ✅ 可用出路：`account/rateLimits/read`（`v2_all.py:5737`）→ `RateLimitSnapshot`
  （`v2_all.py:6724-6734`）带 `RateLimitWindow.resets_at` / `used_percent` 和
  `CreditsSnapshot.has_credits`——**主动**区分额度耗尽与计费失败，且 `resets_at` 给真实
  恢复时间，胜过硬编码 sleep 1200s。
- ⚠️ Rust CLI **内部会自己重试**，经 `ErrorNotification.will_retry`（`v2_all.py:7930-7937`）
  告知。这发生在单个 `turn/start` 内部、对 Python 不可见，最终表现为
  `responseTooManyFailedAttempts`。所以一个 turn 到达我们时可能已经消耗了数次网络尝试。

**沙箱**

- `[抓包]` `Sandbox.read_only` 是默认模式且**网络受限**——`codex debug prompt-input`
  渲染出的权限说明写着 "Network access is restricted"。无 `curl` 外传风险。
- `[实测]` ✅ **cwd 之外的读本来就被预设允许**（`cwd` 与目标文件在兄弟目录，`cat` 成功）。
  `Sandbox.read_only` 的 docstring 也写着 "allows file reads without writes"。
- `[实测]` ❌ **`sandbox_permissions` 不是合法配置键，静默忽略**。二进制里 `disk-full-read-access`
  只出现在**过时的 `--config` 帮助示例**里；唯一活着的 `sandbox_permissions` 是
  `ShellCommandToolCallParams` 的逐命令字段，不是配置键。既然预设已允许外部读，
  本方案**不需要**它。
- ⚠️⚠️ **`thread_start(config=)` 会静默接受未知键** —— 这是个通用陷阱。它确实校验真实键
  （`{"model_auto_compact_token_limit": "not-a-number"}` → 拒绝 `expected i64`；
  `{"sandbox_mode": "totally-bogus"}` → 拒绝 `unknown variant`），但
  `{"sandbox_permissions": ["not-a-real-permission"]}` 和
  `{"zz_totally_bogus_key_qx": ["nonsense"]}` **都被接受**。
  **绝不可因为一个键"没报错"就认为它生效**——目前只有 MCP 那组键与
  `model_auto_compact_token_limit` 是被**行为**证实的。

### 1.2 实测推翻的 v3 设计

| v3 写法 | 实测结论 | v4 改法 |
|---|---|---|
| `self._record_usage(result.usage)` 当每轮成本 | `usage.last` 是每请求，**每轮成本会少算 6 倍以上，且静默** | 用 `usage.total` 前后差（§4.5） |
| ~~v4 曾改用 `developer_instructions`~~ | v4 的理由（替换会炸掉 shell 用法指导）**后经实测证伪**：替换后 shell 照用、与叠加逐字节相同 | v5 定回 `base_instructions`（替换），§4.6 |
| 「退路：关自动压缩、自己调 `thread.compact()`」 | 显式 `compact()` 的通知**两个通道都到不了**，这条退路是坏的 | 删除该退路（§4.7） |
| `SkillInput` 指向包内任意路径 | 未注册根目录下**静默丢弃** | 放 `<cwd>/.codex/skills/`（§4.6） |
| ~~v3/v4 曾提"隔离 CODEX_HOME + 复制 auth.json"~~ | 用户否决（"AoA 那种太丑陋，用标准用法"）；复制凭证会破坏 token 自管 | 标准用法：直接用真实 `~/.codex`（§4.6） |
| 「自动压缩发 `thread/compacted`，在 `stream()` 里接」 | **该通知从不被发出**（0.144.4） | 改用 `dedup=False`；替代信号见 §4.7 |
| `config={"sandbox_permissions": [...]}` 放开外部读 | 该键**不被识别、静默忽略**；而外部读本来就允许 | 直接删掉（§4.4） |

### 1.3 仍未核实（实现前一律当假设对待，不阻塞步骤 1）

1. ChatGPT 后端是否在 `instructions` 之上再加服务端提示词（客户端不可知；已证的是客户端行为）。
2. `thread/compacted` 是否在**其它** codex 版本上会发（只测了 SDK 自带的 0.144.4）。
3. §4.7 的「`last` 动、`total` 冻」替代信号是否在所有压缩路径上都成立（只观察到一次）。
4. codex 端对孤立 UTF-16 代理项的行为（Claude 侧是 API 400 → PoisonedSession）。
5. **错误分类（§4.8）全部是读源码得出，`codex_error_info` 的运行时形状从没被任何探针
   观察过。** RootModel 各变体的实际字段、`http_status_code` 是否真的在对象变体里、
   `TurnCompletedNotification` 上错误信息能否在 stream 里先于异常拿到——都待实测。
6. **`ToolCall_ret` 从没过 `mcp.server.lowlevel.Server`**（探针用的是 FastMCP / 自写 server +
   标量返回），所以 §4.2 的翻译层是照源码写的、未端到端验证。步骤 3 的离线单测负责它。

已结清项（原列于此，现移出）：`base_instructions` 替换后 shell 可用 + MCP 工具共存
（[实测]，§1.1）；健康检查 `mcpServerStatus/list` 带 `threadId` 在**异步 client** 上工作
（组合验证中实跑，两次都在该 thread 下列出工具）。

实测累计花费：**约 13 次微型模型请求**，用户 `~/.codex` 全程未被读取/复制（mtime/size 未变）。

## 2. 与 Claude Code 路径的能力对照

| 能力 | Claude Code | Codex SDK | 结论 |
|---|---|---|---|
| 5 个 Isabelle 工具 | in-process SDK MCP | HTTP MCP server + `thread_start(config=...)` | 唯一的大工程 |
| 读 theory 源码 | `Read` / `Grep` 内置 | 沙箱 shell 的 `cat` / `rg`（SDK 自带 rg） | 不用手写 |
| 领域知识 | `.claude/skills/` 三个 SKILL.md | `<cwd>/.codex/skills/` 指向同样三个文件 | 同一份文件服务两条路径 |
| 任务提示词 | `system_prompt=`（替换） | `base_instructions=`（替换，实测能力等价） | 见 §4.6 |
| 上下文压缩 | CLI 自动 + `PreCompact` hook（清 `seen_constants`） | 自动压缩，但**无任何可用信号**（通知+钩子全死） | 关掉常量去重 `dedup=False`，见 §4.7 |
| 成本 | `total_cost_usd` 直报 | 只报 token，且需 `total` 差分 | 自算（§4.5） |
| 会话续接 | `client.query()` 同一 client | `thread.turn()` 同一 thread | 直接对应 |
| 中断 | SDK 自理 | `turn_handle.interrupt()` | 直接对应 |
| 权限控制 | `PreToolUse` hook + `allowed_tools` | `Sandbox.read_only` + `ApprovalMode.deny_all` | 更简单 |
| 错误分类 | 结构化 `AssistantMessage.error` 枚举 | 需从 `stream()` 自取 `codex_error_info` | 更麻烦（§4.8） |

**用 SDK 相比手工 spawn CLI 省掉的**：子进程生命周期（`stdin=DEVNULL` 防挂死、
`killpg` 防孤儿、stderr drain）、JSONL 事件解析、扁平名拆分重拼、`-c` 字符串拼装、
临时 `config.toml`、生成钩子脚本、`--dangerously-bypass-hook-trust`。

## 3. 模块结构

三个既有约束：`__init__.py:16` 的 `from .semantic_interpretation import interpret_file,
_interpret_file` 是 RPC 注册的承重点（模块路径不能挪）；包目前是扁平的；`drivers/`
已被 embedding 层的 `make_embedding_provider` 占用（另一个 ABC，不能混）。

```
Isabelle_Semantic_Embedding/
  semantic_interpretation.py            ← 原位不动。driver 无关核心 + RPC shim
  interpretation_driver/                ← 新子包
    __init__.py                         ← InterpretationDriver ABC + DRIVERS 注册表
                                          + register_interpretation_driver + make_interpretation_driver
    claude_code.py                      ← 现有 SDK 路径原样搬入
    codex.py                            ← 新 driver
    mcp_server.py                       ← 5 个工具的 HTTP MCP server（§4.2）
    config.py                           ← driver/model 解析 + pricing 表加载
  Agent_Interpretation_Dir/
    .claude/skills/…                    ← 既有，Claude Code 路径用
    .codex/skills/…                     ← 新增，指向同样三个 SKILL.md（§4.6）
  interpretation_config_template.yaml   ← 与 embedding_config_template.yaml 并列
```

**不变量（写进 `__init__.py` 注释）**：`interpretation_driver/__init__.py`
**绝不 import 具体 driver**。`make_interpretation_driver` 用 `importlib` 惰性导入
`interpretation_driver.{name}`，与 `make_embedding_provider`（`semantic_embedding.py:250-265`）
同构。具体 driver 反向 import `semantic_interpretation` 的异常类和 `InterpretationTask`
——因为惰性，运行时不成环；谁在 `__init__.py` 里加一句 `from . import codex` 就立刻炸。

**本轮不拆 `semantic_interpretation.py`**（瘦身后仍有 ~800 行）。步骤 1 动的是唯一在生产上
跑过的路径，diff 越小越好；再拆会连带改 `__init__.py:16`、`semantics_manage.py:552`、
`test_interpretation_error_classifier.py:13` 三处导入。

## 4. 设计

> ⚠️ **本文所有 `semantic_interpretation.py` / `semantic_store.ML` 的行号是近似的**
> （评审已指出普遍偏 50–70 行）。实现时**按符号名 grep 定位**（`_run_agent`、`interpret'`、
> `interpret_with_parallel`、`_answer_tool`、`seen_constants`、`write_cost` 等），不要盲信行号。

### 4.1 Driver ABC

driver 只负责"把一个 user prompt 跑到模型自然停止"。batch 推进、missing-entry 重试、
限流等待、recycle 全留在共享的 `_run_agent`（现 `semantic_interpretation.py:829`）。

```python
class InterpretationDriver(ABC):
    def __init__(self, model: str, system_prompt: str,
                 tools: list[SdkMcpTool], task: InterpretationTask,
                 on_context_reset: Callable[[], None]): ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc) -> None: ...

    @abstractmethod
    async def run_turn(self, prompt: str) -> None:
        """发一轮 user prompt，跑到模型停止。期间必须把用量累加进 self.task
        并每轮 write_cost()；失败时抛 semantic_interpretation 的五个异常之一。"""
```

`on_context_reset` 是第五条通道（评审 minor 6）：`seen_constants` 是 `interpret_file` 里的
裸局部变量（`:1017`），既不在 task 上也不在 `SdkMcpTool` 上，前四个参数够不着它。

`_run_agent` 只把 `client.query(...)` + `receive_response()` 换成 `drv.run_turn(...)`，
`:849-891` 的 missing-entry 重试循环和 `:895-939` 的异常处理原样保留。
`:924` 的 `(CLINotFoundError, ProcessError)` 分支下沉到 `claude_code.py`。

### 4.2 工具：in-process HTTP MCP server（核心工程量）

Codex 跑在 SDK 拉起的 `codex app-server` 子进程里，够不到 `create_sdk_mcp_server` 那种
in-process MCP；而 5 个工具的 handler 闭包捕获着活的 `Isabelle_RPC_Host.Connection`，
**不可能挪进子进程**。所以必须在 Python 进程内起 HTTP MCP server 让 codex 连回来。

**工具的 handler 零改动，但结果需要一层翻译（评审 major 3）。** `SdkMcpTool` 是纯
dataclass（`claude_agent_sdk/__init__.py:156-163`）：`name` / `description` /
`input_schema` / `handler`。`mk_query_by_name_tool` / `mk_definition_tool` /
`mk_hover_tool` / `mk_desugar_and_explain_tool` / `_answer_tool` **一行不改**，server 读这四个
字段生成 `mcp.types.Tool`，调用时 `await t.handler(args)`。

⚠️ **但 handler 返回的 `ToolCall_ret`（`base.py`）不是 `mcp.server.lowlevel` 认的形状。**
`mk_ret` 返回的是 Claude-SDK 私有的普通 dict（`{"content":[...], "is_error"?: ...}`，
snake_case）。`mcp/server/lowlevel/server.py:548-551` 收到 dict 会当成 **structuredContent**，
正文变成 `TextContent(json.dumps(results, indent=2))`，且 `isError` 硬编码为 `False`。
Claude 路径能工作全靠 `create_sdk_mcp_server`（`claude_agent_sdk/__init__.py:452-516`）里那
65 行翻译层，而该层够不到（正是本节存在的理由）。**`mcp_server.py` 必须独立重写这层翻译**
（不 import）：把 `ret["content"]` 拆成 `types.TextContent` / `ImageContent` /
`EmbeddedResource`，返回 `types.CallToolResult(content=content,
isError=ret.get("is_error", False))`。不做这层，`_answer_tool` 装在返回值里的**下一批
prompt**（`:510-515`）会被 JSON 包裹、换行转义后喂给模型，`desugar` 的错误标志丢失，
整轮跑完但 interpretation 质量退化。

实现用已装的 `mcp.server.lowlevel.Server` + `StreamableHTTPSessionManager` + `uvicorn`
（与 AoA 同库，但**独立实现，不 import**）。

**单例 server + 会话路由，与 AoA 同构（独立实现，不 import）。** 一个进程一个 server
（`get_or_create`，第一个 driver 建、整进程共用），"session" = 一次 `interpret_file` 调用
= 一个 driver 实例，各自持有自己的 5 个工具闭包；路由 `/mcp/<session_id>` → 该 session 的
工具集，注册/注销随 driver 的 `__aenter__` / `__aexit__`。`_answer_tool` **已经**在用
`_local_task` contextvar 做 session 隔离，机制半成品已在。并发度由 `schedule_dag` 的
`Multithreading.max_threads()` 限死。

> 为什么不是"每 driver 一个 server"（评审 major 5，已据此翻转）：那会让每个 driver 各调一次
> `uvicorn.Server.serve()`，而 `serve()` = `with capture_signals(): await _serve()`，
> `capture_signals` 在主线程全局改写 `SIGINT`/`SIGTERM`（存进程时的旧 handler、退出时恢复）。
> RPC host 是单主线程 event loop（`Isabelle_RPC_Host/launcher.py:29` 的 `asyncio.run`），
> N 个 server 生命周期非 LIFO 交错时，最后退出的会把一个**已死 Server 的 `handle_exit`**
> 永久装成进程 handler —— 一次并发跑之后 `kill <rpc-host-pid>` / Ctrl-C 失效。单例只
> `serve()` 一次，capture/restore 平衡，此问题不存在。server 起在主 loop 上，故工具 handler
> 能自然 `await connection`。

**服务器名固定 `isabelle_semantics`** → 扁平名 `mcp__isabelle_semantics__answer` 等，
与 Claude Code 侧**完全一致**。于是 `_SYSTEM_PROMPT`（`:178-183`）、`build_prompt`
（`:421,428`）、`_answer_tool` 返回文案（`:513,515,522`）、retry prompt（`:887`）
**一个字都不用改**，两条路径共用同一套 prompt。

**启动健康检查（评审 major 4，两处修正）**：MCP 静默失败的唯一守卫（§7）。
`__aenter__` 里、`thread_start` **之后**，用公开泛型 `request` 带 `threadId` 查：
```python
resp = await asyncio.wait_for(codex._client.request(
    "mcpServerStatus/list", {"detail": "toolsAndAuthOnly", "threadId": self._thread.id},
    response_model=ListMcpServerStatusResponse), timeout=_HEALTHCHECK_TIMEOUT_S)
```
断言 `isabelle_semantics` 条目在、其 `tools` 含全部 5 个名字，缺则报缺名。
⚠️ 两个坑：(a) `_request_raw` **只存在于同步 `CodexClient`**（`client.py:318,323`），
`AsyncCodexClient` 没有它也没 `__getattr__` —— 我们的 driver 是异步的，调它直接
`AttributeError`；必须用 `request(..., response_model=...)`。(b) **必须带 `threadId`**：
MCP 是 per-thread overlay，未限定作用域的 list 看的是进程级空视图，要么恒失败要么空洞通过。
同一形式也用于 §4.6 的 `skills/list`（`SkillsListResponse`）和 §4.8 的
`account/rateLimits/read`（`GetAccountRateLimitsResponse`）——这三个都无 typed method。
把响应模型的 `ValidationError` 当**健康检查 WARNING**，不要当启动 abort。

### 4.3 会话与轮次

```python
async def run_turn(self, prompt: str) -> None:
    before = self._cum_total()                     # usage.total 快照
    handle = await self._thread.turn(self._make_input(prompt))
    err_info = None
    async for note in handle.stream():
        self._log_note(note)
        if _is_compacted(note):
            self._on_context_reset()               # §4.7
        if _is_turn_completed(note):
            err_info = _extract_error_info(note)   # §4.8：必须在 run() 丢弃之前取
        self._observe_usage(note)                  # §4.5：ThreadTokenUsageUpdated
    self._record_turn_cost(before)                 # total 差分 → task.write_cost()
    if err_info is not None:
        raise self._classify(err_info)
```

⚠️ **必须用 `thread.turn()` + `.stream()`，不能用 `thread.run()`**。三个独立原因：
(a) 只有 stream 里拿得到 `TurnCompletedNotification.turn.error.codex_error_info`——
`run()` 会先抛裸 `RuntimeError` 把它丢掉（§4.8）；
(b) `thread/compacted` 只在 stream 里（§4.7）；
(c) 需要逐条 usage 更新做差分（§4.5）。

`AsyncTurnHandle.interrupt()` 用于 Isabelle 中断路径。

### 4.4 沙箱与权限

`Sandbox.read_only` + `ApprovalMode.deny_all`。read-only 就是我们要的语义：agent 能
`cat` / `rg` / `sed` 读文件，写不了任何东西，且网络受限（已实测）。`deny_all` 保证它不会
因为想提权而卡住。

theory 源码和 `mk_unicode_file` 的输出在 cwd 外——**无需任何额外配置**：实测确认沙箱预设
本来就允许 cwd 之外的读。~~`sandbox_permissions: ["disk-full-read-access"]`~~ 是个
**不被识别的键**，静默忽略，别写（§1.1）。

**不需要 AoA 那套 PreToolUse 允许列表钩子**——AoA 必须用是因为它跑 `danger-full-access`，
钩子是唯一屏障；我们跑 read-only，沙箱本身就是屏障。

### 4.5 成本

codex 只报 token 不报金额，自算。新建 `$ISABELLE_HOME_USER/etc/interpretation_config`
（复用 `_user_config.User_Config` + `embedding_config.py:1-45` 的 seeding 模式，
env `INTERPRETATION_CONFIG_PATH` 覆盖），模板 `interpretation_config_template.yaml`：

```yaml
models:
  gpt-5.5:
    pricing: {input: 1.25e-6, cached_input: 0.125e-6, output: 10.0e-6}
```

**核算规则（实测校正，照做，别凭直觉）**：

- 每轮成本 = `usage.total` 的**前后差**。**绝不用 `usage.last`**——它是每次模型请求的，
  一个带工具调用的 turn 会少算 6 倍以上，且数字看着完全合理。
- `input_tokens` **含** `cached_input_tokens` → 落 `total_input_tokens`（uncached）时要
  相减，与现有语义对齐。
- `reasoning_output_tokens` **含**在 `output_tokens` 里 → 不要重复计。
- `usage.total` 是**计费量**（含每次请求的全量重发前缀），**不是上下文占用量**。
  不要拿它做任何阈值判断。
- 防御：30/2954 条记录四分量全零但 `total_tokens` 非零 —— 不要 assert
  `input+output==total`。

**校验时机（评审 major 4）**：`__aenter__` 里一次性取出 pricing 三键，**发出任何 codex
调用之前**。缺失则抛 `FatalAgentError`，消息以 `USER_ERROR_MARKER` 开头、单行、写明模型名
与 `config_source()` 路径——这样 `extract_user_error`（`Tools/semantic_store.ML:1052-1057`）
走 SOME 分支，且命中 `_run_agent:921-925` 的不重试快路，而不是掉进 catch-all 白烧 8 次
recycle。**不**对齐 `embedding_config.dimension()` 的裸 `KeyError` + 惰性时机。

### 4.6 提示词、skills、CODEX_HOME

**任务提示词用 `base_instructions`（完全替换），默认；步骤 7 复核质量。**
`thread_start(base_instructions=_SYSTEM_PROMPT)`，字符串直传。理由：`_SYSTEM_PROMPT` 是一份
**任务规格**（怎么把形式化陈述翻译成英文），替换后模型只拿到这份规格，没有内置的
"You are a coding agent" 框架去和 informalization 任务打架。**实测已排除能力风险**（§1.1）：
替换后 shell 照用、我们的 MCP 工具照样共存可调、与 `developer_instructions` 对照组逐字节
相同。唯一未测的是长会话翻译**质量**——那 20.7 KB 里的输出/纠错纪律有无隐性价值——
**步骤 7 用真实 theory 两种都跑一遍比，可回退到 `developer_instructions`（叠加）或混合**。

**Skills 放 `<cwd>/.codex/skills/`。** 我们本来就控制 `cwd`（Claude Code 路径已把它设为
`Agent_Interpretation_Dir`），那里已有 `.claude/skills/` 放着三个 SKILL.md；旁边加
`.codex/skills/` 做成指向 `.claude/skills/` 的**目录软链**（决定见 §5 步骤 6；setuptools
的 glob 跟随软链，已验证）。自动发现，scope=repo，**无需 RPC、无需私有方法、无需碰 `~/.codex`**。
`build_prompt:425` 的 "Load the skills …" 原样保留——已注册 skill 本来就会经
`<skills_instructions>` 广告给模型。是否额外用 `SkillInput` 强制灌入，实测模型行为后再定。

⚠️ **`SkillInput` 的静默失败**：未注册根目录下的路径会被无声丢弃（无报错/通知/日志）。
若采用 `SkillInput`，必须在 `__aenter__` 里用 `skills/list` 断言三个 skill 都已解析出来。

**CODEX_HOME —— 标准用法：直接用真实 `~/.codex`（已定）。** 不隔离、不复制 `auth.json`，
让 SDK 按默认方式用用户的 `~/.codex`，token 由 codex 自管。这是用户明确定下的
（"AoA 那种用法太丑陋了，用标准正常用法"）——不复制凭证，也就没有 v3/v4 那种两份凭证
漂移、以及复制动作触发凭证告警的问题。skills 走 `<cwd>/.codex/skills/`（§4.6 上文），
不依赖 CODEX_HOME，与此独立。

代价（接受）：用户 `~/.codex/config.toml` 注册的 `isabelle-mcp` stdio server 会随每个
app-server 启动被拉起——启动延迟的小烦扰，对我们无用但无害。
可选的纯优化（**不阻塞实施，将来再看**）：CLI 有 `--ignore-user-config`（不加载
config.toml、认证仍用 CODEX_HOME）能免掉这次拉起；SDK 是否暴露它未确认，属锦上添花。
⚠️ 另留意 §4.10 的并发刷新隐患：单次 refresh token + N 个并发 app-server 共用一份凭证，
理论上可能争抢刷新——待实测，若属实用"预热先刷一次再并发"解，仍不改动标准用法的选择。

### 4.7 `seen_constants` 与压缩

`seen_constants`（`:1017`，被 desugar 工具闭包捕获于 `:1023`）是 `desugar_and_explain`
的去重集合：该工具在展开的项后附一段 `Constants:`，把每个常量标注上语义库里的英文解释，
同一常量在一段对话里只标注一次以省 token（`desugar.py:103-118`）。

压缩会让去重变**有害**：压缩后早先的标注已不在 agent 上下文里，但集合仍记着"讲过了"，
工具于是静默跳过——agent 拿到一个它已看不到解释的常量，且不知道自己缺了什么。
Claude Code 侧因此挂 `PreCompact` 在压缩前清空（`:1028-1034`）。

**❌ Codex 侧拿不到可用的压缩信号——四条路全部实测堵死：**

1. ~~SDK `thread/compacted` 通知~~ — 0.144.4 **从不发出**（§1.1，13 次压缩零通知）。
2. ~~关闭自动压缩~~ — 未找到开关（§1.1）。
3. ~~自己调 `thread.compact()`~~ — 其通知落进无人读的 pending buffer（§1.1）。
4. ~~`PreCompact` 钩子~~ — **实测不触发**：经 `config_overrides` 注册的钩子恒为
   `trustStatus=untrusted, source=sessionFlags`，`bypass_hook_trust=true` 被 headless
   app-server 忽略；13 次自动压缩里钩子零执行，连 `SessionStart`/`Stop`/`PreToolUse`
   session-flag 钩子也全不触发。唯一未测的受信变体（on-disk 钩子）要么需隔离 CODEX_HOME
   （违背标准用法决定，§4.6），要么要写进用户真实 `~/.codex/config.toml`（侵入其配置），
   两者皆不可接受，故不追。

**决定：codex 路径关闭去重（`dedup=False`）——由上述四条全死逼出，非任意选择。**
给 `mk_desugar_and_explain_tool` 加显式参数 `dedup: bool = True`，codex 路径传 `False`
——每次都标注常量。

理由是**失效方向不对称**：多标注只是多花 token（每个常量几十到上百 token），
漏标注则是 agent 拿到一个它看不到解释的常量、且不自知——直接损害 interpretation 质量，
而这正是整个子系统的产品。既然 §4 的目的是降本而非抠 token，这个交换是划算的。

⚠️ 一个**可选**的优化，暂不实现：压缩时流里会多出一条 `thread/tokenUsage/updated`，
其 `usage.last` 变化而 `usage.total` 不前进（§1.1 实测）。据此可以近似地检测压缩并
调 `on_context_reset()`，恢复去重。但它依赖一个**未文档化的巧合**，且只观察到一次
（§1.3 第 3 条），所以**先按 `dedup=False` 实现**，等实测出 token 代价确实可观再回来
优化。注意其误判方向也是安全的：误报只会多清一次集合（无害），漏报才有害。

`InterpretationDriver.__init__` 的 `on_context_reset` 通道**仍然保留**——Claude Code
路径要用它（`PreCompact`），且它是上述可选优化的接入点。

### 4.8 错误分类

保持 `semantic_interpretation` 的 5 个异常类不变（共享 `_run_agent` 依赖它们）。
⚠️ **不能建立在 SDK 的类型化异常上**——它们分不出我们要的五桶（§1.1）。两条信息通路：

**主通路：从 stream 自取。** 在 `TurnCompletedNotification` 到达时读
`turn.error.codex_error_info`。⚠️ **它不是枚举，是 RootModel 联合（评审 blocker 1）**：
`CodexErrorInfo`（`v2_all.py:5901-5925`）= `RootModel[CodexErrorInfoValue（11 值枚举）
| HttpConnectionFailedCodexErrorInfo | ResponseStreamConnectionFailedCodexErrorInfo
| ResponseStreamDisconnectedCodexErrorInfo | ResponseTooManyFailedAttemptsCodexErrorInfo
| ActiveTurnNotSteerableCodexErrorInfo]`。**那四个连接/流变体恰恰就是网络故障**，包括
§1.1 自己点名的 `responseTooManyFailedAttempts`（CLI 内部重试耗尽的终态，最可能的长跑
故障）。**必须先 `err_info.root` 再分派**，直接对 RootModel 查字典全部 miss。

分派规则（先 `isinstance` 对象变体，再枚举）：

| `err_info.root` 的类型 / 枚举值 | 映射 | `_run_agent` 的处理 |
|---|---|---|
| `HttpConnectionFailed*` / `ResponseStreamConnectionFailed*` / `ResponseStreamDisconnected*` / `ResponseTooManyFailedAttempts*` / `ActiveTurnNotSteerable*` / 枚举 `internalServerError` / `serverOverloaded` | `TransientAgentError` | recycle（≤8） |
| 对象变体里 `http_status_code == 429`（深一跳） | `ReachLimitError` | sleep（见辅通路） |
| 对象变体里 `http_status_code ∈ {401, 403}` | `FatalAgentError`（文案：`codex login`） | 直接失败 |
| 枚举 `usageLimitExceeded` | `ReachLimitError` | sleep（见辅通路） |
| 枚举 `unauthorized` | `FatalAgentError`（`codex login`） | 直接失败 |
| 枚举 `badRequest` / `cyberPolicy` | `FatalAgentError(_MSG_INVALID_REQUEST)` | 直接失败 |
| 枚举 `contextWindowExceeded` | `PoisonedSessionError` | recycle 换新会话 |
| 枚举 `sessionBudgetExceeded` | `FatalAgentError` | 直接失败 |
| 枚举 `sandboxError` / `threadRollbackFailed` / **未识别** | `TransientAgentError` | recycle（≤8）后再抛 |
| `TransportClosedError`（异常层） | `TransientAgentError` | recycle |

⚠️ **fall-through 极性（评审 blocker 1）**：未识别 → `TransientAgentError`（有界 recycle 后
再抛），**不是** `FatalAgentError`。因为 codex 的故障剖面以网络抖动为主，把未知错默认成
"直接杀 cone"会让一次 SSE 抖动在 AFP 跑到几小时时灭掉整个锥。**每个分支都 log
`type(root).__name__`**，未识别的能事后补进上表。

⚠️ **这与 Claude Code 路径的极性相反且是有意的**：Claude 侧未识别 → `FatalAgentError`
（保留 traceback，`semantic_interpretation.py` 有注释论证"未识别的桶没有诚实的一句话可说，
栈是唯一线索"）。两条路径的故障剖面不同——Claude 侧以 CLI/鉴权的确定性失败为主，codex 侧
以网络抖动为主——故默认极性不同是对的。这个不对称在此显式记录，不让它悄悄存在。

**辅通路：主动查配额。** `account/rateLimits/read` → `RateLimitSnapshot`
（`RateLimitWindow.resets_at` / `used_percent`、`CreditsSnapshot.has_credits`）。
用途有二：把 `usageLimitExceeded` / 429 进一步分成"额度用完（等到 `resets_at`）"与
"没钱了（`has_credits` 为假 → `FatalAgentError` 计费文案）"；以及**用真实
`resets_at` 取代硬编码的 sleep 1200s**。⚠️ 它也无 typed method，用 §4.2 的
`request(..., response_model=GetAccountRateLimitsResponse)` 形式。

⚠️ 别依赖 `is_retryable_error()` —— `_is_server_overloaded` 的 snake/camel case bug 使
真正的 `serverOverloaded` 返回 False。
⚠️ 别调 `request_with_retry_on_overload` —— 重试策略统一由 `_run_agent` 负责，
避免两层叠乘。
⚠️ Rust CLI 内部已自行重试（`ErrorNotification.will_retry`），一个 turn 到达我们时可能
已消耗数次网络尝试。记日志时把 `will_retry` 记下来，否则会误判重试预算。

⚠️ `_MSG_AUTH_FAILED` / `_MSG_BILLING`（`:689-696`）现在的措辞是 Claude Code 专属
（"Run 'claude' and use /login"），必须参数化成 per-driver 文案（codex 版说 `codex login`）。
`USER_ERROR_MARKER` 机制（`:656`）保持不变。

### 4.9 配置

**一个选项，值是 AoA 那种 `<Driver>[.<model>]` 串（已定）。** 不设第二个 model 选项：
driver 和 model 分两个选项时，两者可以来自不同层（`declare` 只给 model、CLI 只给 driver），
拼出谁也没打算要的组合——拿 Claude 的模型名去调 Codex。合成一串后这种组合在结构上不可能出现。
语法与解析规则照抄 AoA（`AoA/toplevel.py:249-253` 按**第一个点**切、`driver_codex.py:101` 的
`model or argument or DEFAULT_MODEL`），本项目独立实现，不 import：

```
ClaudeCode                      → ClaudeCodeDriver.DEFAULT_MODEL
ClaudeCode.claude-opus-4-8[1m]  → 显式
Codex.gpt-5.5                   → 显式（按第一个点切，模型名里的点安全）
```

只写 `gpt-5.5` 不写 driver ⇒ driver 名读成 `gpt-5` ⇒ 报「未知 driver」。响亮失败，接受。

**四级解析，"" 即未给**（三层各自的"未给"表示法统一成空串，沿用本库既有约定：
`embedding_driver` 的 `K ""`、`embed --driver` 的 `default=""`）：

| 层 | 形式 | "未给" |
|---|---|---|
| CLI（最高） | `semantics_manage collect --driver Codex.gpt-5.5` | `default=""` |
| ML config | `declare [[Semantic_Embedding.interpretation_driver = "…"]]` | `Attrib.setup_config_string … (K "")` |
| env | `INTERPRETATION_DRIVER` | 未设或设成空 |
| 默认 | `ClaudeCode` | — |

CLI 高于 `declare`（已定）：批量跑是这条路径的入口，用户敲了就以它为准。
显式敲 `--driver ""` 等同于没敲——空串没有别的合理含义，且引入第二套"未给"表示法不划算。

⚠️ **`collect --model` 删除，换成 `--driver`**（已定；全仓库无引用）。模块全局
`interpretation_model` 随之退休：它的 argparse 默认值写死 `claude-opus-4-8[1m]`，
使批量路径下"用户敲了"与"没敲"不可分，是本节整套优先级无法成立的根源。

**关键：在 ML 入口解析一次、当数据往下传，绝不逐节点 config_lookup（评审 blocker 2，
修法 A，已批准）。** 原因是 Isabelle config 的可见范围：`declare [[…]]` 的值只沿
theory 依赖图 parent→child 流动，祖先 theory 看不见。而 interpretation 的调用链
（`interpret_with_parallel` → `map Context.theory_of roots` → `collect_cone` →
`interpret_cone` 里 `interpret' (Context.Theory thy)`，`semantic_store.ML:1489-1496`）
**在每个 cone 节点用该节点自己的 theory 重建 context**。若在此逐节点 `config_lookup`，
`Config.get` 就落在 `HOL.List` 等祖先 theory 上，读到 `K ""` 默认 → Python 侧 `or` 回落到
`ClaudeCode`。**全锥静默跑在 ClaudeCode 上，无报错，`b"driver"` 忠实记着 ClaudeCode——
方案唯一目的（降本）被静默反转。** embedding 的 `query_knn` 没这问题，是因为它的 `su`
建自**调用者** context（`:1642`），先例不适用于逐节点重建 context 的 interpret。

修法：给 `interpret_with_parallel` **加一个首参**——读配置的 context——在那里
`Config.get_generic` **解析一次**，把那一个字符串当普通字段塞进现有 `rpc_arg`，
一路传给 `interpret_cone` / `interpret'` / `make_interpret_file_cmd`。
⇒ **不再需要 `Config.lookup` callback**（上一轮那个 blocker 一并消失），
Python 侧不调 `config_lookup`；该选项也因此**不做** `Config.register_rpc_option`
——注册了只会诱使将来有人逐节点查一次，正好踩回 blocker 2。

加首参而不是"从 `hd roots` 读"：四个调用点里有一个（`make_interpret_theory_callback`，
`:1578`）的 roots 是 `map (Theory_Hash.resolve_theory context) names` 解出来的**别的**
theory，`map Context.Theory` 一做，caller 的 `declare` 就没了。加首参强制每个调用点
**明说配置从哪来**，四处一眼可查：`interpret`、`interpret_command.ML:118`、
`semantic_interpretation_app.ML:73`（无用户 context，用第一个 root）、上述 callback（用 caller context）。

⚠️ 这**改变了 interpret 命令的 RPC 参数形状**（`rpc_arg` 加一个字段），Python 侧
`_interpret_file` 解包要跟着改。这是生产上唯一在跑的路径，故放在步骤 2、单独回归。

`write_cost` 的 `b"model"` 用**解析出的** model（不是模块全局），并加写 `b"driver"`
（新字段，读侧 `.get` 兼容旧记录，无需迁移脚本）。

回归测试：在**后代** theory 里 declare 该选项，断言一个**祖先** cone 节点的 `b"driver"`
等于声明值而非默认——这正是 blocker 2 的复现点。

### 4.10 并发

并行由 Isabelle/ML 驱动（`Tools/semantic_store.ML:1394`，每个 cone 节点一个 Future）。
每节点独立 `interpret_file` 协程 → 独立 driver 实例 → 独立 `AsyncCodex`（各自一个
`codex app-server` 子进程），`_local_task` contextvar 已保证隔离。
**MCP server 是进程级单例，各节点是它的一个 session（§4.2），不是各起一个 server。**

⚠️ 进程数 = `max_threads()` 个 app-server 子进程，**全部共用真实 `~/.codex`**（标准用法，
§4.6）。由此带出一个待实测的隐患：token 到期需刷新时，单次 refresh token 被 N 个进程争抢，
可能只有一个成功、其余失败。若实测属实，解法是**在 fork 出并发之前先跑一个空 turn 触发
一次刷新**（此时 token 已新，并发期内不会再触发），而不改标准用法。若实测发现 app-server
子进程本身开销可观，可让多个 driver 共享一个 `AsyncCodex`——单例 MCP server 已能容纳。

`_Semantic_DB` 的 CONCURRENCY INVARIANT（`semantics.py:156-171`：LMDB 写事务内不得
`await`）必须遵守——`write_cost` / `write_answer` 保持同步。

## 5. 分步实施

> **实施状态（2026-07-27）：步骤 1–6 已落地并提交，步骤 7 待跑。**
>
> | 步骤 | 提交 | 验证 |
> |---|---|---|
> | 1 纯重构 | `c5163ec` | fake-driver harness；分类器测试改指新位置后全绿 |
> | 2 配置入口解析 | `9f916c4` | `Test/Interpretation_Driver_Config_Test.thy`（`isabelle build -d . -d Test` 通过）+ 四级链单测 |
> | 3 HTTP MCP server | `1bb612b` | 真实 loopback HTTP 往返；翻译层与 contextvar 重绑各自**验证过"去掉就失败"** |
> | 4 价格表 | `dbdc290` | 载入/缺失/半填/算术单测 |
> | 5 Codex driver | `bd5fbda` | 成本差分、错误分类（全枚举 + 全对象变体 + HTTP 状态）、两处拒绝启动 |
> | 6 打包 | `10833a1` | setuptools 自己的 `find_data_files`；另实建 wheel 核对六个 SKILL.md |
>
> **有意未做**（非遗漏）：
> - §4.8 辅通路只用于「额度用完 vs 没钱了」的分辨与 log `resets_at`；**不**用 `resets_at`
>   替换 `_run_agent` 里硬编码的 `sleep(1200)`（用户 2026-07-27 定：固定 20 分钟即可）。
> - §4.3 提到的 `AsyncTurnHandle.interrupt()` **未接线**。中断在本子系统里本来就是"按设计硬崩"
>   （答案与成本都已逐条落盘、重跑可续），Claude 路径同样不接；driver 的 `__aexit__` 关掉
>   client 已足以让 app-server 随之退出。
> - §4.6 的 `SkillInput` 强制灌入未做（计划本就写"实测模型行为后再定"）；skill 走
>   `<cwd>/.codex/skills/` 自动发现。
>
> **conda**：不带 Codex（用户 2026-07-27 决定）。`openai-codex` 只在 PyPI 上，
> conda-forge 的 `codex` 是另一个东西（Rust CLI，SDK 从不查 PATH 故用不上）。
> 理由已写进 `conda/recipe.yaml` 的 run 段注释。
>
> **价格与模型 id（2026-07-27 查证，两个 agent 独立取证、数字一致，来源
> `developers.openai.com/api/docs/pricing` + `learn.chatgpt.com/docs/models`）：**
>
> - §4.5 示例里的 `gpt-5.5` 价格已被真值取代。模板现在收录 6 个模型
>   （`gpt-5.6-{sol,terra,luna}` / `gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini`）。
>   `gpt-5.3-codex-spark` 有意不收：它只对 ChatGPT Pro 开放、**没有公开的每 token 价格**，
>   拿别的模型的价格顶上会产出一个看着合理的错数。
> - ⚠️ **`gpt-5.6` 不是真 slug。** 它出现在 codex 官方文档示例里，但不在模型目录中
>   （本机 `~/.codex/models_cache.json` 实查：只有 `gpt-5.6-{sol,terra,luna}` /
>   `gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini` / `gpt-5.3-codex-spark` / 内部的
>   `codex-auto-review`）。默认取 **`gpt-5.6-sol`**——codex 自己的文档默认
>   （"the default Power setting, which uses gpt-5.6-sol"），且模板给它定了价，
>   所以 `--driver Codex` 开箱能跑。单测钉住"模板必须给默认模型定价"。
> - ⚠️ **记进库里的美元数对 ChatGPT 订阅是名义值。** 订阅模式下 codex 用量走的是
>   五小时窗口的 credit 配额，不按美元计费；我们算出的是"这些 token 按 API 标价折合多少钱"
>   ——用于两条 driver 横向比较是对的，当账单看是错的。API key 模式下它才是真账单。
> - ⚠️ **两处已知少算，均接受**：(a) GPT-5.6 家族对 **cache write** 另收一档
>   （未缓存 input 价的 1.25 倍），但 SDK 的用量结构里**根本没有 cache-write 字段**
>   （只有 input / cached input / output / reasoning output / total），无从计算；
>   (b) 单次请求 input 超 272K 时按 2× input、1.5× output 计，未建模——本管线的批次远小于此。
> 以上要点已逐条写进 `interpretation_config_template.yaml` 的注释。

1. **纯重构，零行为变化**（单独提交）。抽 ABC + 注册表，现有路径搬进
   `interpretation_driver/claude_code.py`，`_run_agent` 改走 driver，接上 `on_context_reset`。
   **验收**（评审 major 3）：
   (a) 把 `test_interpretation_error_classifier.py:13-21` 的 import 改指
   `interpretation_driver.claude_code`（或在 `semantic_interpretation` 里 re-export
   `_handle_message`），作为本步显式交付物，测试全绿；
   (b) 新写 fake-driver harness：脚本化 `run_turn` 序列驱动 `_run_agent`，覆盖 batch 推进、
   `answer` 写入、可重试错误、missing-entry 重试、一次 context reset，断言 `task.results`、
   `write_answer` 调用序列、`write_cost` 增量。
   **不用**"与重构前逐字节一致"做验收——有缓存时 `if uncached:`（`:994`）短路使其恒真，
   清缓存后 `ThinkingConfigAdaptive`（`:1044`）的非确定采样使其恒假。
2. **ML 侧配置入口解析（修法 A）**：`interpret_with_parallel` 加读配置的首参、在那里
   `Config.get_generic` 解析一次，塞进 `rpc_arg` 往下传；声明配置选项
   `Semantic_Embedding.interpretation_driver`（**不** `register_rpc_option`）；四个调用点
   各自明说配置来源；Python `_interpret_file` 解包新字段并按 §4.9 四级链解析成
   (driver_name, model)；`collect --model` 换成 `--driver`、模块全局
   `interpretation_model` 退休；`InterpretationTask` 记住解析后的 driver+model，
   `write_cost` 用它写 `b"model"` 并加写 `b"driver"`。
   **回归测试**：后代 theory declare、断言祖先节点 `b"driver"` = 声明值。
   改 `.ML` 后**重启 REPL 即可**，不需要 rebuild。
3. **MCP server（单例 + 路由 + 结果翻译层）**：`interpretation_driver/mcp_server.py` + 单测。
   验收（评审 major 3）：**不是**"断言返回与 handler 一致"——坏代码恰好满足它（structuredContent
   与 handler dict 逐字节相同）。改为断言 (a) `result.content[0].text` = handler 的纯文本、
   **无 `json.dumps` 外壳**（用 `_answer_tool` 的批次翻页返回值当 fixture）；(b) `is_error=True`
   的 handler → `result.isError is True`。另加单测：起两个交错生命周期的 session，断言
   `signal.getsignal(SIGINT/SIGTERM)` 前后是同一对象（守 major 5，即便单例也钉住不碰信号）。
4. **配置层**：`interpretation_config` + pricing 加载 + `__aenter__` 校验 + 单测。
5. **Codex driver**：`interpretation_driver/codex.py`，接进 `_run_agent`。
   成本核算按 §4.5 写单测（构造多请求 turn 的 usage 序列，断言用的是 total 差分）；
   错误分类按 §4.8 写单测（构造各 RootModel 变体，断言网络类 → Transient 而非 Fatal）。
6. **打包**：与建 `Agent_Interpretation_Dir/.codex/` 同一提交，往 `pyproject.toml` 的
   `package-data` 加 `"Agent_Interpretation_Dir/.codex/**/*"`（紧挨现有 `.claude` 条目，
   保留其"dot component 必须写出"的注释）；`.codex/skills` 做成指向 `../.claude/skills` 的
   目录软链（setuptools 的 glob 跟随软链，已验证）。打包测试：build wheel，断言三个 SKILL.md
   在 `.claude/skills/` 和 `.codex/skills/` 下都存在且非空。
7. **端到端**：同一个小 theory 两个 driver 各跑一遍，人工对比 interpretation 质量与成本。

## 6. 评审结论的迁移

**两轮对抗评审**（各 4 视角 × 2 轮，22 条 → 裁判保留 6 条）。第一轮审 v1（裸 API），
第二轮审 v4（本文的前身）。以下是**第二轮（v4→v5）**的 6 条，全部已并入：

| v4 评审结论 | 处置 |
|---|---|
| **blocker** 错误分类把 `codex_error_info` 当枚举，实为 RootModel 联合，网络故障全落进杀 cone 的分支 | §4.8 重写：先 `.root` 再分派，未识别→Transient |
| **blocker** ML config 逐节点解析，祖先锥读默认值，静默反转降本目的 | §4.9 修法 A：入口解析一次往下传 |
| **major** `ToolCall_ret` 非 MCP 形状，结果被 JSON 包裹、`is_error` 丢失 | §4.2 加独立翻译层 |
| **major** 健康检查 `_request_raw` 异步侧不存在、且未限定作用域 | §4.2 改 `request(response_model=)` + `threadId` |
| **major** 每实例 `uvicorn.serve()` 污染进程信号，host 杀不掉 | §4.2 翻转为单例 server |
| **major** `.codex/skills/` 未进 package-data，安装即丢 | §5 步骤 6 |

第一轮（v1）的 6 条早已并入并大多随架构演进消解，从略。

⚠️ **本文（v5）的最新改动未经过第三轮评审。** 裁判指出 v4 有四条 major 源于
「§1.1 把在**不同 client 类 / 不同作用域 / 不同 SDK 路径**上测得的结果记成普遍事实」——
现已按其建议给 §1.1 **每条标注 provenance**（`[源]/[抓包]/[会话]/[实测]/[推断]`，并写明测的
路径），站不住的（错误分类、`ToolCall_ret` 翻译层）已列入 §1.3 待实测。

## 7. 已知风险

- **质量不对等**：codex 路径没有 Claude Code 的自适应 thinking、subagent、WebSearch。
  两个 driver 的产出混进同一个 LMDB（已确认接受）；`b"driver"` 让这在 theory 级可追溯，
  entity 级不可追溯。
- **SDK 年轻且有已知 bug**：`CodexConfig.experimental_api` 默认 `True`，`codex app-server`
  自标 `[experimental]`，`_is_server_overloaded` 的 case bug 已证实。方案刻意绕开了
  `run()` / `is_retryable_error()` / `request_with_retry_on_overload` 三个不可靠面。
- **静默失败面多，且 `thread_start(config=)` 会接受任何未知键**（实测：瞎编的键和垃圾值
  都不报错）。MCP 未注册、`SkillInput` 路径未注册、配置键拼错——全都是无报错地继续跑。
  故 §4.2 / §4.6 要求 `__aenter__` 里做显式断言，且**任何新配置键都必须用行为验证
  它真的生效**，不能以"没报错"为准。
- **协议 schema 与实际行为不一致**：`thread/compacted` 在 v2 schema 和 SDK 的
  `notification_registry` 里俱全，实际却从不发送。**读 schema 不能替代实测**——
  本方案有两处（usage 结构、该通知）就是这样栽的。
- **打包漏项前科**：`.claude/skills` 曾因 setuptools glob 跳过隐藏目录被漏进 wheel
  （已修，commit 5c6eefb），`.codex/skills` 是同一个坑的双胞胎。§5 步骤 6 的打包测试是唯一
  拦它的东西——未注册 skill 路径静默丢弃（§1.1），装了包的用户会以全价拿到无知的
  deformalization，与正常跑无法区分。
- **两个 driver 的错误分类极性相反**（§4.8）：codex 未识别错→有界重试，Claude 未识别错→
  直接失败。有意为之（故障剖面不同），但削弱了"未知故障要吵得响"的原则；靠每分支
  log `type(root).__name__` 补偿。
- **`_answer_tool` 的 surrogate 剥离**（`:496`）driver 无关，继续生效；但 codex 端对孤立
  UTF-16 代理项的行为未验证（Claude 侧是 API 400 → PoisonedSession）。
