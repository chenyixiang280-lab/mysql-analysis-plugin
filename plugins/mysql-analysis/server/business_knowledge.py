"""Offline warehouse/MySQL comparison and read-only MCP enrichment."""
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_PATH = ROOT / 'knowledge/business_catalog.json'
SOURCE_ZIP = ROOT / 'knowledge/source/dw-sql-rules.zip'
PREFIX = 'dw-sql-rules/'
UNKNOWN = ['推数血缘未证实', '数据覆盖范围及最新更新时间待确认',
           '上游预过滤条件待确认', '业务粒度及连接键唯一性未验证']
MATCH_LABELS = {'same_name': '同名候选', 'annual_suffix': '年度拆表候选',
                'similar_fields': '字段相似候选', 'unmatched': '未匹配',
                'columns_unavailable': '字段不可见'}
EXCLUDED = ['war_zone_goods_stock_sales_dfp', 'shop_goods_price_group_dfp',
            'group_goods_stock_sales_dfp', 'shop_price_group_dfp',
            'hn_war_zone_n_insu_goods_stock_sales_dfp', 'js_goods_stock_sales_dfp',
            'shop_stock_analysis_dfp', 'group_goods_stock_sales_cut_dfp']

# Rules are authored once here; JSON, Markdown and MCP all consume this registry.
RULES = [
    {'id': 'main_business', 'title': '主营口径', 'source': 'SKILL.md §2.1',
     'fields': ['busi_unit_lev1_name'],
     'guidance': "门店级销售/交易分析默认主营。字段存在且粒度适用时用 busi_unit_lev1_name = '主营'；汇总表 zhuying_* 仅沿用其原始注释，预过滤及与明细的等价性待确认。缺字段不能认定上游已过滤。"},
    {'id': 'sales', 'title': '销售金额', 'source': 'SKILL.md §2.2、§2.7',
     'fields': ['acco_amt', 'sale_amt', 'total_amount', 'zhuying_amount', 'xls_amount'],
     'guidance': '明细销售默认 acco_amt；sale_amt 例外限已核实的综合毛利场景。total_amount、zhuying_amount、xls_amount 按各自原注释分别使用，不能直接与 acco_amt 或彼此等同。金额是否含税、退货处理及渠道范围待确认。'},
    {'id': 'cost', 'title': '成本字段', 'source': 'SKILL.md §6.1 小票明细拓展表',
     'fields': ['cost_amt_v2'],
     'guidance': '原明细移动成本字段为 cost_amt_v2。MySQL 缺少时不猜测替代字段，也不由销售额减任意毛利倒推成本；具体指标先核实成本口径。'},
    {'id': 'goods_prefix', 'title': 'X大类', 'source': 'SKILL.md §2.3',
     'fields': ['goods_code'], 'guidance': "X大类指 goods_code LIKE 'X%'。保留编码字符串及前导零，不改为包含匹配。"},
    {'id': 'aliases', 'title': '中文别名', 'source': 'SKILL.md §2.4、§2.9',
     'fields': [], 'guidance': 'MySQL 中文标识符用反引号。实际字段名和原始注释以 MySQL 元数据为准；平台注释作为独立来源保留，不覆盖缺失或冲突注释。'},
    {'id': 'normal_shops', 'title': '正常经营直营门店', 'source': 'SKILL.md §2.5',
     'fields': ['busi_ascr_code', 'shop_age_type_code', 'format_code'],
     'guidance': "适用于门店粒度且三个字段齐备时：busi_ascr_code IN ('1','4') AND shop_age_type_code IN ('1','2','3','4','8') AND format_code LIKE '%01%'。字段缺少则需要合适门店维表及时间条件。LIKE 保留原口径，不自行替换为不同的多值精确匹配。"},
    {'id': 'strategy', 'title': '策略分类层级', 'source': 'SKILL.md §2.6；核心DDL',
     'fields': ['strategy_classify_name', 'sc1_name', 'sc2_name', 'sc3_name', 'goods_class_name'],
     'guidance': '禁止以 goods_class_name 分组。strategy_classify_name 在旧技能正文称三级，但部分DDL注释为二级，必须按场景确认；sc1/sc2/sc3 各按自身注释的层级使用，不自动互换或补成同一字段。'},
    {'id': 'deprecated', 'title': '废弃字段', 'source': 'SKILL.md §2.6',
     'fields': [], 'guidance': '禁止使用 MySQL 注释标明废弃或停用的字段。同名候选平台字段出现这些标记时列为风险提示，先核实来源，不覆盖当前字段定义。'},
    {'id': 'profit', 'title': '综合毛利', 'source': 'SKILL.md §2.7、§6.1',
     'fields': ['before_comp_profit', 'comperhensive_profit_included_mkt_payout',
                'total_qt_profit', 'total_bch_profit', 'total_zh_profit', 'total_zh_profit_payout',
                'zhuying_qt_profit', 'zhuying_bch_profit', 'zhuying_zh_profit', 'zhuying_zh_profit_payout'],
     'guidance': '区分前台、补偿后、综合以及含下游支出的毛利额。不同层级和渠道不能混用。原综合毛利表 T-2、dt 过滤约定只保留为来源说明，不能断言 MySQL 同步已满足。'},
    {'id': 'dates', 'title': '日期与ISO周', 'source': 'SKILL.md §2.8、§1.3、§3.1',
     'fields': ['dt', 'month', 'data_date', 'date_id', 'year', 'dw_etl_time', 'dw_last_update_time'],
     'guidance': "以实际字段、类型和确认的日期格式限定范围，不凭表名后缀或年度尾缀断言分区/数据范围。T-1/T-2 时效待证实。MySQL ISO周年使用 DATE_FORMAT(date_value, '%x-W%v')，不用日历年 %Y 拼ISO周；date_value 须为已核实日期值。日期维表缺失时不编造节假日。",
     'reference': 'https://dev.mysql.com/doc/refman/8.0/en/date-and-time-functions.html'},
    {'id': 'joins', 'title': '粒度与关联', 'source': 'SKILL.md §3.1.3–6',
     'fields': [], 'guidance': '先过滤、按目标粒度聚合，再关联维表。核对键类型、前导零、快照日期和重复风险；同名键/索引/50行样例不能证明业务一对一。除法用 NULLIF(分母,0)，空串与NULL分别判断。'},
    {'id': 'heat', 'title': '历史热度与排除', 'source': 'SKILL.md §0、§1.2、§1.6；用户确认的MySQL适配',
     'fields': [], 'guidance': '平台热度是2026-09-22历史参考。H1-H5可优先比较，H0按需；HU和dm_del八张排除来源不自动推荐。未匹配MySQL表仍允许查看结构及受限样例，不能仅凭热度确定正确来源，不改变四库访问白名单。'},
    {'id': 'mysql_readonly', 'title': 'MySQL查询边界', 'source': '项目AGENTS.md；SKILL.md §3',
     'fields': [], 'guidance': '只访问四业务库，显式列裁剪；业务样例每表累计最多50行且缓存复用。具体汇总先明确日期、组织、指标和粒度，再新增参数模板及普通EXPLAIN检查。无任意SQL入口，无全量明细提取，不以外层LIMIT掩盖无范围聚合。'},
    {'id': 'spark_etl', 'title': '平台调度写入规范', 'source': 'SKILL.md §4–5',
     'fields': [], 'guidance': 'Spark建表、分区、临时表、INSERT OVERWRITE和调度参数仅属平台历史知识，本项目不执行；不修改MySQL表、权限、视图或索引。'},
]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def read_source(path=SOURCE_ZIP):
    with zipfile.ZipFile(path) as archive:
        def rows(name):
            return csv.DictReader(io.StringIO(archive.read(PREFIX + name).decode('utf-8-sig')))
        tables = {}
        for record, row in enumerate(rows('assets/表热度关联清单.csv'), 1):
            key = row['database'] + '.' + row['table']
            tables[key] = {k: row[k] for k in ['database', 'table', 'tableDesc', 'hotTier',
                          'columnCount', 'partitionCount', 'dataUpdateTime', 'snapshotDate']}
            tables[key].update(heat_record=record, fields={})
        for record, row in enumerate(rows('assets/字段明细.csv'), 1):
            key = row['数据库'] + '.' + row['表名']
            tables[key]['fields'][row['字段名']] = {'type': row['数据类型'],
                'comment': row['字段注释'], 'record': record, 'ordinal': row['字段序号']}
        texts = {n.removeprefix(PREFIX): archive.read(n).decode('utf-8-sig')
                 for n in archive.namelist() if n.endswith(('.md', '.sql'))}
    return tables, texts


