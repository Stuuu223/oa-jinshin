@echo off
REM 金石系统 dev server 运行脚本(schtasks 调用,完全脱离 bash 进程树)
cd /d "H:\WorkFlow\agents\oa-agent\jinshi"
venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000 --noreload >> server.log 2>&1
