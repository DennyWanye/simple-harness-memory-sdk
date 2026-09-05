# 04 time：20条后继草稿

2026-09-06｜中文审查材料，待主代理复核；未运行模型。不得把本文件整体交给模型。ID/条件/setup/gold仅供设置与计分；模型初始只接收公共输入规则及每条 provider_input，随后只接收真实工具的合格返回。

通用上下文、证据与计分边界见[总索引](/Users/denny/projects/simple-harness-memory-sdk/plans/2026-08-29-human-memory-digital-twin/quality/recall-corpus-candidate/review-zh/successor-12x20/总索引.md)。每条独立隔离数据；记录代号为设置说明，不能当作模型已获得的ref。

本类继承gold：required_types=episode,prospective；no_recall=false；privacy_allowed=true；hard_trigger=无；requires_task_scope_search=false。每条以下gold补充必需事实和禁止行为，不改变这些原类别标签。

## C04-01｜周五验样结果与下周一待办

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月4日验样封面偏暗；P：9月7日09:00上海时区提醒索取修正版，pending。

**provider_input（初始可见）：** 周五验样结果如何？我还留了什么周一要做的提醒？现在只列，不执行。

**gold（仅计分端）：** 取E/P，偏暗+周一九点索样；未到期，不声称触发。

## C04-02｜跨月回顾与下月明确提醒

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：8月31日盘点缺两本；P：9月8日10:00提醒补登记，pending。

**provider_input（初始可见）：** 上月底盘点发现什么，这个月对应的补办提醒是什么时间？

**gold（仅计分端）：** 缺两本+9月8日十点补登记；不选其他月份盘点。

## C04-03｜跨年事件和下一年预约提醒

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：2025年12月31日整理年册缺照片；P：2027年1月2日10:00提醒补拍年册素材，pending。

**provider_input（初始可见）：** 回顾上个跨年整理年册的问题，再列明年一月已经定下的相关提醒。

**gold（仅计分端）：** 分别给2025年缺照片和2027年一月提醒，不把年份自动当同一年。

## C04-04｜已发生事件与未到期时间意图区分

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月5日试用导出成功；P：9月10日15:00提醒清点导出副本，pending。

**provider_input（初始可见）：** 导出试用最后怎么样？未来已经记下哪项核查？不要现在去做。

**gold（仅计分端）：** 成功+未来清点；取episode/prospective，不将未到期作为completed。

## C04-05｜上午下午同日事件消歧

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E1：9月5日09:00打印偏色；E2：当天15:00校色通过；P：9月7日11:00提醒领取校色样。

**provider_input（初始可见）：** 昨天下午那次校色结果和后续取样提醒是什么？

**gold（仅计分端）：** 选下午通过而非上午偏色；给周一十一点取样。

## C04-06｜明确时区换算后的提醒展示

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月4日远程访谈音频缺段；P：9月8日09:00 Europe/London提醒补录，来源有明确时区。

**provider_input（初始可见）：** 访谈出了什么问题？补录提醒换成北京时间告诉我，先别通知任何人。

**gold（仅计分端）：** E缺段；P换算9月8日16:00上海时区；时区转换需明确该日偏移，不执行通知。

## C04-07｜事件时间不等于入库时间

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：8月20日因页码错序返工，9月5日才录入；P：9月9日14:00提醒复核，pending。

**provider_input（初始可见）：** 八月二十日那次返工因为什么，后续复核提醒定在何时？

**gold（仅计分端）：** 按事件发生时间定位页码错序；给9月9日14:00，不说9月5日发生。

## C04-08｜相对昨天与明天结合固定时钟

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月5日交接少一份表；P：9月7日08:30提醒补送表格，pending。

**provider_input（初始可见）：** 昨天交接缺什么，明天一早我留了哪项提醒？

**gold（仅计分端）：** 少一份表+明天08:30补送；相对日期基于当前固定时钟。

## C04-09｜指定周范围不召回其他周

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E1：8月24–30周修复缺页；E2：8月31–9月6周发现重复封面；P：9月8日提醒复核封面。

**provider_input（初始可见）：** 只回顾八月三十一日到九月六日这周，问题是什么，下周对应提醒是什么？

**gold（仅计分端）：** E2重复封面+9月8日复核；不混前周缺页。

## C04-10｜事件触发待办尚未触发

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：上次借书归还时漏带借阅卡；P：下一次归还成功后提醒归档借阅回执，pending事件触发。

**provider_input（初始可见）：** 上次还书漏带了什么？我定过下次还完以后要提醒的哪件事？

