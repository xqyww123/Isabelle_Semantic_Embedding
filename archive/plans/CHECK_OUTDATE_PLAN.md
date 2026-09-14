# 语义解释管线的增量失效改造 — 实施计划（v3 定稿）

状态：**设计定稿，全部条目经用户逐项批准（2026-07-21），待实施**
增补：2026-07-27 逐项批准 §8「dry run 统一与 update_interpretations」及 §3.4 WIP
不写 `finished`；前置清障（平铺路径删除）同日落地（`FLAT_PATH_REMOVAL_PLAN.md`）。
同日晚批准：**种子拷贝整体删除（§6）、`merkle_of_disk` 全线退役（原 A3）、WIP
theory 级跳过判据改用 (进程标识, theory serial) 对（§3.4）**；「加载时刻源
digest」三路探针结论归档于 §3.4 尾注。同日（终）：全计划 17-agent 对抗评审
通过并修复（F1/F3/F6 采纳，F2/F4/F5 驳倒；记录见 CHECK_OUTDATE_REMAINING.md）。
**实施进度（2026-07-28）**：M1–M4 已全部落地、验证、提交推送（含阶段 A/B、
步骤 1–10、14、15、15b；gate 已默认 true；锥回调 wire 实为五元组，第五位
`include_context` 携带「context 原样作根」裁定，用户批准）；过夜日志与验证
记录见 CHECK_OUTDATE_REMAINING.md 顶部。未做：步骤 11、13、16、17–20（M5）。

**执行入口**：本文件自足；从 §12 里程碑注记开工，**M1 = 步骤 15 的五件事**
（锥回调 schema 扩 `dry_run` 位、不 mark 不 skip 调度路径、`interpret'` 两段
拆分、`plan_interpretation` 降私有、命令 :65 调用点升级），全部可在现有代码上
落地。前置清障（平铺路径删除）已于 2026-07-27 落地并推送（Semantic_Embedding
`fcbe8fb`；方案与验证存档 `FLAT_PATH_REMOVAL_PLAN.md`）。文中源码行号以写作
时点为锚，实施时按符号重定位（interpretation driver 重构已造成漂移）。
涉及：`contrib/Semantic_Embedding/`、`contrib/Isabelle_RPC/`
历史：v1（独立机制）、v2（统一换 key）均废；演化过程与批准记录见
`CHECK_OUTDATE_REMAINING.md` 与 `CHECK_OUTDATE_PLAN.md.bak`（整理前全文 917 行）。
本文件只含定稿设计。

---

## 术语表（规范用语——同一概念永远只用同一个词）

| 术语 | 定义 | 废除的别名（勿再使用） |
|---|---|---|
| **uk**（universal key） | 实体记录在 LMDB 的完整 key：16 字节 theory hash ++ 1 字节 kind 标签 ++ 载荷 | entity key |
| **theory hash** | `Theory_Hash.hash_of` 的输出，uk 的前缀；按 theory 类别取下面两种之一 | theory key、前缀 hash |
| **Merkle hash** | persistent theory 的 theory hash：`xxhash128(文件字节 ++ 递归父 Merkle hash)`，WIP 位=0 | 内容 key、content hash、Merkle key |
| **名字哈希** | WIP theory 的 theory hash：`FNV-1a-128(theory 长名)`，WIP 位=1 | FNV key、名字 key、稳定 key、FNV 回退分支 |
| **WIP 位** | theory hash 首字节最低位：0 = persistent、1 = WIP | LSB 约定 |
| **thm128** | 定理 statement 的 128 位内容摘要，定理类 uk 的载荷 | — |
| **semantic digest** | WIP 名字寻址实体自身语义内容的摘要（增量机制字段）；对改名不作不变处理 | digest（单独出现即指它） |
| **dry run** | 模式 4 的运行形态：两级扫描只数不做（§8），返回（theory 名单, 种子实体数 n）；**全系统唯一的工作量计量实现**。n 是各 theory 种子集按 run 前库状态之和：单个 theory 内、对同一库状态，数到的种子全部发送（依赖者不计），跨锥则**上下界都不是**（上游 UNCHANGED 会挡住下游已数的实体），零处精确（`contrib/Semantic_Embedding/ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` §5.2）；用户可见文案一律写 "About n" | 报价、报价单 |
| **semantic change gate** | 重解释一个 tracked 实体之后（无论它是因 digest 变化进了种子集，还是被上游的 CHANGED 裁定纳入），比较新旧两段解释是否同义（LLM judge，以两段 embedding document 的 cosine ≥ 0.90 作后备）；只有判 CHANGED 才 mint version、才把依赖者纳入重解释（同上计划 §3、§5.4） | gate（单独出现即指它） |
| **eff\*** | §4.1 的 eff 的屏蔽版：沿依赖闭包递归时，被 gate 判 UNCHANGED 的 hop 之下的信号不再抬升（同上计划 §4） | — |
| **update_interpretations** | Python 策略壳（§8）：gate + dry run + 阈值 400 + 询问，包住锥回调；aoa 启动与 `_auto_embed` 段(1) 的唯一入口 | interpret_outdated、阈值策略函数 |
| **theory serial** | `Context.theory_identifier` 的值：theory 值不可变，重精化必造新值、必换 serial；WIP 跳过判据存 **(进程标识, theory serial) 对**（serial 是进程内计数器，跨会话必配进程标识防碰撞） | — |
| **名字路径**（the named-fact source） | 常量定义命题的首选来源（§7.3 第 1 条，2026-09-14）：定义命令以常量全名命名的 fact `c.simps`、`c.psimps`、`c_def`，依次取、逐级过保护，第一个非空者即用；三者都空才走结构路径（Defs、Spec_Rules） | 名字查询 |
| **保护**（the guard） | 名字路径对 `.simps`/`.psimps` 的过滤：去掉前提后的结论是等式（`≡` 或 `=`）且左边头部是该常量本身；`_def` 不过保护 | 形状检查、严格保护 |
| **dep 统一判据** | §4.3：对每条 dep 边重解析目标实体的当前 uk 并与存储值比较，失配（含仅 WIP 位翻转）⟹ 过期 | 边界判据、边界 uk 判据、边界失效判据 |

---

## 1. 目标：四个模式

| # | 模式 | 状态 |
|---|---|---|
| 1 | 全量解释新 theory，已解释则跳过 | ✅ 已有（`interpret_with_parallel false`） |
| 2 | force：无视 theory 级 `is_interpreted` gate，强行走完该 theory 及**全部祖先**，实体级缓存保留（已解释**且不过时**的实体不重复解释） | ✅ 已有，零改动（措辞 2026-07-27 重签：过期实体被重做是模式 3 判据的自然结果，非 force 新增行为） |
| 3 | 给定 theory，找出未解释或过时的实体，增量解释这些 | ❌ 本计划主体 |
| 4 | dry-run：列出需要解释的实体，不调 LLM | ❌ 需要新入口（落地形态：§8「dry run 统一与 update_interpretations」） |

模式 4 = 模式 3 在调 LLM 之前返回。
附注：今天「改文件 → key 漂移 → 全 theory 重跑」是 key 机制的连带效果，不是
force 做的；该效果对 persistent 侧继续存在，对 WIP 侧由增量机制取代。

---

## 2. v3 架构总纲

**persistent/WIP 二分保留；增量机制只作用于 WIP。**

- **persistent theory**：uk 前缀 = Merkle hash（既有机制原样保留）。内容变 →
  hash 变 → 下游锥 uk 全漂移 → 粗粒度自动失效。对库合理；key 不换、零迁移。
