@echo off
cd /d "H:\WorkFlow\agents\oa-agent\jinshi"
start "jinshi-devserver" /min "H:\WorkFlow\agents\oa-agent\jinshi\venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000 --noreload
