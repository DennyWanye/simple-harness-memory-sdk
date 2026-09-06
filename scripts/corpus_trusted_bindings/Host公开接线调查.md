# 240语料真正运行前的Host受众用途接线调查

2026-09-06。只读调查主候选 `ba6ac3c7`，读取其实际安装H0.7.3/M0.6.13/S0.3.13源码并核对METADATA版本。本轮不重新宣称完整wheel字节比对。主正在改 `context_route.py` 的失败/timeout/cancel审计，本报告仅引用调查时的召回调用位置，不修改该文件。未启动测试、模型、SDK实例、native或realtime，未创建新worktree；仅新增本报告。

**最小可执行修改必须进入Host当前披露配置、真实查询与物理出站边界，同时补M0613已有的非SELF限制。** 单改21个绑定或把共同policy放进system提示，无法使240 Host路径可执行。现有binding的ready=false是正确历史事实；后继生产实现需要真实配置/回读/验证成功后的执行资格，不能再加一层永久false来替代接线。

## 一、已确认的生产断点

| 位置 | 当前事实 | 对C12的影响 |
|---|---|---|
| [human_memory_api.py:346](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/memory/human_memory_api.py:346)、[human_memory_service.py:250](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/memory/human_memory_service.py:250) | `queue.enqueue`只接受scope_ref/delivery_key/text；`QueueTurnRequest`没有披露配置引用 | 21个source bindings没有可以绑定到实际turn的公共入口 |
| [human_memory_service.py:74](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/memory/human_memory_service.py:74) | `AuthenticatedHostSnapshot`仅subject/principal_id/authority_ref | 已有身份认证不等于当前受众、最终用途或policy已经绑定 |
| [human_memory_v7.py:278](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/memory/human_memory_v7.py:278) | typed_recall的326–338行固定USER_SELF/USER_SELF/TASK_EXECUTION，authority_ref为固定字符串 | 共同policy和最终第三方用途没有进入实际SDK查询；其370/398行将同一固定值送入RecallContext/RecallPlan |
| [primary_dependencies.py:56](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/execution/primary_dependencies.py:56) | `current_disclosure`按run/request拼ref，但仍固定SELF/TASK_EXECUTION | 即使查询改对，历史/记忆的再次使用仍会被当本人用途 |
| [primary_context.py:96](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/execution/primary_context.py:96) | prepare的110–111行只组装PERSONA及用户句；131、174行调用固定current_disclosure | 可信policy、公开材料与当前受众用途没有独立受保护的初始Context来源 |
| [primary_dependencies.py:274](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/execution/primary_dependencies.py:274)、[main.py:7777](/Users/denny/projects/simple_harness-primary-candidate/backend/main.py:7777)、[provider.py:593](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/sdk_adapters/provider.py:593) | 每次ProductProviderAdapter.invoke在delegate前已有primary_guard；它查完整依赖，但仍用固定current_disclosure | 有可复用的物理出站阻断点，缺的是真实当前配置与失效判定，不必另造模型runner |
| [task_scope/disclosure.py:150](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/task_scope/disclosure.py:150) | ScopeDisclosureReader.read也调用固定current_disclosure | C05候选预览、恢复和page-in必须共用相同当前用途，不能留SELF侧路 |

主的memory_types审计工作与本调查独立。`context_route.py`调查时349–353行已将模型选择的memory_types/include_short_horizon交给recall_executor；生产受众用途应由runtime按可信run绑定取值，不应增加模型可提交的recipient/authority参数。组合注入位置为 [main.py:8344](/Users/denny/projects/simple_harness-primary-candidate/backend/main.py:8344) 和8366。

## 二、SDK现有能力与必须修的限制

本节引用候选实际安装文件，定位修订时应修改对应SDK源并重新构建/接入候选，**不能直接改site-packages**。安装根为：

`/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-05/primary-candidate/venv/lib/python3.12/site-packages/`

