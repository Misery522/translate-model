# 译境 Windows 文字宠物宿主（M3 alpha）

这是复用 `web/dist` 的 Tauri 2 宿主，不是新的推理引擎，也不包含模型。
宠物视图由共用 React 前端的 `?view=pet` 路由提供。
当前阶段是可审查的源码与配置；不能把静态检查通过称为已完成 Windows 安装包验收。
本轮 CI 只验证源码，不构建或上传 NSIS 安装包。完整许可再分发审查、签名与真机验收
尚未完成，当前不得作为本项目可分发安装包发布。

## 功能与安全边界

- 360×540 的置顶小窗口；标题栏拖动由前端明确调用 `startDragging()`。
- 托盘提供打开、隐藏、退出；关闭窗口只是隐藏，退出必须从托盘执行。
  点击退出先同步关闭新命令入口，重复点击不会启动第二轮撤销；
  退出请求最多等待三秒尝试撤销远端凭据，再清除内存并关闭。网络失败或强制结束进程时，
  远端可能仍执行已提交任务，需依靠任务超时、结果 TTL 和认证 TTL 收尾。
- 固定 `Ctrl+Shift+T` 唤起；如果与其他软件冲突，状态返回 `shortcut_available=false`，仍可使用托盘。
- 只加载打包在应用内的前端，禁止远端页面导航、新窗口和 iframe。
- 只有 `main` 的本地 capability 拥有三个业务命令与拖动/隐藏权限。
  没有 Shell、文件系统、HTTP 插件、日志插件、自动剪贴板、自动启动或更新器权限。
- 只允许用户明确配置的 HTTPS origin，或 `http://127.0.0.1:端口` / `http://localhost:端口`。
  本机开发端口必须在 1024–65535；不接受用户名、密码、子路径、查询或片段。
  远端必须使用证书可信的 HTTPS，不能关闭证书验证来连接。
- 原生 HTTP 客户端不继承代理，不跟随重定向，不自动重试，不启用 Cookie 存储。
  普通请求总超时 15 秒、连接超时 5 秒，退出/撤销请求总超时 3 秒；返回正文最多 2 MiB。
- Bearer 仅由 Rust 内存保存；配对响应中的令牌不会返回 JavaScript、写入磁盘或打印。
  HTTP 头标记为敏感；部分内存副本用 `Zeroizing` 尽力清除，但不承诺抵御操作系统内存转储。
- 修改服务地址或重新配对时清除旧 token，递增连接代次；迟到结果不能恢复旧认证。
  用户退出后必须重新配置并配对。隐藏不会退出，因此不会丢失当前配对。
- 此桥不保存原文和译文。用户选定远端地址后，翻译文本会发送到该地址，
  不是“手机独立离线推理”。不要配置不可信的第三方服务。

## 前端桥合同

前端安装并固定 `@tauri-apps/api`，使用 `@tauri-apps/api/core` 的 `invoke`；
不要依赖 `window.__TAURI__`，不要在浏览器存储 Bearer。

```ts
const status = await invoke('configure_backend', { origin: selectedOrigin });
// { origin: string|null, paired: boolean, generation: number, shortcut_available: boolean }
const current = await invoke('backend_status');

const reply = await invoke('api_request', {
  request: { operation: 'pair', code: pairingCode, device_name: '译境桌面' },
});
// { status: 201, body: DeviceAuth }，body 不含 access_token 或 token_type
```

`configure_backend` 必须绑定明确的用户保存/确认动作，不得根据模型输出、二维码文本或 URL 自动切换地址。
切换之前先清理旧工作会话；重配不会自动撤销服务端旧设备凭据，旧凭据由退出接口或服务端 TTL 失效。

业务命令 `request.operation` 只允许以下值，额外属性也会被拒绝：

