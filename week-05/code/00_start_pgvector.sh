#!/usr/bin/env bash
# W05 阶段2 · 00 起 pgvector 容器（Docker）
# 作用：起一个独立 Postgres + pgvector 容器，专门给 W05 RAG 用。
# 和你本机 MySQL agent_runtime 库各管各的，端口 5432 不冲突（本机没有原生 Postgres）。
set -e

docker run --name w05-pgvector \
  -e POSTGRES_USER=amber \
  -e POSTGRES_PASSWORD=amber123 \
  -e POSTGRES_DB=w05rag \
  -p 5432:5432 -d pgvector/pgvector:pg17

echo "容器已启动，等待 pgvector 就绪..."
sleep 5
docker exec -i w05-pgvector psql -U amber -d w05rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
echo "pgvector 就绪：host=127.0.0.1 port=5432 db=w05rag user=amber"
echo "下一步：pip install -r requirements.txt && python 01_build_index.py"
