# 增量失效机制的已知缺陷

**日期**: 2026-07-20（2026-07-28 随机制落地同步：计划节号更新、补缺陷 6、
删除已作废的「手动强制重解释入口」承诺；2026-09-12 随 semantic change gate 落地
补缺陷 7；2026-09-13 随函数包方程进 digest 补缺陷 8、缺陷 6/7 各加一段；
2026-09-14 定义来源改为名字路径，缺陷 8 改写、缺陷 6 的一段改写）
**状态**: 缺陷均已知且被明确接受；机制本体已落地（`Tools/semantic_digest.ML` +
`semantic_interpretation.py` 的种子集过滤与 semantic change gate，CHECK_OUTDATE_PLAN
M1–M4 + SEMANTIC_CHANGE_GATE_PLAN）
**关联**: `archive/plans/CHECK_OUTDATE_PLAN.md`（本文是其 §4.4/§7.3 的接受缺陷登记处）；
`ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md`（缺陷 7 的机制与测量）

本文集中记录 `check_outdate` 增量失效机制**已知不能覆盖的情况**。这些缺陷是设计权衡的
结果，不是实现 bug。写下来是为了避免日后有人误以为覆盖是完备的，也为将来改进留下起点。

所有结论均在 Isabelle2025-2 / HOL session 下实测，证据附在各条目内。

---

## 缺陷索引

| # | 缺陷 | 严重度 | 影响范围 |
|---|---|---|---|
| 1 | 类型类实例定义对依赖不可见 | **中** | 全部多态算术/序关系引理 |
| 2 | 类参数常量恒不失效 | 低（且部分正确） | 类参数常量 |
| 3 | class 超类传递闭包会被下游污染 | 低 | 317 个 class |
| 4 | method 永不过期 | 低 | 28 个 |
| 5 | theorem collection 永不过期 | 低 | 64 个 |
| 6 | 无记录的 dep 目标贡献 eff 0（infra 死边） | 低 | Main 上 28% 的 dep 目标 |
| 7 | semantic change gate 的误判「same」让下游停留在过期解释 | 低 | 被误判实体的独占下游依赖者 |
| 8 | 常量自身的定义内容进不了自身的 digest，或不变而 digest 动 | 低 | `overloading` 块里的名字、`instantiation` 里的 `fun`、`termination` 的增删 |

---

## 1. 类型类实例定义对依赖不可见 ⚠️ 主缺陷

### 现象

改变一个类型类实例的定义（例如 `+` 在 `nat` 上如何计算），**不会**让任何关于该类型
该运算的引理失效。

### 证据

一条纯粹关于 nat 加法的引理，其项中出现的常量是：

```
Nat.add_Suc            →  Groups.plus_class.plus :: nat ⇒ nat ⇒ nat
                          Nat.Suc :: nat ⇒ nat
                          HOL.eq :: nat ⇒ nat ⇒ bool
                          HOL.Trueprop :: bool ⇒ prop

(x::nat) + y = y + x   →  Groups.plus_class.plus :: nat ⇒ nat ⇒ nat
                          HOL.eq :: nat ⇒ nat ⇒ bool
```

出现的是**类参数** `Groups.plus_class.plus`（仅类型被实例化为 `nat ⇒ nat ⇒ nat`），
**没有**实例常量 `Nat.plus_nat_inst.plus_nat`。

而类参数 `plus` 本身的 digest 只含名字与声明类型（见缺陷 2），恒定不变。因此依赖链在此
处断开：

```
Nat.plus_nat_def  改变
      ↓ （无边）
Groups.plus_class.plus  digest 不变
      ↓
Nat.add_Suc 等引理  不失效
```

### 根因

两个设计决定叠加：

- **statement 级依赖**（`CHECK_OUTDATE_PLAN.md` §3.2）：依赖取自定理陈述中出现的
  constant/type。类型类的实例解析发生在项之外，陈述看不见它。
- **下游污染过滤器**（同 §7.3）：`Defs.specifications_of` 对 `plus` 返回 9 条实例定义
  公理，分布在 `Nat`/`Int`/`String` 等下游 theory 中。若纳入则 `Groups` 的实体会依赖
  其后代，既造成大面积过度失效，又使依赖边指向前方、破坏拓扑序假设。故必须过滤掉。

