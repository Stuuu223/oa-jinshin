#!/bin/bash
# 金石系统标准部署脚本(唯一服务器部署入口)——三态对齐 SOP(净化 09-01):
#   1. 本地:改代码 → manage.py check + 渲染断言 → git commit + push(GitHub)
#   2. 服务器:bash deploy.sh → git pull(失败自动重试3次,网络持续不通用 git bundle 兜底)→ docker compose 重建
#   3. 验证:docker ps 状态 + 容器内断言(新配置/paintMenuBars)→ 老板 Ctrl+F5 验收
# 用法:bash deploy.sh(在服务器 /opt/jinshi 下执行)
set -e
cd /opt/jinshi

echo "== [1/2] 拉取最新代码 =="
PULLED=0
for i in 1 2 3; do
  if timeout 90 git pull origin main; then
    PULLED=1
    break
  fi
  echo "第 ${i} 次 pull 失败(服务器→GitHub 网络不稳定),5 秒后重试..."
  sleep 5
done
if [ "$PULLED" = "0" ]; then
  echo "警告:3 次 pull 均失败,继续用当前代码重建。"
  echo "提示:网络持续不通时,可用 git bundle 方式同步(见部署文档)。"
fi

echo "== [2/2] 重建并重启容器 =="
docker compose up -d --build

echo "== 部署完成 =="
docker ps --filter name=jinshi --format "{{.Names}} {{.Status}}"
