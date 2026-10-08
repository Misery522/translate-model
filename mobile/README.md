# Android 客户端基础（尚无可安装 APK）

此目录记录 Android 首版的协议和安全边界。目前只实现了共享 TypeScript
传输接口、Android 协议验证和模拟适配器测试；**没有 Capacitor 运行时、Java
宿主、Android 工程或 APK**。普通网页入口及 PWA worker 注册行为没有改变。
模拟桥接测试不是 Redmi K70 真机验收，也不代表手机离线模型或语音已经可用。

## 已实现的基础

- `web/src/translatorTransport.ts`：网页和原生客户端共用的翻译业务接口。
- `web/src/types.ts`：Cookie 认证必须有字符串 CSRF；Bearer 认证必须是 null CSRF。
- `web/src/androidProtocol.ts`：私人 HTTPS 源和纯数据操作白名单。
- `web/src/androidApi.ts`：没有令牌字段、JavaScript 网络请求或持久化的原生适配器。
- `web/src/requestId.ts`：安全 UUID 回退；缺少安全随机源时保留原文并拒绝提交。

`App` 和 `useTranslator` 只依赖共享接口。网页仍使用同源 Cookie、内存 CSRF、
禁止重定向及禁止缓存的 `TranslationApi`；不能以接口支持 null CSRF 为由跳过
网页写操作的保护。`jobResponse`、`workSessionResponse` 保持统一响应验证。

## 原生宿主必须实现的协议

```ts
type AndroidBridgeCommand =
    | { command: "backend_status" }
    | { command: "configure_backend"; origin: string }
    | {
          command: "api_request";
          generation: number;
          request: AndroidApiOperation;
      };
```

`AndroidApiOperation` 只包含 health、auth、pair、logout、create_session、
delete_session、translate、job、cancel。不存在任意 URL、HTTP 请求头、工具、
Shell、文件读写或网络下载操作。Java 必须重复校验所有参数，不能仅信任 TS 类型。

- 状态返回 `{ origin, paired, generation }`，无额外字段。
- HTTP 操作返回 `{ status, body, generation }`，无额外字段。
- generation 是宿主连接代次，不是后端 Job 的工作代次；必须为非负安全整数。
- 配置地址（包括保存同一地址）、配对、注销和后台连接重置都必须使旧连接失效。
- 普通操作回包代次必须等于发起代次；成功 pair/logout 回包使用更大的新代次。
- 宿主必须在请求发起和结束时验证代次，旧响应不能重新保存令牌。
- pair 的 Java 网络响应可包含 Bearer，但 **在发送桥接消息前必须删除令牌和
  token_type**。JS 只接收 device_id、device_name、expires_at、auth_mode、csrf_token。
- TS 拒绝违反此契约的响应；这一防线不能代替尚未实现的 Java 端令牌隔离。
- 配对失败后连接代次未知；用户再次提交时先读回宿主状态，不自动重发旧配对码。
- 取消 JavaScript 等待不能证明服务端停止；必须使用 cancel/delete_session，
  断线或进程被杀时由服务端 TTL 最终回收。

配对码使用后端相同的 12 位 Base32 字符范围，名称最多 64 个 Unicode 字符。
提交、轮询和取消冻结 Job ID、Session ID、Client Request ID 和工作代次；删除
工作会话后清理对应绑定，配置或配对后清理所有绑定。未知原生错误仅显示固定
中文提示，不透传异常信息、响应体、地址、配对码或堆栈。

任务绑定及 JavaScript 等待中的提交合计上限为 128；只按首次确认终态顺序
回收最老记录，活动或未确认任务不被淘汰。已确认终态后，迟到的排队/运行状态
不得返回给调用方；删除或淘汰后的回包不能重建绑定。此上限不是原生网络并发
控制：取消或超时可能只结束 JS 等待，Java 必须另行实现网络资源与响应容量限制。

## 后续 Android 实现不得放宽的约束

1. APK 内置本地静态 React 资源，不使用 `server.url` 加载远程 UI；Android
   独立入口不注册 PWA service worker，不引入 Tauri 或复制 Rust 窗口控制。
2. 只连接用户明确配置的精确私人 Serve HTTPS origin。初版只接受
   `https://设备名.私人网络名.ts.net`；允许规范化默认 443，拒绝非标准端口、
   路径、查询、凭据、片段、IP、HTTP 和编码绕过。`.ts.net` 后缀不是身份认证，
   仍须私人 Tailscale 网络、用户确认正确电脑地址及一次性应用配对。
3. 原生网络使用系统 TLS 与主机名验证，不跳过证书、不跟随重定向、不携带
   WebView Cookie。API 保持电脑回环监听，不能直接暴露 Ollama。
4. Bearer 仅原生进程内存保存；禁止 localStorage、Preferences、Bundle、
   IndexedDB、日志和备份保存原文、译文或令牌。进程死亡后重新配对。
5. 原生前后台生命周期必须失效迟到响应、尽力取消任务并清空敏感界面；不得
   宣称 `onDestroy` 保证执行。用户主动注销或切换地址时，本地立即失效。
6. 最低 API 26；现有 Vite 构建目标 Chromium 111，须明确 WebView 最低版本和
   无桥接错误页。不因 API 26 承诺所有 Android 8 设备或华为机型兼容。
7. 首版仅前台文字翻译，默认只需 INTERNET；不申请麦克风、悬浮窗、通知、
   无障碍、存储、开机启动或后台常驻。复制只响应用户主动操作。

## 开发和验收顺序

先完成本轮共享协议，再锁定 Capacitor 稳定依赖及许可证，加入 Java 宿主和
本地 Android 页面，执行静态检查、Java 单测和 CI 构建。经用户确认补齐 JDK 21
和 SDK Platform 36；已有 Build Tools 36.0.0 不重复安装。无需 NDK/CMake。

之后才生成私人 debug APK、安装到 Redmi K70，检查系统/WebView 版本、配对、
实际译文、取消/清空竞态、返回键、前后台、切网、电脑离线、重启和权限边界。
没有 USB 也可手工安装 APK；USB 调试仅用于真机日志和自动验收，须用户授权。

```powershell
npm --prefix web ci --ignore-scripts
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

测试入口有 60 秒硬上限。构建只在此隔离工作树进行，不覆盖当前试用服务的 dist。
手机有独立图标和窗口，但首版推理仍在电脑：电脑、Ollama、私人 API 和 Tailscale
需要在线。语音、持久设备身份、独立手机模型和系统悬浮宠物各自单独设计验收。

官方依据：[Capacitor Android](https://capacitorjs.com/docs/android)、
[配置安全边界](https://capacitorjs.com/docs/config)、
[原生插件](https://capacitorjs.com/docs/android/custom-code)、
[固定版本模板](https://github.com/ionic-team/capacitor/tree/8.5.3/android-template)、
[Vite 兼容范围](https://vite.dev/guide/build.html)。
