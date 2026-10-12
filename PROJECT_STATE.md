# 插件包状态

2026-10-12：从现有四业务库只读项目打包，插件版本 0.1.0。

- 包含技能、三个未经修改的 MCP 服务模块、原有边界测试及绑定状态目录的启动脚本。
- 标准 plugin.json、mcp.json 和旧版兼容清单均已提供；市场入口为 .agents/plugins/marketplace.json。
- 运行时绑定原项目目录，完整复用样例额度；不在安装目录创建新预算。
- 仅发布代码与规则文字，数据库快照、业务样例、审计和凭据不进入 Git。
- 27项离线测试通过；官方技能格式校验通过。
- 真实CMD启动、MCP握手与四工具发现通过；结构响应business_context.status=current。目录与样例缓存哈希保持不变，新增业务读取0行。
- Codex CLI实际发现mysql-analysis@mysql-analysis-private；本轮未安装到当前用户插件缓存。
- 服务三个模块与原项目逐字节一致；发布文件已检查，快照、样例、审计与凭据均排除。机器证据由verify_package.py生成。
- GitHub上传状态以实际命令结果为准。
