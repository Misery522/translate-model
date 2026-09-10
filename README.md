# 译境 · 本地智能翻译

译境是使用 Ollama、Gradio 和 LangGraph 的本地受控翻译 Agent。
当前版本提供浏览器界面，用 `qwen3.5:4b` 翻译文字、处理专业术语，并为代码生成注解。
模型只能选择预设处理路径，不能执行输入中的命令或代码。

仓库地址：[Misery522/translate-model](https://github.com/Misery522/translate-model)。
项目处于早期版本。除原有 Gradio 界面外，现提供私人 API 与会话式网页；
原生桌面宠物、手机客户端和语音仍按[开发路线](docs/ROADMAP.md)分阶段验证。
核心已独立为 `yijing` 包，Gradio 经统一服务调用既有翻译工作流，见
[核心服务架构](docs/ARCHITECTURE.md)。

## 当前能力

- 自动识别源语言，提示不确定或混合语言；支持常用目标语言。
- 标准、正式、口语三种风格，以及通用、技术、商务、金融、法律、医疗和学术领域。
- 本地自定义术语表；按指定译法恢复术语，词库冲突会明确报错。
- 由程序保存段落、换行和受保护内容，模型翻译带稳定 ID 的文字片段。
- 普通翻译、Python 注释、特殊内容说明和混合文档路由。
- Python 注释副本重新解析并比较 AST；校验失败时回退为外部说明。
- 清空后丢弃迟到结果，输入上限为 4000 个字符。
- 仅监听本机回环地址，关闭 Gradio 分享和分析统计；不提供翻译历史存储。

工作流：

```text
输入校验 → 规则分类 → 必要时模型判断 → 白名单路由
        → 翻译或注解 → 验证 → 最多一次修复 → 返回
```

法律、医疗等内容会提示复核。模型译文和代码说明都可能出错，不能代替专业判断。

## 快速开始

当前推荐 Python 3.14。项目元数据允许 Python 3.11–3.14；其他版本和系统的
支持情况以对应提交的 CI 结果为准，不代表已经完成真机模型验收。

先安装 [Git](https://git-scm.com/downloads)、[uv](https://docs.astral.sh/uv/getting-started/installation/)
和 [Ollama](https://ollama.com/download)，启动 Ollama。
以下命令适用于 Windows PowerShell，在自行选择的开发目录执行：

```powershell
git clone https://github.com/Misery522/translate-model.git
cd translate-model
uv sync --locked --group dev
ollama pull qwen3.5:4b
uv run python agent.py
```

依赖安装和首次模型下载需要联网。已经安装模型时，使用 `ollama list` 确认即可，
无需重复下载。模型权重未包含在仓库内，应单独阅读其许可证。

浏览器打开终端打印的地址。默认优先使用 `http://127.0.0.1:7860`，端口被占用时
自动尝试 7860–7959。Ollama 离线时界面仍可启动，但模型操作会提示连接问题。

使用锁文件建立环境后，也可保持原有启动方式：

```powershell
.\.venv\Scripts\python.exe .\agent.py
```

不要将 `.venv` 从其他电脑复制过来；每台设备应从锁文件创建自己的环境。
需要会话式网页或私人手机访问时，按照[私人部署说明](docs/PRIVATE_DEPLOYMENT.md)
构建 `web/` 并运行 `uv run yijing-api --static-dir web/dist`。
私人手机访问还需要用户配置 HTTPS 与设备访问控制；不是打开 `share=True`。

## 配置

应用读取进程环境变量，**不会自动加载 `.env` 文件**；`.env.example` 仅作为配置示例。
例如在当前 PowerShell 中设置：

```powershell
$env:TRANSLATOR_INBROWSER = "0"
$env:TRANSLATOR_PORT = "7861"
uv run python agent.py
```

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Ollama 中已安装的模型名 |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | 仅允许本机回环地址 |
| `OLLAMA_TIMEOUT` | `120` | 单次模型请求超时秒数 |
| `TRANSLATOR_KEEP_ALIVE` | `30m` | 模型内存驻留提示，不是磁盘保留设置 |
| `TRANSLATOR_PORT` | 自动选择 | 设定后仅使用指定端口 |
| `TRANSLATOR_INBROWSER` | `1` | 设为 `0` 时不自动打开浏览器 |
| `YIJING_DATA_DIR` | 按运行方式选择 | 可写的本地数据目录，保存自定义词库 |

核心模块拒绝非回环 Ollama 地址。界面入口遇到不合规地址会回退到本机默认地址，
并显示警告。启动诊断会打印脚本和解释器路径、服务地址、模型和最终网页地址；
公开日志或截图前请隐藏个人路径。

## 术语与数据

源码运行时，自定义术语保存在项目的 `data/glossary.json`，该文件默认被 Git 忽略。
安装 wheel 后使用操作系统的当前用户 `Yijing` 数据目录，不写入 `site-packages`。
如需指定位置，设置 `YIJING_DATA_DIR` 为可写目录；请自行保护该目录并避免纳入 Git。
可以从 [示例词库](data/glossary.example.json) 了解格式，在界面内编辑和保存自己的词条。
应用不会自动将示例词库覆盖到已有词库。

原文、译文和会话处理状态在运行时内存中使用，应用没有翻译历史保存功能。
操作系统、浏览器、Ollama 或调试工具可能有自己的缓存和日志。详细数据边界见
[隐私说明](PRIVACY.md) 和 [威胁模型](THREAT_MODEL.md)。

## 模型存在与内存卸载

```powershell
ollama list
ollama ps
```

`ollama list` 显示当前 Ollama 服务可见的已安装模型；`ollama ps` 显示已加载到
内存或显存的模型。`ps` 为空通常表示尚未加载或已经卸载，不代表磁盘模型被删除。
退出译境、空闲卸载和 `keep_alive` 过期本身不会删除模型文件。

需要更改模型目录时，请遵循当前 [Ollama Windows 文档](https://docs.ollama.com/windows)
和 [FAQ](https://docs.ollama.com/faq)，完整保留 `manifests` 与 `blobs`，保留可回退副本，
再重启 Ollama 验证。译境不会迁移或删除模型，也不会自动修改系统环境变量。

## 测试与开发

```powershell
uv run ruff check .
uv run python -m pytest -q -m "not ollama"
uv pip check
```

普通测试使用替身模型，不要求 Ollama。真实模型测试必须显式启用，只连接本机；
执行前确认机器没有其他重要推理任务，并为每个测试设置外部运行时限：

```powershell
$env:OLLAMA_INTEGRATION = "1"
uv run python -m pytest -q -m ollama
Remove-Item Env:OLLAMA_INTEGRATION
```

模型测试耗时受硬件影响，不能用单元测试通过来代替模型质量验收。
具体贡献流程、检查和报告要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可与支持

源码采用 [Apache-2.0](LICENSE)，版权为 `2026 Misery522 and contributors`。
依赖、模型和素材具有各自许可证，见 [第三方说明](THIRD_PARTY_NOTICES.md)。
软件按现状提供；当前版本的翻译质量和设备兼容性需要用户在自己的场景验证。

一般问题请遵循 [支持说明](SUPPORT.md) 提交 Issue；安全漏洞请先阅读
[SECURITY.md](SECURITY.md)，不要在公开 Issue 中粘贴敏感原文、令牌或漏洞利用细节。
