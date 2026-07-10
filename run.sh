#!/bin/bash
# 一键启动 竞品监测 Agent（首次运行会自动配环境）
set -e

echo "==> 检查虚拟环境"
if [ ! -d ".venv" ]; then
  echo "    创建 .venv ..."
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "==> 安装依赖"
pip install -r requirements.txt -q

echo "==> 检查 .env"
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "    已生成 .env —— 请打开填入你的 API Key（OpenAI 或 DeepSeek）后重新运行 ./run.sh"
  exit 0
fi

echo "==> 启动 Streamlit"
streamlit run app.py
