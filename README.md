# Enhanced Kemono and Coomer Downloader

[![Views](https://hits.sh/github.com/Puremeo/hits.svg)](https://github.com/Puremeo/Enhanced-Kemono-and-Coomer-Downloader)

这是一个改进版的 **Kemono 和 Coomer 下载器**，修复了原项目的多个 bug 和代码问题，不保证更新。

> 原项目：[Better-Kemono-and-Coomer-Downloader](https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader/)  
> 本项目是对原项目的改进版本，使用Cursor，修复了大量 bug 并改进了代码质量。

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Puremeo/Enhanced-Kemono-and-Coomer-Downloader&type=Date)](https://star-history.com/#Puremeo/Enhanced-Kemono-and-Coomer-Downloader&Date)

## ✨ 主要特性

- 🚀 **一键启动**：提供便捷的启动脚本，无需手动配置
- 📥 **批量下载**：支持单个帖子、多个帖子、整个用户主页的批量下载
- 🔄 **并行处理**：支持并行提取和下载，大幅提升下载速度
- 💾 **断点续传**：自动跳过已下载的文件，支持断点续传
- 🔐 **身份验证**：支持 API Token 和用户名/密码登录
- ⭐ **收藏下载**：支持从收藏列表中批量下载所有收藏的账户
- 📁 **智能组织**：自动按平台、作者、帖子组织文件结构
- 🛠️ **自动依赖**：自动检测并安装所需依赖包
- 📝 **详细信息**：可选保存帖子标题、描述、嵌入内容等信息

## 📋 系统要求

- **Python 3.7+** （推荐 Python 3.8 或更高版本）
- **网络连接**
- **Windows / Linux / macOS** 系统

## 🚀 快速开始

### 方法一：一键启动（推荐）

#### Windows 用户

1. 下载或克隆项目到本地
2. 双击运行 `start.bat` 文件
3. 程序会自动检查 Python 环境并启动

#### Linux / macOS 用户

1. 下载或克隆项目到本地
2. 给启动脚本添加执行权限：
   ```bash
   chmod +x start.sh
   ```
3. 运行启动脚本：
   ```bash
   ./start.sh
   ```

### 方法二：手动启动

1. **克隆仓库**
   ```bash
   git clone https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader.git
   cd Better-Kemono-and-Coomer-Downloader
   ```

2. **（可选）创建虚拟环境**
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate
   
   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```
   
   > 注意：程序会在首次运行时自动检测并安装缺失的依赖，但建议手动安装以确保环境正确。

4. **运行程序**
   ```bash
   python main.py
   ```

## 📖 使用指南

### 主菜单功能

运行程序后，你会看到以下选项：

```
1 - Download 1 post or a few separate posts        # 下载单个或多个帖子
2 - Download all posts from a profile              # 下载用户主页的所有帖子
3 - Customize the program settings                 # 自定义程序设置
4 - Exit the program                                # 退出程序
5 - Download all favorite accounts                 # 从收藏列表批量下载
```

### 功能详解

#### 1. 下载单个或多个帖子

支持三种输入方式：
- **直接输入链接**：粘贴一个或多个帖子链接（用逗号或空格分隔）
- **从文件读取**：从 TXT 文件中读取多个链接
- **重试失败下载**：自动从 `failed_downloads.txt` 读取之前失败的链接并重试

支持并发处理多个链接，提升下载效率。

#### 2. 下载用户主页帖子

提供多种下载模式：
- **下载所有帖子**：下载该用户的所有帖子
- **下载指定页面**：下载特定页面的帖子
- **下载页面范围**：下载指定页面范围内的帖子
- **下载帖子区间**：下载两个指定帖子之间的所有帖子

支持并行模式（同时提取和下载），大幅提升速度。

#### 3. 自定义设置

可配置选项：
- **获取空帖子**：是否下载没有附件的帖子
- **从旧到新处理**：是否按时间顺序从旧到新下载
- **保存帖子信息**：是否保存帖子的标题、描述等信息
- **信息文件格式**：选择 Markdown (.md) 或文本 (.txt) 格式
- **跳过已存在文件**：是否跳过已下载的文件（推荐开启）
- **身份验证**：设置 API Token 或登录凭据

#### 4. 收藏列表批量下载

从你的收藏列表中批量下载所有收藏的账户，支持：
- 自定义下载目录
- 限制下载账户数量
- 并行处理模式

### 身份验证

程序支持两种身份验证方式：

1. **API Token（推荐）**
   - 在设置中选择 "Authentication" → "Set API token"
   - 输入你的 Coomer API Token
   - Token 会安全保存到配置文件中

2. **用户名/密码登录**
   - 在设置中选择 "Authentication" → "Login with username/password"
   - 输入用户名和密码
   - 可选择保存凭据以便下次自动登录

## 📁 文件组织结构

下载的文件会按照以下结构自动组织：

```
项目目录/
│
├── kemono/                          # Kemono 平台文件夹
│   ├── 作者名-服务-ID/              # 作者文件夹（格式：Name-Service-Id）
│   │   ├── posts/                   # 帖子文件夹
│   │   │   ├── 帖子ID_帖子标题/     # 单个帖子文件夹
│   │   │   │   ├── 文件1.jpg
│   │   │   │   ├── 文件2.mp4
│   │   │   │   └── files.md         # （可选）帖子信息文件
│   │   │   └── ...
│   │   └── ...
│   └── ...
│
├── coomer/                          # Coomer 平台文件夹
│   ├── 作者名-服务-ID/
│   │   ├── posts/
│   │   │   └── ...
│   │   └── ...
│   └── ...
│
├── failed_downloads.txt             # 失败下载链接记录（自动生成）
├── config/                          # 配置文件目录
│   ├── conf.json                    # 程序配置
│   └── domain.json                  # 域名配置
└── ...
```

### 关于 `failed_downloads.txt`

当下载失败时，链接会自动保存到此文件。你可以：
1. 在主菜单选择 "Download 1 post or a few separate posts"
2. 选择 "Loading links from a TXT file"
3. 输入 `failed_downloads.txt`
4. 程序会自动重试失败的下载

成功下载后，链接会自动从文件中移除。

### 关于 `files.md` / `files.txt`

这是可选的帖子信息文件，包含：
- **标题**：帖子标题
- **描述/内容**：帖子内容或描述
- **嵌入内容**：嵌入元素信息（如有）
- **文件链接**：附件、视频、图片的 URL

可在设置中关闭此功能，或选择 Markdown 或文本格式。

## ⚙️ 配置说明

### 配置文件位置

- **程序配置**：`config/conf.json`
- **域名配置**：`config/domain.json`

### 配置方式

1. **通过程序界面配置**（推荐）
   - 在主菜单选择 "Customize the program settings"
   - 按提示修改各项设置

2. **手动编辑配置文件**
   - 直接编辑 `config/conf.json` 文件
   - 修改后重启程序生效

### 域名配置

如果 Kemono 或 Coomer 更换了域名，需要更新 `config/domain.json` 文件：

```json
{
  "kemono": "https://kemono.su",
  "coomer": "https://coomer.party"
}
```

> 注意：域名变更不频繁，通常不需要修改。

## 🔧 高级功能

### 命令行参数

程序支持非交互式命令行参数：

```bash
# 下载收藏列表
python main.py --download-favorites [目标目录]
```

### 并行处理

程序支持并行处理模式，可以同时提取和下载，大幅提升速度：
- 在下载用户主页时，可选择启用并行模式
- 在下载收藏列表时，可选择启用并行模式
- 多个链接下载时，自动使用并发处理

## 📦 依赖包

程序依赖以下 Python 包（会自动安装）：

- `requests` - HTTP 请求库
- `tqdm` - 进度条显示

## ❓ 常见问题

### Q: 程序启动时提示 "未检测到 Python"
**A:** 请确保已安装 Python 3.7+，并且 Python 已添加到系统 PATH 环境变量中。

### Q: 下载速度很慢
**A:** 
- 尝试启用并行处理模式
- 检查网络连接
- 某些内容可能需要身份验证才能下载

### Q: 某些文件下载失败
**A:**
- 检查链接是否有效
- 确认是否需要登录（某些内容需要身份验证）
- 查看 `failed_downloads.txt` 文件，使用重试功能

### Q: 如何更新程序？
**A:** 
```bash
git pull origin main
```

### Q: 支持哪些平台？
**A:** 目前支持 Kemono 和 Coomer 两个平台。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

- **Bug 报告**：请在 [Issues](https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader/issues) 页面提交
- **功能建议**：欢迎提出新功能建议
- **代码贡献**：Pull Request 请附带详细的说明和测试证据

## 📝 版本说明

- **稳定版本**：查看 [Releases](https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader/releases)
- **开发版本**：`main` 分支可能包含实验性功能
- **最新功能**：新功能和 bug 修复会先在 [develop 分支](https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader/tree/develop) 更新，测试通过后合并到主分支

## 📄 许可证

本项目采用 MIT License 许可证。

## 🙏 致谢

- 原项目：[Kemono and Coomer Downloader](https://github.com/e43b/Kemono-and-Coomer-Downloader/) by e43b
- 二代项目：[Kemono and Coomer Downloader](https://github.com/isaswa/Better-Kemono-and-Coomer-Downloader) by isaswa

- 所有贡献者和用户的支持


---

**注意**：请遵守相关网站的使用条款和版权规定，仅下载你有权访问的内容。