- **WIP theory**：uk 前缀 = 名字哈希（`theory_hash.ML:180-186`，既有正式设计
  原样沿用）——与内容无关、跨编辑跨会话稳定。增量机制的四字段
  （semantic digest / deps / version / interpreted_at）只存在于 WIP 记录。
  实施时在名字哈希分支加注释记录新依赖方；以探针确认 `Resources.loaded_theory`
  的分支边界即 WIP 的定义。
  **边界测得事实（2026-07-28 探针，用户确认合意）**：`isabelle build` 下在建
  session **自己的 theory 也是 loaded_theory = true**——batch 构建的 theory 从头
  就走 persistent 分支（按文件算 Merkle key，与之后加载该 heap 的会话算出的 key
  相同）。因此**实体级增量只发生在交互加载场合**（jEdit/VSCode/REPL scratch）；
  batch 反复构建享受的是 persistent 侧的 key 漂移粗粒度重做。§3.4「三条加载路径
  通吃」中批处理一条由此是空虚成立（batch theory 根本不入 WIP 判据）。探针存档：
  `Test/Test_All.thy` 的 WIP 边界探针。
- **失效责任分工**：
  - theorem-alike（占库 88%）：uk 含 thm128，statement 一改即新 uk，单实体粒度
    自动失效，无需 digest；
  - WIP 名字寻址实体中 **constant / type / class / locale 四类**：uk 不随内容变，
    由 semantic digest + version/eff 机制负责（本计划主体）；
  - **method 与 theorem collection 永不过期**（锁定决策，
    `doc/invalidation_limitations.md` #4/#5：`Method.get_methods` 等未导出、
    改 Pure 已否决），永不过期即终态。
- ~~R2 同步按 WIP 位从 push/pull 排除~~（push/pull 已随 LAYERED_PLAN 退役，
  本条语义翻译为 CI export 的过滤 job，见 §9）。
- `clean_wip` 保留（WIP 垃圾回收的本职）。

⚠️ `expr` 字段不可用作变更判定：它是展示文本（`mk_prop_str`，
`semantic_store.ML:436-467`；常量分支 `:458-461` 只打印类型）——重排版假阳性、
改定义体假阴性，两头都错。必须用 semantic digest。

---

## 3. 存储设计

### 3.1 Record 扩四字段

`semantics.py` 的 `Record`（`:180-228`）尾部追加：`semantic_digest`、`deps`、
`version`、`interpreted_at`。编解码是位置式尾部追加：`:265` 的
`vals += [None] * (8 - len(vals))` 改 8 → 12，旧记录自动读为 None。

- ⚠️ `_decode` 对 `len(vals) > 8` 静默截断（`:266` `vals[:8]`）——降级运行旧代码
  会丢新字段，改 codec 时同步处理。
- 需补新字段值的构造点仅两处：`semantics.py` 的 `Gate_Writer.put_interpretation`
  （原 `semantic_interpretation.py` 的 write_answer；semantic change gate 落地后
  Record 共 15 字段，`RECORD_FIELD_COUNT`）、
  `Isa-Mini/.../mcp_http_server.py:2318`（experience，四字段恒 None）。
  `update_expr`（整表重打包）与 `_migrate_constituent_records`（codec 升级后经
  扩展 Record 往返）自动正确。
- 测试补 12 字段用例：`test_experience_index.py:54,:290`、`test_document_text.py:102,:116`。

### 3.2 deps 字段

**格式**：每个元素存 **uk**（`(kind, 名字)` 在 Python 侧拼不出 LMDB key，且 uk
兼任 dep 统一判据的时刻印记，见 §4.3）。

**内容**（放哪些边）：
- constant：own-defining-axioms（§7.3 第 1 条：先取以常量命名的 fact `c.simps`/`c.psimps`/`c_def`，没有才取过滤后的同 theory Defs 公理）提取的命题中出现的
  constant/type/class/locale；
- type：定义结构（typedef 定义集合、ctr_sugar 等）中的实体；
- **class / locale 统一走 locale dependencies 表 + serial 过滤**：
  条目 serial < 宿主 locale entry serial ⟺ 定义时 import（条目 serial 是注册
  事件的时间戳，与目标无关；Main 243 locale/537 条实测零反例）。class 借其
  class-locale 取直接 dep（def-time import 实测恰等于声明直接超类）；
  `subclass`/`sublocale` 的事后条目被过滤，`interpretation` 与 `instance ⊆`
  根本不进该表——**注册边由构造零残留排除**。
  序关系由构造成立：定义时边的记录在阐释导入表达式时构造，是注册动作的
  输入，serial 单调（2026-07-30 裁决：删除曾规定的位置护栏断言——实施评审
  查明它把「关键字与名字分行」的合法排版误判为失败、且在 id-only 的 PIDE
  位置下空虚恒真；抽取类实施错误由 §14 敏感性断言把守）。
  def-parse（解析 `Axclass.get_info` def 的 OFCLASS 合取）**只进测试**：
  敏感性套件断言两种取法全 Main 一致。无 class-locale 的老式公理化 class
  （`HOL.type` 等）deps 取 `[]`。

### 3.3 全局计数器

`0xF0` 单键（非 Record）。全库游标扫描核实：长度判别式使其不被误当 entity；
需显式处理的两处统计失真——`check_consistency` 的记录计数、
`isabelle_semantics.py` remove 路径的 `key[:16]` 归属集——各加
`len(key) < 16: skip`。计数器自增必须与 Record put 同一写事务（单调性前提）；
**读写 user env 直达，不经分层 facade**（§9）。

### 3.4 theory 状态记录

WIP 的 thy-status 记录加 **(进程标识, theory serial) 对**（存该次成功解释时刻
loaded theory 的身份）；`is_interpreted'`/`mark_interpreted'` RPC 加该对作参数
（`semantic_store.ML:221-239`、`semantics.py:408-433`）。**embed 侧同构一套**：
`is_thy_embedded`/`mark_thy_embedded`（`semantics.py:1151-1181`）。

**判据（2026-07-27 用户裁定，取代先前的磁盘 Merkle 方案）**：WIP 跳过 ⟺ 存储的
(进程标识, theory serial) == 当前 loaded theory 的值。健全性根据：theory 值不可
变，内容要变只能重精化造新值、必换 serial；父值变则子值必重建 ⟹ 祖先变化自动
传播；且判据长在 **loaded 世界**自身——磁盘代理的两个撒谎方向（buffer 超前磁盘、
磁盘超前 loaded）从根上不存在，jEdit/VSCode/批处理三条加载路径通吃（ML 侧不区分
编辑器）。进程标识 = ML 进程启动时生成一次的随机标识，**跨会话必须比对**：serial
是进程内计数器，不同会话可碰撞出相同值，裸 serial 会假跳过。代价画像：每个新会话
对工作集首扫一次（digest 层随即归零，亚秒级）；同内容重精化也换 serial ⟹ 多余
重扫一次，digest 层立即回答无活，无害。

**实施注记（2026-07-27 批准，原 B1 剩余部分，免单独成文并入本节）**：
1. **删除 `persist_wip`**（semantics.py:136，环境变量 `SEMANTIC_PERSIST_WIP`）及其
   三个守卫点（:592 `mark_interpreted`、:1392 `mark_thy_embedded`、:1913 嵌入批量
   路径）——新式 WIP thy-status 不撒谎，"要不要写"的开关失去存在理由，且守卫
   不删新记录写不进去。
2. **`_user_config.py` 注释改写**（`env_bool` docstring，现 :113）：它拿
   `SEMANTIC_PERSIST_WIP` 的 `os.getenv(x,"") != ""` 解析惯用法当反面教材；旗标
   删除后指涉对象消失，教训保留、引用改为一般性表述。
3. **serial 取值纪律**：写入的 (进程标识, theory serial) 从**管线中传递的被扫描
   theory 值**上取；**禁止写入时按名字或 context 重解析取值**。theory 值不可变
   ⟹ 同一值任何时刻取 serial 相同，无「枚举 vs 写入时刻」之分（2026-07-27
   用户纠正：早先「枚举时刻快照」的时间性框架有误——与写回纪律 4 的 eff 快照
   不同类，eff 读可变全局状态、时刻有意义；serial 是不可变值的属性，唯一危险
   是重解析换了值、给未扫内容盖章）。自然实现已满足：`interpret_cone` body
   闭包捕获 `thy`，`mark_interpreted thy` 同值（semantic_store.ML:1536-1541）。

