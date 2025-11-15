@echo off
chcp 65001 >nul
title Better Kemono and Coomer Downloader

echo ========================================
echo Better Kemono and Coomer Downloader
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python！
    echo 请先安装 Python: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [信息] Python 已安装
python --version
echo.

REM 检查是否存在虚拟环境
if exist ".venv\Scripts\activate.bat" (
    echo [信息] 检测到虚拟环境，正在激活...
    call .venv\Scripts\activate.bat
) else (
    echo [提示] 未检测到虚拟环境
    echo [提示] 建议创建虚拟环境以获得更好的依赖管理
    echo [提示] 创建命令: python -m venv .venv
    echo.
)

REM 运行主程序
echo [信息] 正在启动程序...
echo.
python main.py

REM 如果程序异常退出，暂停以便查看错误信息
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出，错误代码: %errorlevel%
    pause
)