过滤是必需的；断链是过滤的代价。

### 为何接受

本机制检测的是**英文解释是否过时**，而非逻辑健全性。改变一个类型类实例的实现，
几乎不会改变"自然数加法的交换律"这句描述。同时实例定义在实践中极少变动。

### 可能的修复方向（未实施）

对项中每个 `Const (c, T)`，若 `c` 是类参数且 `T` 已实例化，则通过 `Axclass` 的
类型类解析机制找出对应的实例常量，将其补为依赖。

- 拓扑序上是安全的：实例常量（如 `Nat.plus_nat`）位于 `Nat`，而使用它的引理必在 `Nat`
  或更下游，边仍指向后方。
- 代价：需对每个常量出现位置做一次类型类解析，成本与复杂度均显著。
- 建议在有实际证据表明该缺陷造成困扰后再实施。

---

## 2. 类参数常量恒不失效

### 现象

类型类参数（`Groups.plus_class.plus`、`Orderings.ord_class.less_eq` 等）**按明确规则**
不保留任何定义公理，其 digest 只由 `名字 ⊕ 声明类型 ⊕ 所属类` 构成。此后只有改变其声明
类型、或其所属类的公理，才会使它失效。

实现上这不是过滤的副产品，而是一条独立规则：

```sml
if is_some (Axclass.class_of_param thy c) then []   (* 类参数没有自己的定义 *)
```

### 为什么必须如此

仅按"同 theory"过滤是不够的。实测 `Orderings.ord_class.less_eq` 的 16 条定义公理中，
`ord_bool_inst.less_eq_bool_def` 与 `ord_fun_inst.less_eq_fun_def` **就声明在
`Orderings.thy` 自己里**，同 theory 过滤放行它们。

而 `less_eq` 被 **13.3%** 的定理提及。若保留这两条，则编辑 bool 实例会失效八分之一的库，
其中绝大多数是 bool 实例根本影响不到的 nat/int/real 引理。故必须按"是否类参数"判定，
而非按 theory 判定。

### 部分正确性

这个结果**在其自身层面是正确的**：`plus` 在 `Groups` 中本就只被声明、未被定义；那些实例
定义属于 `Nat`、`Int` 各自的实体。新增实例或在下游新增子类，都不应改变"加法，某个 plus
类上的二元运算"这句描述。

缺陷仅在于它与缺陷 1 叠加：类参数恒定，而实例常量又不出现在项里，于是断链无法在此处补上。

---

## 3. class 超类传递闭包会被下游污染

### 现象

`Sign.super_classes` 返回的是**传递闭包**（实测 `Orderings.order` supers=3、
`Groups.semigroup_add` supers=8，均多于其直接超类）。

而 Isabelle 的 `subclass A < B` 命令可以在**下游 theory** 中证明新的类包含关系。一旦如此，
上游某个类的传递超类集合就会增长——与缺陷 1 中 `plus` 的 9 条实例定义完全同构的下游污染。

### 处理（已落地）

`semantic_digest.ML` 的 `sem_class`：超类结构经由 `Axclass.get_info` 的 `def`
定理进入 payload——它在声明时刻冻结，下游 `subclass` 不改写它，digest 因此不随
env 漂移（敏感性断言 S7：`Rings.idom` 跨 env digest 相同）。传递超类集只进
**依赖边**；下游新增的边指向前方，由 Python 侧递归 eff 求值自然容忍。

---

## 4. method 永不过期

`Method` 是注册在 name space 中的 ML 闭包，**无项结构可编码**。

其描述串确实存在于 theory data 中：

```
Method.setup : binding -> ... -> string -> theory -> theory      (* 末位 string 即描述 *)
Data:  {methods: ((Token.src -> Proof.context -> method) * string) Name_Space.table}
                                                                  (Pure/Isar/method.ML:293)
访问器: val get_methods = #methods o Data.get                     (method.ML:310)
```

但 `get_methods` 不在 `METHOD` 签名内，实测不可达：

