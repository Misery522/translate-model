# 译境会话式网页

React + TypeScript + Vite 前端，通过同源 `/api/v1` 使用电脑上的译境服务。
小译是原创 SVG 交互角色：会显示等待、思考和离线状态。网页本身不包含模型，
也不提供麦克风监听、语音识别或自主执行命令。

## 构建并运行

使用 Node.js 24.15–24.x、npm，以及根目录说明要求的 Python / uv 环境。
依赖版本记录在 `package-lock.json` 中，不需要全局安装 Vite。

在仓库根目录执行：

```powershell
npm --prefix web ci
npm --prefix web run build
uv sync --locked --group dev
uv run yijing-api --static-dir web/dist
```

打开终端打印的地址，默认为 `http://127.0.0.1:8765`，输入终端显示的
12 位一次性配对码。配对码 5 分钟有效；要连接另一台设备时，在服务器终端
输入 `p` 并按 Enter，取得新的配对码。请勿将配对码贴进公开 Issue 或日志。

本机地址不会让手机自动获得访问能力。私人跨设备 HTTPS 访问和服务端安全边界
见 [私人部署说明](../docs/PRIVATE_DEPLOYMENT.md)。不要直接公开 Ollama 端口。
网页可以安装到支持 PWA 的浏览器主屏幕，但安装网页不等于在手机上安装模型；
电脑关机、Ollama 不可用或网络中断时不能进行新翻译。

## 前端开发

先在仓库根目录启动允许开发页面来源的 API：

```powershell
uv run yijing-api --public-origin http://127.0.0.1:5173
```

另开一个终端：

```powershell
npm --prefix web run dev
```

打开 `http://127.0.0.1:5173`。Vite 只监听回环地址，将 `/api` 同源代理到
`127.0.0.1:8765`，保留浏览器的 Origin。不要关闭来源校验来解决配置错误。
开发服务不用于生产部署；`npm run preview` 只用于查看静态构建，不提供此 API 代理。
Service Worker 仅在生产构建中注册。

## 验证与接口类型

```powershell
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
npm --prefix web audit
```

测试入口对全套测试设定 60 秒硬超时，单项测试默认 5 秒。
`test:watch` 是手动开发模式，不受全套 60 秒限制。
构建和模拟 API 测试不能替代真实浏览器、真实模型及移动设备验收。

API 数据类型只能从后端 OpenAPI 生成；不要手工维护第二份请求或结果字段。
后端接口变更后，在仓库根目录执行：

```powershell
uv run python scripts/export_openapi.py
npm --prefix web run generate:api
npm --prefix web run typecheck
npm --prefix web test
```

提交 `openapi.json` 和 `src/api.generated.ts` 的同步变更。
`src/types.ts` 仅提供生成类型的别名、经运行时验证的浏览器鉴权类型和页面显示状态。

## 状态与隐私约束

- 原文与结果只在当前页面内存中保留，最多 20 轮；刷新不恢复历史。
- 浏览器凭据使用 HttpOnly Cookie，CSRF 值仅保存在内存中。
  不向 `localStorage` 或 `sessionStorage` 写入令牌、配对码、原文和译文。
- 清空立即清除本页输入和结果，然后请求服务器撤销旧工作会话。
  请求代次与 AbortController 阻止迟到结果恢复旧内容。
- 未确认取消或退出时明确提示，并保留恢复连接或重试操作；网络断开不意味着
  服务器工作已经停止。页面离开时只做最佳努力清理，服务端仍须提供到期兜底。
- 离线不会缓存任务、自动重新提交文本或后台录音。
  原文和模型输出均按文本节点 / `pre` 显示，不执行 HTML、代码或命令。
- 词库在运行后端的电脑上保存；清空对话不会删除词库。
  复制由用户明确触发，会将选择的译文写入操作系统剪贴板。

## 静态资产与更新

公开构建目录仅包含：`index.html`、`manifest.webmanifest`、`pet-icon.svg`、
`sw.js`、`THIRD_PARTY_LICENSES.txt` 和 `assets/` 下的构建资产。
构建时从已锁定安装的 React、React DOM、Scheduler 包读取完整版权和许可，
合并生成 `THIRD_PARTY_LICENSES.txt`，发布前端时必须一并提供。
构建插件按实际文件名生成精确缓存白名单，许可文件不需要离线缓存。
Service Worker 不拦截或缓存 `/api`、查询参数请求或非同源资源。

离线缓存只用于打开界面壳，不提供离线推理。更新不会调用 `skipWaiting` 强制
替换正在使用的页面，也不会自动刷新进行中的翻译。完成当前工作后关闭旧页面
并重新打开，可让待更新版本正常接管。

不要把整个仓库目录作为公开静态目录：其中可能含配置、个人词库或开发文件。
生产部署应使用后端 `--static-dir web/dist` 的受限静态挂载及安全响应头。
