#!/usr/bin/env bash
# pgvector 操作脚本（幂等）· W06 起所有课程的 RAG 向量库统一走它
# 容器引用统一用 CONTAINER ID（amber 本机 name 解析不稳定，W07 已踩坑 No such container: gp17）
#
# 用法:
#   PG_CONTAINER_ID=<ID> bash 00_start_pgvector.sh            # 默认建 w06rag
#   PG_CONTAINER_ID=<ID> bash 00_start_pgvector.sh w08lg      # 建对应库（同一容器，不新建）
#   取 ID: PG_CONTAINER_ID=$(docker ps -a --filter name=gp17 --format '{{.ID}}')
#
# 设计:
#   - 容器复用：按 CONTAINER ID 引用（不再依赖 name gp17）；新建时仍打 --name gp17 标签便于管理
#   - 容器不存在才 docker run；已存在则直接 docker start（保留已灌的向量数据）
#   - 用户 amber / 库 wNNrag 已存在则忽略错误，重复运行不报错
#   - 与 W05 的 w05rag 共用同一个 pgvector 实例（不同 database），不抢 5432
#   - 建库用超级用户 PGADMIN（默认与 PGUSER 同名=amber；若容器超级用户是 postgres，.env 设 PG_ADMIN=postgres）
set -e

# 容器引用统一用 CONTAINER ID；未设则报错提示，不再静默回退 name
CONTAINER="${PG_CONTAINER_ID:?请先设置 PG_CONTAINER_ID（docker ps -a 第一列 CONTAINER ID），例如：PG_CONTAINER_ID=a1b2c3d4e5f6 bash 00_start_pgvector.sh w08lg}"
DB="${1:-w06rag}"
PGPASS=amber123
PGUSER=amber
PGADMIN="${PG_ADMIN:-${PGUSER}}"

# 1) 容器已存在（按 ID 判断）-> 直接启动；不存在 -> 新建（--name gp17 仅作管理标签）
if ! docker ps -a --format '{{.ID}}' | grep -q "^${CONTAINER}$"; then
  echo "[新建] 未找到 ID=${CONTAINER}，启动新容器（标签名 gp17）"
  docker run -d --name gp17 -e POSTGRES_PASSWORD="${PGPASS}" -p 5432:5432 pgvector/pgvector:0.8.6-pg17
  CONTAINER=$(docker ps -lq)
  sleep 3
else
  echo "[复用] 容器 ${CONTAINER} 已存在，确保启动"
  docker start "${CONTAINER}" 2>/dev/null || true
  sleep 2
fi

# 2) 建用户（已存在忽略）—— 必须 -d template1 跳板，否则 psql -U amber 默认连 amber 库不存在会失败
echo "[建用户] ${PGUSER}（已存在则忽略）"
docker exec -i "${CONTAINER}" psql -U "${PGADMIN}" -d template1 -c \
  "CREATE USER ${PGUSER} WITH PASSWORD '${PGPASS}' SUPERUSER;" 2>/dev/null || true

# 3) 建库（已存在忽略）—— 同上，用 template1 当跳板库
echo "[建库] ${DB}（已存在则忽略）"
docker exec -i "${CONTAINER}" psql -U "${PGADMIN}" -d template1 -c \
  "CREATE DATABASE ${DB} OWNER ${PGUSER};" 2>/dev/null || true

echo "done -> psql -h 127.0.0.1 -U ${PGUSER} -d ${DB} (密码 ${PGPASS})"
