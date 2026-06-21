@echo off
set NOVEL_AGENT_DATA_ROOT=%~dp0novel_agent_data
set FLET_VIEW_PATH=%~dp0vendor\flet-desktop
title novel_agent
start "" "%~dp0novel_agent.exe"