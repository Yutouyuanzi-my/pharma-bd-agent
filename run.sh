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
  cat > .env <<'ENVEOF'
# 在此填入你的 API Key（DeepSeek / OpenAI 兼容端点）
DEEPSEEK_API_KEY="在此填入你的_API_Key"

# 可选：自定义 API 端点（DeepSeek 为 https://api.deepseek.com）
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 可选：自定义模型名（DeepSeek 为 deepseek-chat）
DEEPSEEK_MODEL=deepseek-chat
ENVEOF
  echo "    已生成 .env —— 请打开填入你的 API Key（OpenAI 或 DeepSeek）后重新运行 ./run.sh"
  exit 0
fi

echo "==> 启动 Streamlit"
streamlit run app.py
