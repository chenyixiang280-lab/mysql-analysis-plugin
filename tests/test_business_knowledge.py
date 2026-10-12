import copy
import json
from pathlib import Path
import pytest
import business_knowledge as bk
import mysql_analysis as db
import mcp_server


def sf(names, hot='H3', table='goods', database='dm_cate'):
    return {'database': database, 'table': table, 'tableDesc': '来源说明', 'hotTier': hot,
        'snapshotDate': '2026-09-22', 'dataUpdateTime': '历史时间', 'partitionCount': '0',
        'heat_record': 1, 'fields': {n: {'type': 'string', 'comment': n, 'record': i+1,
        'ordinal': str(i+1)} for i,n in enumerate(names)}}


def mf(names):
    return {n: {'type': 'varchar(20)', 'comment': n, 'ordinal': i+1} for i,n in enumerate(names)}


def test_same_name_keeps_ambiguity_and_no_lineage_claim():
    source={'dm_cate.goods':sf(['goods_code']), 'dm_bi.goods':sf(['goods_code'],database='dm_bi')}
    method, candidates=bk.candidates('goods',mf(['goods_code']),source,{'goods':list(source)})
    assert method=='same_name' and len(candidates)==2
    assert all(c['lineage_status']=='unverified' and c['field_name_set_equal'] for c in candidates)


def test_annual_name_beats_more_similar_cumulative_table():
    source={'dm_cate.monthly':sf(['goods_code','month'],table='monthly'),
            'dm_cate.cumulative':sf(['goods_code','month','total'],table='cumulative')}
    method,candidates=bk.candidates('monthly_2026',mf(['goods_code','month','total']),source,{'monthly':['dm_cate.monthly']})
    assert method=='annual_suffix' and [c['source_table'] for c in candidates]==['dm_cate.monthly']
    assert not candidates[0]['field_name_set_equal']


def test_similar_candidate_never_becomes_verified():
    names=['c'+str(i) for i in range(12)]
    source={'dm_cate.t'+str(i):sf(names[:10],table='t'+str(i)) for i in range(5)}
    method,candidates=bk.candidates('renamed',mf(names),source,{})
    assert method=='similar_fields' and len(candidates)==3
    assert all(c['lineage_status']=='unverified' for c in candidates)


@pytest.mark.parametrize('names,status',[([], 'columns_unavailable'),(['id'], 'unmatched')])
def test_no_field_or_no_source_remains_unknown(names,status):
    method,cs=bk.candidates('unknown',mf(names),{}, {})
    assert method==status and cs==[]


def test_type_comment_and_absent_fields_are_not_overwritten():
    current=mf(['id','new']); source=sf(['id','old'])['fields']
    source['id']['comment']='源端另一口径'
    rows=bk.compare_fields(current,source)
    identity=next(r for r in rows if r['mysql_field']=='id')
    assert identity['type_status']=='different_review' and identity['comment_status']=='different'
    assert identity['mysql_comment']=='id' and identity['source_comment']=='源端另一口径'
    assert {r['presence'] for r in rows}=={'shared','mysql_only','source_only'}


def test_hu_is_flagged_without_changing_database_allowlist():
    source={'dm_cate.goods':sf(['id'],hot='HU')}
    _,cs=bk.candidates('goods',mf(['id']),source,{'goods':list(source)})
    assert not cs[0]['automatic_recommendation_allowed']
    assert db.DATABASES==('category_strategy','data_manage','new_goods','new_goods_manage')


def test_store_rule_requires_all_three_fields_and_business_confirmation():
    rows=bk.applicable_rules(mf(['busi_ascr_code','format_code']))
    rule=next(r for r in rows if r['rule_id']=='normal_shops')
    assert rule['missing_fields']==['shop_age_type_code'] and rule['status']=='门店过滤字段不足'
    rows=bk.applicable_rules(mf(['busi_ascr_code','format_code','shop_age_type_code']))
    assert next(r for r in rows if r['rule_id']=='normal_shops')['status']=='三字段齐备_门店粒度待确认'


def test_metric_and_strategy_fields_remain_distinct():
    rows=bk.applicable_rules(mf(['total_amount','zhuying_amount','sc3_name']))
    rules={r['rule_id']:r for r in rows}
    assert rules['sales']['present_fields']==['total_amount','zhuying_amount']
    assert 'acco_amt' in rules['sales']['missing_fields']
    assert rules['strategy']['present_fields']==['sc3_name']
    assert rules['cost']['present_fields']==[]


def test_join_keeps_type_difference_and_unknown_cardinality():
    all_fields={'data_manage.group_goods_info_dfn':mf(['goods_code'])}
    current={'goods_code':{'type':'bigint','comment':''}}
    joins=bk.join_candidates('data_manage.fact',current,all_fields)
    assert joins[0]['keys'][0]['source_type'] != joins[0]['keys'][0]['target_type']
    assert joins[0]['cardinality']=='unknown' and joins[0]['status']=='candidate_unverified'


def test_knowledge_staleness_and_corruption(tmp_path):
    catalog={'tables':[]}; path=tmp_path/'knowledge.json'
    assert bk.load_knowledge(catalog,path)['status']=='unavailable'
    data={'schema_version':1,'catalog_fingerprint':bk.digest(catalog),'tables':{},'rules':[]}
    path.write_text(json.dumps(data))
    assert bk.load_knowledge(catalog,path)['status']=='current'
    assert bk.load_knowledge({'tables':[1]},path)['status']=='stale'
    path.write_text('{')
    assert bk.load_knowledge(catalog,path)['status']=='unavailable'


def test_missing_knowledge_preserves_raw_mcp_structure(tmp_path,monkeypatch):
    monkeypatch.setattr(bk,'KNOWLEDGE_PATH',tmp_path/'missing.json')
    raw={'table':{'TABLE_SCHEMA':'data_manage','TABLE_NAME':'goods'},'columns':[{'COLUMN_NAME':'id','COLUMN_COMMENT':'原注释'}]}
    monkeypatch.setattr(db,'describe_table',lambda *args:copy.deepcopy(raw))
    monkeypatch.setattr(db,'load_catalog',lambda:{'tables':[]})
    monkeypatch.setattr(db,'connect',lambda:pytest.fail('metadata connected to database'))
    result=mcp_server.describe_table('data_manage','goods')
    assert {k:result[k] for k in raw}==raw
    assert result['business_context']['status']=='unavailable'


def test_no_knowledge_entry_not_reported_current(tmp_path,monkeypatch):
    catalog={'tables':[]}; path=tmp_path/'knowledge.json'
    path.write_text(json.dumps({'schema_version':1,'catalog_fingerprint':bk.digest(catalog),'tables':{},'rules':[]}))
    monkeypatch.setattr(bk,'KNOWLEDGE_PATH',path)
    assert bk.enrich_tables(catalog,[{'TABLE_SCHEMA':'data_manage','TABLE_NAME':'goods'}])[0]['business_summary']['status']=='unavailable'


def test_source_internal_conflicts_are_retained():
    source={'dm_com.comprehensive_profit_base_data_dfp':sf(['a','b'])}
    texts={'SKILL.md':'74字段，三级策略分类',
        'references/ddl/dm_com.comprehensive_profit_base_data_dfp.sql':"strategy_classify_name STRING COMMENT '二级策略分类' PARTITIONED BY (DATE STRING)"}
    assert len(bk.source_conflicts(source,texts))==3
