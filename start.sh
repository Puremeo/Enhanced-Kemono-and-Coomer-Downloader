#!/bin/bash

# 设置颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "Better Kemono and Coomer Downloader"
echo "========================================"
echo ""

# 检查 Python 是否安装
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo -e "${RED}[错误] 未检测到 Python！${NC}"
    echo "请先安装 Python: https://www.python.org/downloads/"
    exit 1
fi

# 确定 Python 命令
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

echo -e "${GREEN}[信息] Python 已安装${NC}"
$PYTHON_CMD --version
echo ""

# 检查是否存在虚拟环境
if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    echo -e "${GREEN}[信息] 检测到虚拟环境，正在激活...${NC}"
    source .venv/bin/activate
elif [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo -e "${GREEN}[信息] 检测到虚拟环境，正在激活...${NC}"
    source venv/bin/activate
else
    echo -e "${YELLOW}[提示] 未检测到虚拟环境${NC}"
    echo -e "${YELLOW}[提示] 建议创建虚拟环境以获得更好的依赖管理${NC}"
    echo -e "${YELLOW}[提示] 创建命令: $PYTHON_CMD -m venv .venv${NC}"
    echo ""
fi

# 运行主程序
echo -e "${GREEN}[信息] 正在启动程序...${NC}"
echo ""
$PYTHON_CMD main.py

# 检查退出状态
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}[错误] 程序异常退出${NC}"
    exit 1
fi

