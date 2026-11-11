#!/usr/bin/env bash
# 一键启动：后端 FastAPI（8000）+ 前端 Vite（5173）
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi

mkdir -p data/uploads data/duckdb

# 后端
.venv/bin/python -I -m uvicorn app.api:app --app-dir backend --port 8000 &
API_PID=$!
trap 'kill $API_PID $VITE_PID 2>/dev/null || true' EXIT

# 前端（依赖未装时先装）
cd frontend
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev &
VITE_PID=$!

echo
echo "后端 API:  http://127.0.0.1:8000/docs"
echo "前端界面:  http://localhost:5173"
wait
