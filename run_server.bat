@echo off
chcp 65001 >nul
title 金石管理系统 - 开发服务器
echo.
echo  ============================================
echo   金石管理系统 开发服务器
echo  ============================================
echo.
echo  启动中...
echo  服务地址: http://localhost:8000/admin/
echo  测试账号: boss1 / sale_zhang / jia_yin (密码 admin123)
echo  日志文件: server.log (同目录)
echo.
echo  按 Ctrl+C 停止服务
echo  ============================================
echo.
cd /d "H:\WorkFlow\agents\oa-agent\jinshi"
venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000 --noreload 2>&1 | tee server.log
