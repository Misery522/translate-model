# Android 可安装客户端实施方案

更新日期：2026-10-08。用户选择：先做可安装 Android App，再做语音。
这是实施与验收方案，不是已经交付 APK 的公告。

## 产品形态与边界

首版是有独立桌面图标、窗口和安装包的 Android App，不需要用户每次打开外部浏览器。
采用 Capacitor 原生宿主承载随安装包分发的 React 界面，由 Java 原生桥连接私人 API。
内部使用 Android WebView 不等于使用浏览器标签页，也不等于已经有手机端模型。

- Redmi K70 的系统版本由用户报告为 HyperOS 3.0.307.0；实际 Android/WebView 版本待验收。
- 原有 PWA 保留为测试和回退入口，不是最终手机客户端的唯一形态。
- 第一版仍依赖电脑开机、API/Ollama 运行和私人 Tailscale 网络；不使用公网 Funnel。
- 宠物先在 App 内反馈连接、翻译、停止与离线状态；不申请系统悬浮窗或后台监听权限。
- 手机离线推理、按住说话、连续口译、华为及 iPhone 原生客户端分别验收，不提前承诺。

## 已完成的前置验证

- PWA 已通过 431 项 Python、115 项网页测试，两个 npm 传递依赖已定向修复。
- 本轮 11 项真实本地模型集成通过；私人 HTTPS 与静态壳可访问。
  上述电脑侧测试不等于手机译文质量、交互或蜂窝网络验收。
- 用户已确认手机配对并能发送；尚未确认全部译文与恢复场景。
- M3 隔离升级至 Tauri 2.12.1 后，34 项 Rust、170 项网页、53 项桌面测试通过。
  严格审计仍有两项 GTK 链警告，桌面合并和安装包发布继续暂停。
- Android 客户端从 `origin/main` 的 `049a86e` 独立开展，不依赖尚未合并的 M3。
- 本轮已完成共享 `TranslatorTransport`、Cookie/Bearer 元数据、Android 白名单
  协议、原生适配器模拟和安全 UUID 回退。审查后补齐终态回收、UUID 响应和
  迟到状态回退保护；最终复验 161 项网页/协议测试通过
  （5.62 秒，入口硬限 60 秒），全量格式检查、TypeScript、静态构建和 npm 审计通过。
  没有 Capacitor 运行时、Java 宿主、Android 工程或 APK；模拟测试不代表真机验证。
- 新 CI 发现 urllib3 三项公告后已定向修复到 2.8.0，网页两项 npm 传递依赖
  同步安全锁补丁；不以旧审计绿灯代替当前提交。详见独立依赖修复 PR #25。

## 环境核验与补装范围

拟锁定 Capacitor core/cli/android 8.5.3；产品最低 API 26。
官方模板使用 compile/target SDK 36、AGP 8.13.0、Gradle 8.14.3 和 Java 21。
minimum SDK 是可安装下限，compile/target SDK 是构建及系统行为目标，三者不能混淆。

已安装 Android Studio、Node 24.18.1、SDK Platform 37.0、Build Tools 36.0.0。
尚缺 JDK 21、SDK Platform 36 和 SDK command-line tools。
Android Studio 的 JBR 25 不直接用于 Gradle 8.14.3。

补装必须取得单独系统变更确认：保留 API 37，保留 Android Studio 自身 Java，
只为此项目选择 JDK 21；不修改全局 PATH/JAVA_HOME，不安装 NDK/CMake，
不重建 Python 环境或变动模型。原 Native C++ 模板不覆盖、不删除。

## 实施顺序

1. 抽取共享传输契约、认证元数据和响应校验；保持网页 Cookie/CSRF 行为不变。
   移植已测试的安全请求编号回退，避免依赖未合并桌面宿主。
2. 实现 Android 原生操作协议与模拟测试：白名单路由、任务绑定、固定错误映射、
   连接代次和取消语义。模拟测试不作为真实原生宿主或手机测试。
