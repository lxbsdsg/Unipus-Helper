@echo off
cd /d "%~dp0"
rem 终端备选模式：不启动 Web UI，直接在 cmd 里登录并学习
call "%~dp0run.bat" --cli %*