**WIP 的 thy-status 不写 `finished`（同日用户裁定）**：`finished` 的语义是「该
key 下的解释已完成且永久可信」，只对内容寻址的 Merkle key 成立；WIP 名字哈希 key
与内容脱钩。记录形状 = 计费字段 + (进程标识, theory serial)——`finished` 字段
**不存在**（不是写 False：留一个无人读的字段会诱使未来代码去读）。过渡安全：旧
判定对无 `finished` 字段的记录读缺省 False，不会误跳过。embed 侧同构适用。

> 探针归档（2026-07-27，三路并行核查「加载时刻源 digest」可行性，为 serial 判据
> 的替代方案）：批处理路径 digest 在 `Resources.check_thy` 有算、存 `Thy_Info`
> 全局表，但签名封死、theory 值不携带、`Session.finish` 抹除——取用须 ~15 行
> Pure 补丁（heap 全量重建）；jEdit 全文以逐命令 token source 驻留 `Document.state`
> 但 `abstype` 封死，唯一官方出口只在 theory 完整跑完后触发；VSCode 与 jEdit 在
> `Document.Model` 层完全汇流，ML 侧不可区分。结论：源 digest 路线仅在需要
> **跨会话**跳过时值得重启（Pure 补丁方案 A 已探明），serial 判据零补丁零成本胜出。

---

## 4. 过期判据

### 4.1 eff：递归求值定稿

```
E 的 interpretation 过期  ⟺  eff(E) > interpreted_at(E)

eff(E) = max{ version(X) : X ∈ E 的依赖闭包（含 E 自身），环按 SCC 折叠 }
```

`version(E) := ++全局计数器`，在扫描发现 E 的 semantic digest 与库存不同时 bump。

**2026-09-12 起（semantic change gate 落地）判据改为 eff\***：digest 失配只把 E
送进种子集去重解释；version 只在 gate 判 CHANGED 时 mint（重解释之后），扫描不再
bump；闭包递归时，被判 UNCHANGED 的 hop 之下的信号不再抬升。本节以下的「扫描时
bump」按此读；细节见 `contrib/Semantic_Embedding/ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md` §4。

**「全局」是判据成立的关键**：任何一次变更拿到的号大于历史全部取值，max 立即抬升
（每实体各自计数则小 dep 会被吞——sum 提案由此产生、由全局计数器化解并正式放弃；
max 的幂等性是 memo 递归 O(V+E) 的前提，sum 在菱形依赖下无法 memo）。

求值 = 带**全局数值 memo** 的递归 DFS，作用在「本批实体 ∪ LMDB 库存」的并集上：

- 首访批内实体先比 semantic digest，变了**当场 bump**（digest+version+deps
  同一次 Record put）；「哪些 digest 变了」是本批固定事实，首访即 bump ⟹
  memo 永不作废。
- visited-set 盖全部环（只跳过起始节点不够——环可整体位于前向区域）。
  SCC 内 version 折叠取 max 对**环内**信号无损（环内成员同命令定义、一起 bump），
  但 memo 的定稿必须以 SCC 为整体（Tarjan lowlink：任何节点在其 SCC 根出栈前
  不得写 memo；根出栈时把 SCC 统一值——成员 version 与全体成员环外后继 eff
  的 max——一次性写给全部成员）。逐节点定稿会让非根成员的 memo 漏掉仅经
  环边可达的**环外**贡献，造成随条目顺序确定复现的假新鲜
  （2026-07-28 对抗评审第 1 条，阻断级，已实测复现）。
- memo 存数值 eff（实体自身属性，跨判定对象复用）；布尔「变没变」相对
  interpreted_at 不可复用，最坏 O(V·E)，禁用。
- 批外实体沿其库存 deps 用**同一条递归**继续算（库存读取经分层 facade，§9）。
  两个被构造出反例的捷径**禁用**：
  只读 version（漏「已消化上游变更」的传导）；`max(version, interpreted_at)`
  （漏传递变更）。
- 惰性优化（语义等价）：顺序处理时后向边直接命中 memo，只在遇前向边时展开递归
  （前向边实测占 theory 内边 1.1%）。
- 前向边**不丢弃**（旧版四类豁免体系整体退役；同 theory 延迟定义的第五类漏洞
  随之消灭）。

### 4.2 不变量

| | 内容 |
|---|---|
| I1 单调 | version 只增不减（全局计数器 + 同事务自增） |
| I2 何时 bump | 名字寻址四类：gate 判 CHANGED 时（重解释之后；扫描不 bump）；theorem-alike：永不（key 自失效） |
| I3 eff 不减 | deps 变 ⟹ 声明变 ⟹ digest 必变 ⟹ 进种子集、重解释、过 gate，判 CHANGED 即 bump（deps 冻结取法下无例外）。注：此链只覆盖 dep **集合**的变化；dep 目标实体的 **uk 值**漂移（翻转/重 key）不经 digest 链，由 §4.3 统一判据负责 |
| I4 幂等 | 查而不修；interpreted_at 只在重解释时更新，或在同一 run 中被后来 mint 的依赖抬升（SEMANTIC_CHANGE_GATE_PLAN §5.3.1 snapshot raise） |

### 4.3 dep 统一判据（2026-07-27 批准；原「边界判据」的推广，A2 终批）

扫描时对 deps 中**每条** dep 边——**不看存储的 uk 的 WIP 位**——重解析该边
目标实体的**当前** uk：

```
存储的 uk ≠ 目标实体的当前 uk（含仅 WIP 位翻转）   ⟹  E 过期，进待办集
相等，且目标所在 theory 是 WIP（WIP 位 = 1）        ⟹  version/递归 eff 接手
相等，且目标所在 theory 是 persistent（WIP 位 = 0）  ⟹  新鲜，无事
```

- **为什么推广**：原「边界判据」只对存储的 uk 的 WIP 位 = 0 的边做比较，
  WIP 位 = 1 的边一律免检直走 version 路。目标 theory 从 WIP 翻成 persistent
  后实体搬进 Merkle keyspace，version 路拿旧 uk 查库永远安静（`clean_wip` 后
  查无记录读 0；未清则读到 version 永不再 bump 的僵尸记录）——**死边**：
  目标此后一切变化传不到 E，E 的解释永久过期且不可见。统一判据下比较对
  所有边发生，翻转只是「uk 变了」的普通原因，不再是特殊情形。
- **成本≈零**：目标实体的当前 uk 本就是模式 3 扫描随 entries 送到 Python 的
  deps 载荷（§12 步骤 9，已含在 M0 实测 ~92µs/实体内）；存储的 uk 在 Python
  自己的记录里。新增仅待办集过滤段的逐边字节比较（~11.7 边/实体，全锥毫秒级），
  零新增 RPC、零新增 ML 工作。
- 重解释后 deps 更新为各目标实体的当前 uk。Merkle hash 递归折入祖先 ⟹ 不漏报；
  粒度 theory 级 ⟹ 会多报（与 persistent 侧自身哲学同构）。persistent 记录
  零新字段——变更信号是内容寻址 uk 白送的。
- 原 A2 讨论所遗「读取时种子拷贝」已随种子拷贝整体删除（§6）自然消解。

### 4.4 取值约定

- dep 无库内记录（infra 目标，Main 上占 dep 目标 28%）：eff 贡献取 **0**。
  显式设计决定，limitations #1/#2 的接受理由覆盖（机制检测英文解释是否过时，
  非逻辑闭包）。`invalidation.ML:44-60` 与此冲突的旧注释在瘦身时重写。
- `version/interpreted_at = None` 读作 0（未知待重判，配「名字寻址 WIP 记录
  digest=None ⟹ 过期」）。
- **ε 纪元**：首写实体的基线值 = 写入时刻的计数器快照（正值）。
  **字面 0 禁止作为存储值**。

---

## 5. 发送序（serial）