3. 系统补装获确认后，固定 Capacitor 依赖、生成独立 Android 工程和本地界面入口。
   不设置远程 `server.url`，不把 Tauri/Rust 窗口插件复制到手机。
4. 实现 Java 内存认证、HTTPS 网络桥、导航/CSP、生命周期和隐私配置。
5. 执行依赖及许可审查、前端测试、Java 单测、Android lint 与私人 debug 构建。
   构建预编译与单测计时分离；每套单元测试运行上限 60 秒。
6. 在 Redmi K70 手工安装、配对、翻译、停止、清空和恢复验收；USB 是调试辅助手段，
   不强制作为安装条件。系统安装来源/USB 调试授权由用户在手机明确操作。
7. 真机验收通过后再决定内部候选、签名、公开分发；不自动上传 APK 或创建 Release。
8. 文字客户端稳定后改进宠物互动，再评估本地 ASR/TTS，最后开展连续双向口译。

## 不可降低的安全要求

- Bearer 只存原生进程内存；不返回 JS，不写 Preferences、Bundle、日志、备份、
  localStorage、sessionStorage 或 IndexedDB。进程丢失后重新配对。
- JS 仅能请求声明过的操作，不传任意 URL、方法或请求头；原生端必须重复验证。
- 用户明确选择精确私人 Serve HTTPS origin；不将整个 `.ts.net` 通配视为可信身份。
  拒绝路径、查询、片段、凭据、HTTP 与非标准端口，地址变化立即使旧身份失效。
- 保留系统证书及主机名验证，禁止 trust-all、忽略 SSL 错误和自动重定向。
  不硬编码会轮换的短期证书，不放宽后端 Host/Origin/CSRF 边界。
- 原生入口不得注册 PWA Service Worker；远程页面、外部链接与错误页不获得桥接权限。
- 清空、地址切换、注销与进入后台后作废旧代次；取消本地等待不冒充服务器模型已停止。
  尽力清理有时限，系统杀进程仍由后端 TTL 兜底，不无限等待销毁回调。
- 仅申请文字联网所需权限；不预先申请麦克风、存储、悬浮窗、通知、无障碍或后台保活。
- 关闭敏感页面截图/最近任务缩略图和自动备份；复制仅响应用户主动操作。
  服务地址设置是否记忆与长期身份保存分开设计，不借保存地址保存令牌或文本。

## 兼容与验收门槛

当前 Vite 默认构建目标为 Chromium 111；Capacitor 宿主默认 WebView 60 不足以保证
此应用兼容。首版明确要求 WebView 111+，不满足时显示无原生桥的升级说明。
若要覆盖更旧 WebView，另行转译、polyfill 审查与真机验证，不能只降低 minSDK。

- 安装、卸载、首次启动、配对成功/错误/过期、地址变更与证书失败。
- 文本、术语、Markdown、同语种与代码注解；4000 字符边界。
- 复制、停止、重试、清空；迟到结果不得恢复旧内容。
- 熄屏/后台恢复、弱网切换、电脑离线、后端重启、进程被杀后重新配对。
- 请求/响应限额、非法操作、提示注入、伪造身份与畸形返回均不能突破原生白名单。
- 正确记录 Redmi 的 Android 与实际 WebView 版本；不据此宣称全部华为或 iOS 兼容。

## 官方依据

- [Capacitor Android](https://capacitorjs.com/docs/android) 与
  [配置边界](https://capacitorjs.com/docs/config)。
- [8.5.3 固定 SDK 模板](https://github.com/ionic-team/capacitor/blob/8.5.3/android-template/variables.gradle)
  与 [固定 Gradle](https://github.com/ionic-team/capacitor/blob/8.5.3/android-template/gradle/wrapper/gradle-wrapper.properties)。
- [Gradle Java 兼容矩阵](https://docs.gradle.org/current/userguide/compatibility.html)。
- [Android 网络安全](https://developer.android.com/privacy-and-security/security-config)
  与 [WebView 安全建议](https://developer.android.com/privacy-and-security/security-best-practices)。
- [Vite 构建兼容范围](https://vite.dev/guide/build.html)。