def mysql_fields(catalog):
    result = defaultdict(dict)
    for c in catalog['columns']:
        result[c['TABLE_SCHEMA'] + '.' + c['TABLE_NAME']][c['COLUMN_NAME']] = {
            'type': c['COLUMN_TYPE'], 'comment': c['COLUMN_COMMENT'],
            'ordinal': c['ORDINAL_POSITION']}
    return result


def compare_fields(current, source):
    result = []
    for name in sorted(current.keys() | source.keys()):
        left, right = current.get(name), source.get(name)
        result.append({'mysql_field': name if left else None, 'source_field': name if right else None,
            'mysql_type': left['type'] if left else None, 'source_type': right['type'] if right else None,
            'mysql_comment': left['comment'] if left else None, 'source_comment': right['comment'] if right else None,
            'source_record': right['record'] if right else None,
            'presence': 'shared' if left and right else ('mysql_only' if left else 'source_only'),
            'type_status': ('same_declaration' if re.sub(r'\s+', '', left['type']).lower() ==
                            re.sub(r'\s+', '', right['type']).lower() else 'different_review') if left and right else None,
            'comment_status': ('same' if left['comment'] == right['comment'] else
                               'different' if left['comment'] and right['comment'] else 'missing_one_side') if left and right else None})
    return result


