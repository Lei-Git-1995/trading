#!/bin/bash

# Linux 平台构建脚本
# 此脚本需要在 Linux 环境下运行

echo -e "======================================"
echo -e "  go-stock Linux 构建脚本"
echo -e "======================================"

# 检查是否在 Linux 环境下运行
if [ "$(uname -s)" != "Linux" ]; then
    echo -e "\n错误：此脚本只能在 Linux 环境下运行"
    echo -e "请使用 Docker、WSL 或 Linux 虚拟机进行构建"
    echo -e "\n示例 Docker 构建命令:"
    echo -e "  docker run --rm -v \$(pwd):/app -w /app golang:1.21 ./scripts/build-linux.sh"
    exit 1
fi

# 进入项目根目录
cd "$(dirname "$0")/.."

echo -e "\n[1/5] 检查依赖..."

# 检查 Go 是否安装
if ! command -v go &> /dev/null; then
    echo -e "错误：未找到 Go 编译器，请先安装 Go 1.21+"
    exit 1
fi
echo -e "  ✓ Go 版本：$(go version)"

# 检查 Node.js 是否安装
if ! command -v npm &> /dev/null; then
    echo -e "错误：未找到 Node.js/npm，请先安装 Node.js 18+"
    exit 1
fi
echo -e "  ✓ Node.js 版本：$(node --version)"

# 检查 Wails 是否安装
if ! command -v wails &> /dev/null; then
    echo -e "  正在安装 Wails..."
    go install github.com/wailsapp/wails/v2/cmd/wails@latest
    if ! command -v wails &> /dev/null; then
        echo -e "错误：Wails 安装失败"
        exit 1
    fi
fi
echo -e "  ✓ Wails 版本：$(wails version)"

# 检查 libgtk-3-dev 和 libwebkit2gtk-4.0-dev 是否安装 (Ubuntu/Debian)
if command -v apt-get &> /dev/null; then
    if ! dpkg -l | grep -q libgtk-3-dev || ! dpkg -l | grep -q libwebkit2gtk-4.0-dev; then
        echo -e "\n  警告：缺少必要的系统依赖"
        echo -e "  请运行以下命令安装依赖:"
        echo -e "    sudo apt-get update && sudo apt-get install -y \\"
        echo -e "      libgtk-3-dev \\"
        echo -e "      libwebkit2gtk-4.0-dev \\"
        echo -e "      gcc \\"
        echo -e "      libglib2.0-dev"
        exit 1
    fi
fi

echo -e "\n[2/5] 清理旧的构建文件..."
rm -rf build/bin/linux

echo -e "\n[3/5] 安装前端依赖..."
cd frontend
npm install
cd ..

echo -e "\n[4/5] 构建前端..."
cd frontend
npm run build
cd ..

echo -e "\n[5/5] 构建 Linux 应用..."
wails build --platform linux/amd64 --clean

echo -e "\n======================================"
echo -e "  构建完成!"
echo -e "======================================"
echo -e "\n  可执行文件位置：build/bin/linux/go-stock"
echo -e "\n运行方式:"
echo -e "  ./build/bin/linux/go-stock"
echo -e "\n======================================"
