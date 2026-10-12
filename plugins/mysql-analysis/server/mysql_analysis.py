"""Fixed-scope metadata discovery and once-per-table bounded samples."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import ssl

ROOT = Path(__file__).resolve().parent
DATABASES = ('category_strategy', 'data_manage', 'new_goods', 'new_goods_manage')
TARGET = '10.243.0.221:3306'
CATALOG_PATH = ROOT / 'state' / 'catalog.json'
SAMPLE_DIR = ROOT / 'state' / 'samples'
AUDIT_PATH = ROOT / 'state' / 'audit.jsonl'
SAMPLE_LIMIT = 50

class AccessError(Exception):
    """Diagnostic safe for model context: no credentials or row contents."""

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {'binary_hex': value.hex()}
    raise TypeError(f'Unsupported value type: {type(value).__name__}')

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_value), encoding='utf-8')
    os.replace(temporary, path)

def audit(operation, status, **details):
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {'timestamp_utc': timestamp(), 'operation': operation, 'status': status, **details}
    with AUDIT_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')

def credential():
    if os.name != 'nt':
        raise AccessError('WINDOWS_CREDENTIAL_MANAGER_REQUIRED')
    class Credential(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                   ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                   ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                   ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                   ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                   ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    pointer = ctypes.POINTER(Credential)()
    if not api.CredReadW(TARGET, 1, 0, ctypes.byref(pointer)):
        raise AccessError(f'CREDENTIAL_UNAVAILABLE_WIN32_{ctypes.get_last_error()}')
    try:
        item = pointer.contents
        return item.UserName, ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('utf-16-le')
    except UnicodeError:
        raise AccessError('CREDENTIAL_ENCODING_UNSUPPORTED') from None
    finally:
        api.CredFree(pointer)

def safe_error(exc):
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else type(exc).__name__
    return f'DATABASE_ERROR_{code}'

def connect():
    import pymysql
    user, password = credential()
    # MySQL SSLMODE=REQUIRED equivalent; CA/hostname verification was not supplied.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = None
    try:
        connection = pymysql.connect(host='10.243.0.221', port=3306,
            user=user, password=password, ssl=context, charset='utf8mb4', autocommit=True,
            connect_timeout=10, read_timeout=20, write_timeout=20, local_infile=False,
            cursorclass=pymysql.cursors.DictCursor)
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SET SESSION max_execution_time = 15000')
            cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            if not cursor.fetchone()['Value']:
                raise AccessError('TLS_REQUIRED')
        return connection
    except Exception as exc:
        if connection:
            connection.close()
        raise AccessError(str(exc) if isinstance(exc, AccessError) else safe_error(exc)) from None
    finally:
        password = None

def metadata(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()

def refresh_catalog():
    scope = ','.join(['%s'] * len(DATABASES))
    where = f'TABLE_SCHEMA IN ({scope})'
    definitions = {
        'tables': f'SELECT TABLE_SCHEMA,TABLE_NAME,TABLE_TYPE,ENGINE,TABLE_COLLATION,TABLE_COMMENT FROM information_schema.TABLES WHERE {where} ORDER BY TABLE_SCHEMA,TABLE_NAME',
        'columns': f'SELECT TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION,COLUMN_NAME,COLUMN_TYPE,DATA_TYPE,IS_NULLABLE,COLUMN_DEFAULT,COLUMN_KEY,EXTRA,COLUMN_COMMENT,CHARACTER_SET_NAME,COLLATION_NAME,GENERATION_EXPRESSION FROM information_schema.COLUMNS WHERE {where} ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION',
        'indexes': f'SELECT TABLE_SCHEMA,TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,COLLATION,SUB_PART,INDEX_TYPE,INDEX_COMMENT,IS_VISIBLE,EXPRESSION FROM information_schema.STATISTICS WHERE {where} ORDER BY TABLE_SCHEMA,TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX',
        'foreign_keys': f'SELECT CONSTRAINT_SCHEMA,TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,ORDINAL_POSITION,REFERENCED_TABLE_SCHEMA,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE CONSTRAINT_SCHEMA IN ({scope}) AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY CONSTRAINT_SCHEMA,TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION',
        'foreign_key_rules': f'SELECT CONSTRAINT_SCHEMA,TABLE_NAME,CONSTRAINT_NAME,UPDATE_RULE,DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA IN ({scope}) ORDER BY CONSTRAINT_SCHEMA,TABLE_NAME,CONSTRAINT_NAME',
        'views': f'SELECT TABLE_SCHEMA,TABLE_NAME,VIEW_DEFINITION,CHECK_OPTION,IS_UPDATABLE,SECURITY_TYPE FROM information_schema.VIEWS WHERE {where} ORDER BY TABLE_SCHEMA,TABLE_NAME',
    }
    connection = connect()
    try:
        server = metadata(connection, 'SELECT VERSION() AS version, @@version_comment AS version_comment, @@session.transaction_read_only AS transaction_read_only, @@session.max_execution_time AS max_execution_time')[0]
        grants = metadata(connection, 'SHOW GRANTS')
        catalog = {'captured_at_utc': timestamp(), 'target': TARGET, 'databases': list(DATABASES),
            'server': server, 'tls': metadata(connection, "SHOW SESSION STATUS WHERE Variable_name IN ('Ssl_cipher','Ssl_version')"),
            'tls_identity_verified': False, 'privileges': [next(iter(r.values())).split(' TO ', 1)[0] for r in grants],
            'business_rows_read': 0}
        for key, sql in definitions.items():
            catalog[key] = metadata(connection, sql, DATABASES)
            audit('metadata', 'ok', section=key, returned_rows=len(catalog[key]), business_rows=0)
        catalog['issues'] = catalog_issues(catalog)
        save_json(CATALOG_PATH, catalog)
        return catalog
    except Exception as exc:
        message = str(exc) if isinstance(exc, AccessError) else safe_error(exc)
        audit('refresh_catalog', 'failed', error=message, business_rows=0)
        raise AccessError(message) from None
    finally:
        connection.close()

def catalog_issues(catalog):
    issues = []
    for table in catalog['tables']:
        schema, name = table['TABLE_SCHEMA'], table['TABLE_NAME']
        columns = [c for c in catalog['columns'] if (c['TABLE_SCHEMA'], c['TABLE_NAME']) == (schema, name)]
        indexes = [i for i in catalog['indexes'] if (i['TABLE_SCHEMA'], i['TABLE_NAME']) == (schema, name)]
        def issue(kind, detail):
            issues.append({'database': schema, 'table': name, 'kind': kind, 'detail': detail})
        if not columns:
            issue('字段不可见', table['TABLE_COMMENT'] or '当前账号无法取得字段定义，原因未确认')
        if not table['TABLE_COMMENT']:
            issue('表注释缺失', '业务用途待确认')
        missing = sum(not c['COLUMN_COMMENT'] for c in columns)
        if missing:
            issue('字段注释缺失', f'{missing} 个字段缺少注释，含义不自动补写')
        if table['TABLE_TYPE'] == 'BASE TABLE':
            if not indexes:
                issue('未见索引', '后续报表需要评估执行计划，不自动修改数据库')
            if not any(i['INDEX_NAME'] == 'PRIMARY' for i in indexes):
                issue('未见主键', '数据粒度及连接键唯一性须按具体报表验证')
        else:
            view = next((v for v in catalog['views'] if (v['TABLE_SCHEMA'], v['TABLE_NAME']) == (schema, name)), None)
            if not view or not view['VIEW_DEFINITION']:
                issue('视图定义不可见', '当前账号未取得定义，不猜测来源或直接抽样视图')
    return issues

def load_catalog():
    try:
        return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        raise AccessError('CATALOG_UNAVAILABLE_RUN_REFRESH') from None

def check_database(database):
    if database not in DATABASES:
        raise AccessError('DATABASE_NOT_ALLOWED')

def list_databases():
    return {'captured_at_utc': load_catalog()['captured_at_utc'], 'databases': list(DATABASES)}

def list_tables(database):
    check_database(database)
    return [t for t in load_catalog()['tables'] if t['TABLE_SCHEMA'] == database]

def describe_table(database, table):
    check_database(database)
    catalog = load_catalog()
    item = next((t for t in catalog['tables'] if (t['TABLE_SCHEMA'], t['TABLE_NAME']) == (database, table)), None)
    if item is None:
        raise AccessError('TABLE_NOT_IN_CATALOG')
    def items(section):
        return [r for r in catalog[section] if (r.get('TABLE_SCHEMA', r.get('CONSTRAINT_SCHEMA')), r['TABLE_NAME']) == (database, table)]
    return {'table': item, 'columns': items('columns'), 'indexes': items('indexes'),
        'foreign_keys': items('foreign_keys'), 'foreign_key_rules': items('foreign_key_rules'),
        'views': items('views'), 'issues': [i for i in catalog['issues'] if (i['database'], i['table']) == (database, table)]}

def quoted(identifier):
    return '`' + identifier.replace('`', '``') + '`'

def sample_table(database, table):
    structure = describe_table(database, table)
    if structure['table']['TABLE_TYPE'] != 'BASE TABLE':
        raise AccessError('VIEW_SAMPLING_NOT_ALLOWED')
    excluded = [c['COLUMN_NAME'] for c in structure['columns'] if c['DATA_TYPE'] in
        ('blob', 'tinyblob', 'mediumblob', 'longblob', 'binary', 'varbinary', 'geometry') or
        any(word in c['COLUMN_NAME'].lower() for word in ('password', 'passwd', 'secret', 'token'))]
    columns = [c['COLUMN_NAME'] for c in structure['columns'] if c['COLUMN_NAME'] not in excluded]
    if not columns:
        raise AccessError('NO_SAMPLEABLE_COLUMNS')
    key = hashlib.sha256(f'{TARGET}/{database}/{table}'.encode()).hexdigest()
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    cache = SAMPLE_DIR / f'{key}.json'
    try:
        fd = os.open(cache, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        try:
            saved = json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            raise AccessError('SAMPLE_STATE_UNCERTAIN_NO_RETRY') from None
        if saved.get('status') != 'complete':
            raise AccessError('SAMPLE_ALREADY_RESERVED_NO_RETRY')
        audit('sample', 'cache_hit', database=database, table=table, business_rows=0)
        return {**saved['result'], 'cache_hit': True}
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump({'status': 'reserved', 'reserved_rows': SAMPLE_LIMIT, 'timestamp_utc': timestamp()}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    connection = None
    try:
        connection = connect()
        sql = f'SELECT {",".join(map(quoted, columns))} FROM {quoted(database)}.{quoted(table)} LIMIT 50'
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        if len(rows) > SAMPLE_LIMIT:
            raise AccessError('SAMPLE_LIMIT_VIOLATION')
        result = {'database': database, 'table': table, 'sampled_at_utc': timestamp(),
            'limit': SAMPLE_LIMIT, 'row_count': len(rows), 'columns': columns, 'excluded_columns': excluded,
            'rows': rows, 'cache_hit': False, 'note': '一次固定样例，不代表全表分布、最新数据或字段唯一性；Decimal以字符串精确保留。'}
        save_json(cache, {'status': 'complete', 'reserved_rows': SAMPLE_LIMIT, 'result': result})
        audit('sample', 'ok', database=database, table=table, business_rows=len(rows), limit=50)
        return json.loads(json.dumps(result, ensure_ascii=False, default=json_value))
    except Exception as exc:
        message = str(exc) if isinstance(exc, AccessError) else safe_error(exc)
        save_json(cache, {'status': 'failed_no_retry', 'reserved_rows': SAMPLE_LIMIT, 'error': message})
        audit('sample', 'failed_no_retry', database=database, table=table, error=message, reserved_rows=50)
        raise AccessError(message) from None
    finally:
        if connection:
            connection.close()

def summary(catalog):
    return {'captured_at_utc': catalog['captured_at_utc'], 'business_rows_read': 0,
        'objects': len(catalog['tables']), 'columns': len(catalog['columns']),
        'indexes': len({(r['TABLE_SCHEMA'], r['TABLE_NAME'], r['INDEX_NAME']) for r in catalog['indexes']}),
        'foreign_keys': len({(r['CONSTRAINT_SCHEMA'], r['TABLE_NAME'], r['CONSTRAINT_NAME']) for r in catalog['foreign_keys']}),
        'issues': len(catalog['issues'])}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['refresh', 'summary', 'describe', 'sample'])
    parser.add_argument('--database', choices=DATABASES)
    parser.add_argument('--table')
    args = parser.parse_args()
    try:
        if args.command in ('refresh', 'summary'):
            result = summary(refresh_catalog() if args.command == 'refresh' else load_catalog())
        elif args.database is None or args.table is None:
            parser.error('describe/sample require --database and --table')
        else:
            result = describe_table(args.database, args.table) if args.command == 'describe' else sample_table(args.database, args.table)
        print(json.dumps(result, ensure_ascii=False, default=json_value))
    except AccessError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from None

if __name__ == '__main__':
    main()