| 安装根下文件及行号 | 已读事实 | 最小修订要求 |
|---|---|---|
| `simple_harness/runtime/disclosure_protocol.py:149–176` | recipient有USER_SELF/HOUSEHOLD/TASK_COLLABORATOR/EXTERNAL_PARTY/PUBLIC；audience分别有USER_SELF/HOUSEHOLD/TASK_COLLABORATORS/EXTERNAL/PUBLIC；purpose有TASK_EXECUTION/PERSONALIZATION/TASK_RESUME/USER_REVIEW/AUDIT/EXPORT/UNKNOWN | 使用真实枚举；工作介绍/草稿是Host细分用途，不得伪造SDK中的USER_INTERACTION或“work_intro”枚举 |
| `simple_harness/runtime/disclosure_protocol.py:222–282` | DisclosureContext已有recipient_id、intended_audience、purpose、source/trust/generation、authority_ref及context_hash；可信authority要求可信source及非空ref，自然语言/model source不能授信 | 类型构造的检查不能代替Host持久配置回读、当前代次检查或目的地验证；policy_id/hash/revision、最终对象/转交链须在Host快照中，必要公共协议扩展另行实现 |
| `simple_harness_memory/backends/sqlite_v5.py:5073–5080` | 普通召回只容许self/household/task_collaborator；external/public直接不满足门 | 外部/公开场景要有明确、统一的资格规则；不能伪装成self或collaborator通过，也不能盲目全面放开 |
| `simple_harness_memory/backends/sqlite_v5.py:5083–5101` | 候选门只读recipient/purpose/分类。self可读personal/sensitive；household/collaborator仅public且无health/family等敏感属性；没有联合判断intended_audience | 草稿当前交给本人但最终向外的情况必须按最终用途约束；仅设置intended_audience仍会留下self私密放行路径 |
| `simple_harness_memory/backends/history_visibility.py:428–435` | 直接要求`intended_audience.value == recipient.value` | 合法collaborator与collaborators枚举字符串不同，直接相等会拒绝；改成有语义的兼容/收紧矩阵。self接收、最终external的草稿也必须被明确建模，不能删除比较后毫无限制 |
| `simple_harness_memory/backends/history_visibility.py:216–255` | 原证据可见性明确限self，注释说明缺少item级authority；随后继续检查分类、认知引用和登记来源 | 只改Host受众会让当前用户证据也被拒绝。需新增来源与用途绑定的当前输入披露依据，不能把旧私人历史统一放开 |
| `simple_harness_memory/backends/sqlite_v5.py:2766–2789` | 短期非self过滤非public，typed short还走候选分类门 | 与长期、history和最终出站使用同一受众/用途语义；只改长期路径不足 |

这组限制是静态代码事实，未运行新反例。Host当前 [human_memory_v7.py:82](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/memory/human_memory_v7.py:82) 还把分类policy下限设为PERSONAL；不能为了让C12通过而把全库下限改成PUBLIC。

## 三、建议的最小生产修改

以下名称是拟新增API/实体，不冒称已存在。建议按同一交付实现Host配置到SDK和出站验证的闭环；先以少数真实fixture证明闭环，再补齐240设置，不改变类别/分母。

1. **增加Host用途配置的公开入口，并真正持久绑定turn。** 在`HumanMemoryHostService`增加创建/读取用途配置的受保护操作，例如`disclosure.bind`、`disclosure.read`；复用 [control_binding.py:30](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/memory/control_binding.py:30) 的连接认证、epoch/lease检查和writer fence。配置输入为21个显式绑定里的受众/用途/公开材料及独立policy配置引用，不能带gold或允许结果。Host选择真实subject与policy，写入不可变revision、canonical hash、有效代次、直接收件人/最终受众与转交目标、current input/public material的源hash，返回自己生成并可回读的receipt/ref。`human_memory_api.py:34–60`对subject/authority_ref等自授字段的拒绝保持，不把新字段做成自签权限入口。

2. **enqueue只绑定已验证的配置引用，且与幂等身份绑定。** 给`QueueTurnRequest`增加可验证的配置ref及预期revision/hash，在`enqueue_turn:956`的事务链内确认subject和配置仍有效；与 [foreground_queue.py:366](/Users/denny/projects/simple_harness-primary-candidate/backend/deskpet/execution/foreground_queue.py:366) 的turn payload/hash、幂等冲突及SDK run binding关联。同一delivery_key不得换用途静默重放；重启从持久记录恢复。不得从“用户说已同意”改policy。原SELF chat默认仅用于明确本人的普通入口，不能用于缺字段的C05-07 fixture救场。

