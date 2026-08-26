# -*- coding: utf-8 -*-
"""文档 SPA 生成 —— VitePress 风格现代文档站(工业级排版 + 交互)."""
import markdown, os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshi-system")
OUT = os.path.join(SRC, "docs-html")
os.makedirs(OUT, exist_ok=True)

# ---- 集成 Django 实时统计(总纲关键数字,老板一目了然) ----
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
try:
    import django
    django.setup()
    from apps.customers.models import Customer
    from apps.projects.models import Project, ProjectPayment, ProjectExpense

    def stats():
        cust = Customer.objects.count()
        proj = Project.objects.count()
        pay = sum(p.amount or 0 for p in ProjectPayment.objects.all())
        exp = sum(e.amount or 0 for e in ProjectExpense.objects.all())
        pending = Project.objects.exclude(site_progress__in=["deployed", "completed_pending"]).count()
        return cust, proj, pay, exp, pay - exp, pending
except Exception:
    def stats():
        return 0, 0, 0, 0, 0, 0

CSS = """
:root{
  --bg:#fff; --fg:#1F2328; --fg2:#59636E; --fg3:#8C959F;
  --brand:#0969DA; --brand-bg:#DDF4FF; --brand-border:#54AEFF66;
  --border:#D0D7DE; --side-bg:#F6F8FA; --hover:#EEF2F6;
  --code-bg:#F6F8FA; --code-fg:#24292F; --dark-bg:#0D1117;
  --green:#1A7F37; --green-bg:#DAFBE1; --amber:#9A6700; --amber-bg:#FFF8C5;
  --red:#C0392B; --red-bg:#FFEBE9; --gray-bg:#EAEEF2;
  --radius:10px; --shadow:0 1px 3px rgba(31,35,40,.06),0 4px 14px rgba(31,35,40,.05);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;
  color:var(--fg);font-size:15px;line-height:1.75;background:var(--bg)}
/* 顶部导航 */
.top{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.92);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--border);padding:12px 32px;display:flex;align-items:center;gap:12px}
.top .brand{font-size:16px;font-weight:700;color:var(--fg);letter-spacing:.2px}
.top .brand .dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--brand);margin-right:8px}
.top .sub{font-size:12.5px;color:var(--fg3)}
.top .right{margin-left:auto;font-size:12.5px;color:var(--fg3)}
/* 三栏布局 */
.layout{display:flex;align-items:flex-start;max-width:1440px;margin:0 auto}
/* 左侧侧边栏 */
.side{width:272px;flex-shrink:0;position:sticky;top:49px;height:calc(100vh - 49px);overflow-y:auto;
  background:var(--side-bg);border-right:1px solid var(--border);padding:16px 12px}
.search{width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;
  background:#fff;color:var(--fg);margin-bottom:14px;outline:none}
.search:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-bg)}
.side .grp{font-size:11.5px;font-weight:700;color:var(--fg3);text-transform:uppercase;letter-spacing:.6px;
  padding:14px 10px 6px}
.side .item{display:block;padding:8px 12px;border-radius:7px;cursor:pointer;font-size:13.5px;color:var(--fg2);
  text-decoration:none;margin-bottom:2px;transition:background .15s,color .15s}
.side .item:hover{background:var(--hover);color:var(--fg)}
.side .item.active{background:var(--brand-bg);color:var(--brand);font-weight:600}
.side .item .cnt{float:right;font-size:11px;color:var(--fg3);background:var(--gray-bg);border-radius:999px;padding:1px 8px}
/* 内容区 */
.main{flex:1;min-width:0;padding:40px 48px 96px}
.content{max-width:840px;margin:0 auto}
.content .crumb{font-size:12.5px;color:var(--fg3);margin-bottom:18px}
.content .crumb a{color:var(--fg3);text-decoration:none}
.content .crumb a:hover{color:var(--brand)}
.card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:32px 40px;box-shadow:var(--shadow)}
/* 排版 */
h1{font-size:26px;font-weight:700;letter-spacing:-.3px;border-bottom:1px solid var(--border);padding-bottom:14px;margin:0 0 22px}
h2{font-size:20px;font-weight:650;margin:36px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--border)}
h3{font-size:16px;font-weight:600;margin:26px 0 10px}
p{margin:10px 0;color:var(--fg)}
strong{font-weight:600}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}
ul,ol{padding-left:24px;margin:10px 0}
li{margin:5px 0}
blockquote{margin:16px 0;padding:12px 20px;background:var(--side-bg);border-left:4px solid var(--brand);border-radius:0 8px 8px 0;color:var(--fg2)}
code{background:var(--code-bg);color:var(--code-fg);padding:2px 7px;border-radius:5px;font-size:13px;
  font-family:ui-monospace,SFMono-Regular,'Cascadia Code',Consolas,monospace}
pre{background:var(--dark-bg);color:#E6EDF3;padding:18px 22px;border-radius:10px;overflow:auto;font-size:13px;line-height:1.7}
pre code{background:transparent;color:inherit;padding:0}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13.5px;border-radius:8px;overflow:hidden}
th{background:var(--side-bg);color:var(--fg);text-align:left;padding:10px 14px;border:1px solid var(--border);font-weight:650}
td{padding:9px 14px;border:1px solid var(--border);vertical-align:top}
tr:nth-child(even) td{background:#FBFCFD}
tr:hover td{background:var(--brand-bg)}
hr{border:none;border-top:1px solid var(--border);margin:28px 0}
/* 状态色点(替代emoji) */
.dot-s{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:2px 10px;border-radius:999px;font-weight:600}
.dot-s::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor}
.dg{background:var(--green-bg);color:var(--green)}
.da{background:var(--amber-bg);color:var(--amber)}
.dr{background:var(--red-bg);color:var(--red)}
.dg2{background:var(--gray-bg);color:var(--fg2)}
/* 徽章(替代emoji) */
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;margin:0 2px}
.b-green{background:var(--green-bg);color:var(--green);border:1px solid #ACEEBB}
.b-amber{background:var(--amber-bg);color:var(--amber);border:1px solid #D4A72C66}
.b-red{background:var(--red-bg);color:var(--red);border:1px solid #FF818266}
.b-gray{background:var(--gray-bg);color:var(--fg2);border:1px solid var(--border)}
.b-blue{background:var(--brand-bg);color:var(--brand);border:1px solid var(--brand-border)}
/* 可视化:架构图 */
.arch{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.arch .box{flex:1;min-width:180px;border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;background:var(--side-bg);transition:box-shadow .2s}
.arch .box:hover{box-shadow:var(--shadow)}
.arch .box .t{font-weight:700;font-size:13px;margin-bottom:6px;color:var(--brand)}
.arch .box .d{font-size:12.5px;color:var(--fg2);line-height:1.6}
/* 流程步骤条 */
.flow{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:16px 0;font-size:13px}
.flow .step{background:var(--brand-bg);border:1px solid var(--brand-border);color:var(--brand);border-radius:8px;padding:6px 14px;font-weight:600;white-space:nowrap}
.flow .arr{color:var(--fg3);font-weight:700}
/* 权限矩阵色块 */
.pm{display:grid;grid-template-columns:110px repeat(4,1fr);gap:4px;margin:16px 0;font-size:12.5px}
.pm .h{font-weight:650;padding:7px;text-align:center;background:var(--side-bg);border:1px solid var(--border);border-radius:6px}
.pm .c{padding:7px;text-align:center;border:1px solid var(--border);border-radius:6px}
.pm .ok{background:var(--green-bg);color:var(--green)}
.pm .no{background:var(--side-bg);color:var(--fg3)}
.pm .rd{background:var(--red-bg);color:var(--red)}
/* 右侧TOC */
.toc{width:210px;flex-shrink:0;position:sticky;top:66px;height:calc(100vh - 80px);overflow-y:auto;padding:10px 8px;display:none}
.toc .toc-t{font-size:11px;font-weight:700;color:var(--fg3);text-transform:uppercase;letter-spacing:.5px;padding:6px 10px}
.toc a{display:block;font-size:12.5px;color:var(--fg2);padding:4px 10px;border-radius:6px;text-decoration:none;border-left:2px solid transparent}
.toc a:hover{color:var(--brand)}
.toc a.active{color:var(--brand);border-left-color:var(--brand);font-weight:600}
/* 返回顶部 */
#totop{position:fixed;right:24px;bottom:24px;width:40px;height:40px;border-radius:50%;border:1px solid var(--border);
  background:#fff;color:var(--fg2);font-size:16px;cursor:pointer;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .2s}
#totop.show{opacity:1;pointer-events:auto}
#totop:hover{color:var(--brand);border-color:var(--brand)}
/* 响应式 */
@media(max-width:1100px){.toc{display:none}}
@media(max-width:860px){.side{width:100%;position:static;height:auto;border-right:none;border-bottom:1px solid var(--border)}
  .layout{flex-direction:column}.main{padding:24px 16px 64px}.card{padding:20px 18px}}
"""

