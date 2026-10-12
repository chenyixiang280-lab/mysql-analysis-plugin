@echo off
setlocal
set "taskProject=%MYSQL_ANALYSIS_PROJECT%"
if not "%~1"=="" set "taskProject=%~1"
if not defined taskProject set "taskProject=E:\codex_program\data_base_analysis"
if not exist "%taskProject%\.venv\Scripts\python.exe" (
  >&2 echo MYSQL_ANALYSIS_PROJECT_PYTHON_MISSING
  exit /b 1
)
"%taskProject%\.venv\Scripts\python.exe" -X utf8 "%~dp0..\server\launch_mcp.py" --project "%taskProject%"
exit /b %errorlevel%