3. **统一一个Host披露解析器，替换散落的固定构造。** 解析器按sdk_run_id/turn绑定与当前有效policy生成DisclosureContext。注入`HumanMemoryV7Runtime`、`PrimaryForegroundContextPort`、`ScopeDisclosureReader`、final primary_guard，统一query、short、Context、page-in、候选预览和出站。`typed_recall`不再自行固定SELF；`current_disclosure`改为可信存储/服务回读，必要时改异步或显式传入已验证快照。模型仍只提议query/type/route。旧固定字符串不能冒充当前配置receipt。

4. **补SDK联合披露策略与当前输入的来源许可。** 将上述ordinary/candidate/history/short门的recipient、intended_audience和purpose规则统一。草稿物理交给本人时可以保留实际recipient=USER_SELF，但最终audience=EXTERNAL/PUBLIC/TASK_COLLABORATORS必须收紧可用来源；实际向第三方发送时recipient需与可信工具目的地一致。C12-19还要核最终供应商，不能仅看助理。SDK对非本人工作用途继续拒绝health/family等受限来源；允许范围由真实配置与来源决定，不能只依靠输入里的“公开”字样。

   为避免非SELF下所有当前用户证据都被拒绝，增加**仅针对本轮确切输入/公开材料的可验证来源许可**：绑定source ref/hash、turn/run、subject、目的地/用途、policy revision、有效代次，经公开authority resolver/readback验证后才能在history可见性中使用。现有HostHistorySourceAuthority只提供source/forget来源证明（`history_source_authority.py:53/115`），不等于这种披露许可；需要真实公共协议或resolver扩展。没有该许可的旧原文证据继续按现有保守规则拒绝，不因为它出现在当前prompt就重新授信。保留suppression、完整因果/来源、分类和到期检查；特别不能把当前输入分支变成“忽略所有history依赖”的快捷通道。

5. **把可信配置投影到模型，并在每次物理出站核对它。** `primary_context.py:110–112`将共同policy、真实受众/用途及本轮公开材料作为独立受保护Context来源纳入snapshot hash和预算；用户句单独为user message。它们只来自Host配置，不来自class/gold/私密记录存在性。`check_runtime_dependencies:274`除已有来源可见性外，必须回读当前policy代次、核请求snapshot所绑定的配置和实际材料hash；变更/撤销/目的地替换后不能把旧请求标CURRENT。继续使用`ProductProviderAdapter.invoke:598`这一delegate前边界拒绝，已经物理handoff之后按主现有审计记录处理，不能倒填“未发送”。所有后继Provider请求也要检查，不能只查第一轮。

6. **记录真实执行证据后才允许ready。** Host setup receipt、SDK admission/mutation/readback、输入/配置snapshot、查询/无查询/最终出站trace均对应相同case/turn/run及clock。绑定成功、seed成功和执行成功分别记状态。C12模型选择零查询时只能证明决策与出站结果；后台隐私gate是否被触发须有真实trace，不能自动记100%。主正在实现的route失败审计不在本报告修改范围，接线时保留其完整失败/取消语义。

物理接收者与最终受众不能用一张字符串同值表混为一谈。C12的用途文字可映射到SDK TASK_EXECUTION这一粗粒度类别，但应同时保留Host具体用途及最终受众配置；是否为EMAIL/EXPORT等真实外发要由已验证产品操作决定，不能因为用户说“草稿”就忽略最终用途，也不能把所有草稿伪装成已经执行外发。

## 四、已有公开setup能力及240剩余义务

