# -*- coding: utf-8 -*-
"""文档 markdown → SPA 整合页(单页,左侧导航+右侧内容切换,无需逐页点)."""
import markdown, os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshi-system")
OUT = os.path.join(SRC, "docs-html")
os.makedirs(OUT, exist_ok=True)

CSS = """
*{box-sizing:border-box}
body{font-family:'Microsoft YaHei','Segoe UI',sans-serif;margin:0;background:#F1F5F9;color:#1E293B}
.top{background:#0F172A;color:#fff;padding:12px 24px;font-size:15px;font-weight:700;display:flex;align-items:center;gap:10px}
.top .sub{font-size:12px;font-weight:400;color:#94A3B8}
.layout{display:flex;min-height:calc(100vh - 46px)}
.side{width:220px;background:#fff;border-right:1px solid #E2E8F0;padding:14px 10px;flex-shrink:0}
.side .item{padding:10px 14px;border-radius:8px;cursor:pointer;font-size:13px;color:#475569;margin-bottom:4px;transition:background .15s}
.side .item:hover{background:#F1F5F9}
.side .item.active{background:#EFF6FF;color:#1D4ED8;font-weight:600}
.main{flex:1;padding:24px 30px;overflow:auto}
.card{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:22px 28px;box-shadow:0 2px 10px rgba(15,23,42,.04)}
.page{display:none}
.page.active{display:block}
h1{font-size:21px;color:#0F172A;border-bottom:2px solid #2563EB;padding-bottom:8px}
h2{font-size:16px;color:#1D4ED8;margin-top:24px;border-left:4px solid #2563EB;padding-left:10px}
h3{font-size:14px;color:#334155}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th{background:#EFF6FF;color:#1D4ED8;text-align:left;padding:8px 10px;border:1px solid #DBEAFE}
td{padding:7px 10px;border:1px solid #E2E8F0;vertical-align:top}
tr:nth-child(even) td{background:#F8FAFC}
code{background:#EEF2F7;padding:2px 6px;border-radius:4px;font-size:12px;color:#0F172A}
blockquote{border-left:4px solid #F59E0B;background:#FFFBEB;margin:8px 0;padding:8px 14px;color:#92400E;border-radius:0 8px 8px 0}
pre{background:#0F172A;color:#E2E8F0;padding:12px 16px;border-radius:8px;overflow:auto;font-size:12px}
@media(max-width:720px){.side{width:100%;display:flex;flex-wrap:wrap;gap:4px}.side .item{margin-bottom:0}.layout{flex-direction:column}.main{padding:16px}}
"""

DOCS = [
    ("22-项目文档", "架构 / 技术栈 / 模块 / 数据模型 / 权限体系 / 部署"),
    ("23-使用手册", "19 个账号密码 / 各角色操作指南 / 演示流程 / FAQ"),
    ("24-功能介绍", "细则 22 项功能对照表 + 增强功能 + 演示数据"),
    ("25-文档更新日志", "同步更新机制 + 变更日志"),
    ("26-细则歧义记录", "细则设计意图疑问/歧义/意见/预期(供老板审阅)"),
]

bodies = []
for name, _desc in DOCS:
    md_path = os.path.join(SRC, name + ".md")
    if not os.path.exists(md_path):
        continue
    md = open(md_path, encoding="utf-8").read()
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    bodies.append((name, body))

nav = "".join('<div class="item%s" onclick="showPage(%d)">%s</div>' % (" active" if i == 0 else "", i, name) for i, (name, _) in enumerate(bodies))
pages = "".join('<div class="page%s" id="page%d"><div class="card">%s</div></div>' % (" active" if i == 0 else "", i, body) for i, (_, body) in enumerate(bodies))

HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>金石企服系统 · 文档中心</title><style>%s</style></head>
<body>
<div class="top">📚 金石企服客户管理系统 · 文档中心 <span class="sub">单页文档 · 点击左侧导航切换</span></div>
<div class="layout">
  <div class="side">%s</div>
  <div class="main">%s</div>
</div>
<script>
function showPage(i){
  document.querySelectorAll('.item').forEach(function(el,j){el.classList.toggle('active',j===i)});
  document.querySelectorAll('.page').forEach(function(el,j){el.classList.toggle('active',j===i)});
  window.scrollTo(0,0);
}
</script>
</body></html>""" % (CSS, nav, pages)

out_path = os.path.join(OUT, "index.html")
open(out_path, "w", encoding="utf-8").write(HTML)
print("SPA 整合页已生成:", out_path, "(%dB, %d 个文档)" % (os.path.getsize(out_path), len(bodies)))
