' 金石系统 dev server 隐藏启动脚本(计划任务/后台用,无终端窗口)
' 输出重定向到 server.log,可观测性靠日志
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d H:\WorkFlow\agents\oa-agent\jinshi && venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000 --noreload >> server.log 2>&1", 0, False
