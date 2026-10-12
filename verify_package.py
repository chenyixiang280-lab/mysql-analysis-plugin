"""Verify distributable files and the actual CMD/stdin MCP launch; no DB reads."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / 'plugins/mysql-analysis'
SOURCES = ['mysql_analysis.py', 'business_knowledge.py', 'mcp_server.py']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_hashes(project):
    paths = [project / 'state/catalog.json', project / 'knowledge/business_catalog.json']
    paths.extend(sorted((project / 'state/samples').glob('*')))
    return {str(path.relative_to(project)): sha(path) for path in paths if path.is_file()}


async def verify(project):
    if (ROOT / '.git').exists():
        files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                                        cwd=ROOT).decode('utf-8').split('\0')
    else:
        files = [str(path.relative_to(ROOT)) for path in ROOT.rglob('*') if path.is_file()
                 and path.name != 'verification.json'
                 and not {'__pycache__', '.pytest_cache'}.intersection(path.parts)]
    files = sorted(set(filter(None, files)))
    forbidden = {'state', 'outputs', 'knowledge', '.venv', 'node_modules', '__pycache__', '.git'}
    secrets = re.compile(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|'
                         r'sk-(?:proj-)?[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----')
    for name in files:
        path = Path(name)
        assert not forbidden.intersection(path.parts), f'EXCLUDED_PATH: {name}'
        assert path.suffix.lower() not in {'.zip', '.csv', '.xlsx', '.jsonl'}, f'EXCLUDED_FILE: {name}'
        assert not path.name.startswith('.env'), f'EXCLUDED_ENV: {name}'
        assert not secrets.search((ROOT / path).read_text(encoding='utf-8')), f'SECRET_PATTERN: {name}'
    manifest = json.loads((PLUGIN / 'plugin.json').read_text(encoding='utf-8'))
    market = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
    assert (ROOT / market['plugins'][0]['source']['path']).resolve() == PLUGIN
    assert market['plugins'][0]['name'] == manifest['name']
    current = json.loads((PLUGIN / 'mcp.json').read_text(encoding='utf-8'))['mcpServers']['mysql_analysis']
    compatibility = json.loads((PLUGIN / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['mysql_analysis']
    assert {k: v for k, v in current.items() if k != 'type'} == compatibility
    skill = PLUGIN / 'skills/mysql-business-rules/SKILL.md'
    for link in re.findall(r'\]\(([^)]+)\)', skill.read_text(encoding='utf-8')):
        assert (skill.parent / link).is_file(), f'SKILL_REFERENCE_MISSING: {link}'
    source_hashes = {}
    for name in SOURCES:
        source_hashes[name] = sha(PLUGIN / 'server' / name)
        assert source_hashes[name] == sha(project / name), f'SOURCE_CHANGED: {name}'
    before = local_hashes(project)
    args = [arg.replace('${CLAUDE_PLUGIN_ROOT}', str(PLUGIN)) for arg in current['args']]
    parameters = StdioServerParameters(command=current['command'],
                                      args=args + [str(project)], cwd=str(ROOT))
    async with Client(parameters, read_timeout_seconds=45) as client:
        tools = (await client.list_tools()).tools
        names = sorted(tool.name for tool in tools)
        assert names == ['describe_table', 'list_databases', 'list_tables', 'sample_table']
        assert all(tool.annotations.read_only_hint for tool in tools)
        listing = await client.call_tool('list_databases', {})
        assert not listing.is_error
        assert listing.structured_content['databases'] == [
            'category_strategy', 'data_manage', 'new_goods', 'new_goods_manage']
        context = await client.call_tool('describe_table', {
            'database': 'data_manage', 'table': 'group_goods_info_dfn'})
        assert not context.is_error and context.structured_content['business_context']['status'] == 'current'
    assert local_hashes(project) == before, 'LOCAL_CATALOG_OR_SAMPLE_STATE_CHANGED'
    report = {'version': manifest['version'], 'publishable_file_count': len(files),
              'tools': names, 'business_context_status': 'current',
              'source_sha256': source_hashes, 'local_catalog_and_sample_hashes_preserved': True,
              'new_business_rows_read': 0, 'credentials_published': False}
    (ROOT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    asyncio.run(verify(Path(parser.parse_args().project).resolve(strict=True)))
