# 私人 API 与会话式网页（M2）

这是连接自己电脑的文字客户端，不是公共多人翻译网站。
电脑必须保持开机，Python 服务与 Ollama 必须可用；离线缓存只有网页壳，不含模型。
本阶段不会自动安装 VPN、修改防火墙、开放端口或申请证书。

## 本机开始

要求 Node.js 24 LTS、uv 和已有的 Ollama 模型。在项目根目录执行：

```powershell
uv sync --locked --group dev
npm --prefix web ci
npm --prefix web run build
uv run yijing-api --static-dir web/dist
```

打开终端地址 `http://127.0.0.1:8765`，输入终端打印的 12 位一次性配对码。
码 5 分钟有效、成功使用即作废。需要配对另一台设备时，在运行服务的本机终端
输入 `p` 后按 Enter。不要把配对码、Cookie、Bearer 令牌或终端完整截图公开。

端口被占用时先检查是否已经启动此服务；可显式加 `--port 8766`。
API 不自动结束占用端口的进程，也不在后台启动第二个 Ollama。

Gradio 仍可用原命令启动，但 API 与独立 Gradio **不要同时写同一词库**。
如确需同时运行，应通过进程环境中的 `YIJING_DATA_DIR` 指定不同数据目录。
API 的词库是电脑端共用资源；所有已配对设备均视为可信用户，不提供多租户隔离词库。

## 手机访问：先建立私人 HTTPS

手机的 `127.0.0.1` 指手机自己，不能用电脑终端的回环地址直接连接。
推荐先由用户在电脑及手机安装、登录并核准私人网络工具，再配置仅向受信设备开放的
HTTPS 反向代理。不能把 Ollama 的 11434、Gradio 或此 API 直接映射到公网。

一种可选方式是 [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)。
确认设备访问规则、MagicDNS 和 HTTPS 之后，以实际分配的设备域名启动后端：

```powershell
uv run yijing-api --static-dir web/dist --public-origin https://YOUR-DEVICE.YOUR-TAILNET.ts.net
tailscale serve --bg http://127.0.0.1:8765
```

示例域名必须替换为自己的实际域名，不能照抄。使用 Serve 的私人访问，不使用
Funnel 公网分享。代理必须保留公网 `Host`，否则后端会明确拒绝请求；
通过 `tailscale serve status` 检查实际地址后，再在已授权手机浏览器访问、配对。
自定义反向代理也必须保证 TLS、精确 Host、无正文／凭据日志，并限制来源设备。

浏览器可将网页添加到主屏幕；具体入口由系统和浏览器决定。
原生鸿蒙设备是否能接入所选私人网络工具需另行核查，不能假设全部手机均支持。
目前未完成 Android/iOS 真机和私人 HTTPS 实网验收。

## 状态、取消与过期

- 浏览器只在当前页面内存保留最近 20 轮，刷新不恢复原文或译文。
- 默认一轮运行、最多八轮排队；每设备只能有一轮未完成请求。
- 排队最多 30 秒，运行最多 180 秒，结果在服务内存保留最多 5 分钟。
- 配对会话空闲 30 分钟过期，最长 24 小时，服务重启后所有设备重新配对。
- 清空立即清界面并请求删除工作会话；断网时明确提示尚未确认服务端停止。
- 取消或超时会回收 API 自己创建的 Python 推理进程，不停止 Ollama。
  HTTP 断开不保证 Ollama 的 GPU 计算在同一瞬间停止。
- 输入中的命令、代码、URL 仍是数据，不获得 Shell、文件写入或额外网络工具。

关闭服务会清除 API 内存会话，但不能安全擦除浏览器、系统交换文件或 Ollama 缓存。
API 不接受客户端更改模型 URL，不向客户端返回私有磁盘路径。

## 前端开发与协议检查

开发服务器的 Origin 与实际 API 监听端口可以不同。以下配置保留 Vite 代理的
Host，并只允许本机地址；仅供开发，不用 HTTP 连接远程手机：

```powershell
uv run yijing-api --public-origin http://127.0.0.1:5173
npm --prefix web run dev
```

协议来自本地 Pydantic/FastAPI 类型，不从生产服务抓取、不包含运行时配对码：

```powershell
uv run python scripts/export_openapi.py
npm --prefix web run generate:api
uv run python scripts/export_openapi.py --check
npm --prefix web test
npm --prefix web run build
```

wheel 提供 Python API 与核心；网页须从同版本源码的 `web/` 构建后通过
`--static-dir` 挂载。GitHub Pages 不能运行 Ollama 或此 Python 后端。
