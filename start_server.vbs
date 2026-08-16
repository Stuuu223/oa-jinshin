' 金石系统 dev server 启动脚本——用 WScript.Shell.Run 启动完全脱离的进程
' Run 第三参数 False = 不等待,进程完全脱离调用者,可跨 bash 调用存活
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d H:\WorkFlow\agents\oa-agent\jinshi && venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000 --noreload > server.log 2>&1", 0, False