`entry_ord`（`semantic_store.ML:394-400`）主键由源码行号改为 Name_Space entry
serial。行号序被证伪：生成物 binding 回落命令首行（三个 HOL 核心反例实测坐实），
动态加载 theory 更是完全没有行号。serial 序实测（9 theory / 10,758 条 theory 内
依赖边）：违反 118 条全部落入保留类，真反例 0，无 serial 实体 0，重复 serial 0，
跨加载层单调。

- **实现**：decorate-sort-undecorate——`sort entry_ord` 全文件唯一调用点（:1283）
  处新增 ~50 行 `serial_of`（按 kind 分派各 name space 查 `the_entry` 取
  `#serial`）；六个 getter、12 个生产点、元组形状全不动。
- 边角：动态集合成员借所属 collection 的 serial（`semantic_store.ML:1168-1185`）；
  `the_entry` 失败兜底 +∞ 排最后（`theory_structure.ML:203,262,289,352`，
  都是 theorem 类、不被依赖）。
- 角色：解释阶段 dep 的新鲜解释先落地供依赖者 prompt 引用 + 递归求值的顺序优化。
  eff 正确性**不**依赖发送序（§4.1 递归求值）。
- 顺带修显示 bug：ML 缺行号发 999999999（`semantic_store.ML:666`），Python 注释
  称 -1（`semantic_interpretation.py:209`），`format_entries:399` 把
  `[line 999999999]` 打进 LLM prompt。

---

## 6. 种子拷贝——已删除（2026-07-27 用户裁定）

原设计（WIP keyspace 冷启动时从 persistent 版本搬解释）**整体删除**：p→WIP
翻转后实体一律按 uncached 重新解释。删除理由存档：

1. **定理侧保不住**：定理 uk 的 XOR 前缀里，T 本地常量项只能拿按名字查到的代
   哈希顶上、无从验证——thm128 只证陈述未变，不证陈述中本地常量的定义未变；
   正确性要靠 eff 隔一拍兜底，窗口内检索照常端出过期文本。`xor_theory_prefix`
   整表重算又是标记在案的易错点。
2. **名字寻址侧更险**：无内容证明而按名字播种 = 过期解释配新 digest 永久盖章
   （原 F7 窗口的放大版）。
3. 安全版本的内容证明依赖 `merkle_of_disk`（原 A3），后者因磁盘代理的两个撒谎
   方向（buffer 超前磁盘、磁盘超前 loaded）整体退役——见 §3.4 判据。
4. 代价有界：p→WIP 翻转罕见；深库编辑（整锥翻 WIP）场景的重付由阈值对话框
   把关（n 大必先问）；原条件 B 本也救不了失配的下游锥。

净删除：`merkle_of_disk` 全部站点、F7 窗口、xor 整表重算、分层种源适配条款。
**反向拷贝（WIP→persistent 晋升）已裁决不做（§13，2026-07-28）：变成
persistent 具有发布含义，值得重新完整解释。**

---

## 7. 语义摘要库（semantic_digest.ML）

`invalidation.ML`（851 行）瘦身改名而来，定位是「WIP 名字寻址实体的语义摘要库」。

### 7.1 瘦身账

整块可删 ≈220 物理行（枚举层 :151-248 + 签名段 + 头部辩护 + `sem_theorem`
摘要半边）；env 六个可弃字段的散点改动仅 ~12 行（就地换取值来源）；保留块连注释
≈600 行。同步三件事：`synthetic_prefix`（:329，派生全部 payload 标签）趁尚无持久化
digest 定名并加「部署后永不可改」注释；重写 :44-60 与 limitations #1/#2 冲突的
旧注释；改名清单带上 limitations 文档中的文件名引用。

### 7.2 实体身份

主体改用 `Universal_Key.entity`（动态成员无名字、多定理 fact 成员名解析不了），
直接复用 `interpret'` 在 `:1275-1290` 算好的 `all_entries_with_pos`。

### 7.3 ⚠️ 最容易被误删、实则不可替代（历经实测的三条）

1. **own_defining_axioms 的过滤与来源**：类参数一律不保留定义
   （`Axclass.class_of_param`；`plus` 有 9 条下游实例定义、`less_eq` 16 条，
   而 `less_eq` 被 13.3% 的定理提及——直接调 `Defs.specifications_of` 会静默
   大规模误失效）；只保留同 theory 定义公理；Defs 为空退
   `Spec_Rules.get_global`（**不是** `retrieve_global`——Item_Net 对空 terms
   不建索引，`HOL.The`/`HOL.eq`/`HOL.implies` 实测中招）；这两处之前**先走名字
   路径**——取定义命令给常量起的 fact（2026-09-14，`ai-artifacts/fun_digest/PLAN.md`
   §10）：`c.simps`、`c.psimps`、`c_def` 依次，第一个过保护后非空者短路返回——函数包写进
   Defs 的公理是 `f ≡ f_sumC`，不含方程体，方程只在 `f.simps`（未证终止则
   `f.psimps`）里；Spec_Rules 里的同一组方程以 `Binding.empty` 登记
   （`function.ML:217`），无名，`same_theory` 永远过不了，而未证终止的
   `function` 在 Spec_Rules 里根本没有条目；locale target 里的 `fun` 和 Nominal2
   的 `nominal_function` 也只有这条路（函数包登记表对前者不可见、后者自有登记表；
   2026-09-13 的登记表来源因此被换掉）。按全名精确查 fact，同 theory 的过滤
   白送。`.simps`/`.psimps` 必须过保护——结论是等式且左边头部是该常量本身——
   因为 datatype/typedef 给**类型**起 `T.simps`，同名常量会撞上
   （`Quickcheck_Exhaustive.unknown`、`Sum_Type.sum`、`Product_Type.prod`）；
   保护逐级应用，`inductive_set` 的 `.simps` 左边是 `a ∈ S r`、被拒后由其
   `_def` 接住；`_def` 只看名字（全 heap 无一误收）。结构路径上还有一步：
   `overloading` 块里的 `fun` 的 fact 以块内局部名命名（`size_hps.simps`），
   常量名查不到，其 Defs 公理 `sz ≡ size_hps_sumC` 无体，于是按 `_sumC` 前的
   局部名再查 `.simps`/`.psimps`（同样过保护）替换这条公理（D9）。
2. **`add_sort_classes` 用 `fold_atyps_sorts`**：`fold_atyps` 看不见
   `TFree (a, S)` 的 S，删掉则全部 class 依赖边消失且双重静默。
3. **class 的传递超类闭包不进 payload**（`Rings.idom` 在 HOL.Rings 下 43 个超类、
   Main 下 48——进 payload 则 digest 随 env 漂移永不收敛）；`Axclass.get_info`
   的 params/axioms 非传递，恰是够用的原因：digest 只描述实体自身，
   继承走依赖边。

---

## 8. 四个模式的落点

```
L0 候选（WIP）：skip ⟺ stored (进程标识, theory serial) == 当前值（不看 finished，§3.4）
  └─ interpret_with_parallel → interpret'   semantic_store.ML:1086
       ├─ 十二路枚举 → all_entries_with_pos :1097-1290（含 digest/deps 计算）
       ├─ build_entries                     :1292
       └─ RPC Semantic_Store.interpret_file :1365
            └─ Python interpret_file        semantic_interpretation.py:1004
                 ├─ 种子集 = 本地过期（digest 失配 ∨ dep uk 漂移（§4.3 统一判据））
                 │   ∪ eff* > interpreted_at ∪ uncached——**过滤落在 Python 段**；
                 │   其余实体从库预填 results；ML 侧去重/排序/唯一性断言/usage 零改动
                 ├─【模式 4】在此返回，不调 LLM（n = 种子数，见术语表 dry run 行）
                 └─ LLM → on_answer → 逐实体 semantic change gate → Gate_Writer.put_interpretation
                     （判 CHANGED 才 mint、才把依赖者入队；SEMANTIC_CHANGE_GATE_PLAN §5.3–§5.4）
```

- **完备性契约扩展**：`:1141-1158` 的「全答或 raise」把过时集纳入同一契约——
  待办集全答，或整体 raise（不 mark、不写 stored (进程标识, theory serial)），
  失败响亮可重试。