```
ML error: Value or constructor (get_methods) has not been declared in structure Method
```

`Method` 仅导出 `method_space`（有名字、无描述）。取得描述需修改 Pure 源码，**已明确否决**。

**后果**：改动某 method 的 ML 实现后，其英文描述静默失效且无人察觉。影响 28 个实体。

---

## 5. theorem collection 永不过期

两条独立原因：

- **成员不可用**：成员是 dynamic 的，来自下游 theory（实测 `no_atp` 174 个、
  `ac_simps` 42 个，贡献散布于整个 HOL）。纳入即违反下游污染规则。这与既有决策一致——
  `semantic_store.ML:462-465` 已写明成员只作 `prompt_hint`，
  "members are deliberately kept out of expr/key"。
- **描述不可用**：`Named_Theorems.declare binding descr`
  （`Pure/Tools/named_theorems.ML:88-100`）**不把 descr 存进自身数据**（其 Data 仅
  `thm Item_Net.T Symtab.table`，只有成员），而是加工成
  `"declaration of " ^ (if descr = "" then name ^ " rules" else descr)` 后交给
  `Attrib.local_setup`，落入**属性表**；而 `Attrib.get_attributes`（`attrib.ML:106`）
  同样未导出。且未写描述者存的是 `"declaration of foo rules"`，纯由名字推出，零信息量。

因此 digest = 名字 + 所属 theory，deps = 空，等价于永不过期。影响 64 个实体。

---

## ⚠️ 「覆盖率」有两种，不要混淆

下表统计的是**解析覆盖率**——「该实体能否算出一个 digest」。它**不等于失效能力**——
「内容改了 digest 会不会变」。

第一版实现在解析覆盖率上是 98.6%，确定性测试也全绿，却同时存在 6 个「改了内容 digest
逐位不变」的缺陷（abbreviation 的 rhs、locale 的 `assumes`、typedef 的定义集合、class 的
参数、sort 的类边、超类闭包污染），外加 axiomatization 常量丢失全部公理。

原因是**确定性测试与解析覆盖率测试，对一个几乎不看内容的 digest 同样会全绿**。唯一能发现
这类缺陷的是敏感性测试（「改了 X，digest 必须变」），而第一版没有。

所以：**下表只说明"算得出来"，不说明"测得出变化"。** 失效能力的依据是
`CHECK_OUTDATE_PLAN.md` §14 的敏感性测试集（已落地：`Test/Test_Sensitivity.thy`，
失败即 build 红）。

## 解析覆盖率汇总

| 状态 | kind | 数量 | 占比 |
|---|---|---|---|
| 可算出 digest | thm + 4 rule、constant、type、class、locale | 116,003 | **98.6%** |
| 永不过期 | theorem collection（64）、method（28） | 92 | 0.07% |
| 不适用 | experience（Python 侧数据） | 180 | 0.15% |

数据取自实际语义库（117,611 条记录 / 1,513 个 theory）。

那 92 个"永不过期"实体，永不过期即终态（CHECK_OUTDATE_PLAN §2 锁定决策）——
不设也不承诺任何强制重解释入口；要重做只能删记录（`isabelle-semantics remove`）
后按 uncached 重解释。

---

## 6. 无记录的 dep 目标贡献 eff 0（infra 死边）

`deps` 边的目标若在库中没有记录——Main 实测 28% 的 dep 目标是被 Infra_Filter
排除的基础设施实体（`BNF_Def.Grp`、`HOL.equal_class` 等）——则递归 eff 求值对
这条边取 **0**（CHECK_OUTDATE_PLAN §4.4 的显式设计决定）：infra 实体永远不被
解释，也就永远没有 version 可供抬升，这条边对失效**永远沉默**。被判定为
uninterpreted 的常量（`[[uninterpreted_constant …]]` 或 `Performant_Isabelle_HOL.SSymb`
的 theory 标记）同样没有记录，指向它们的边同属此类。

