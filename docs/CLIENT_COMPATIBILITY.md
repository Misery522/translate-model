# 客户端兼容目标与验证边界

兼容目标整理日期：2026-09-10；平台依据首次核查于 2026-09-07。
下表是开发目标，不是已通过全部设备测试的承诺。
“客户端能运行”与“手机能独立离线运行 4B 模型”是两个不同项目。

## 最小兼容矩阵

| 平台 | 第一阶段建议 | 目标 / 限制 | 当前验收状态 |
| --- | --- | --- | --- |
| Windows 10/11 | Tauri 2 文字宠物 + 私人 API | WebView2；先做 x64；托盘与快捷键仅桌面 | 宿主源码，待编译、签名与真机 |
| 小米等 Android 设备 | HTTPS 网页/PWA，随后 Capacitor 壳 | 产品目标 Android 8+（minSDK 26）；WebView 与厂商权限仍需实测 | 目标，未真机验证 |
| 支持 Android APK 的华为机型 | 同 Android 路线 | 必须核对机型、完整系统版本，不能按品牌一概判断 | 目标，未真机验证 |
| 原生 HarmonyOS 5/6 等 | 先用系统浏览器访问 HTTPS 页面 | 不把 APK 兼容服务视为原生支持；安装/PWA/网络能力单独验收 | 浏览器兜底目标 |
| iPhone/iPad | HTTPS 网页，随后 Capacitor iOS 壳 | 原生壳目标 iOS 15+；iOS PWA 安装方式与后台能力有限制 | 目标，未真机验证 |

当前手机路线是远端客户端：手机发送文本到用户配对的电脑 API，电脑仍需开机、
保持服务运行并能通过受控网络到达。电脑睡眠、关机或网络断开时不能推理。
GitHub 保存源码不等于部署服务器；GitHub Pages 也不能运行本项目 Python/Ollama 推理服务。

## Android 8+ 与 Capacitor 8

`minSdkVersion=26` 表示允许安装的最低 Android API 为 26（Android 8.0），
包含 Android 8.0，而不是只允许高于 8.0 的版本。
不表示只使用 API 26 编译，也不代表支持所有厂商固件。
`compileSdk` / `targetSdk` 分别控制编译 API 与系统行为/商店要求，必须单独维护。
[Android uses-sdk](https://developer.android.com/guide/topics/manifest/uses-sdk-element.html)

Capacitor 8 官方基线支持 API 24+，因此选择产品 minSDK 26 是可行的收窄；
其官方升级要求包括 Node 22+、Android Studio Otter 2025.2.1+、compile/target 36，
以及 iOS 15+ / Xcode 26+。构建时仍须核对每个插件的最低要求和商店最新政策。
[Capacitor Android](https://capacitorjs.com/docs/android)、
[Capacitor 8 升级指南](https://capacitorjs.com/docs/updating/8-0)、
[Google Play target API 要求](https://developer.android.com/google/play/requirements/target-sdk)

APK 必须签名；正式分发不能复用调试密钥。签名私钥应独立备份并保存在受控的秘密存储中，
使用 Play 分发时再决定 App Signing 与上传密钥策略。
[Android 应用签名](https://developer.android.com/studio/publish/app-signing)

## 华为：不能将 Android 兼容与原生鸿蒙混为一谈

华为官方说明，HarmonyOS 5+ 的部分 APK 可通过卓易通/出境易等兼容服务使用；
这不意味着本项目 APK 能直接作为原生鸿蒙应用安装，也不意味着所有插件都可用。
必须区分旧版支持 Android 应用的系统、兼容服务和原生鸿蒙应用。
[华为官方 APK 兼容说明](https://consumer.huawei.com/cn/support/content/zh-cn16061787/)

若后续需要原生鸿蒙，应单独评估 ArkTS/ArkUI、DevEco Studio、ArkWeb 与华为分发流程。
第一阶段可复用网页交互，但不能未经实测承诺 PWA 安装、后台录音或私网 VPN 兼容。
[华为应用规划](https://developer.huawei.com/consumer/cn/app/planning)、
[ArkWeb 概览](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/web-component-overview)

私人访问方案也需核对设备：例如 Tailscale 的官方客户端支持列表不能直接当成原生鸿蒙承诺。
没有可用的私网客户端时，先使用可达的受控 HTTPS 浏览器入口，不能直接暴露 Ollama 端口。
[Tailscale 官方安装平台](https://tailscale.com/docs/install)

## iOS 与 PWA 的明确限制

Capacitor iOS 构建、签名和设备调试需要受支持的 macOS/Xcode 环境。
Apple 免费 Personal Team 可用于个人设备测试，但配置文件有短期限制；
TestFlight/App Store 等分发需要 Apple Developer Program 及相应审核。
[Apple 会员能力比较](https://developer.apple.com/support/compare-memberships/)

iOS 网页可由用户添加到主屏幕；Web Push 对主屏幕 Web App 从 iOS/iPadOS 16.4 开始支持，
所以“iOS 15 能运行客户端”不等于“iOS 15 支持全部 PWA 能力”。
浏览器安装入口、存储回收、后台挂起和声音策略依平台而异。
[WebKit 主屏幕应用与推送](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)

未来麦克风采集需要安全上下文（通常 HTTPS）与用户权限；手机访问电脑的普通局域网 HTTP
不是手机本机的 localhost。连续后台监听、系统悬浮宠物、跨应用取词、自动读剪贴板不能用
“网页/PWA 已安装”来承诺；这类能力要单独设计原生权限与明确的用户控制。
[getUserMedia 安全上下文](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

## 离线模型是独立评估，不降低手机系统门槛来替代

第一阶段手机不下载 Qwen 权重。若需要完全离线，应另建可替换的设备端推理适配：
检查 CPU/ABI、可用 RAM、模型量化大小、上下文峰值内存、首字延迟、功耗与温度。
不能仅按“8 GB 手机”或“支持 Android 8”保证 4B 模型体验。
例如 llama.cpp 官方 Android 文档当前有 API 28 的构建示例；它是示例约束，
既不能证明 API 26 一定不可行，也不能证明 API 26 已被本项目验证。
[llama.cpp Android 文档](https://github.com/ggml-org/llama.cpp/blob/master/docs/android.md)

## 为什么暂不承诺覆盖 90% 手机

minSDK 只是安装下限；实际覆盖还取决于地区设备分布、Android WebView/Safari 版本、
JavaScript/CSS API、CPU 架构、厂商后台策略、麦克风权限、网络和分发渠道。
框架宣传的市场覆盖比例不能直接转化为本项目的兼容率。

跨平台优先共享会话式文本界面和受控 API 协议，而不是直接复用 Windows 宿主能力。
目前桌面托盘、全局快捷键与置顶窗口是 Tauri Windows 功能，不能推导出手机能够
常驻悬浮、锁屏监听或绕过系统权限。Android、iOS 和原生鸿蒙必须分别验收这些能力。

进入移动端验收前需要用户提供：

- 至少一台小米、一台华为及一台 iPhone 的完整型号与系统版本。
- Android/Harmony 浏览器和 WebView 版本（如可查看），内存与剩余存储。
- 使用场景：同一局域网、外网私人访问或完全离线；是否需要锁屏后连续语音。
- 是否有可用于 iOS 构建和真机调试的 Mac，以及预期分发渠道。

推荐顺序：私人 HTTPS 文本/PWA → Windows 文字宠物 → Android/iOS 包装与真机测试
→ 按住说话 → 连续双向语音。原生鸿蒙与设备端离线模型分别评估，不阻塞文本版。
