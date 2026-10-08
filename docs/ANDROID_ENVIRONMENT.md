# Android 项目专用构建环境

此文档说明 Windows 开发工具的使用，不是可安装 App 的交付说明。
当前共享客户端协议测试不能代替 Java 宿主、APK 或 Redmi K70 真机验收。

## 固定工具及范围

- PowerShell 7+；脚本使用安全的独立参数列表和精确子进程树终止。
- JDK 21.0.12.1+1，默认 `%LOCALAPPDATA%\Yijing\toolchains\jdk-21.0.12.1+1`。
- Gradle 8.14.3，默认 `%LOCALAPPDATA%\Yijing\toolchains\gradle-8.14.3`。
- SDK，默认 `%LOCALAPPDATA%\Android\Sdk`：Platform 36、Build Tools 36.0.0、
  Command-Line Tools 22.0。固定命令行工具位于 `cmdline-tools\22.0`。
- 产品最低 API 26；不能把已有 SDK 37 或 Studio JBR 25 当成上述固定版本。

`scripts/android-env.ps1` 不负责下载和安装，不修改注册表、全局或父终端
`PATH` / `JAVA_HOME`，不删除缓存、模型或原 Android Native C++ 模板。
系统安装须独立取得授权，下载只能使用官方来源并核验归档校验和。

## 2026-10-08 本机验收记录

经用户独立确认，上述固定工具已安装；JDK、命令行工具与 Gradle 官方归档
SHA256 校验一致。真实 `java`、`javac`、`sdkmanager` 与 Gradle 入口全部通过。
AGP 8.13.0 的独立 Android library Java 编译在英文探针路径成功（13 秒），
输出 major version 65 的 `.class`，真实引用 Android API，没有 APK/AAB。

本地 30 项启动器回归与独立审查通过；完整 456 项非模型 Python 测试通过
（28.57 秒，60 秒硬限），161 项网页测试通过（5.01 秒）。本轮没有重跑
20 项需要模型的测试，也没有进行 Java 原生宿主或手机 App 真机验收。
环境值与受保护关键文件哈希、原模板组合哈希保持一致，试用服务未停止。

工具会报告 sdkmanager 弃用、AGP SDK XML 3/4 版本差异和 Gradle 弃用特性；
这些提醒未阻止本次固定工具编译，不等于已经通过未来 APK、lint、许可或发布门禁。
不为消除提醒无条件升级 AGP/Gradle 或改动现有 Android Studio。

## 使用方法

在仓库根目录的 PowerShell 7 终端运行：

```powershell
./scripts/android-env.ps1 -Mode doctor
./scripts/android-env.ps1 -Mode sdk -ToolArguments @('--list_installed')
./scripts/android-env.ps1 -Mode gradle -ToolArguments @('--version')
```

其他电脑可明确覆盖路径，版本仍须一致；空格无需改写命令字符串：

```powershell
./scripts/android-env.ps1 -Mode doctor `
    -JdkHome 'D:\DeveloperTools\jdk-21.0.12.1+1' `
    -SdkRoot 'D:\DeveloperTools\AndroidSdk' `
    -GradleHome 'D:\DeveloperTools\gradle-8.14.3' `
    -GradleUserHome 'D:\DeveloperCaches\yijing-gradle'
```

启动器仅在自己的子进程中设置 `JAVA_HOME`、`ANDROID_HOME`、
`ANDROID_SDK_ROOT` 和 `GRADLE_USER_HOME`。默认 Gradle 缓存是仓库忽略的
`artifacts/android-gradle-user-home`，不会切换其他项目的构建缓存。
Java 直接启动 SDK/Gradle 入口，不调用 `cmd`、`Invoke-Expression` 或拼接 Shell。
参数里的空格、分号、引号与中文按独立参数传入。
**安全传参不等于第三方编译支持中文工程根目录**：真实 AGP 8.13.0 在 Windows
拒绝非 ASCII 项目路径。`doctor` 可以从当前中文仓库运行，正式 Android 原生工程
应在纯英文路径的 Git worktree 中开发，不能用 `android.overridePathCheck` 绕过。
不复制零散源文件，也不因此搬动、覆盖原 Native C++ 模板。

SDK 默认只列出已安装包，固定稳定通道、SDK 根目录与 HTTPS。
额外安装、删除和许可证操作属于可信开发者的 SDK 管理操作，仍需确认范围；
该脚本不是模型工具桥，不向模型开放这些命令。

Gradle 固定 `--no-daemon`、所选 Java 和缓存；禁止覆盖这些设置。
通过 `-Porg.gradle.java.installations.auto-download=false` 禁止自动下载其他 JDK，
并关闭自动发现其他 JDK。若当前终端存在 `JAVA_TOOL_OPTIONS`、
`JDK_JAVA_OPTIONS` 或 `_JAVA_OPTIONS`，脚本明确拒绝启动，不暗中清除或改变它们。
Gradle 无常驻 daemon 模式仍可能为这次构建创建一次性 JVM，结束时正常释放。

## 验证范围与时间限制

`doctor` 验证本地文件、版本以及四个真实 CLI；缺失时返回明确错误，不自动安装。
它不能单独证明 Android Java 编译成功。环境验收还应在独立、被忽略的 Android
library smoke 项目执行 `compileDebugJavaWithJavac`，检查真实 `.class` 输出：

```powershell
$probeRoot = Join-Path $env:LOCALAPPDATA 'Yijing/environment-probes/android-20261008'
./scripts/android-env.ps1 -Mode gradle -TimeoutSeconds 1200 `
    -ToolArguments @('-p', $probeRoot, 'compileDebugJavaWithJavac')
```

上例探针由独立环境验收步骤创建，路径须全部为 ASCII；若 Windows 用户目录含
非 ASCII 字符，须先选择受控的其他纯英文探针路径，不能直接套用默认目录。
smoke 固定 AGP 8.13.0、compileSDK 36、minSDK 26、Build Tools 36.0.0 和 Java 21；
只编译引用 Android API 的最小 library，不调用 `assemble`、`bundle`、`install`，
不生成或分发 APK，不使用原 Native C++ 模板。

启动器默认命令与输出共享 1200 秒时限，超时返回 124；正常工具退出码原样传递。
终止只针对自己创建、父进程仍存活且可定位的进程树，不按进程名结束其他工具。
终止与排水另有最多 3 秒清理窗口；父进程先退出而后代仍持有输出管道时，
启动器及时关闭读流，不保证回收已经脱离父进程的全部后代，不无限等待 EOF。
单元测试仍使用独立的 60 秒硬上限，首次依赖下载与
编译不计作单元测试。无 SDK 的跨平台 CI 可执行源码及模拟进程测试；
没有 PowerShell 7 时仅跳过需要该运行时的动态测试，不把它当成 Android 环境验收。

## 官方依据

- [Capacitor 8.5.3 Android 模板](https://github.com/ionic-team/capacitor/blob/8.5.3/android-template/variables.gradle)
- [固定 Gradle 模板](https://github.com/ionic-team/capacitor/blob/8.5.3/android-template/gradle/wrapper/gradle-wrapper.properties)
- [Gradle Java 兼容矩阵](https://docs.gradle.org/current/userguide/compatibility.html)
- [SDK 管理工具](https://developer.android.com/tools/sdkmanager)

源码检查和工具就绪、真实 Android 编译、真机验收、公开发布是四个不同门槛。