**后果**：改动一个 infra 实体的定义不会经 version 走廊失效它的依赖者。接受理由
与缺陷 1/2 相同——本机制检测英文解释是否过时，不算逻辑闭包；infra 实体的语义
变动几乎不改变依赖者的英文描述。persistent 侧不受影响（infra theory 的内容变化
照样使 Merkle hash 漂移）。

函数包（`fun`/`function`）的常量自 2026-09-13 起不再靠这条死边看见自己的方程；
自 2026-09-14 起它的定义命题就是 fact `f.simps`（未证终止则 `f.psimps`），
不含 `f ≡ f_sumC` 那条公理，指向 `f_sumC` 的死边随之消失（`f.psimps` 的
`accp f_rel` 前提仍留一条指向 `f_rel` 的死边，同样沉默；CHECK_OUTDATE_PLAN
§7.3 第 1 条）。

---

## 7. semantic change gate 的误判「same」让下游停留在过期解释

### 机制

自 semantic change gate（`ai-artifacts/SEMANTIC_CHANGE_GATE_PLAN.md`）落地起，一个
tracked 实体（constant / type / typeclass / locale）被重解释之后——无论它是因 digest
变化进了种子集，还是被上游的 CHANGED 裁定纳入——都比较新旧两段英文解释：一个 LLM
judge 回答「意思是否相同」，并以两段 embedding document 的 cosine 相似度作后备——judge
说 same **且** cosine ≥ 0.90 才算 UNCHANGED；相似度无法计算时（embedding 服务未配置或
不响应，计划 D2）后备关闭，由 judge 独判，漏判率回到下面「judge 单独」那一行。
只有判 CHANGED 才 mint 新 version、才把依赖者纳入重解释；判 UNCHANGED 则它之下的
依赖者被屏蔽（eff\*，计划 §4）。

### 缺陷

judge 把一次真实的意思变化误判为 same（且 cosine ≥ 0.90）时，该实体不 mint，
**只经它**到达这次变更的下游依赖者不会重解释，直到该实体或它们的另一条上游再次
变化为止。另一条上游的变化照常传播——屏蔽只作用于被误判的那一跳。

附带说明（不是缺陷）：digest 对变量改名不作不变处理（原有的 alpha 归一化已于
2026-09-13 撤销），所以只改了绑定变量名或模式变量名的实体会进种子集，被重解释
一次并交 gate 裁定；记录带 baseline 时应判 UNCHANGED、屏蔽其依赖者；gate 落地前
写下的记录（有 digest、无 baseline）则按 SEMANTIC_CHANGE_GATE_PLAN §3 第 2 行强制
CHANGED 并 mint——这是设计路径。

### 测得的比率

- judge 单独：严格标准下漏判 1/87（1.1 %），误报 5/663；测量总体以 lemma 为主
  （`ai-artifacts/similarity_measurement/REPORT_PHASE2.md` §7、§11）。
- 加 0.90 后备后：tracked kinds 漏判 0/24（type class 与 type 未测，计划 §7）；
  全部 kinds 0/87。
- 代价模型：漏判率按 1 % 计，一次误判平均留下 0.6 个本应重解释的下游实体
  （`ai-artifacts/eff_shield_verification/REPORT.md`，该目录只保留在本地、不进 git）。

### 生产 judge 与测量所用 comparator 的偏差

测量用 gpt-5.6-sol、reasoning effort low、每对一次调用、JSON 回答，prompt 写的是
「a constant, a lemma, a type, or a locale」。生产 judge 用解释 driver 的模型
（`Semantic_Embedding.interpretation_driver`），系统提示词列 constant / type /
typeclass / locale，经 `verdict` 工具报告，没有 verdict 时补问一轮；Codex driver
的只读沙箱允许 judge 读文件（计划 §5.5）。上面的比率因此不能直接照搬。

### 被中断的强制 run（计划 §8.1）

ML 侧中断时 `schedule_dag` 取消任务而不等它们结束，各 worker 连接各自关闭，
Python 侧对被取消的 handler 保留 3 秒宽限，其间它的 gate 写入仍可能 mint。下一个
run 若已读到 mint 前的记录，就会错过这次 mint。theory 之间靠 `schedule_dag` 的
祖先先于后代、theory 之内靠计划 §5.3.1 的入队与 snapshot raise 兜底，唯一残留的
角落是：被中断的 force run 作用于本进程内已 mark 的 theory。记录本身不会损坏
（每次写入是一个事务）。

