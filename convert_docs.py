# -*- coding: utf-8 -*-
"""文档 markdown → HTML 转换脚本(项目文档中心)."""
import markdown, os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshi-system")
OUT = os.path.join(SRC, "docs-html")
os.makedirs(OUT, exist_ok=True)

CSS = """
body{font-family:'Microsoft YaHei','Segoe UI',sans-serif;margin:0;background:#F1F5F9;color:#1E293B}
.wrap{max-width:980px;margin:0 auto;padding:24px 20px 60px}
.top{background:#0F172A;color:#fff;padding:14px 24px;display:flex;align-items:center;gap:16px}
.top a{color:#93C5FD;text-decoration:none;margin-right:14px;font-size:13px}
.top a:hover{color:#fff}
.top .t{font-weight:700;font-size:15px}
.card{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:22px 26px;margin-top:18px;box-shadow:0 2px 10px rgba(15,23,42,.04)}
h1{font-size:22px;color:#0F172A;border-bottom:2px solid #2563EB;padding-bottom:8px}
h2{font-size:17px;color:#1D4ED8;margin-top:26px;border-left:4px solid #2563EB;padding-left:10px}
h3{font-size:15px;color:#334155}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th{background:#EFF6FF;color:#1D4ED8;text-align:left;padding:8px 10px;border:1px solid #DBEAFE}
td{padding:7px 10px;border:1px solid #E2E8F0;vertical-align:top}
tr:nth-child(even) td{background:#F8FAFC}
code{background:#EEF2F7;padding:2px 6px;border-radius:4px;font-size:12px;color:#0F172A}
blockquote{border-left:4px solid #F59E0B;background:#FFFBEB;margin:8px 0;padding:8px 14px;color:#92400E;border-radius:0 8px 8px 0}
pre{background:#0F172A;color:#E2E8F0;padding:12px 16px;border-radius:8px;overflow:auto;font-size:12px}
"""

def page(title, body):
    return (
        '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>' + title + '</title><style>' + CSS + '</style></head>\n'
        '<body><div class="top"><a href="index.html">← 文档中心</a><span class="t">' + title + '</span></div>\n'
        '<div class="wrap"><div class="card">' + body + '</div></div></body></html>'
    )

index_rows = [
    ("22-项目文档", "架构 / 技术栈 / 模块 / 数据模型 / 权限体系 / 部署"),
    ("23-使用手册", "19 个账号密码 / 各角色操作指南 / 演示流程 / FAQ"),
    ("24-功能介绍", "细则 22 项功能对照表 + 增强功能 + 演示数据"),
    ("25-文档更新日志", "同步更新机制 + 变更日志"),
    ("26-细则歧义记录", "开发中细则设计意图疑问/歧义/意见/预期(供老板审阅)"),
]
rows = "".join(
    '<tr><td><a href="%s.html">%s</a></td><td>%s</td></tr>' % (name, name, desc)
    for name, desc in index_rows
)
INDEX = page("文档中心", (
    '<h1>📚 金石企服客户管理系统 · 文档中心</h1>'
    '<table><tr><th>文档</th><th>说明</th></tr>' + rows + '</table>'
    '<p style="font-size:13px;color:#64748B">与 markdown 源同步，每次系统变更后重新生成。</p>'
))
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(INDEX)

for name, _ in index_rows:
    md_path = os.path.join(SRC, name + ".md")
    if not os.path.exists(md_path):
        print("跳过(不存在):", md_path)
        continue
    md = open(md_path, encoding="utf-8").read()
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    out = os.path.join(OUT, name + ".html")
    open(out, "w", encoding="utf-8").write(page(name, body))
    print("生成:", out, "(%dB)" % os.path.getsize(out))

print("完成: docs-html/ 共 %d 个文件" % len(os.listdir(OUT)))