def candidates(name, current, source, by_name):
    if not current:
        return 'columns_unavailable', []
    keys = by_name.get(name, [])
    method = 'same_name'
    if not keys:
        annual = re.sub(r'_20\d{2}$', '', name)
        keys = by_name.get(annual, []) if annual != name else []
        method = 'annual_suffix'
    if not keys:
        scores = []
        names = set(current)
        for key, item in source.items():
            other = set(item['fields'])
            shared = len(names & other)
            score = shared / len(names | other) if names | other else 0
            if shared >= 8 and score >= 0.55:
                scores.append((-score, key))
        keys = [key for _, key in sorted(scores)[:3]]
        method = 'similar_fields' if keys else 'unmatched'
    result = []
    for key in sorted(keys):
        src = source[key]
        comparisons = compare_fields(current, src['fields'])
        result.append({'source_table': key, 'source_description': src['tableDesc'],
            'hot_tier': src['hotTier'], 'source_snapshot': src['snapshotDate'],
            'source_update_time': src['dataUpdateTime'], 'source_partition_count': src['partitionCount'],
            'heat_record': src['heat_record'], 'field_name_set_equal': set(current) == set(src['fields']),
            'mysql_field_count': len(current), 'source_field_count': len(src['fields']),
            'common_field_count': len(set(current) & set(src['fields'])),
            'automatic_recommendation_allowed': src['hotTier'] != 'HU' and key not in ['dm_del.' + n for n in EXCLUDED],
            'lineage_status': 'unverified', 'fields': comparisons})
    return method, result


def applicable_rules(fields):
    names = set(fields)
    result = []
    for rule in RULES:
        present = [n for n in rule['fields'] if n in names]
        missing = [n for n in rule['fields'] if n not in names]
        status = '通用规则' if not rule['fields'] else '有相关字段_业务前提待确认' if present else '无对应字段_需映射'
        if rule['id'] == 'normal_shops':
            status = '三字段齐备_门店粒度待确认' if not missing else '门店过滤字段不足'
        if rule['id'] == 'spark_etl':
            status = '本项目不适用'
        result.append({'rule_id': rule['id'], 'status': status, 'present_fields': present,
                       'missing_fields': missing})
    return result


def join_candidates(key, fields, all_fields):
    result = []
    for anchor, keys, grain in [
        ('data_manage.group_goods_info_dfn', ['goods_code'], '商品编码候选粒度'),
        ('new_goods_manage.xp_shops_info_qll_dfp', ['dept_id'], '门店及快照日期候选粒度')]:
        target = all_fields.get(anchor, {})
        if key == anchor or not all(k in fields and k in target for k in keys):
            continue
        result.append({'target_table': anchor, 'status': 'candidate_unverified',
            'keys': [{'source_field': k, 'target_field': k, 'source_type': fields[k]['type'],
                      'target_type': target[k]['type']} for k in keys],
            'target_grain': grain, 'cardinality': 'unknown',
            'risk': '仅同名键候选；业务编码域、前导零、重复记录及历史快照条件须按具体报表核验，不能直接认定一对一。'})
    return result