def page(title, body):
    return (
        '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + title + '</title><style>' + CSS + '</style></head>\n<body>'
        '<div class="top"><span class="brand"><span class="dot"></span>金石企服客户管理系统</span>'
        '<span class="sub">文档中心</span><span class="right">单页文档 · 点击左侧切换</span></div>\n'
        '<div class="layout">'
        '<aside class="side"><input class="search" type="text" placeholder="搜索文档…" id="q">'
        '<div id="nav"></div></aside>\n'
        '<main class="main"><div class="content"><div class="crumb"><a href="index.html">文档中心</a> / <span>' + title + '</span></div>'
        + body + '</div></main>\n'
        '<aside class="toc" id="toc"><div class="toc-t">本页目录</div><div id="tocLinks"></div></aside>'
        '</div><button id="totop">↑</button>\n'
        '<script>\n' + JS + '</script></body></html>'
    )

JS = """
function renderNav(filter){
  var nav = document.getElementById('nav'); nav.innerHTML = '';
  var home = document.createElement('a');
  home.className = 'item' + (!location.hash || location.hash === '#home' ? ' active' : '');
  home.href = '#home';
  home.textContent = '总纲';
  nav.appendChild(home);
  var keys = Object.keys(DOCS || {}).filter(function(k){ return !filter || String(DOCS[k]).toLowerCase().indexOf(filter) >= 0; });
  keys.forEach(function(k){
    var a = document.createElement('a');
    a.className = 'item' + (location.hash === '#doc-' + k ? ' active' : '');
    a.href = '#doc-' + k;
    a.textContent = k;
    nav.appendChild(a);
  });
  if(!keys.length){ var e=document.createElement('div'); e.className='item'; e.textContent='无匹配文档'; nav.appendChild(e); }
}
document.getElementById('q').addEventListener('input', function(){ renderNav(this.value.trim().toLowerCase()); });

function showDoc(k){
  var all = document.querySelectorAll('.page'); all.forEach(function(x){ x.style.display='none'; });
  var el = document.getElementById('doc-' + k);
  if(el){ el.style.display='block'; } else { document.getElementById('home').style.display='block'; }
  renderNav();
  var toc = document.getElementById('tocLinks'); toc.innerHTML='';
  if(!el) return;
  el.querySelectorAll('h2').forEach(function(h){
    var a=document.createElement('a'); a.textContent=h.textContent; a.href='#doc-'+k;
    a.addEventListener('click',function(){ h.scrollIntoView({behavior:'smooth'}); });
    toc.appendChild(a);
  });
  var links = toc.querySelectorAll('a');
  var obs = new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){
      links.forEach(function(l){ l.classList.remove('active'); });
      links.forEach(function(l){ if(l.textContent===e.target.textContent) l.classList.add('active'); });
    }});
  }, {rootMargin:'-60px 0px -70% 0px'});
  el.querySelectorAll('h2').forEach(function(h){ obs.observe(h); });
}
window.addEventListener('hashchange', function(){
  var m = location.hash.match(/doc-(.+)/);
  if(m) showDoc(decodeURIComponent(m[1]));
  else showDoc('');
});
// 初始:URL 带 #doc-x 时直接切到对应文档(刷新不丢页)
(function(){ var m = location.hash.match(/doc-(.+)/); if(m) showDoc(decodeURIComponent(m[1])); })();
// 返回顶部
var tt = document.getElementById('totop');
window.addEventListener('scroll', function(){ tt.classList.toggle('show', window.scrollY > 300); });
tt.addEventListener('click', function(){ window.scrollTo({top:0,behavior:'smooth'}); });
// 初始渲染导航(此时 DOCS 已在骨架前定义)
renderNav();
"""