---

## 8. 常量自身的定义内容进不了自身的 digest，或不变而 digest 动

### 现象

常量的 digest 由它自己的定义命题算出（`own_defining_axioms`，2026-09-14 起的
规则：先走名字路径，即取定义命令给它起的 fact——`c.simps`、`c.psimps`、`c_def` 依次，
第一个非空者即用；`.simps`/`.psimps` 只收「去掉前提后的结论是等式且左边头部是
该常量本身」的那些，`_def` 只看名字；三者都空才取同 theory 的 Defs 公理，再空取
Spec_Rules；CHECK_OUTDATE_PLAN §7.3 第 1 条）。在以下情形，这条规则要么取不到
定义内容，要么在定义未变时让 digest 动：

- **`overloading` 块里的名字**：块内 `primrec funpow` 生成的 `funpow.simps`、
  `funpow_def` 说的都是 `compow`（被 overload 的那个类运算），左边头部不是
  `Nat.funpow`：`.simps` 被保护拒掉，`_def` 按名字命中，内容 `compow ≡ rec_nat …`
  ——与 2026-09-13 之前结构路径给出的是同一条命题，只是来源换成了 fact；发行版
  实例 `Nat.funpow`、`Transitive_Closure.relpow`、`relpowp` 三个。块内的 `fun`
  （AFP `Pairing_Heap_List2_Analysis.thy` 的 `sz`）不在此列：它的 fact 叫
  `size_hps.simps`（块内局部名），三个名字都落空，但结构路径上那条无体公理
  `sz ≡ size_hps_sumC` 会按 `_sumC` 前的局部名再查一次 `size_hps.simps`（同样过
  保护）并被方程替换（PLAN.md §10.3 D9，2026-09-14）。
- **`instantiation` 里的 `fun`**：实例常量是 `Infra("inst_infix")`，无记录；
  类参数本身按缺陷 2 恒不失效。（其 fact 名 `T.c.simps` 与常量名 `T.c_inst.c`
  连前缀都不同，即便有记录按名字也取不到。）
- **`termination` 的增删让 digest 动一次**：证终止前只有带 `accp f_rel` 前提的
  `f.psimps`，证完多出 `f.simps`，来源从 `f.psimps` 换成 `f.simps`，方程未变而 digest 动一次
  （重解释一次、裁定一次、依赖者屏蔽）。在别的 theory 里证的 `termination`
  声明 theory 看不见，常量停在 `.psimps` 形式，方程编辑照样抓到。`.simps` 排在
  `.psimps` 之前是 2026-09-14 的决定；反过来能免掉这一次移动，但被否决。

### 已接受的约定

作者自己写的 `lemma X_def: "X x = …"` 按名字取到即当作 X 的定义——`_def`
不过保护（PLAN.md §10.3 D4）。对 abbreviation 尤其如此：`Fun.inj_def` 的左边
展开后头部是 `inj_on`，正因为 `_def` 不过保护它才进得来；全 heap 有 `_def`
fact 的入库 abbreviation 30 条（2026-09-14，87 个 theory 的 heap）都由此进
digest，替代展开体。它是作者给 X 的刻画等式，改了就该失效。

### 为何接受

`overloading` 三个名字的命题不变、来源换成 fact，块内 `fun` 的方程由 D9 补回；
`instantiation` 的实例常量本就无记录；
`termination` 增删极少发生，多付的是一次解释加一次裁定。2026-09-13 登记在此的
「locale target 里的 `fun`/`function`」与「自带登记表的定义包（Nominal2）」已
随名字路径关闭：前者的 `….F.simps` 是 theory 层 fact（实测
`Bit_Operations.fold2_bit_int.F`；它的 `termination` 是 `private`，fact 因而是
private 条目，按全名直接查 fact 表照样取到），后者记 fact 的代码是函数包的复制品、名字相同
（读 `nominal_function.ML:105-170`，未实测）。