- **模式 4**：另立 RPC 入口 + ML 侧不 mark、不 skip 的调度路径；`interpret'`
  在 entries/RPC 边界拆成「枚举+build+断言」与「发送」两段（机械抽取）。
  三个冲突的由来：完备性不变量、`interpret'` 返回即 mark（:1496-1498）、
  finished 早退在前（:1407）。

### 写回纪律（四条，各堵一类「永久静默漏报」）

1. digest/version/deps 同一次 Record put（分开写则崩溃点留下「digest 新、
   version 未 bump」→ 变更信号永久丢失）。
2. stored (进程标识, theory serial) 只在实体级扫描+解释**成功完成**时写（写早了
   = 同进程内后续 L0 全部误跳过——唯一致命的写序；其余崩溃点只造成重复劳动）。
3. 模式 4 不 mark：不写 thy-status 的 (进程标识, theory serial) 对、不 mark
   finished（写了 = dry run 撕掉自己刚报告的工作单）。**扫描与 dry run 不写
   任何东西**，唯一例外是 dry path 的 statement refresh（写 expr，并给该实体的向量写 tombstone）；live run
   的 refresh 在 LLM 工作之后。（2026-09-12 随 semantic change gate 反转：原
   「扫描本身的 bump 允许照常落库」作废——version 只在 gate 判 CHANGED 时
   mint，扫描不 bump。）
4. interpreted_at 的快照在该实体**自己写入时**取（其 mint 之后）；同一 run 中若有
   依赖随后 mint，则抬升该快照（SEMANTIC_CHANGE_GATE_PLAN §5.3.1）。健全性来自
   一个 run 内的 theory 值不可变、且并发 run 被 interpretation lock 排斥——
   例外是 rpc.py 在某个 worker 连接关闭后的 3 秒宽限，其间一个已取消 handler
   的 gate 写入仍可能 mint（同计划 §8.1）。（2026-09-12 取代原「agent 启动前
   算好的 eff 快照」。）

### dry run 统一与 update_interpretations（2026-07-27 逐项批准）

**dry run 是全系统唯一的工作量计量实现**，两级结构：

```
第 1 级  theory 级筛：filter_out (skip_interpreted force) (collect_cone roots)
         ——原 plan_interpretation 的函数体降为 structure 内私有函数（保名字，
         支撑 semantic_store.ML:1528「报价集 = 实际工作集，按构造相等」注释）；
         签名条目与 "Lets a caller size the job" 注释删除。
第 2 级  对名单 theory 跑「枚举 + digest/deps 计算 + Python 种子集过滤」，
         只数不做（纪律 3：不调 LLM、不 mark、不 bump）。
返回     (名单内 theory 长名列表, 种子实体数 n)——一次带够全部调用方。
```

RPC 协议：锥回调 `"Semantic_Store.interpret_theories"` 扩展为
`(context, names, force, dry_run)`（平铺路径删除时 D2 裁定推迟至此的 schema 变更）。

**计量纪律**：theory 数退出工作量计量（C1 教训——名单与锥可任意背离）；花钱的
数只有实体数 n；theory 名单仅用于向用户展示范围（识别，非计量）。
**n 不是界，只是种子数**（2026-09-12，semantic change gate）：dry run 按 run 前的
库状态数各 theory 的种子集（变了/未缓存的实体）之和。live run 可能多发——gate 判
CHANGED 会把依赖者纳入；也可能少发——live run 逐 theory 做、后代在祖先写完之后才
扫描，祖先里一个 UNCHANGED 裁定把它的 interpreted_at 抬到 eff\*，挡住后代 theory
里一个 dry run 已经数过的实体。零处精确（n = 0 当且仅当 live run 一个也不发）。
用户可见文案一律 "About n"（SEMANTIC_CHANGE_GATE_PLAN §5.2、§12）。

**`update_interpretations`（Python 策略壳，semantics.py "Other utilities" 段）**：

```python
async def update_interpretations(connection, ask_user=False,
                                 theory_names=None, include_context=True,
                                 ctxt=None):
    # 1. gate（auto_interpret_for_embedding）关 -> 静默返回
    # 2. 根集 = theory_names ∪（include_context 时 connection 当前 context，
    #    按原样形态作根——见下「aoa 启动的 context 根」裁定）
    # 3. dry run -> n（同一锥回调，dry_run=true，context 位填 ctxt）
    # 4. n == 0 -> 无事返回
    # 5. 0 < n < 阈值（常量写死，现值 400，2026-07-29 裁定）-> 静默解释（同回调 dry_run=false）
    # 6. n >= 阈值 -> ask_user: dialogue 问一次（三选项，见下「复问粒度」），Yes 才干
    #             -> not ask_user: warning 报 n + 提示显式命令，不干
```

**复问粒度（2026-07-27 深夜批准，三选项方案）**：n≥阈值 的对话框为
「**Yes / No / No，本 Isabelle 会话内不再问**」三选项。第三项置 **RPC host 的
模块级全局旗标**——RPC host 是 per-Isabelle-instance 进程，作用域天然 = 本
Isabelle 实例生命期（跨 aoa 连接有效，host 重启自然重置，零清理逻辑）。语义：
- 旗标只压制**询问**：启动检查照跑，n<100 的静默更新照做；
- 普通 No 只拒绝本次，下一次 `by aoa` 照常再问；
- Isar 命令的 `Active.dialog` 不受此旗标影响（显式意图永远问）。

调用方分工（交互层各自保留，工作量数全部引自 dry run；**对话框只有两个家**：
aoa 启动与 Isar 命令——查询时刻永不弹框）：

| 调用方 | 参数 | 交互 |
|---|---|---|
| aoa 启动 `_ensure_semantic_db`（每次 `by aoa`；run 内不再查） | `ask_user=True`，全默认；**context 根按原样形态传入**（见下） | 阈值策略，对话框之家一 |
| `_auto_embed` 段(1)（2026-07-27 深夜定稿，见下） | `ask_user=False, theory_names=missing 推导名单, include_context=False, ctxt=一路传入的 ctxt`（定点修复） | 永不弹框：小活静默、大活警告 |
| `run_semantic_interpretation` 命令（**不接策略壳**——用户显式意图不套阈值） | 不经 `update_interpretations` | `Active.dialog` 照旧（对话框之家二），报「About n 个实体」+ 名单展示（2026-09-12：theory 数不再显示，SEMANTIC_CHANGE_GATE_PLAN §12 #8） |
| `collect --dry-run`（已批） | 同协议 | 打印报告，不干 |

**段(1) 定稿（2026-07-27 深夜逐项批准）**：
- **双重把关**：第一道 = `Semantic_Vector_Store` 新增普通成员
  `enable_interpret_in_auto_embed: bool = True`（不进配置系统、不经 RPC）；
  **AoA 取得 store 后置 False**——启动巡检已覆盖，查询时刻零开销（字段短路时
  连 gate 读取都不发生）。字段只管段(1)；段(2) 嵌入不受影响。
  第二道 = gate **原地现读、禁止缓存**（`__aenter__`/async init 快照方案均否决：
  gate 是 per-context 活配置、declare 可随时翻，连接池化复用使其逐调用变化；
  且 semantic_embedding.py:1192 的 missing 闸使读取只在真有活时发生，无成本可省）。
- 旧 >5 计数与弹框（semantics.py:1437-1446）删除；**名单推导（:1419-1436）保留**
  （带名单 = 定点修复，与 aoa 启动的全面巡检是两种语义，参数就该不同）。
  查询时刻永不弹框 ⟹ 「答 No 后每查必问」的复问骚扰结构性消灭
  （memo 方案审后否决：策略函数内藏进程级隐藏状态 + 脆弱的 parents-serial 键）。
- **`ctxt` 全链参数**：`lookup → topk → _auto_embed → update_interpretations`
  各加 `ctxt=None`（None = ML 侧当前命令 context，现状零回归）；链内消费者 =
  `config_lookup`、`theory_long_name`、锥回调 context 位。`query_knn` 的 wire
  九元组暂不加 context 位（需要时再扩协议）。