index_rows = [
    ("01-项目文档", "架构 / 技术栈 / 模块 / 数据模型 / 权限体系 / 部署"),
    ("02-使用手册", "19 个账号密码 / 各角色操作指南 / 演示流程 / FAQ"),
    ("03-功能介绍", "细则 22 项功能对照表 + 增强功能 + 演示数据"),
    ("04-文档更新日志", "同步更新机制 + 变更日志"),
    ("05-细则歧义记录", "细则设计意图疑问/歧义/意见/预期(供老板审阅)"),
]

# ---- 可视化注入(22 项目文档) ----
ARCH = """
<div class="arch">
  <div class="box"><div class="t">config/</div><div class="d">Django 配置 · SIMPLEUI 菜单与权限映射 · 会话/日志</div></div>
  <div class="box"><div class="t">apps/accounts</div><div class="d">用户/角色/部门/团队 · 站内通知 · 工作台视图+权限边界</div></div>
  <div class="box"><div class="t">apps/customers</div><div class="d">客户/归属历史/跟进/附图 · 回收站/提交日志 · 撞单查重</div></div>
  <div class="box"><div class="t">apps/projects</div><div class="d">成交项目/收款/支出 · 咨询师分配历史 · 建站信息与进度</div></div>
  <div class="box"><div class="t">templates+static</div><div class="d">覆盖模板(change_form/403) · simpleui 单内容区 · dup_check</div></div>
</div>
"""
PERM_MATRIX = """
<div class="pm">
  <div></div><div class="h">销售</div><div class="h">销售主管</div><div class="h">咨询/技术</div><div class="h">总经办</div>
  <div class="h">客户列表</div><div class="c ok">本人</div><div class="c ok">组员+本人</div><div class="c no">无权</div><div class="c ok">全部</div>
  <div class="h">客户公海池</div><div class="c ok">可见可领</div><div class="c ok">可见</div><div class="c no">隐藏</div><div class="c ok">全部</div>
  <div class="h">回收站</div><div class="c ok">本人删</div><div class="c ok">组员+本人</div><div class="c no">隐藏</div><div class="c ok">全部</div>
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

EMOJI_MAP = {
    "📚": "", "👥": "", "⏳": "", "✅": '<span class="badge b-green">已实现</span>',
    "❌": '<span class="badge b-red">未实现</span>', "⏸": '<span class="badge b-gray">已搁置</span>',
    "⚠️": '<span class="badge b-amber">注意</span>', "👤": "", "→": "→",
}

def clean_emoji(text):
    for k, v in EMOJI_MAP.items():
        text = text.replace(k, v)
    return text

def render(name, body_md, injects):
    for i in range(0, len(injects or []), 2):
        anchor, html = injects[i], injects[i + 1]
        body_md = body_md.replace(anchor, anchor + "\n" + html, 1)
    body = markdown.markdown(body_md, extensions=["tables", "fenced_code"])
    return clean_emoji(body)

DOCS_META = [
    # (显示名, 源文件名, injects...)
    ("01-项目文档", "22-项目文档", "## 三、架构与模块", ARCH, "## 四、权限体系", PERM_MATRIX, "## 五、核心业务闭环", FLOW),
    ("02-使用手册", "23-使用手册", None, None, None, None, None, None),
    ("03-功能介绍", "24-功能介绍", None, None, None, None, None, None),
    ("04-文档更新日志", "25-文档更新日志", None, None, None, None, None, None),
    ("05-细则歧义记录", "26-细则歧义记录", None, None, None, None, None, None),
]

pages = []
nav_docs = {}
for name, src, *injects in DOCS_META:
    md_path = os.path.join(SRC, src + ".md")
    if not os.path.exists(md_path):
        continue
    md = open(md_path, encoding="utf-8").read()
    inj = [x for x in injects if x is not None] if injects else []
    body = render(name, md, inj)
    pages.append('<section class="page" id="doc-%s" style="display:none"><div class="card">%s</div></section>' % (name, body))
    nav_docs[name] = ""  # 值用空字符串(搜索匹配用),避免数字导致 DOCS[k].toLowerCase 报错

# 首页
def index_page():
    # 总纲(老板一目了然):关键数字 + 业务闭环 + 部门分工 + 文档导航
    cust, proj, pay, exp, profit, pending = stats()
    fmt = lambda v: format(v, ",.0f")
    stat_cards = (
        '<div class="arch">'
        '<div class="box"><div class="t">%s 个客户档案</div><div class="d">全公司客户总量 · 销售唯一建档入口(进线/咨询/线索) · 含公海与成交</div></div>'
        '<div class="box"><div class="t">%s 个成交项目</div><div class="d">已成交并转立项 · 自动流转咨询部办证 · 进度全程可查</div></div>'
        '<div class="box"><div class="t">¥%s 累计收款</div><div class="d">项目回款合计 · 咨询填写收款、财务审核后计入</div></div>'
        '<div class="box"><div class="t">¥%s 累计支出</div><div class="d">项目成本合计 · 成本申请、老板审核后计入</div></div>'
        '<div class="box"><div class="t">¥%s 累计利润</div><div class="d">收款 − 支出 · 系统自动核算</div></div>'
        '<div class="box"><div class="t">%s 个待建站</div><div class="d">技术部待领取建站任务 · 领取后进度同步全员</div></div>'
        '</div>' % (cust, proj, fmt(pay), fmt(exp), fmt(profit), pending)
    )
    depts = (
        '<div class="arch">'
        '<div class="box"><div class="t">销售部</div><div class="d">唯一建档 · 客户跟进 · 成交转项目 · 查看全流程进度</div></div>'
        '<div class="box"><div class="t">咨询部</div><div class="d">嘉茵分配 · 办证节点 · 收款/支出 · 站点交接信息 · 成本申请</div></div>'
        '<div class="box"><div class="t">技术部</div><div class="d">建站任务池 · 领取承接 · 进度(待开始/进行中/已完成待部署/已部署)</div></div>'
        '<div class="box"><div class="t">财务/总经办</div><div class="d">全盘账务 · 成本审核 · 利润核算 · 客户资源调配</div></div>'
        '</div>'
    )
    docnav = "".join(
        '<div class="arch" style="margin:0 0 10px"><div class="box" style="cursor:pointer" onclick="location.hash=\'#doc-%s\'">'
        '<div class="t">%s →</div></div></div>' % (n, n) for n in nav_docs
    )
    body = (
        "<h1>总纲</h1>"
        "<p>客户从 <strong>进线 → 成交 → 办证 → 建站 → 核算</strong> 全流程数字化,四部门各司其职,管理层全盘管控。</p>"
        "<h2>关键数字(实时)</h2>" + stat_cards +
        "<h2>核心业务闭环</h2>" + FLOW +
        "<h2>四部门分工</h2>" + depts +
        "<h2>文档导航</h2>" + docnav +
        '<p style="margin-top:26px;color:var(--fg3);font-size:13px">数字为文档生成时快照,与 markdown 源同步;系统变更后重新生成。</p>'
    )
    # 首页也是 .page section(#home),纳入 showDoc 统一切换——避免首页与文档内容混显(layout 崩)
    home_section = '<section class="page" id="home" style="display:block"><div class="card">' + body + '</div></section>'
    doc_sections = "\n".join(pages)
    # DOCS 引导 script 在骨架 JS 之前执行:只定义 DOCS(renderNav 由骨架 JS 末尾调用,避免此处 renderNav 未定义报错)
    bootstrap = "\n<script>DOCS=" + str(nav_docs).replace("'", '"') + ";</script>"
    # 返回完整页面骨架(骨架 page() 生成一次;首页+文档 sections+引导 script 都在 body 内)
    return page("总纲 · 金石企服系统", home_section + doc_sections + bootstrap)

out = os.path.join(OUT, "index.html")
html = index_page()  # 完整页面骨架:首页+文档sections+DOCS引导script 一次输出
open(out, "w", encoding="utf-8").write(html)
print("SPA 文档站已生成:", out, "(%dB, %d 个文档)" % (len(html), len(nav_docs)))