**gold（仅计分端）：** 漏卡+归档回执；未有新归还成功信号，不触发或结算。

## C04-11｜失败事件不满足成功型提醒

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月5日试印失败，颜色不符；P：试印验收成功后提醒寄正式样，pending。

**provider_input（初始可见）：** 昨天试印结果和我定下的后续提醒分别是什么？只回顾和列待办。

**gold（仅计分端）：** 失败/颜色不符+成功后寄样；失败不满足成功触发。

## C04-12｜延期事件与改期后的提醒

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月4日因场地检修推迟讨论；P：已rescheduled为9月9日09:30提醒确认新场地；旧9月7日提醒superseded。

**provider_input（初始可见）：** 讨论为什么延期？现在有效的场地确认提醒是哪天？

**gold（仅计分端）：** 检修+9月9日09:30；不重提旧提醒作当前待办。

## C04-13｜同一截止日前的结果和准备提醒

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月3日申请材料核对缺签名；P：9月9日10:00提醒补签，截止日9月10日。

**provider_input（初始可见）：** 申请上次查出缺什么，截止前我设了什么准备提醒？

**gold（仅计分端）：** 缺签名+9月9日十点补签；不把截止日当提醒时间。

## C04-14｜分阶段任务的对应事件与待办

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：第一阶段数据去重完成，第二阶段格式检查未开始；P：9月8日14:00提醒开始格式检查。

**provider_input（初始可见）：** 第一阶段上次完成了什么，接第二阶段的已定提醒是什么？

**gold（仅计分端）：** 去重完成+开始格式检查；不声称第二阶段已完成。

## C04-15｜季度边界的回顾和下一季度动作

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-30T18:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：2026年9月30日16:00三季度清点缺备份索引，17:00已入账；P：2026年10月2日10:00提醒补索引，pending。

**provider_input（初始可见）：** 三季度清点发现什么，下一季度首项提醒是什么？

**gold（仅计分端）：** 缺索引+10月2日十点补索引，跨季度不跨成错误年份。

## C04-16｜最近一次而非首次事件

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E1：7月首次试课麦克风失效；E2：9月4日最近试课计时超长；P：9月7日12:00提醒缩短练习。

**provider_input（初始可见）：** 最近一次试课出了什么问题，随后设下了什么提醒？

**gold（仅计分端）：** E2超时+缩短练习；不选首次麦克风问题。

## C04-17｜历史取消经历与仍有效另一待办

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：8月团体出游因天气取消；P：9月10日16:00提醒核对退回押金，pending；旧出发提醒已取消。

**provider_input（初始可见）：** 那次出游为什么取消？现在还有效的相关待办提醒是什么？

**gold（仅计分端）：** 天气取消+核对押金；不复活出发提醒。

## C04-18｜日期缺省年份由明确上下文补足

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：2026年8月12日修订封面缺作者名；P：2026年9月12日09:00提醒交修正版。

**provider_input（初始可见）：** 这里说的八月和九月都是2026年。八月十二日改封面发现什么，九月十二日有什么提醒？

**gold（仅计分端）：** 作者名缺失+9月12日九点交修正版，不猜别的年份。

## C04-19｜过去结果未知不补造但仍列明确待办

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月4日测试已开始但执行记录中结果尚未确认；P：9月8日10:00提醒追问测试结果。

**provider_input（初始可见）：** 周五测试最终结果是什么？我对后续跟进设了什么提醒？

**gold（仅计分端）：** 取E说明结果未确认而非编造成功；P给追问时间，两个来源均必需。

## C04-20｜两个时区下日期翻转但同一时刻

**scenario_clock（设置端，非用户文本/非gold）：** 2026-09-06T10:00:00+08:00；timezone=Asia/Shanghai。Host clock、public SDK as_of/evaluated_at及Provider可信日期上下文必须由这同一个fixture clock适配；无法统一则记设置缺口，不运行成另一时刻。时钟字段不含提醒正确答案。

**setup（模型初始不可见）：** E：9月4日夜间传稿漏附件；P：9月8日00:30 Asia/Shanghai提醒补附件，原始trigger仅记录上海时间；UTC结果由计分端独立换算核对，不在初始提示补答案。

**provider_input（初始可见）：** 夜间传稿漏了什么？把补交提醒同时按上海和UTC标注日期时间。

**gold（仅计分端）：** 漏附件+两种等价时间；日期翻转不是两条提醒，不新增调度。

本文件20条；gold是期望，不是实测结果。零查询、零披露、后台gate是否执行必须分别由真实trace核对。