- 此步落地即满足 §12 的 C1 排序硬约束（确认口径失真的源头代码消失，
  警告报的 n 来自 dry run 真实工作集）。

调用链事实（2026-07-27 核查存档）：`_auto_embed` 全库唯一调用点 =
`topk`（semantic_embedding.py:1192，missing 非空才调）；`topk` 唯一调用者 =
`lookup`（semantics.py:1716/:1723）；`lookup` 调用者 = AoA query 工具
（Isa-Mini/AoA/model.py:2169 直调）+ `query_knn` RPC（ML 侧现役调用者仅
Semantic_Embedding.thy:20 演示行）。**Sledgehammer_Embedding 不经此路**
（自有 Termtab 向量机制，sledgehammer_embedding.ML:239-243）——早前「段(1)
服务 Sledgehammer_Embedding」的说法作废；段(1) 的现实受众 = query_knn 面的
未来调用方。

其余连带改动：
- `interpret_theories_by_names` 退役（或降为策略壳内部私有帮手）。
- 命令 interpret_command.ML:65 的 `plan_interpretation` 调用点升级为 dry run。

**aoa 启动的 context 根（2026-07-27 深夜裁定：包含自身 + 原样形态）**：
- **包含当前 theory 自身**——semantics.py:1435 的既有排除定性为待修缺陷：不解释
  最新实体（刚写的定义/引理）恰恰会让当前的 `by aoa` 失去最需要的检索支持；
  草稿多付的 LLM 钱是为"帮到正在做的工作"付的，值。serial 判据在活 theory 上
  永不命中 ⟹ 每次重扫，属预期行为（实体级 digest/缓存挡住重复花费）。
- **根按原样形态传入**（`Context.Proof`/local-theory context 原样作根，不降级为
  `Context.Theory`）——决定性理由是 locale：块内引理提升（`end`）之前只存在于
  local context，theory 通道看不见，只有 proof 通道的减法枚举
  （theory_structure.ML:194-196，context 可见 facts 减背景全局 facts）能产出它们；
  证明本地假设同理，且是检索相关性的强信号。成本由 uk 级缓存兜底：本地事实
  thm128 寻址，同一陈述只解释一次，同目标重试零花费。
- 重复处理核查存档（2026-07-27）：theory 级 `collect_cone` 按 id 去重、proofs
  另队；定理两通道零交集（`dest_static` 减法）；常量在 proof 通道会重枚举一遍
  但 Python 侧 uk 过滤挡住重复 LLM（仅毫秒级载荷）；proof 通道 never marked
  （semantic_store.ML:1548-1551），不污染 thy-status。Proof 根通道此前零现役
  调用者，aoa 启动是首个点亮者。

**段(3) 警告——删除，并入策略壳（2026-07-27 深夜裁定）**：警告纪律 =
「gate 开 ∧ 缺口未修 ∧ 无人被问过（ask_user=False 路径）才警告，其余一律沉默」。
逐情形：gate 关 ⟹ 沉默（用户亲手关的，逐查询唠叨即骚扰——此改消灭骚扰盘点
最高频源）；AoA 字段关 ⟹ 沉默（启动弹框已问过，知情已决策）；n<阈值 ⟹ 静默修掉
无需说；唯一警告点 = 非 AoA、gate 开、n≥阈值——恰好就是 `update_interpretations`
第 6 步 not-ask 分支已有的那条 warning（报 dry run 真实 n + 提示显式命令）。
因此独立的段(3)（semantics.py:1464-1510，含 gate 判断/blocked 统计/命名过滤）
**整段删除**；`_auto_embed` 最终语义 = 段(1) 一行委托 + 段(2) 嵌入，无第三段。

至此本节全部设计点已裁决完毕，无待裁项。

---

## 9. 分发与分层（对接 SEMANTIC_DB_LAYERED_PLAN，2026-07-26 兼容性修订）

`contrib/Semantic_Embedding/SEMANTIC_DB_LAYERED_PLAN.md`（system/user 双层、
万能墓碑、conda 分发）是正在执行的存储层重构，**本计划以它为地基**：

- **记录级合并不复存在**（其 L7/L13：R2 客户端、merge_env、push 全删；「pull」
  变为 system DB 的 conda 包安装器）。因此本计划旧 §9 两项整体退役：
  - 「push/pull 按 WIP 位排除」→ 语义翻译为对 export 的修订请求（见下）；
  - **域平移机制正式退役（2026-07-26 用户批准）**——其防御对象（记录级合并）
    已从架构中消失，且 export 过滤后发行物中不含任何域绑定数值；设计全文
    存档于 `.bak` 与交接清单，唯一复活场景是将来出现跨机批量导入带域字段
    记录的新需求。
- **已批决策「发布物只含 persistent 数据」的落点 = CI export 加一个过滤 job**
  （LAYERED_PLAN 修订，**2026-07-26 用户批准**）：
  export 丢弃 ① **WIP 位 = 1 的全部 key**（WIP 记录是机器本地工作态，四字段
  落地后更携带发行机的计数器域值，绝不可发布——丢弃后全库任何地方不再出现
  跨域数值；HF 源 tarball 现状含 WIP，见其 §15.3）；② **`0xF0` 计数器键**
  （发行机的计数器值对消费者无意义且有害）。
- **计数器键的读写走 user env 直达，绝不经分层读取**（纵深防御：即使历史
  快照含 0xF0 也读不到发行机的值）。
- 本计划新增的一切读取器（digest/eff 扫描、dep 统一判据、prune）
  **一律经分层 facade**（user 先、墓碑即缺席、再 system——指分层读取语义，
  非要求持有 Semantic_DB 单例对象）；新写入照旧全落
  user env。thy-status 的 (进程标识, theory serial) 字段（§3.4）加入
  LAYERED_PLAN §3.1 的 RMW copy-up 纪律（保留未触字段、不得从零模板起写、
  墓碑即从头开始）。
- Record codec 8→12 与 LAYERED_PLAN §15.1 的长度容忍解码相容——同一处
  pad/slice 目标从 8 改 12；**墓碑判定（`b""`）先于解码**，本计划全部新
  读取器遵守。
- ~~消费者机器种子拷贝以 system 层为种源~~（随 §6 删除作废，2026-07-27）。

---

## 10. prune 与 orphans（批量删除，不是 GC）

- `isabelle-semantics prune <theory 名…> [--all] [--keep N] [--apply] [--yes]
  [--no-backup] [--current-from store|repl --repl-addr … --session …]`：
  **缺省即演习（2026-07-27 批准）**：裸敲只打印将删清单（theory、代数、
  记录/向量条数），结尾一行明示「DRY RUN——未删除任何内容。加 --apply 执行。」；
  `--apply` 才确认+备份+真删（`--yes` 免确认，`--no-backup` 显式跳过备份；
  顺序经 2026-07-29 裁决改为确认在先——滚动备份的轮换不可逆，放弃确认的
  运行不得消耗上一份备份；不变量只是「删除前有备份」）。
  对点名 theory 删除**旧代**记录。「代」= `theory_hash.lmdb`（hash→[名,ts]，
  put 覆盖刷新，ts=最后经手时间）反向按名分组、与语义库实有记录求交、按 ts
  降序的各 hash；当前代 = ts 最新（默认）或活会话权威（repl 模式）；删除排位
  > `--keep`（默认 1）的代。删除引擎复用 `cmd_remove`（名字寻址按前缀、
  thm/rule 按成分表、同代状态记录含入、连向量库；抽共享函数）。
- `isabelle-semantics orphans [--limit N]`：只读报告，列出前缀/成分解析不到
  任何已知 theory 名的记录（默认扫 user 层，`--system` 附带只读报告）；
  孤儿删除无自动模式，人审后用现有 `remove <hash>`。
