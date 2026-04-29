#!/bin/bash

# AI 图片生成工作流 - 快速启动脚本

echo "=================================="
echo "AI 图片生成工作流 - 启动脚本"
echo "=================================="

# 检查 Python 版本
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "检测到 Python 版本: $python_version"

# 检查依赖
echo ""
echo "检查依赖..."
if pip show flask > /dev/null 2>&1; then
    echo "✓ Flask 已安装"
else
    echo "✗ Flask 未安装，正在安装..."
    pip install -r requirements.txt
fi

if pip show requests > /dev/null 2>&1; then
    echo "✓ Requests 已安装"
else
    echo "✗ Requests 未安装，正在安装..."
    pip install requests
fi

# 检查环境变量
echo ""
echo "检查环境变量..."
if [ -z "$COZE_API_URL" ]; then
    echo "⚠ COZE_API_URL 未设置"
    echo "  请设置: export COZE_API_URL=https://your-api.coze.site/run"
fi

if [ -z "$COZE_API_TOKEN" ]; then
    echo "⚠ COZE_API_TOKEN 未设置"
    echo "  请设置: export COZE_API_TOKEN=your_token"
fi

# 创建目录
echo ""
echo "创建必要的目录..."
mkdir -p /tmp/uploads /tmp/outputs
echo "✓ 目录已创建"

# 启动应用
echo ""
echo "=================================="
echo "启动应用..."
echo "=================================="
echo ""
echo "访问地址: http://localhost:5000"
echo "按 Ctrl+C 停止"
echo ""

python app.py
