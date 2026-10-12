# MySQL 业务规则与平台经验对照

MySQL结构快照：2026-10-12T04:53:31.538519+00:00；平台资产快照：2026-09-22。

原始结构和实际字段以MySQL为准，平台资料是独立历史来源。所有自动来源匹配与关联均为候选，推数血缘、预过滤、时效、完整性和唯一性未获证实。未知业务含义留空。

每个业务问题先查表与business_context，辨明目标粒度、日期、组织、指标，再设计受限参数模板。结构工具只读本地资料；业务样例遵循每表累计50行及持久缓存。

## 主营口径

门店级销售/交易分析默认主营。字段存在且粒度适用时用 busi_unit_lev1_name = '主营'；汇总表 zhuying_* 仅沿用其原始注释，预过滤及与明细的等价性待确认。缺字段不能认定上游已过滤。

来源：SKILL.md §2.1。

## 销售金额

明细销售默认 acco_amt；sale_amt 例外限已核实的综合毛利场景。total_amount、zhuying_amount、xls_amount 按各自原注释分别使用，不能直接与 acco_amt 或彼此等同。金额是否含税、退货处理及渠道范围待确认。

来源：SKILL.md §2.2、§2.7。

## 成本字段

原明细移动成本字段为 cost_amt_v2。MySQL 缺少时不猜测替代字段，也不由销售额减任意毛利倒推成本；具体指标先核实成本口径。

来源：SKILL.md §6.1 小票明细拓展表。

## X大类

X大类指 goods_code LIKE 'X%'。保留编码字符串及前导零，不改为包含匹配。

来源：SKILL.md §2.3。

## 中文别名

MySQL 中文标识符用反引号。实际字段名和原始注释以 MySQL 元数据为准；平台注释作为独立来源保留，不覆盖缺失或冲突注释。

来源：SKILL.md §2.4、§2.9。

## 正常经营直营门店

适用于门店粒度且三个字段齐备时：busi_ascr_code IN ('1','4') AND shop_age_type_code IN ('1','2','3','4','8') AND format_code LIKE '%01%'。字段缺少则需要合适门店维表及时间条件。LIKE 保留原口径，不自行替换为不同的多值精确匹配。

来源：SKILL.md §2.5。

## 策略分类层级

禁止以 goods_class_name 分组。strategy_classify_name 在旧技能正文称三级，但部分DDL注释为二级，必须按场景确认；sc1/sc2/sc3 各按自身注释的层级使用，不自动互换或补成同一字段。

来源：SKILL.md §2.6；核心DDL。

## 废弃字段

禁止使用 MySQL 注释标明废弃或停用的字段。同名候选平台字段出现这些标记时列为风险提示，先核实来源，不覆盖当前字段定义。

来源：SKILL.md §2.6。

## 综合毛利

区分前台、补偿后、综合以及含下游支出的毛利额。不同层级和渠道不能混用。原综合毛利表 T-2、dt 过滤约定只保留为来源说明，不能断言 MySQL 同步已满足。

来源：SKILL.md §2.7、§6.1。

## 日期与ISO周

以实际字段、类型和确认的日期格式限定范围，不凭表名后缀或年度尾缀断言分区/数据范围。T-1/T-2 时效待证实。MySQL ISO周年使用 DATE_FORMAT(date_value, '%x-W%v')，不用日历年 %Y 拼ISO周；date_value 须为已核实日期值。日期维表缺失时不编造节假日。

来源：SKILL.md §2.8、§1.3、§3.1。

[官方参考](https://dev.mysql.com/doc/refman/8.0/en/date-and-time-functions.html)

## 粒度与关联

先过滤、按目标粒度聚合，再关联维表。核对键类型、前导零、快照日期和重复风险；同名键/索引/50行样例不能证明业务一对一。除法用 NULLIF(分母,0)，空串与NULL分别判断。

来源：SKILL.md §3.1.3–6。

## 历史热度与排除

平台热度是2026-09-22历史参考。H1-H5可优先比较，H0按需；HU和dm_del八张排除来源不自动推荐。未匹配MySQL表仍允许查看结构及受限样例，不能仅凭热度确定正确来源，不改变四库访问白名单。

来源：SKILL.md §0、§1.2、§1.6；用户确认的MySQL适配。

## MySQL查询边界

只访问四业务库，显式列裁剪；业务样例每表累计最多50行且缓存复用。具体汇总先明确日期、组织、指标和粒度，再新增参数模板及普通EXPLAIN检查。无任意SQL入口，无全量明细提取，不以外层LIMIT掩盖无范围聚合。

来源：项目AGENTS.md；SKILL.md §3。

## 平台调度写入规范

Spark建表、分区、临时表、INSERT OVERWRITE和调度参数仅属平台历史知识，本项目不执行；不修改MySQL表、权限、视图或索引。

来源：SKILL.md §4–5。

## 对照与刷新

同名表优先，再检查仅去除年度尾缀的名称；其余用字段名Jaccard相似度检索至多3个候选（共有字段至少8个、相似度至少0.55）。这些阈值只控制候选检索，不代表置信度或业务认可。

同名字段按名称对照，不执行自动重命名。字符串存储类型、数值精度、注释和缺失字段差异均保留。来源CSV记录号指数据记录序号，从1开始，不是文本行号。

原技能ZIP内的SKILL.md、CSV与DDL保留原文。核心DDL与CSV冲突时并列证据；源侧排除的dm_del八表仍保留排除标记。源侧已有候选不代表MySQL数据已同步完成。

先执行 mysql_analysis.py refresh 刷新元数据，再执行 reconcile_knowledge.py 离线重建。两步间MCP显示资料过期，原始结构仍可使用。无需清理state/samples，禁止通过重建重置读取额度。

## 来源内部冲突

- 来源内部字段数冲突：SKILL.md §2.7为74字段；随包CSV为35字段。以各快照的实际字段清单为准。 证据：SKILL.md §2.7 / assets/字段明细.csv / references/packaging-changelog.md §4.2
- 来源内部分类层级冲突：技能正文将strategy_classify_name称为三级；综合毛利DDL将其注释为二级。不能全局认定同一层级。 证据：SKILL.md §2.6 / references/ddl/dm_com.comprehensive_profit_base_data_dfp.sql
- 业务日期与分区字段不同：综合毛利旧规则要求按dt过滤，但DDL分区字段为DATE。不能把dt直接等同分区列，MySQL范围过滤须另行核实。 证据：SKILL.md §2.7 / references/ddl/dm_com.comprehensive_profit_base_data_dfp.sql
