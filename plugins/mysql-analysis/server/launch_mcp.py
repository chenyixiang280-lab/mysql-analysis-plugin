"""Bind packaged code to the existing local catalog and persistent sample budget."""
import argparse
from pathlib import Path

import business_knowledge as knowledge
import mysql_analysis as db


def bind_project(project):
    project = Path(project).resolve(strict=True)
    if not (project / 'state/catalog.json').is_file() or not (project / 'state/samples').is_dir():
        raise db.AccessError('EXISTING_PROJECT_STATE_REQUIRED')
    db.ROOT = project
    db.CATALOG_PATH = project / 'state/catalog.json'
    db.SAMPLE_DIR = project / 'state/samples'
    db.AUDIT_PATH = project / 'state/audit.jsonl'
    knowledge.ROOT = project
    knowledge.KNOWLEDGE_PATH = project / 'knowledge/business_catalog.json'
    knowledge.SOURCE_ZIP = project / 'knowledge/source/dw-sql-rules.zip'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    bind_project(parser.parse_args().project)
    from mcp_server import server
    server.run(transport='stdio')