- **分层适配（2026-07-26）**：删除引擎对接 LAYERED_PLAN 的万能墓碑（其 L8，
  `cmd_remove` 重写后即墓碑引擎）——「删」= user 层写 `b""`（覆写旧值即回收
  大部分空间；墓碑键残留有界，其 L20 判无害）。prune 的作用域 = **user 层**
  的旧代记录；system 层是只读发行物，其瘦身由 CI export 的墓碑丢弃完成——
  发行机上 prune 出的墓碑经 HF → CI 自动进入下一个快照。
  **备份定稿（2026-07-26 用户批准方案 (a)）**：prune **自带**轻量备份，
  不复活通用备份设施——仅 `--apply` 时、删除动作之前，对 **semantics.lmdb
  单库**做一次 `Environment.copy(compact=True)` 到滚动目录（temp 拷完原子
  rename 覆盖上一份，恒只留最近一份），打印位置与「恢复 = 停 RPC host 后
  把目录换回」一行提示；ENOSPC 在备份阶段即中止、未删任何东西。
  **向量库与 experience index 不备份**：向量是惰性缓存（误删由
  `_auto_embed` 按需重嵌，花的是 embedding 零钱不是 LLM），index 可
  `rebuild_experience_index` 重建——不可替代的只有解释文本本身。
  自包含 ~15-25 行；`--no-backup` 保留为显式跳过开关。
- experience 记录不在 prune 范围（检索走桶枚举而非重算 key）；WIP 垃圾归
  `clean_wip`。
- 配套：删实体连带删同代 theory 状态记录；删 uk 连带删全部 embedding 模型向量。
- statement 漂移的 thm 垃圾**接受积累**（不加声明 theory 字段）。
- 工作量 ~200-250 行 Python，零 ML 改动、零 key 格式改动。

---

## 11. 存量迁移（v3 后所剩无几）

- persistent 侧：**零迁移**（key 不动，旧记录即现役记录）。
- WIP 侧：升级时跑一次 `clean_wip` 清空（WIP 记录本为可弃缓存），之后按
  uncached 在线重解释（种子拷贝已删除，§6）。
- codec：离线脚本只做 Record 加字段（读出 None 即可），沿
  `migrate_record_provenance.py` 模式（备份/幂等判磁盘字节/--dry-run）。

---

## 12. 实施顺序

> **前置（2026-07-26）**：本计划全部阶段排在 LAYERED_PLAN Phase 1–2（分层
> facade + snapshot_sync 重构）之后。文中 `semantics_manage.py`/`r2_sync.py`
> 按其 L22/L5 读作 `isabelle_semantics.py`/`snapshot_sync.py`；本计划的
> 文件行号锚点采于分层重构之前，实施时按符号重定位。

> **里程碑顺序（2026-07-27 用户批准）**：M1 = 模式 4/dry run 先行（步骤 15）→
> M2 = 模式 3（步骤 9/10/14）→ M3 = dep 统一判据 + serial 判据（步骤 8/10/14 的
> 对应部分）→ M4 = 阈值策略（步骤 15b）→ M5 = prune/收尾（步骤 17-20）。
> 阶段 A/B 为各里程碑的公共前置，按依赖顺序穿插。
> **M1 的 n 口径（评审 F2 争论的定论）**：dry run 数的永远是「当时已部署管线
> 的待办集」——M1 时点过时判据尚未部署，n = uncached 数（既有过滤，
> semantic_interpretation.py 的 uncached 计算）；步骤 9/10 落地后**同一实现**
> 自动加宽为完整待办集。不存在第二套计数实现（术语表：dry run 是唯一工作量
> 计量），M1 无需等待步骤 9/10。
> **阶段 A 与 LAYERED Phase 2 并行已批**（2026-07-27，附带前置：经对抗评审
> 确认无冲突——阶段 A 动 ML 侧文件，Phase 2 动 Python 存储层，文件面不相交）。

**阶段 A — 瘦身与改名**
1. `invalidation.ML` → `semantic_digest.ML`（§7.1 三件事同步；工期半天到一天）
2. 实体身份改 `Universal_Key.entity`（§7.2）
3. ~~接入 `Semantic_Embedding.thy`~~ 已完成（`:12`）；改名后更新该 `ML_file` 行
4. ~~测试套件入库~~ 已抢救至 `Semantic_Embedding/Test/`；残留：注册进 `Test/ROOT`、
   `Test_All.thy` 的绝对路径 `ML_file` 随改名更新
5. 名字哈希分支加不变量注释；`Resources.loaded_theory` 边界探针

**阶段 B — 存储扩展**
6. Record 四字段 + codec 8→12 + 向后兼容验证（含测试补 12 字段用例）
7. 全局计数器 `0xF0`（自增与 put 同事务）
8. thy-status 加 (进程标识, theory serial) 对 + RPC 参数 + embed 侧同构（§3.4；
   进程标识生成一次、跨会话必比对）。实施前**清点 `finished` 的全部调用面**
   （interpret 侧与 embed 侧各自的读/写点）逐一改造——早前清点的行号已随
   interpretation driver 重构漂移，按符号重新定位；**点名最易漏的一处**：
   `write_cost`（semantic_interpretation.py，现无 WIP 守卫、无条件写 finished）

**阶段 C — 判定与模式**
9. `interpret'` 算 digest/deps（内容按 §3.2：三层过滤 + locale 表 serial 过滤 +
   断言护栏）随 entries 送出——与步骤 10 是同一条 RPC 协议改动的两端，合并设计
   （`packTuple8`/`make_interpret_file_cmd`/`Entry`/解包/`write_answer` 一条链，
   全程强类型响错；mlmsgpack 备有 `packTuple9`–`packTuple12`（现役代码已在用
   packTuple9），9 元及以上直接换用，无需嵌套）
10. Python 侧递归 eff 求值（§4.1）+ dep 统一判据（§4.3）+ 待办集过滤 + 完备性
    契约扩展（§8）+ 写回纪律（§8）
11. `entry_ord` 改 serial（§5 decorate-sort；顺带修 999999999/-1 显示 bug）
12. ~~种子拷贝~~（§6 已删除，2026-07-27；步骤号保留防错位）
13. CI export 加过滤 job：丢弃 WIP 位 = 1 的 key 与 `0xF0` 计数器键（§9，
    已批；已写入 LAYERED_PLAN export 六件事之 ②）。**过滤须覆盖 export 的
    全部拷贝循环**（记录、向量、experience index——漏一处即发行泄漏）；
    计数器键 user-env 直达访问落地
14. 模式 3 入口谓词接入调度（persistent：finished；WIP：(进程标识, theory
    serial) 未变，§3.4）
15. 模式 4 = dry run 统一（§8）：锥回调 schema 扩展 `(context, names, force,
    dry_run)` + 不 mark 不 skip 调度路径 + `interpret'` 两段拆分 +
    `plan_interpretation` 降私有并删签名条目 + 命令 :65 调用点升级为 dry run
15b. 阈值策略：`update_interpretations`（§8）+ aoa 启动调用点
    （`_ensure_semantic_db`）+ 段(1) 改造（双重把关字段/gate + 删 >5 弹框 +
    `ask_user=False` 带名单）+ `ctxt` 全链参数 + `interpret_theories_by_names`
    退役；完成后 gate 默认翻 true（两前置：平铺路径删除 ✅ 2026-07-27、
    本步骤即前置二）
16. 敏感性测试套件扩展：§14 全部断言（**含三组新机制断言：serial 判据、
    dep 统一判据、dry run**）+ def-parse↔locale 表交叉校验

> **排序硬约束（2026-07-27，平铺路径删除方案评审 C1 记录，用户裁定修复归本计划）**：
> `auto_interpret_for_embedding` 默认翻 true 之前，必须先落地 `_auto_embed` 段(1)
> 的确认口径修正（阈值策略：dry run 按真实工作集计数）。原因：平铺路径删除后该
> 回调走锥路径，实际工作集是名单的祖先锥减已解释，而 Python 侧现有确认框与
> tracing（semantics.py:1438-1446、:1447-1450）仍按名单计数——小名单可静默点燃
> 数百 theory 的 LLM 花费，且击穿 semantics.py:1516-1522 注释记载的「LLM 花费由
> 段(1) 自己的确认把守」这条成文护栏。即 gate 翻转的前置从一个变两个：平铺路径
> 删除方案（✅ 2026-07-27 已落地，`FLAT_PATH_REMOVAL_PLAN.md`；Semantic_Embedding
> `fcbe8fb`）+ 本条（由步骤 15b 落实）。

