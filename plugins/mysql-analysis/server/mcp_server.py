"""Local stdio MCP. No SQL text, pagination or writable database tools."""
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp import types
from typing import Any
import mysql_analysis as db
import business_knowledge as knowledge

server = MCPServer('mysql_analysis')
readonly = types.ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False)

def invoke(function, *args):
    try:
        return function(*args)
    except db.AccessError as exc:
        raise ToolError(str(exc)) from None
    except Exception as exc:
        raise ToolError(f'LOCAL_ERROR_{type(exc).__name__}') from None

@server.tool(annotations=readonly, structured_output=True)
def list_databases() -> dict[str, Any]:
    """列出获准的四个业务库及本地结构快照时间，不连接数据库。"""
    return invoke(db.list_databases)

@server.tool(annotations=readonly, structured_output=True)
def list_tables(database: str) -> dict[str, Any]:
    """读取四业务库本地目录，附业务用途、平台来源候选及口径提示，不读取业务记录。"""
    rows = invoke(db.list_tables, database)
    return {'database': database, 'tables': invoke(knowledge.enrich_tables, db.load_catalog(), rows)}

@server.tool(annotations=readonly, structured_output=True)
def describe_table(database: str, table: str) -> dict[str, Any]:
    """返回本地原始结构及business_context：平台字段对照、适用规则、关联候选与待确认口径。不连接数据库；来源候选不代表血缘已证实。"""
    result = invoke(db.describe_table, database, table)
    result['business_context'] = invoke(knowledge.table_context, db.load_catalog(), database, table)
    return result

@server.tool(annotations=readonly, structured_output=True)
def sample_table(database: str, table: str) -> dict[str, Any]:
    """仅在确需了解内容时调用。实体表每表一次LIMIT 50，无分页；重复调用复用固定缓存。
    当前仅允许结构与样例，不能据此计算真实业务范围统计；视图与任意SQL禁止。
    """
    return invoke(db.sample_table, database, table)

if __name__ == '__main__':
    server.run(transport='stdio')
