@echo off
cd /d H:\WorkFlow\agents\oa-agent\jinshi
echo ===== %date% %time% 手动启动 runserver(8000) ===== >> server.log
venv\Scripts\python.exe manage.py runserver 8000 >> server.log 2>&1
