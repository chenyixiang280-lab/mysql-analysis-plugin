import json

import pytest

import business_knowledge as knowledge
import launch_mcp
import mysql_analysis as db


def test_missing_state_does_not_create_a_new_budget(tmp_path):
    with pytest.raises(db.AccessError, match='EXISTING_PROJECT_STATE_REQUIRED'):
        launch_mcp.bind_project(tmp_path)
    assert not (tmp_path / 'state').exists()


def test_existing_reserved_budget_is_shared(tmp_path, monkeypatch):
    for module, names in [(db, ['ROOT', 'CATALOG_PATH', 'SAMPLE_DIR', 'AUDIT_PATH']),
                          (knowledge, ['ROOT', 'KNOWLEDGE_PATH', 'SOURCE_ZIP'])]:
        for name in names:
            monkeypatch.setattr(module, name, getattr(module, name))
    state = tmp_path / 'state'
    (state / 'samples').mkdir(parents=True)
    (state / 'catalog.json').write_text('{}', encoding='utf-8')
    reservation = state / 'samples/budget.json'
    reservation.write_text(json.dumps({'status': 'reserved'}), encoding='utf-8')
    original = reservation.read_bytes()
    launch_mcp.bind_project(tmp_path)
    assert db.SAMPLE_DIR.resolve() == reservation.parent.resolve()
    assert db.CATALOG_PATH.resolve() == (state / 'catalog.json').resolve()
    assert knowledge.KNOWLEDGE_PATH == tmp_path / 'knowledge/business_catalog.json'
    assert reservation.read_bytes() == original
