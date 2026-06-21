@echo off
chcp 65001 >nul 2>&1
title novel_agent

:: 为 exe 设置持久化数据目录（exe 同目录下的 novel_agent_data）
set NOVEL_AGENT_DATA_ROOT=%~dp0novel_agent_data

:: 启动 exe
start "" "%~dp0novel_agent.exe"