| 能力 | 确切入口/缺口 | 后续使用方式 |
|---|---|---|
| 主体与隔离实例 | `human_memory_v7.py:197–208`调用公开build并register_principal_owner；Host构造支持独立DB路径 | 每例或确定性隔离批次经真实组合构造，不写SDK私有表；不能使用case名字生成伪权限 |
| 证据/认知seed | 安装M0613 `core/manager.py:154` admit_evidence_source、163 ingest_committed_evidence、207 apply_memory_mutation_plan；Host `human_memory_service.py:514` append_primary_event | 可复用公开方法，但每个setup仍须有可验证的sanitation/classification/action来源与实际回读。不存在可把整段setup自然语言直接变成合法mutation的万能入口；缺日期/关系不得从gold或followup补 |
| 任务设置 | Host `human_memory_service.py:579` create_task_scope返回真实ref/revision/hash；603的deterministic event seed缺authority会拒绝 | C05任务、别名/revision/资料必须先经公开入口固定。预览继续只返回reader过滤的scope_disclosure，内部open不是正式resume授权 |
| 显式历史 | Host queue/foreground完整因果组与M0613 `core/manager.py:188` register_conversation_evidence、176 check_history_visibility | C07按既有真实提交/终态链建立user→assistant组；不能为了无模型seed伪造Provider terminal/ACK。缺可重放公开fixture来源时记录具体设置缺口 |
| 可信时钟 | M0613 `core/manager.py:512–537`已有公开构造clock，明确供recall/page-in/authority共用；Host `runtime_composition.py:24`虽收clock，但50–63没有传给HumanMemoryV7Runtime，`build_kwargs:153`也未传SDK；typed_recall:322仍默认time.time | 将同一可信clock沿组合→runtime→SDK builder、查询、context日期投影传到底。业务scenario time与真实资源/lease计时分开；不能只传请求now或只改system日期。C04-15用9月30日18:00 fixture，其他用原规定时间 |

提醒与Procedure的signal/observation公开facade分别在M0613 manager.py:1286/1280；它们仍要求真实authority来源，不能把正式240变成只有可seed类别的子集。全部seed具体化仍是后续工作，本次只读调查不宣称240已可运行。

## 五、原计划义务与本修订边界

- 原Memory计划 [acceptance.md:69](/Users/denny/projects/simple-harness-memory-sdk-corpus-runtime-input/plans/2026-08-29-human-memory-digital-twin/acceptance.md:69)（HM-AC-4）：全局候选仍强制recipient/purpose/最小披露；no-recall不查询记忆；任务搜索不直接授予scope执行范围。
- [acceptance.md:89](/Users/denny/projects/simple-harness-memory-sdk-corpus-runtime-input/plans/2026-08-29-human-memory-digital-twin/acceptance.md:89)：远程LLM调用前完成主体、scope、recipient/purpose、suppression和最小披露过滤。仅加prompt不满足这个义务。
- [acceptance.md:129](/Users/denny/projects/simple-harness-memory-sdk-corpus-runtime-input/plans/2026-08-29-human-memory-digital-twin/acceptance.md:129)（HM-S6）：给同事介绍时家庭/健康内容受限，审计解释用途过滤。当前SELF固定值不能覆盖该场景。
- S5a增量 [acceptance.md:96](/Users/denny/projects/simple-harness-memory-sdk-corpus-runtime-input/plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-s5a-context-route/acceptance.md:96)确实明确单用户chat lane由Host固定SELF/TASK_EXECUTION，模型值被覆盖。因此这不是模型应被允许提交权限的理由；后继需将该单用户默认扩展为Host可信配置选择，原文保留并在新的生产修订记录中说明，不能悄悄改冻结义务。
- 原HM-AC-8 [acceptance.md:73](/Users/denny/projects/simple-harness-memory-sdk-corpus-runtime-input/plans/2026-08-29-human-memory-digital-twin/acceptance.md:73)的90%/15%/100%和预算门不改；后继12×20仍是240，C05额外轮及C12补充对照不加分母。

## 六、建议下一个可验证交付

先实现上述同一披露配置从Host公开设置→turn/run→SDK查询→Context→物理出站的闭环，覆盖本人正向一例与C12同事、外部草稿、口头声称同意、助理转交四种语义。必须同时证明公开当前材料可进入请求、旧私密来源不可进入请求，以及配置失效后旧Context不能继续发送；不能只有“永远拒绝”负例。

先在主协调的资源槽做公共真实store/authority及delegate前拒绝验收，补充强制违规lookup可验证SDK门，但不把这些补充调用计入正式零查询题或原分母。主复核21个绑定及生产闭环后，再通过真实Host公共setup逐类补齐240；设置不足留下明确case级原因，不自动缩小正式评估集。真实模型/native执行由主安排，本调查不启动任何调用，也不恢复暂停的realtime。
