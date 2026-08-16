@echo off
REM 金石系统 dev server 启动脚本——用 start 开独立窗口,脱离 bash 进程树
cd /d "H:\WorkFlow\agents\oa-agent\jinshi"
start "jinshi-devserver" /min "H:\WorkFlow\agents\oa-agent\jinshi\venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000 --noreload
