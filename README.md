# MySQL 只读分析插件

私有 GitHub 插件包：`mysql-analysis`，市场名 `mysql-analysis-private`。包含 `mysql-business-rules` 技能和本地 stdio MCP `mysql_analysis`。

## 能力与边界

- `list_databases`：四个获准业务库与结构快照时间。
- `list_tables(database)`：表目录及业务用途提示。
- `describe_table(database, table)`：原始结构、来源候选、适用规则与待确认事项。
- `sample_table(database, table)`：实体表一次固定样例，最多 50 行；重复调用复用持久缓存。

仅访问 `category_strategy`、`data_manage`、`new_goods`、`new_goods_manage`。目录及结构读取本地快照。业务抽样只使用当前 Windows 用户凭据管理器中的 `10.243.0.221:3306` 凭据，不接受配置文件密码。无任意 SQL、分页、报表执行或数据库写入工具。未知业务含义保持未知。

本仓库只包含代码、技能、规则说明和测试。数据库快照、业务样例、审计、源技能 ZIP、业务目录 JSON、Office 文件、虚拟环境和凭据均不上传。

## 安装到 Codex

要求 Windows、本地 Codex 客户端、可访问私有仓库的 GitHub 账号，以及已获准的原项目目录。原目录需保留 `.venv/Scripts/python.exe`、`state/catalog.json`、完整 `state/samples/` 和 `knowledge/business_catalog.json`。运行依赖见 `requirements.txt`，已验证环境的版本锁定见 `requirements.lock.txt`。

```powershell
codex plugin marketplace add https://github.com/chenyixiang280-lab/mysql-analysis-plugin.git
codex plugin add mysql-analysis@mysql-analysis-private
```

安装后新开本地聊天，先调用 `list_databases`，再调用 `describe_table`，确认 `business_context.status=current`。本机默认绑定 `E:\codex_program\data_base_analysis`；其他 Windows 环境在启动客户端前设置 `MYSQL_ANALYSIS_PROJECT` 为其获准原项目根目录。该变量只包含路径，不含凭据。

已有用户级 `mysql_analysis` MCP 注册仍可保留。启用插件后可能出现两个入口，二者必须绑定同一个原项目状态目录。不得新建、清空或复制不完整的样例目录来扩大额度。安装和更新插件不生成新的业务读取授权。

当前包是本地插件；GitHub 上传不等于安装，也不等于发布到公共插件目录。云端 agent 不能直接启动本机 stdio 服务。另一用户首次业务抽样仍需其自己的获准 Windows 凭据及内网访问。

## 其他 MCP 客户端

支持 stdio 的客户端可用 `cmd.exe` 启动 `plugins/mysql-analysis/scripts/start_mcp.cmd`，参数为 `/d /s /c call <脚本绝对路径> <获准原项目目录>`。使用脚本的实际路径，无需解析插件根目录变量。原生 CMD 启动不依赖 PowerShell 脚本执行策略。

## 验证

```powershell
& 'E:\codex_program\data_base_analysis\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider
& 'E:\codex_program\data_base_analysis\.venv\Scripts\python.exe' verify_package.py --project 'E:\codex_program\data_base_analysis'
```

测试使用模拟数据。协议验证仅调用本地目录和结构工具，不连接数据库、不抽样；验证前后核对原目录及缓存哈希。结果写入被 Git 忽略的 `verification.json`，不能手工修改验收状态。

来源：现有项目三个服务模块保持原文；技能仅调整发布后的相对引用与运行目录说明。规则资料的快照日期是历史证据，不表示当前实时业务数据。

官方格式参考：[插件打包](https://developers.openai.com/plugins/build/plugins)、[MCP 接入](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。
