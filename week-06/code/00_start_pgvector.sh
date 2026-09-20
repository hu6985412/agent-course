#!/usr/bin/env bash
# pgvector 操作脚本（幂等，复用同一容器 gp17）· W06 起所有课程的 RAG 向量库统一走它
#
# 用法:
#   bash 00_start_pgvector.sh            # 默认建 w06rag
#   bash 00_start_pgvector.sh w07rag     # 后续课程：建对应库（容器仍是 gp17，不新建）
#
# 设计:
#   - 容器名固定 gp17（amber 本机已建，后续课程全部复用，按 database 名 wNNrag 区分）
#   - 容器不存在才 docker run；已存在则直接 docker start（保留已灌的向量数据）
#   - 用户 amber / 库 wNNrag 已存在则忽略错误，重复运行不报错
#   - 与 W05 的 w05rag 共用同一个 gp17 实例（不同 database），不抢 5432
#   - 建库用超级用户 PGADMIN（默认与 PGUSER 同名=amber；若容器超级用户是 postgres，.env 设 PG_ADMIN=postgres）
set -e

CONTAINER=gp17
DB="${1:-w06rag}"
PGPASS=amber123
PGUSER=amber
PGADMIN="${PG_ADMIN:-${PGUSER}}"

# 1) 容器已存在 -> 直接启动；不存在 -> 新建
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "[新建] 启动 ${CONTAINER} 容器"
  docker run -d --name "${CONTAINER}" -e POSTGRES_PASSWORD="${PGPASS}" -p 5432:5432 pgvector/pgvector:0.8.6-pg17
  sleep 3
else
  echo "[复用] ${CONTAINER} 已存在，确保启动"
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