def source_conflicts(source, texts):
    result = []
    skill = texts['SKILL.md']
    profit = source.get('dm_com.comprehensive_profit_base_data_dfp', {})
    if '74字段' in skill and profit:
        result.append({'table': '', 'kind': '来源内部字段数冲突',
            'detail': f"SKILL.md §2.7为74字段；随包CSV为{len(profit['fields'])}字段。以各快照的实际字段清单为准。",
            'evidence': 'SKILL.md §2.7 / assets/字段明细.csv / references/packaging-changelog.md §4.2'})
    ddl = texts.get('references/ddl/dm_com.comprehensive_profit_base_data_dfp.sql', '')
    if '三级策略分类' in skill and "strategy_classify_name STRING COMMENT '二级策略分类'" in ddl:
        result.append({'table': '', 'kind': '来源内部分类层级冲突',
            'detail': '技能正文将strategy_classify_name称为三级；综合毛利DDL将其注释为二级。不能全局认定同一层级。',
            'evidence': 'SKILL.md §2.6 / references/ddl/dm_com.comprehensive_profit_base_data_dfp.sql'})
    if 'PARTITIONED BY (DATE STRING)' in ddl:
        result.append({'table': '', 'kind': '业务日期与分区字段不同',
            'detail': '综合毛利旧规则要求按dt过滤，但DDL分区字段为DATE。不能把dt直接等同分区列，MySQL范围过滤须另行核实。',
            'evidence': 'SKILL.md §2.7 / references/ddl/dm_com.comprehensive_profit_base_data_dfp.sql'})
    return result


def build(catalog, source, texts, zip_hash):
    columns = mysql_fields(catalog)
    by_name = defaultdict(list)
    for key, item in source.items():
        by_name[item['table']].append(key)
    tables = {}
    conflicts = source_conflicts(source, texts)
    for table in catalog['tables']:
        key = table['TABLE_SCHEMA'] + '.' + table['TABLE_NAME']
        fields = columns[key]
        method, matches = candidates(table['TABLE_NAME'], fields, source, by_name)
        hints = []
        if len(matches) > 1:
            hints.append('多个来源候选，未选定唯一来源')
        if any(m['hot_tier'] == 'HU' for m in matches):
            hints.append('含HU来源候选，不自动推荐')
        forbidden = [n for n, f in fields.items() if n == 'goods_class_name' or re.search('废弃|停用', f['comment'])]
        if forbidden:
            hints.append('存在禁止使用字段：' + '、'.join(forbidden))
        for m in matches:
            for f in m['fields']:
                if f['presence'] == 'shared' and re.search('废弃|停用', f['source_comment'] or ''):
                    hints.append('平台候选字段标记废弃/停用：' + m['source_table'] + '.' + f['source_field'])
        tables[key] = {'database': table['TABLE_SCHEMA'], 'table': table['TABLE_NAME'],
            'object_type': table['TABLE_TYPE'], 'business_purpose': table['TABLE_COMMENT'] or None,
            'purpose_status': 'mysql_comment' if table['TABLE_COMMENT'] else 'unknown',
            'match_method': method, 'match_label': MATCH_LABELS[method],
            'lineage_status': 'unverified', 'mysql_fields': fields, 'source_candidates': matches,
            'rules': applicable_rules(fields), 'join_candidates': join_candidates(key, fields, columns),
            'forbidden_fields': forbidden, 'key_hints': list(dict.fromkeys(hints)), 'unknowns': UNKNOWN.copy()}
        for hint in dict.fromkeys(hints):
            conflicts.append({'table': key, 'kind': '选表或字段风险', 'detail': hint,
                              'evidence': 'MySQL元数据及表字段对照'})
        for match in matches:
            diffs = Counter(f['presence'] if f['presence'] != 'shared' else 'shared' for f in match['fields'])
            types = sum(f['type_status'] == 'different_review' for f in match['fields'])
            comments = sum(f['comment_status'] == 'different' for f in match['fields'])
            if types or comments or diffs['mysql_only'] or diffs['source_only']:
                conflicts.append({'table': key, 'kind': '候选结构差异',
                    'detail': f"MySQL独有{diffs['mysql_only']}字段，来源独有{diffs['source_only']}字段，类型声明差异{types}处，非空注释冲突{comments}处。仅记录差异，不覆盖原始结构。",
                    'evidence': match['source_table'] + '；详见字段对照'})
        if method in ('unmatched', 'columns_unavailable'):
            conflicts.append({'table': key, 'kind': MATCH_LABELS[method],
                              'detail': '不自动补写业务含义或来源；保留现有结构及受限样例能力。', 'evidence': '结构对照'})
    stats = dict(Counter(t['match_method'] for t in tables.values()))
    stats.update(mysql_objects=len(tables), mysql_fields=len(catalog['columns']),
        source_tables=len(source), source_fields=sum(len(t['fields']) for t in source.values()),
        same_name_equal_fieldsets=sum(t['match_method'] == 'same_name' and any(m['field_name_set_equal'] for m in t['source_candidates']) for t in tables.values()),
        ambiguous_same_name=sum(t['match_method'] == 'same_name' and len(t['source_candidates']) > 1 for t in tables.values()))
    return {'schema_version': 1, 'mysql_captured_at_utc': catalog['captured_at_utc'],
        'catalog_fingerprint': digest(catalog), 'source_zip_sha256': zip_hash,
        'source_snapshots': sorted({s['snapshotDate'] for s in source.values()}),
        'matching_policy': {'priority': ['same_name', 'annual_suffix', 'similar_fields'],
            'similarity': 'Jaccard of exact field names', 'minimum_common_fields': 8,
            'minimum_jaccard': 0.55, 'max_similar_candidates': 3,
            'note': '排序仅检索候选，不证明同源、语义相同或可直接替代。'},
        'statistics': stats, 'rules': RULES, 'excluded_source_tables': ['dm_del.' + n for n in EXCLUDED],
        'tables': tables, 'conflicts': conflicts}


