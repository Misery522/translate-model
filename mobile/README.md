# Android 私人文字客户端（内部 Alpha）

此目录包含本地 React 页面、受限原生 WebView 宿主、Java 安全核心和 Android
工程，已能生成私人 debug APK。**手机安装与真机验收尚未完成，不是正式发布版。**
普通网页入口及 PWA worker 行为不变；模拟、JVM 单测和 APK 编译不能代替真机。
模型仍在电脑运行，语音、离线推理和系统悬浮宠物均未实现。

经用户确认，不引入 Capacitor/Cordova 运行时：其默认通用 HTTP/Cookie 桥没有
完整的官方关闭开关。使用 AndroidX WebKit 1.14.0 的唯一来源受限消息桥，
不反射修补依赖，也不降级到旧式 JavaScript 接口。

## 已实现的基础

- `web/src/translatorTransport.ts`：网页和原生客户端共用的翻译业务接口。
- `web/src/types.ts`：Cookie 认证必须有字符串 CSRF；Bearer 认证必须是 null CSRF。
- `web/src/androidProtocol.ts`：私人 HTTPS 源和纯数据操作白名单。
- `web/src/androidApi.ts`：没有令牌字段、JavaScript 网络请求或持久化的原生适配器。
- `web/src/requestId.ts`：安全 UUID 回退；缺少安全随机源时保留原文并拒绝提交。
- `mobile/src`：私人地址配置、原生独立入口、消息 ID/容量/超时和迟到结果丢弃。
- `mobile/android`：真实 Java 白名单、系统 TLS、内存身份及前后台复位。
- `scripts/run-android-unit-tests.py`：不联网的真实 JVM 单测，总硬限 60 秒。

`App` 和 `useTranslator` 只依赖共享接口。网页仍使用同源 Cookie、内存 CSRF、
禁止重定向及禁止缓存的 `TranslationApi`；不能以接口支持 null CSRF 为由跳过
网页写操作的保护。`jobResponse`、`workSessionResponse` 保持统一响应验证。

## 原生宿主协议

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
- TS 和 Java 双重验证；令牌隔离由真实 Java 宿主执行，不只依赖模拟桥。
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

## 不得放宽的约束

1. APK 内置本地静态 React 资源，入口 `https://localhost/app/index.html`；Android
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

共享协议、构建环境和原生源码已完成；不代表真机和正式 App 已交付。经用户确认补齐
JDK 21.0.12.1+1、SDK Platform 36（修订 2）、命令行工具 22.0、Gradle 8.14.3，
已有 Build Tools 36.0.0 未重装。真实 AGP 8.13.0 Android Java 编译探针通过，
输出 Java 21 `.class`，没有 APK。全局环境变量、API 37、Studio JBR 和原模板保持不变。
详见 [项目环境启动器](../docs/ANDROID_ENVIRONMENT.md)。

Windows AGP 不接受中文工程根路径；正式原生工程将使用英文路径 Git worktree，
不移动现有仓库或绕过路径检查。原生宿主已锁定 WebKit 及传递依赖，校验元数据
与完整许可证随源码保存；无需 NDK/CMake。工作目录为独立英文路径 worktree。

私人 debug APK 在构建、lint、权限和许可验证通过后才用于安装到 Redmi K70，检查系统/WebView 版本、配对、
实际译文、取消/清空竞态、返回键、前后台、切网、电脑离线、重启和权限边界。
没有 USB 也可手工安装 APK；USB 调试仅用于真机日志和自动验收，须用户授权。

```powershell
npm --prefix web ci --ignore-scripts
npm --prefix web test
npm --prefix mobile test
npm --prefix mobile run build
.\.venv\Scripts\python.exe scripts/run-android-unit-tests.py --jdk-home '固定 JDK 路径'
./scripts/android-env.ps1 -Mode gradle -ToolArguments @('-p', 'mobile/android', ':app:assembleDebug', ':app:lintDebug')
```

测试入口有 60 秒硬上限。构建只在此隔离工作树进行，不覆盖当前试用服务的 dist。
手机有独立图标和窗口，但首版推理仍在电脑：电脑、Ollama、私人 API 和 Tailscale
需要在线。语音、持久设备身份、独立手机模型和系统悬浮宠物各自单独设计验收。

构建产物：`mobile/android/app/build/outputs/apk/debug/app-debug.apk`。
这是 Android 自动使用调试证书签名的内部 APK，不是正式签名、商店发布或公开分发。
APK、调试证书、SDK、缓存和模型不提交 GitHub；CI 不上传 APK。
Gradle 校验文件记录首次受信下载的摘要，不等于独立安全审计或完整作者签名验证。

安装操作与验收清单见 [Android 试用与下一步](../docs/ANDROID_NATIVE.md)。
完整原生许可见 [第三方署名](THIRD_PARTY_ANDROID_NOTICES.md)，前端 MIT 在构建时生成。

官方依据：[本地资源宿主](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content)、
[原生桥安全](https://developer.android.com/privacy-and-security/risks/insecure-webview-native-bridges)、
[WebKit 1.14.0](https://developer.android.com/jetpack/androidx/releases/webkit#1.14.0)、
[Vite 兼容范围](https://vite.dev/guide/build.html)。