| operation | 其他参数 | 后端固定路由 |
| --- | --- | --- |
| health | 无 | GET `/api/v1/health` |
| pair | code, device_name | POST `/api/v1/pair/exchange`，强制 bearer |
| auth / logout | 无 | GET / DELETE `/api/v1/auth/session` |
| capabilities | 无 | GET `/api/v1/capabilities` |
| create_session | 无 | POST `/api/v1/sessions` |
| delete_session | session_id | DELETE `/api/v1/sessions/{UUID}` |
| translate | session_id, client_request_id, request | POST `/api/v1/translations` |
| job / cancel | job_id | GET 任务 / POST 任务的 `/cancel` |
| glossary | 无 | GET `/api/v1/glossary` |

`request` 翻译对象与公共 API 的 `AgentRequest` 一致；所有字段都要提交，文本最多 4000 个 Unicode 字符。
首版不开放词库写入桥；它不是任意 URL、method、headers、path 代理。
成功结果为 `{status, body}`，204 的 body 为 null。
错误为固定的 `{code, message, retryable, status}`，不转发服务器错误正文。
401 使用 `PAIRING_REQUIRED`；连接代次过期使用 `STALE_OPERATION`。
响应正文读取中断使用 `NETWORK_UNCONFIRMED`，不能因已收到 202 响应头就假定任务 ID 已收到，
也不能把网络中断当作“任务肯定没有创建”。对于状态或结构异常的翻译响应，前端同样必须
保留未确认状态，并通过原工作会话停止/查询；不能自动产生新的请求 ID 重发。

取消前端 Promise 不代表服务端任务取消；必须显式调用 `cancel` 或 `delete_session`。
已经发送到旧服务的请求无法撤回，但它不会被改发给新 origin，也不能更新新配对状态。
`logout` 在网络调用前就撤销本地的正常请求能力；网络失败后仅在 Rust 内存保留一份
待撤销令牌，让用户可以重试 Logout。该令牌不能用于翻译，收到 204 或已失效的 401 后销毁。
重新配置、重新配对或退出进程会销毁待撤销令牌；未确认的远端撤销由服务端 TTL 兜底。
界面仍须实施自己的请求代次，防止同一连接上的旧译文覆盖新译文。

## 本地检查与 Windows 构建

截至本次实施，本机有 Node，没有可用的 Cargo、Rust 和 MSVC。
未安装全局工具；已审查并导入 CI 生成的 Cargo.lock 及官方 Rust 格式化结果。
锁文件包含 480 个条目，除本项目外均为带校验和的 crates.io 来源，直接版本与 Cargo.toml 一致。
这不是完整许可证审查；实际 Rust 编译、安全审计、签名和 Windows 真机验收分别记录状态。

不依赖 Rust 的检查，在仓库根目录运行：

```powershell
npm --prefix desktop ci --ignore-scripts
npm --prefix desktop run check
npm --prefix desktop test
```

配置检查同时使用固定版本 CLI 自带的 JSON Schema 和项目最小权限断言，不访问运行中的服务。