def load_knowledge(catalog, path=None):
    try:
        data = json.loads((path or KNOWLEDGE_PATH).read_text(encoding='utf-8'))
        if data['schema_version'] != 1 or not isinstance(data['tables'], dict) or not isinstance(data['rules'], list):
            raise ValueError('unsupported knowledge')
        if data['catalog_fingerprint'] != digest(catalog):
            return {'status': 'stale', 'message': '口径资料已过期；运行reconcile_knowledge.py重新对照。原始结构仍可使用。'}
        return {'status': 'current', 'data': data}
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unavailable', 'message': '口径资料不可用；运行reconcile_knowledge.py生成。原始结构仍可使用。'}


def table_summary(item):
    return {'status': 'current', 'business_purpose': item['business_purpose'],
            'match_status': item['match_label'], 'lineage_status': item['lineage_status'],
            'source_candidates': [m['source_table'] for m in item['source_candidates']],
            'key_hints': item['key_hints']}


def enrich_tables(catalog, rows):
    knowledge = load_knowledge(catalog)
    result = []
    for row in rows:
        key = row['TABLE_SCHEMA'] + '.' + row['TABLE_NAME']
        if knowledge['status'] == 'current':
            item = knowledge['data']['tables'].get(key)
            summary = table_summary(item) if item else {'status': 'unavailable', 'message': '该表缺少口径记录，请重新对照。'}
        else:
            summary = knowledge
        result.append({**row, 'business_summary': summary})
    return result


def table_context(catalog, database, table):
    knowledge = load_knowledge(catalog)
    if knowledge['status'] != 'current':
        return knowledge
    data = knowledge['data']
    item = data['tables'].get(database + '.' + table)
    if item is None:
        return {'status': 'unavailable', 'message': '该表缺少口径记录，请重新对照。'}
    rules = {r['id']: r for r in data['rules']}
    return {'status': 'current', **item,
            'rules': [{**r, 'definition': rules[r['rule_id']]} for r in item['rules']],
            'source_zip_sha256': data['source_zip_sha256'],
            'mysql_captured_at_utc': data['mysql_captured_at_utc'],
            'source_snapshots': data['source_snapshots']}
