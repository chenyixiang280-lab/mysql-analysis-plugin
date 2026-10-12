---
name: mysql-business-rules
description: 查询当前四个MySQL业务库、解释平台推数表和字段、设计经营分析或报表SQL时，结合mysql_analysis MCP读取真实结构与历史业务规则对照。适用于本项目，不用于操作旧大数据平台或通用SQL问题。
---

# MySQL 业务规则

本项目以已经接通的 MySQL 作为目录、结构和受限样例入口。旧平台经验提供业务口径参考。

## 使用

1. 使用 `mysql_analysis.list_tables` 找表，再用 `describe_table` 取得原始结构和 `business_context`。字段、类型及现有注释以 MySQL 返回为准。
2. 阅读 `business_context` 中该表的来源候选、规则、关联候选和待确认项。需要规则全文或冲突背景时，读取[MySQL业务规则](references/MySQL业务规则.md)。完整机器目录在绑定的原项目 `knowledge/business_catalog.json`，按表读取，不把整份目录送入上下文。
3. 询问具体报表缺少的日期、组织、指标和粒度。依已确认口径设计 MySQL 8.0 参数模板；当前 MCP 没有报表执行或任意 SQL 工具。
4. 只有确需了解内容才调用 `sample_table`，每表累计最多50行，重复调用读取固定缓存。目录重建不产生新的读取额度。

## 使用证据

- `status=current` 仅表示口径资料与当前元数据快照匹配，不表示数据库实时数据、推数血缘或业务口径已验证。
- 同名、字段名集合一致、年度尾缀、字段相似均为来源候选。缺少推数SQL时，不声明同步来源已证实，也不把样例当作完整性、时效或唯一性证据。
- 平台热度是历史参考；HU及源端排除表不自动推荐。未匹配MySQL对象仍可查看结构与受限样例，不继承平台“未登记即禁用”的整体限制。
- 原始MySQL注释、平台注释分开保留。业务用途缺失时留空，不能把候选来源说明写成已确认用途。
- 主营过滤、正常经营直营门店三条件、销售/成本/毛利字段、策略分类层级，均按本表的适用条件执行。缺字段时提示需要映射，不自动跳过或认定上游已处理。
- `goods_class_name` 及MySQL注释含“废弃”“停用”的字段不使用。`strategy_classify_name` 与 `sc1/sc2/sc3` 不自动等同。
- `business_context.status` 为 `stale` 或 `unavailable` 时，仍可查看原始结构，不能把旧口径当当前适用结论；在绑定的原项目目录使用其 `.venv/Scripts/python.exe` 运行 `reconcile_knowledge.py` 离线重建。需要最新结构时先使用同一原项目环境运行 `mysql_analysis.py refresh`，这一步只采集元数据。

## 读取边界

仅访问 `category_strategy`、`data_manage`、`new_goods`、`new_goods_manage`。凭据仅由既有连接模块从Windows凭据管理器读取。不得分页、换条件扩大样例或删除缓存重取；不得全量明细提取。汇总必须先明确报表口径并新增有范围参数模板；不修改原数据库、权限、索引或视图。

技能与MCP的口径以统一JSON为依据；源技能ZIP仅保留在绑定的原项目 `knowledge/source/`，不随插件发布。本技能不要求重新打通或自动回退到旧平台。