Windows 构建环境需要 Rust MSVC 工具链、Visual Studio C++ Build Tools、WebView2，
详见 [Tauri 前置要求](https://v2.tauri.app/start/prerequisites/)。不要为了构建修改现有 Python 环境。

活动工作流位于 [desktop.yml](../.github/workflows/desktop.yml)，静态测试只验证这份实际工作流，
不回退到旧模板。还应将 `Desktop required checks` 纳入受保护分支的
必需检查（或接入现有总门禁），不能只新增一个会失败但不阻止合并的工作流。
本次源码变更没有修改仓库分支保护设置。

工作流固定 `windows-2022`、Node `24.18.1`、Rust `1.98.0` MSVC 工具链。
官方 Actions 均固定完整 commit SHA，`persist-credentials=false`、`contents: read`，没有签名秘密、
发布写权限、工作区整体上传或依赖缓存。临时 runner 安装工具链不会修改用户电脑环境。

**没有已提交的 Cargo.lock 时**，只生成锁文件和真实 rustfmt 格式化补丁供审查，
跳过 npm/Rust 测试与 Rust 安全审计；本阶段无论是否有锁文件都不构建安装包，
最终 `Desktop required checks` 必须失败。此时工作流产物不是已通过构建的源码/安装包。
在对应运行的 Artifacts 中下载：

```text
desktop-cargo-lock-review-<run_id>-<run_attempt>
├── Cargo.lock
└── rustfmt.patch
```

取出 `Cargo.lock`，放到 `desktop/src-tauri/Cargo.lock`；审查注册表来源、版本、校验和、
不期望的 Git/path 依赖及许可证后，通过普通 PR 提交，不能直接覆盖受保护主分支。
锁文件需要与这次运行的提交 SHA、`Cargo.toml` 一致；不能复用来源不明或过期运行的产物。
该审查产物保留 7 天；上传产物不会自动提交锁文件或源码。

`rustfmt.patch` 来自固定 Rust 版本实际执行 `cargo fmt --all` 后的限定 `git diff`，
使用无 BOM 的 UTF-8；仅允许以下四个项目源码路径：

- `desktop/src-tauri/build.rs`
- `desktop/src-tauri/src/main.rs`
- `desktop/src-tauri/src/bridge.rs`
- `desktop/src-tauri/src/bridge/tests.rs`

如果格式化触及其他源码，引导阶段直接失败，不扩展上传范围。产物不包含完整工作区、
`target` 或其他源码副本。先人工确认补丁仅有上述路径的格式调整，再在对应提交的仓库根目录
运行 `git apply --check <解压目录>/rustfmt.patch`，检查通过后才应用并审查差异；
补丁为空表示无需格式调整，不必执行 `git apply`。CI 不自动应用或提交本地开发者的补丁。

**已有锁文件时**，先安装固定 npm 依赖，运行前端测试/构建、图标/配置测试、npm audit，
再进行 Rust 安全审计、格式检查、锁定编译与测试。
`cargo-audit 0.22.2` 通过 `--locked --no-default-features` 安装到 runner 临时私有工具根，
不覆盖预装工具，不修改用户电脑。工具安装上限 15 分钟，审计上限 5 分钟，
与 Rust 编译和 60 秒测试执行期限分开计算。

审计使用明确的已提交锁文件与新的临时 RustSec 数据库：

```powershell
# 以下由 CI 在临时 runner 执行，不需要在用户电脑全局安装工具。
$toolRoot = Join-Path $env:RUNNER_TEMP 'yijing-rust-audit-tools'
$lockfile = Join-Path $env:GITHUB_WORKSPACE 'desktop/src-tauri/Cargo.lock'
& "$toolRoot/bin/cargo-audit.exe" audit --file $lockfile --deny warnings
```

漏洞、严格警告、审计数据库更新失败都不能忽略。工作流不允许隐式项目/用户 `audit.toml`
降低门禁，不使用忽略漏洞、允许过期数据库或自动修改依赖的参数。
审计成功仅表示当前数据库未发现需阻止的已知问题，不等于完整安全审计或许可审查通过。
其后的源码验证命令等价于：

```powershell
Set-Location desktop/src-tauri
cargo fmt --all -- --check
cargo check --locked
cargo test --locked --no-run
# 上一步完成编译后，脚本仅管理自己启动的测试进程树，硬限 60 秒。
pwsh -NoProfile -File ../scripts/run-rust-tests.ps1
Set-Location ..
node scripts/verify-config.mjs --require-dist --require-lock
```

`desktop/package.json` 仍保留供受控本地开发使用的 `npm run build`，其命令固定为
`tauri build --bundles nsis --no-sign --ci -- --locked`；本轮 CI 不调用它。
最后的 `--locked` 是 Cargo 参数，前面的 `--` 不可省略。能在本地生成文件不代表可再分发。
首次引导可以审查并应用上述真实格式化补丁；已有工具链的开发环境也可直接执行
`cargo fmt --all` 后审查。格式化结果必须随源码提交，有锁阶段仍执行 `fmt --check`，
不得为通过检查删除格式门禁。
构建进程需要独立的合理上限（例如 20 分钟），不要把首次依赖编译误当成“60 秒单元测试”。
无安装工具链权限时只做只读检查，不下载便携工具链来绕过限制。

## 安装包分发的后续独立门禁

当前不生成安装包审查通过标记，也不创建空许可清单代替审查。
后续需要依据已审查 Cargo.lock 收集 Rust 直接与传递依赖的完整许可证、版权文本和 NOTICE，
不能只附 React 或 Tauri JavaScript 的许可证。可使用固定 `cargo-about 0.9.2` 的
`--locked --fail` 生成数据，但还要检查通用文本回退与缺失版权信息；只渲染经过转义的
白名单字段，不公开包含本机源码路径的原始元数据。

完整文本通过验证后，再将明确文件映射到 Tauri `bundle.resources`；生成目录必须受控，
不得用整个工作区或 `target` 通配打包。然后才能另行启用 NSIS 构建、精确安装包的
SHA256 清单及发布审查。校验和不能替代代码签名或可信来源审查。

安装器可能从 Microsoft 下载 WebView2 Bootstrapper，需在安装验收中记录这一行为。
公开分发之前还必须人工验证安装、卸载、托盘、快捷键冲突、缩放、多屏、配对、
重定向拒绝、改地址、超时、清空与退出；经批准后再配置代码签名。
不要把证书私钥或签名密码放入仓库，也不要通过关闭 SmartScreen 作为发布流程。

## 版本与官方依据

- Tauri `2.11.5`、tauri-build `2.6.3`：
  [Tauri crate](https://docs.rs/tauri/latest/tauri/)、
  [命令 ACL 生成](https://docs.rs/tauri-build/latest/tauri_build/struct.AppManifest.html)。
- CLI `2.11.4`：[@tauri-apps/cli](https://www.npmjs.com/package/@tauri-apps/cli)。
- global-shortcut `2.3.2`：
  [插件 crate](https://docs.rs/tauri-plugin-global-shortcut/latest/tauri_plugin_global_shortcut/)、
  [官方快捷键指南](https://v2.tauri.app/plugin/global-shortcut/)。
- reqwest `0.13.4`：
  [单次请求超时覆盖连接及正文读取](https://docs.rs/reqwest/0.13.4/reqwest/struct.RequestBuilder.html#method.timeout)、
  [禁止重试](https://docs.rs/reqwest/latest/reqwest/retry/fn.never.html)。
- [cargo-audit 0.22.2 固定版本](https://github.com/rustsec/rustsec/blob/cargo-audit/v0.22.2/cargo-audit/Cargo.toml)、
  [明确锁文件参数避免自动生成](https://github.com/rustsec/rustsec/blob/cargo-audit/v0.22.2/cargo-audit/src/lockfile.rs)。
- 后续许可方案依据：
  [cargo-about 0.9.2 文本回退与完整文本生成](https://github.com/EmbarkStudios/cargo-about/blob/0.9.2/src/generate.rs)、
  [Tauri 显式资源打包](https://v2.tauri.app/develop/resources/)。
- CI 固定 Actions：
  [checkout v4.2.2](https://github.com/actions/checkout/commit/11bd71901bbe5b1630ceea73d27597364c9af683)、
  [setup-node v4.4.0](https://github.com/actions/setup-node/commit/49933ea5288caeca8642d1e84afbd3f7d6820020)、
  [upload-artifact v4.6.2](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02)。
- [Windows 2022 官方 runner 工具清单](https://github.com/actions/runner-images/blob/main/images/windows/Windows2022-Readme.md)
  与 [Cargo 锁文件生成规则](https://doc.rust-lang.org/cargo/commands/cargo-generate-lockfile.html)。

移动端与原生鸿蒙的目标、限制和真机清单见 [客户端兼容性](../docs/CLIENT_COMPATIBILITY.md)。
