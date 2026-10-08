# Android 安装版试用与下一步

更新：2026-10-09。开发顺序由用户调整为 **可安装 Android 文字 App → 真机稳定 → 语音**。
最新工作状态、CI 问题和执行顺序统一记录在[项目动态进度](PROJECT_STATUS.md)。

## 当前实现

- 原生 `Activity` + AndroidX WebKit 1.14.0，仅加载 APK 内置的 React 界面。
- 安装后拥有独立图标和窗口，不需要用夸克或其他浏览器作为 App 载体。
  系统 WebView 仍是绘制组件，须识别为 Chromium 111+ 且支持受限消息桥。
- 私人 HTTPS 精确源、九项翻译操作白名单、Java 内存 Bearer、前后台失效、
  有界任务和网络队列、错误恢复、普通文本/术语/代码注解共用已有 API。
- Android 8.0（API 26）为最低安装条件，compile/target SDK 36。
  这不等于所有 Android 8 设备、华为、原生鸿蒙或 iPhone 已兼容。
- 不申请麦克风/存储/悬浮窗权限，不读取剪贴板，不保存身份或翻译历史。
  复制由用户触发，之后系统剪贴板不属于 App 清理边界。

经授权调整了技术选型：不采用默认注册通用 HTTP/Cookie 能力的 Capacitor，
不修改其私有实现；只使用来源受限的标准 WebMessageListener。
原 Android Native C++ 模板、Ollama 模型、桌面与 PWA 服务不动。

## 开发和构建

在纯英文路径 Git worktree 中打开 `mobile/android`，而不是旧 C++ 模板。
开发分支为 `feat/android-native-host`；
堆叠于 Android 协议/环境基础 `feat/android-client`，不混入桌面审计分支。

```powershell
uv sync --locked --group dev
npm --prefix web ci --ignore-scripts
npm --prefix web test
npm --prefix mobile test
npm --prefix mobile run build
./scripts/android-env.ps1 -Mode gradle -ToolArguments @('-p', 'mobile/android', ':app:assembleDebug', ':app:lintDebug')
```

Java 单测用明确的项目解释器和已核验的 JDK；共享 60 秒截止，不发送真实请求：
下面的 JDK 路径仅为示例，须替换为环境说明中核验过的实际目录。

```powershell
.\.venv\Scripts\python.exe scripts/run-android-unit-tests.py `
  --jdk-home 'C:\Dev\jdk-21'