**阶段 D — 清理**
17. 删除死码 `get_theorems_with_positions_of`（`theory_structure.ML:406-439` +
    签名 :28）；将本会话既有未提交删除（`interpret_entities` 等）并入提交
18. codec 迁移脚本 + 升级时 `clean_wip`（§11）
19. `prune` + `orphans`（§10）
20. limitations 文档同步：删 #4/#5 的「手动强制重解释入口」承诺句（改直白陈述
    永不过期）；补 R1 推广条（infra dep 死边、eff 取 0）；
    与本计划互引；文件名引用随改名更新

---

## 13. 开放问题——已全部关闭

反向拷贝（WIP→persistent 晋升）：WIP 会话新解释的实体在 theory 持久化后 key
前缀变 Merkle、用不上，LLM 费重付（今天即此行为）。

**已裁决：不做（2026-07-28 用户终局裁定，本计划最后一个开放问题就此关闭）。**
设计理由：**变成 persistent 的那一刻具有发布的含义**——theory 进入 heap 即
成为可交付内容，值得对它重新完整跑一遍解释，而不是沿用草稿期（WIP）攒下的
解释文本。重付不是缺陷，是发布语义的一部分。（技术上 M2 之后带 digest 的
安全搬运已可行，此点已知悉并仍然否决——理由在语义不在安全。）

---

## 14. 验收：敏感性测试是唯一有效手段

解析覆盖率与确定性测试对「几乎不看内容的 digest」同样全绿——第一版两项全过
却藏 7 个盲区。必须逐类断言「该进 digest 的内容确实进去了」：

| 断言 | 缺了会怎样 |
|---|---|
| `Set.range` 依赖 `Set.image` | abbreviation rhs 不进 digest（占可解释常量 18%） |
| `Set.member` 依赖 `Set.Collect` | axiomatization 常量丢失全部公理 |
| `HOL.The` 有定义公理 | `retrieve_global` 空索引检索不到 |
| `plus`/`less_eq` 保留 0 条定义公理 | 下游实例污染，13.3% 的库误失效 |
| `Groups.semigroup` 依赖不止 1 项 | locale 的 assumes 不进 digest |
| `sens_def` 依赖其 defines 体 | `Element.Defines` 被丢弃 |
| `abel_semigroup` 有 LocaleK 父边 | 父 locale 依赖缺失 |
| `Int.int` 依赖 `Int.intrel` | typedef 定义集合不进 digest |
| `Nat.nat` 依赖 `Nat.Nat` | ctr_sugar 短路吞掉 typedef 通道 |
| `Orderings.ord` 依赖 `less_eq`/`less` | class 参数不进 digest |
| `not_less` 有 `linorder` 的 ClassK 边 | sort 里的类不产生依赖边 |
| `Rings.idom` 的 digest 跨 env 相同 | 超类闭包污染 digest |
| `fun` 常量恰取 `f.simps`，提及其方程体里的常量（`sens_fun` → `less`）且无 `accp` 前提 | 函数包的方程不进 digest（Defs 只有 `f ≡ f_sumC`）；`.psimps` 排到了 `.simps` 之前 |
| 未证终止的 `function` 恰取 `f.psimps`（提及方程体常量与 `accp`） | 未证终止的函数没有任何方程进 digest |
| `primrec`/`partial_function` 恰取 `.simps`，`definition` 恰取 `_def` | 名字路径没有短路，结构路径的公理混进来 |
| `context fixes` 下的 `fun` 恰取 `.simps`，提及 `plus`（`sens_cfun`） | 导出后多一个参数的函数取不到方程 |
| locale target 里的 `function` 恰取导出的 `L.f.psimps`，提及方程体常量 | 登记表来源（2026-09-13）对 locale target 不可见，方程不进 digest |
| 与 datatype 同名的常量恰取 `_def`，不提及构造子 | 无保护时类型的 `T.simps` 被当成常量的定义 |
| `inductive_set` 恰取 `_def` | 左边是 `a ∈ S r` 的 `.simps` 没被保护拒掉，进了 digest（`inductive_set` 的 Defs 公理本身就叫 `_def`，所以这一行钉的是保护，不是逐级回落；逐级回落由上一行钉：`definition` 的 Defs 公理叫 `_def_raw`） |
| 有作者 `X_def` 引理的 abbreviation 恰取 `X_def` | `_def` 被按形状过滤，abbreviation 的作者定义丢失 |
| `overloading` 块里的 `fun`（`sens_sz`）取到局部名的 `.simps`、兄弟 `definition` 的 Defs 公理，不含 `_sumC` 公理 | 块内 `fun` 的方程不进 digest（fact 以局部名命名，常量名查不到） |
| `digest_term t = Term_Digest.term128 t`（参数改名使 digest 变化） | digest 在 hash 前被做了变换（归一化已撤销，2026-09-13） |
| **class：locale 表取法 ≡ def-parse 取法（全 Main）** | serial 过滤判据漂移无人发现 |
| **`Rings.idom` 的 deps 恰 2 项、跨 env 相同** | 注册边混入 deps |

发送序验收：`rel_fun` 先于 `rel_fun_def`、`Node` 先于 `case_tree`（serial 序）；
中等 session 里 `Position.line_of = NONE` 的实体按 kind 分组无名字寻址四类；
resume 场景发送序列覆盖依赖闭包的比例。

**三组新机制断言（2026-07-27 评审补，覆盖计划自述的三类静默失败模式）**：

- **serial 判据（§3.4）**：同一 theory 值二次扫描 ⟹ 跳过；重精化（新 theory
  值）后 ⟹ 不跳过；**同 serial、不同进程标识 ⟹ 不跳过**（裸 serial 碰撞 =
  假跳过）；模拟解释中途失败 ⟹ thy-status 的 pair 未写、下次照常重扫
  （纪律 2 的写序）。
- **dep 统一判据（§4.3）**：构造 theory 的 WIP↔persistent 翻转，断言依赖者 E
  因存储 uk ≠ 当前 uk 进待办集、dry run n > 0——该判据被窄化实现（按存储的
  WIP 位免检）时此断言必红（死边复活探测器）。
- **dry run（§8）**：跑后 thy-status 的 pair 未写、不 mark、不 bump（纪律 3，
  2026-09-12 版）；对含已解释祖先的锥，**n = 0 当且仅当随后的 live run 一个
  也不发送**（原「n == 实做数」的断言随 semantic change gate 退役；「n ≤
  实做数」也不成立——上游 UNCHANGED 会挡住下游已数的实体，见 §8 的「n 不是
  界」段）；单个 theory 内、对同一库状态，数到的种子全部发送。

⚠️ 测试主体必须选在缺陷会显形处：`Orderings.order` 两个 env 下超类都是 3、
必然通过；须用 `Rings.idom`（43 vs 48）。选错主体的测试比没有测试更危险。

---

## 15. 教训存档（压缩）

- **性能测量只能证明它实际测的那个用法**：v1 用单 theory 查询 API 的 58× 差距
  论证了重写整个枚举层，而管线从未那样用过；重新发明的五样东西全部发明错。
- **`.gitignore` 含 `/contrib`**：rg/grep 必须 `--no-ignore`，否则整个 contrib
  树被静默跳过——本项目多次误判「不存在」的根因。
- **身份与变更信号是两件事**：v2 想用一个 key 兼任两者；v3 的答案是各归其位
  （persistent：Merkle hash 兼任且合理；WIP：名字哈希管身份、digest 管变更；
  dep 统一判据：uk 兼任时刻印记）。
- **同一概念永远用同一术语**（见文首术语表）；编辑本文件须先 `cp` 备份、
  替换带 `assert old in s` 守卫（曾被无守卫的 `str.replace` 炸成 11MB）。
