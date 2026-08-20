# -*- coding: utf-8 -*-
"""文档 SPA 整合页生成 —— GitHub 风格 + 去 emoji + 关键内容可视化."""
import markdown, os, re

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshi-system")
OUT = os.path.join(SRC, "docs-html")
os.makedirs(OUT, exist_ok=True)

# ---- GitHub 风格样式(去 emoji、干净排版) ----
CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f6f8fa;color:#24292f;line-height:1.65;font-size:14px}
.top{background:#24292f;color:#fff;padding:14px 28px;font-size:16px;font-weight:600;display:flex;align-items:center;gap:10px}
.top .sub{font-size:12px;font-weight:400;color:#8b949e}
.layout{display:flex;min-height:calc(100vh - 54px)}
.side{width:230px;background:#fff;border-right:1px solid #d0d7de;padding:16px 12px;flex-shrink:0}
.side .item{padding:9px 14px;border-radius:6px;cursor:pointer;font-size:13px;color:#57606a;margin-bottom:3px;border:1px solid transparent}
.side .item:hover{background:#f6f8fa}
.side .item.active{background:#ddf4ff;color:#0969da;font-weight:600;border-color:#54aeff66}
.main{flex:1;padding:28px 36px;overflow:auto}
.card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:24px 32px;box-shadow:0 1px 3px rgba(31,35,40,.04)}
.page{display:none}
.page.active{display:block}
h1{font-size:22px;font-weight:600;border-bottom:1px solid #d8dee4;padding-bottom:10px;margin:0 0 18px}
h2{font-size:17px;font-weight:600;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid #eaeef2}
h3{font-size:15px;font-weight:600;margin:18px 0 8px}
p{margin:8px 0}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
th{background:#f6f8fa;color:#24292f;text-align:left;padding:8px 12px;border:1px solid #d0d7de;font-weight:600}
td{padding:7px 12px;border:1px solid #d0d7de;vertical-align:top}
tr:nth-child(even) td{background:#fafbfc}
code{background:#eff1f3;padding:2px 6px;border-radius:4px;font-size:12px;color:#24292f;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
pre{background:#0d1117;color:#e6edf3;padding:14px 18px;border-radius:8px;overflow:auto;font-size:12px;line-height:1.6}
blockquote{border-left:4px solid #d0d7de;background:#f6f8fa;margin:12px 0;padding:10px 16px;color:#57606a;border-radius:0 6px 6px 0}
a{color:#0969da;text-decoration:none}
a:hover{text-decoration:underline}
/* 徽章(替代 emoji) */
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;margin:0 2px}
.b-green{background:#dafbe1;color:#1a7f37;border:1px solid #aceebb}
.b-amber{background:#fff8c5;color:#9a6700;border:1px solid #d4a72c66}
.b-red{background:#ffebe9;color:#cf222e;border:1px solid #ff818266}
.b-gray{background:#eaeef2;color:#57606a;border:1px solid #d8dee4}
.b-blue{background:#ddf4ff;color:#0969da;border:1px solid #54aeff66}
/* 可视化:架构图盒子 */
.arch{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.arch .box{flex:1;min-width:180px;border:1px solid #d0d7de;border-radius:8px;padding:12px 14px;background:#fafbfc}
.arch .box .t{font-weight:600;font-size:13px;margin-bottom:6px;color:#0969da}
.arch .box .d{font-size:12px;color:#57606a;line-height:1.6}
/* 流程步骤条 */
.flow{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:14px 0;font-size:13px}
.flow .step{background:#ddf4ff;border:1px solid #54aeff66;color:#0969da;border-radius:6px;padding:5px 12px;font-weight:600;white-space:nowrap}
.flow .arr{color:#8b949e;font-weight:700}
/* 权限矩阵色块 */
.pm{display:grid;grid-template-columns:110px repeat(4,1fr);gap:4px;margin:12px 0;font-size:12px}
.pm .h{font-weight:600;padding:6px;text-align:center;background:#f6f8fa;border:1px solid #d0d7de;border-radius:4px}
.pm .c{padding:6px;text-align:center;border:1px solid #d0d7de;border-radius:4px}
.pm .ok{background:#dafbe1;color:#1a7f37}
.pm .no{background:#f6f8fa;color:#8b949e}
.pm .rd{background:#ffebe9;color:#cf222e}
@media(max-width:760px){.side{width:100%;display:flex;flex-wrap:wrap;gap:4px}.side .item{margin-bottom:0}.layout{flex-direction:column}.main{padding:16px}}
"""

# ---- emoji / 符号替换(烂大街 emoji 滚一边,用徽章/文字替代) ----
EMOJI_MAP = {
    "📚": "", "👥": "", "⏳": "", "✅": '<span class="badge b-green">已实现</span>',
    "❌": '<span class="badge b-red">未实现</span>', "⏸": '<span class="badge b-gray">已搁置</span>',
    "⚠️": '<span class="badge b-amber">注意</span>', "👤": "", "→": "→",
}

def clean_emoji(text):
    for k, v in EMOJI_MAP.items():
        text = text.replace(k, v)
    return text

# ---- 22 项目文档:架构图 + 权限矩阵(可视化,HTML 注入) ----
ARCH = """
<div class="arch">
  <div class="box"><div class="t">config/</div><div class="d">Django 配置<br>SIMPLEUI_CONFIG 菜单与权限映射<br>会话/日志配置</div></div>
  <div class="box"><div class="t">apps/accounts</div><div class="d">用户/角色/部门/团队<br>站内通知<br>工作台视图 + 权限边界</div></div>
  <div class="box"><div class="t">apps/customers</div><div class="d">客户/归属历史/跟进/附图<br>回收站/提交日志<br>撞单查重</div></div>
  <div class="box"><div class="t">apps/projects</div><div class="d">成交项目/收款/支出<br>咨询师分配历史<br>建站信息与进度</div></div>
  <div class="box"><div class="t">templates + static</div><div class="d">覆盖模板(change_form/403等)<br>simpleui 单内容区<br>dup_check / form_draft</div></div>
</div>
"""

PERM_MATRIX = """
<div class="pm">
  <div></div><div class="h">销售</div><div class="h">销售主管</div><div class="h">咨询/技术</div><div class="h">总经办</div>
  <div class="h">客户列表</div><div class="c ok">本人</div><div class="c ok">组员+本人</div><div class="c no">无权</div><div class="c ok">全部</div>
  <div class="h">客户公海池</div><div class="c ok">可见可领</div><div class="c ok">可见</div><div class="c no">隐藏</div><div class="c ok">全部</div>
  <div class="h">回收站</div><div class="c ok">本人删</div><div class="c ok">组员+本人</div><div class="c no">隐藏</div><div class="c ok">全部</div>
  <div class="h">工作台</div><div class="c ok">销售台</div><div class="c ok">销售台+组员</div><div class="c rd">302</div><div class="c ok">全可看</div>
  <div class="h">老板总览</div><div class="c rd">302</div><div class="c rd">302</div><div class="c rd">302</div><div class="c ok">可见</div>
  <div class="h">系统管理</div><div class="c no">隐藏</div><div class="c no">隐藏</div><div class="c no">隐藏</div><div class="c ok">可见</div>
</div>
"""

FLOW = """
<div class="flow">
  <span class="step">销售建档</span><span class="arr">→</span>
  <span class="step">未成交进公海</span><span class="arr">→</span>
  <span class="step">撞单提醒</span><span class="arr">→</span>
  <span class="step">成交转项目</span><span class="arr">→</span>
  <span class="step">嘉茵分配咨询师</span><span class="arr">→</span>
  <span class="step">办证/收款/支出</span><span class="arr">→</span>
  <span class="step">技术建站</span><span class="arr">→</span>
  <span class="step">财务核算</span>
</div>
"""

# ---- 各文档:markdown 主体 + 可视化注入 ----
DOCS = [
    ("22-项目文档", "架构 / 技术栈 / 模块 / 数据模型 / 权限体系 / 部署",
     "## 三、架构与模块", ARCH, "## 四、权限体系", PERM_MATRIX, "## 五、核心业务闭环", FLOW),
    ("23-使用手册", "19 个账号密码 / 各角色操作指南 / 演示流程 / FAQ", None, None, None, None, None),
    ("24-功能介绍", "细则 22 项功能对照表 + 增强功能 + 演示数据", None, None, None, None, None),
    ("25-文档更新日志", "同步更新机制 + 变更日志", None, None, None, None, None),
    ("26-细则歧义记录", "细则设计意图疑问/歧义/意见/预期(供老板审阅)", None, None, None, None, None),
]

def render(name, body_md, injects):
    # 先注入(在 md 原文锚点后插可视化 HTML),再整体转换——markdown 对原始 HTML 透传
    for i in range(0, len(injects or []), 2):
        anchor, html = injects[i], injects[i + 1]
        body_md = body_md.replace(anchor, anchor + "\n" + html, 1)
    body = markdown.markdown(body_md, extensions=["tables", "fenced_code"])
    body = clean_emoji(body)
    return body

bodies = []
for name, _desc, *injects in DOCS:
    md_path = os.path.join(SRC, name + ".md")
    if not os.path.exists(md_path):
        continue
    md = open(md_path, encoding="utf-8").read()
    inj_list = [x for x in injects if x is not None] if injects else []
    bodies.append((name, render(name, md, inj_list)))

nav = "".join('<div class="item%s" onclick="showPage(%d)">%s</div>' % (" active" if i == 0 else "", i, n) for i, (n, _) in enumerate(bodies))
pages = "".join('<div class="page%s" id="page%d"><div class="card">%s</div></div>' % (" active" if i == 0 else "", i, b) for i, (_, b) in enumerate(bodies))

HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>金石企服系统 · 文档中心</title><style>%s</style></head>
<body>
<div class="top">金石企服客户管理系统 · 文档中心 <span class="sub">单页文档 · 左侧导航切换</span></div>
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
print("SPA 页已生成:", out_path, "(%dB, %d 个文档)" % (os.path.getsize(out_path), len(bodies)))