```

APK 为 `mobile/android/app/build/outputs/apk/debug/app-debug.apk`。
自动使用 Android 调试证书签名，仅供本人内部试用，不是正式签名或发布物。
CI 仅构建和检查，不上传 APK；不提交安装包、密钥、SDK、缓存、模型或私人词库。
校验文件是受信首次下载摘要，不是无漏洞证明或全部作者签名验证。

本机验证记录（2026-10-09）：隔离源码包 476 项 Python 单测通过；共享网页 163 项、
Android 界面 20 项、Java 核心/宿主/模拟 HTTPS 共 127 项通过。Ruff、格式、依赖一致性、
源码包/暂存快照审查、debug 编译和严格 lint 通过；实际 APK 的页面、三份完整许可证、
API 26/36、仅 INTERNET 权限与调试 v2 签名已核验。这些不是手机真机验收。
首次远程构建暴露两份遗漏的 Maven 元数据摘要，已从官方内容核对并补齐；新的空依赖
缓存构建通过。最新远程 CI 的最终状态单独记录在 PR，不用旧成功记录代替。

截至 2026-10-09，PR 事件 CI 的 14 项检查通过，但相同提交的另一轮 push CI
出现 Linux 源码包 PowerShell 探针 10 秒超时，正在定位；不能把一次通过写成所有
检查已稳定。修复及最终同一提交的两类 CI 结果以项目动态进度和 PR 为准。

## 安装与配对（待用户授权和操作）

用户当前选择先查看说明、暂不安装。以下仅为将来操作步骤，须在最新 CI 完整通过并
再次确认手机安装后执行；电脑上的 Android Studio 或构建工具无需安装到手机。

1. 通过 USB 文件传输等受控途径把上述 APK 复制到 Redmi K70，无需先开启 USB 调试。
2. 用户在手机明确允许该次安装来源并安装；只应看到网络权限。
   验收后可以关闭该安装来源授权。不要把 APK 上传公开网盘或 GitHub Release。
3. 打开“译境 · 小译”；确认系统 WebView 未被禁用。若不支持，显示无桥原生错误页，
   不通过忽略安全检查强行使用。
4. 手机 Tailscale 保持在线，填写自己的电脑私人 Serve HTTPS 地址并保存。
   地址不能带路径、查询、凭据、非标准端口；保存相同地址也撤销旧身份和内容。
5. 在运行对应 API 的电脑交互终端输入 `p` 并 Enter，获取新的 12 位、5 分钟有效
   一次性配对码。不要在终端日志、截图或 GitHub 公开配对码。
   若服务由非交互后台启动，需另行授权正常重启为交互服务；不能用过期码绕过配对。
6. 在 App 中配对，先用非敏感文本翻译并确认实际译文。电脑/Ollama/API/私人 Serve
   均需在线；这仍不是手机本地模型。

进入后台、熄屏或退出后会清空身份和内容，返回需新配对。旋转导致 Activity 重建也
可能要求重新配对；第一版不把 Token 放入 Bundle 或长期存储。此行为牺牲便利性保护隐私，
持久设备身份需后续单独设计，不能为了减少配对悄悄保存令牌。
`FLAG_SECURE` 会限制截图和最近任务缩略图；系统/输入法及受信电脑不属于绝对保密保证。
网络取消与注销仅尽力完成；断线或进程被系统杀死后由后端 TTL 回收，不声称模型已经停算。

## 真机验收清单（尚未完成）

- [x] 用户报告 Redmi K70 的 Android 16、HyperOS 3.0.307.0。
- [ ] 登记 System WebView 版本并验证受限桥能力；不能仅凭 Android 版本判断。
- [ ] 安装、图标、启动、返回键、键盘遮挡、转屏和许可页。
- [ ] 正确/错误/过期配对码；401、注销未确认后的首次重配对。
- [ ] 中英日韩、同语种、长文、Markdown、术语与 Python 注解实际结果。
- [ ] 字符计数、复制、停止、重试、清空；清空后迟到结果不恢复。
- [ ] 同地址保存、换地址、前后台/熄屏恢复不泄漏旧身份和文本。
- [ ] Wi-Fi/蜂窝切换、Tailscale断线、电脑离线、后端重启和冷模型加载。
- [ ] 仅网络权限，无表单自动填充保存、备份或额外文件访问。

完整手机验收未完成前，不宣称稳定、全品牌兼容或正式商店版。

## 试用后的项目安排

1. 先完成当前 CI 超时定位和文档收口，准备安装资料；手机继续等待单独安装确认。
2. 授权后完成 Redmi 验收并修复实际问题，经独立 PR 和最新 CI 审查；不自动合并或创建版本。
3. PWA 保留私人回退入口；补蜂窝、主屏幕、熄屏和后端重启验收。
4. Windows 宠物继续 Rust 严格审计、托盘/多屏/DPI、安装/卸载和许可整改；不放宽发布门槛。
5. 明确授权后设计持久设备身份与更便利的后台恢复，再改进文字伙伴及宠物状态反馈。
6. 单独设计录音接口和隐私：按住说话 → 本地 ASR/TTS → 单段翻译 → 连续双向口译。
7. 分别取得华为与 iPhone 真机环境；原生鸿蒙与 Android 兼容层分开判断，iOS 原生构建
   需要 macOS/Xcode。手机离线模型、OCR、授权快捷取词和系统悬浮宠物另行评估。

未经确认不合并 PR、不正式签名、不公开分发、不开放 Funnel/公网/Ollama端口，
不清理原模板或模型，不把尚未验收的能力写成已经交付。

官方依据：[本地 WebView 资源](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content)、
[原生桥安全](https://developer.android.com/privacy-and-security/risks/insecure-webview-native-bridges)、
[固定 WebKit 1.14.0](https://developer.android.com/jetpack/androidx/releases/webkit#1.14.0)。
