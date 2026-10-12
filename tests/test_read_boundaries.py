from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import threading
import time
import pytest
import mysql_analysis as db

@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'CATALOG_PATH', tmp_path / 'catalog.json')
    monkeypatch.setattr(db, 'SAMPLE_DIR', tmp_path / 'samples')
    monkeypatch.setattr(db, 'AUDIT_PATH', tmp_path / 'audit.jsonl')
    catalog = {'captured_at_utc': 'fixture', 'tables': [
        {'TABLE_SCHEMA': 'data_manage', 'TABLE_NAME': 'goods', 'TABLE_TYPE': 'BASE TABLE'},
        {'TABLE_SCHEMA': 'data_manage', 'TABLE_NAME': 'view_goods', 'TABLE_TYPE': 'VIEW'}],
        'columns': [{'TABLE_SCHEMA': 'data_manage', 'TABLE_NAME': 'goods',
            'COLUMN_NAME': name, 'DATA_TYPE': dtype} for name, dtype in
            [('goods_code', 'varchar'), ('amount', 'decimal'), ('password', 'varchar'), ('image', 'blob')]],
        'indexes': [], 'foreign_keys': [], 'foreign_key_rules': [], 'views': [], 'issues': []}
    db.save_json(db.CATALOG_PATH, catalog)
    return tmp_path

class Connection:
    def __init__(self, rows=None, error=None, delay=0):
        self.rows = rows if rows is not None else [{'goods_code': '00001', 'amount': Decimal('1.2300')}] * 50
        self.error = error
        self.delay = delay
        self.queries = []
        self.closed = False
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, sql):
        self.queries.append(sql)
        time.sleep(self.delay)
        if self.error:
            raise self.error
    def fetchall(self):
        return self.rows
    def close(self):
        self.closed = True

def test_single_fixed_sample_and_restart_cache(environment, monkeypatch):
    connection = Connection()
    monkeypatch.setattr(db, 'connect', lambda: connection)
    first = db.sample_table('data_manage', 'goods')
    assert first['row_count'] == 50
    assert first['rows'][0]['amount'] == '1.2300'
    assert connection.queries == ['SELECT `goods_code`,`amount` FROM `data_manage`.`goods` LIMIT 50']
    assert first['excluded_columns'] == ['password', 'image']
    assert connection.closed
    # No in-memory cache: a fresh invocation must reuse persisted state.
    monkeypatch.setattr(db, 'connect', lambda: pytest.fail('cache hit connected to DB'))
    assert db.sample_table('data_manage', 'goods')['cache_hit']
    audit = [json.loads(x) for x in db.AUDIT_PATH.read_text().splitlines()]
    assert sum(x.get('business_rows', 0) for x in audit) == 50
    assert '1.2300' not in db.AUDIT_PATH.read_text()

@pytest.mark.parametrize('schema,table,message', [
    ('mysql', 'user', 'DATABASE_NOT_ALLOWED'),
    ('information_schema', 'TABLES', 'DATABASE_NOT_ALLOWED'),
    ('data_manage', 'goods; DROP TABLE goods', 'TABLE_NOT_IN_CATALOG'),
    ('data_manage', 'view_goods', 'VIEW_SAMPLING_NOT_ALLOWED')])
def test_denied_before_connection(environment, monkeypatch, schema, table, message):
    monkeypatch.setattr(db, 'connect', lambda: pytest.fail('denied request connected'))
    with pytest.raises(db.AccessError, match=message):
        db.sample_table(schema, table)
    assert not db.SAMPLE_DIR.exists()

def test_timeout_and_unknown_save_never_resample(environment, monkeypatch):
    connection = Connection(error=TimeoutError('sensitive diagnostic must not escape'))
    monkeypatch.setattr(db, 'connect', lambda: connection)
    with pytest.raises(db.AccessError, match='DATABASE_ERROR_TimeoutError'):
        db.sample_table('data_manage', 'goods')
    with pytest.raises(db.AccessError, match='SAMPLE_ALREADY_RESERVED_NO_RETRY'):
        db.sample_table('data_manage', 'goods')
    assert len(connection.queries) == 1
    assert 'sensitive diagnostic' not in db.AUDIT_PATH.read_text()
    assert connection.closed

def test_concurrent_requests_only_one_query(environment, monkeypatch):
    connection = Connection(delay=0.05)
    monkeypatch.setattr(db, 'connect', lambda: connection)
    barrier = threading.Barrier(8)
    def run():
        barrier.wait()
        try:
            return db.sample_table('data_manage', 'goods')
        except db.AccessError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: run(), range(8)))
    assert len(connection.queries) == 1
    assert sum(isinstance(x, dict) for x in results) >= 1
    assert all(isinstance(x, dict) or x in ('SAMPLE_ALREADY_RESERVED_NO_RETRY', 'SAMPLE_STATE_UNCERTAIN_NO_RETRY') for x in results)

def test_corrupt_reservation_fails_closed(environment, monkeypatch):
    db.SAMPLE_DIR.mkdir()
    key = db.hashlib.sha256(f'{db.TARGET}/data_manage/goods'.encode()).hexdigest()
    (db.SAMPLE_DIR / f'{key}.json').write_text('{', encoding='utf-8')
    monkeypatch.setattr(db, 'connect', lambda: pytest.fail('uncertain state connected'))
    with pytest.raises(db.AccessError, match='SAMPLE_STATE_UNCERTAIN_NO_RETRY'):
        db.sample_table('data_manage', 'goods')

def test_driver_limit_violation_fails_closed(environment, monkeypatch):
    connection = Connection(rows=[{'goods_code': 'x'}] * 51)
    monkeypatch.setattr(db, 'connect', lambda: connection)
    with pytest.raises(db.AccessError, match='SAMPLE_LIMIT_VIOLATION'):
        db.sample_table('data_manage', 'goods')
    with pytest.raises(db.AccessError, match='SAMPLE_ALREADY_RESERVED_NO_RETRY'):
        db.sample_table('data_manage', 'goods')

def test_directory_tools_do_not_connect(environment, monkeypatch):
    monkeypatch.setattr(db, 'connect', lambda: pytest.fail('metadata cache connected'))
    assert len(db.list_databases()['databases']) == 4
    assert len(db.list_tables('data_manage')) == 2
    assert len(db.describe_table('data_manage', 'goods')['columns']) == 4

def test_missing_credentials_no_cache_refetch(environment, monkeypatch):
    def missing():
        raise db.AccessError('CREDENTIAL_UNAVAILABLE_WIN32_1168')
    monkeypatch.setattr(db, 'connect', missing)
    with pytest.raises(db.AccessError, match='CREDENTIAL_UNAVAILABLE'):
        db.sample_table('data_manage', 'goods')
    with pytest.raises(db.AccessError, match='SAMPLE_ALREADY_RESERVED'):
        db.sample_table('data_manage', 'goods')
