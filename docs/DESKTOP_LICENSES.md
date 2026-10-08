# 桌面许可证收口与发布门禁

更新：2026-10-09。此工作只在 `chore/desktop-license-compliance` 隔离树实施，
不替换正在试用的桌面程序、不更新依赖、不构建或分发安装包。

## 已完成与尚未完成

- 已从固定 cargo-about 0.9.2、锁定原包和 Windows 实际依赖图采集 **267 个
  第三方 crate、476 份材料**；材料包含完整法律文件、额外版权/NOTICE 和内嵌
  源码许可，并非只导出 SPDX 表达式。
- 30 个历史自动回退项的补材按原清单和文件 SHA256 精确复用，不再次下载或用
  通用 MIT 占位版权替换。锁文件、来源和版本变化时必须重新审查。
- 所有条目仍为 `requires-human-review`，`compliance_review_passed=false`。
  **材料采集成功不等于法律审查通过，也不解除严格审计或安装包门禁。**
- Rust 许可资源尚未映射到安装包。前端另有完整许可证生成流程，不能以它代替
  Rust 依赖的版权和再分发说明。

## 生成方式

先核验现有工具：Rust/Cargo 1.98.0、cargo-about 0.9.2。不全局安装工具。
`--version` 只检查工具声称的版本，不能证明二进制来源。调用前须独立依据官方
发布来源和可信摘要核对外部 EXE SHA256；本机已核验 cargo-about EXE 为
`7923ca2d7082c609f27c2fc599366c7b6157f58164b278c8d984653022b8969a`。
固定 Rust/Cargo、完整原包缓存与可信工具路径是本脚本的外部前提，不由版本字符串保证。
在本工作树执行，路径变量替换为已经核验的工具和历史补材清单：

```powershell
python scripts/generate_desktop_notices.py `
  --cargo-about $cargoAboutExecutable `
  --cargo $cargoExecutable `
  --fallback-manifest $verifiedFallbackManifest `
  --out artifacts/desktop-license-review-new
```

脚本仅允许输出到本项目 `artifacts` 内的新目录，拒绝覆盖旧材料。
它复用 `cargo-about generate --locked --offline --fail`，并逐项比对
`cargo tree --locked --offline --target x86_64-pc-windows-msvc --edges normal,build`。
Windows 下使用 cargo-about 正式 `--output-file` 参数，而不是重定向其 stdout。
每个工具调用限时 60 秒；非零退出和超时均保持失败。

输出包括：

- `manifest.json`：名称、版本、来源、SHA256、候选许可选择与待审查事项。
- 每份原始材料和 `REVIEW_MATERIALS.txt`：保留实际法律全文和附加通知。
- 独立忽略目录中的 cargo-about 原始 JSON：只供私有诊断，不公开提交或打包。

公开候选清单不含 Cargo registry 绝对路径、`manifest_path`、`source_path` 或
完整 Cargo metadata。工具不会执行原包代码，tar 成员只读，不解压到任意路径。
原包校验和、补材哈希、实际图、UTF-8 或输出边界不符时均停止生成。
Windows 的文件及目录大小写别名、尾随点/空格也在写盘前拒绝；即使别名原文
相同也不允许悄然合并为同一个文件。

### 当前可复现范围

本次是**本机固定输入的重复采集验证**，不是全新 clone 的完整端到端可复现证明。
30 项固定补材清单和原文目前仍在本机忽略目录，未由仓库自动重新取得；外部工具
与已锁定 `.crate` 缓存同样需要先准备并核验。全新 clone 缺少这些输入时应明确失败。
后续必须另外设计经审查的公开来源准备步骤，才能承诺其他设备完整再现许可材料。

## 必须继续人工审查的材料

1. `siphasher 1.0.3`：原 `COPYING` 文件只有两个真实作者版权
   及授权链接。现保留原字节，并附 [Apache 官方完整条款](https://www.apache.org/licenses/LICENSE-2.0.txt)，
   候选选择 Apache-2.0；不改写作者，也不替换 Apache 附录的示例占位文字。
2. `dunce`、`cargo_toml`、`brotli-decompressor`：分别提议选原包真实提供的
   CC0、Apache、BSD 分支；候选不等于已经审批。
3. `aws-lc-rs` / `aws-lc-sys` 与 `dpi`：保留原始 AND/OR 组合和额外 fiat/libm
   材料，不能简化成单一通用 ISC、BSD 或 Apache 文本。
4. 额外版权/授权文件：包括 Tauri 系的 `LICENSE.spdx`、`utf8_iter/COPYRIGHT`、
   `unicode-segmentation/COPYRIGHT`、COPYING 选择声明和第三方许可证。
   测试材料与真正分发内容要分别判定，不因收集到第三方条款就盲目更改运行时 SPDX。
5. 根许可证由发布提交补齐的五个包：仍需确认 workspace 根许可对各子包的适用关系。

## MPL 的源码获取义务

已附 [Mozilla 官方 MPL 2.0 全文](https://www.mozilla.org/en-US/MPL/2.0/)，并为
每个 crate 保留精确版本源码包 URL 与 package checksum。可执行形式分发时须
按实际覆盖内容提供源码获取说明，不能只放 SPDX 标识。[Mozilla FAQ Q8](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)

离线依赖图用途为：

- `cssparser 0.37.0`、`cssparser-macros 0.7.1`、`dtoa-short 0.3.5`、
  `selectors 0.38.0`：构建或过程宏路径。
- `option-ext 0.2.0`：普通图候选，经 `dirs-sys → dirs → tauri` 引入。

图用途不证明最终 LTO 后的内嵌代码范围，也不能自动断言过程宏生成代码无义务。
此处是分发审查清单，不是替代专业法律意见的合规保证。

## 最新严格审计仍未通过

2026-10-09 用保留的 cargo-audit 0.22.2 创建新的官方 RustSec 数据库，加载
1295 项公告、检查 467 项锁依赖；数据库提交：
`550efd3d587a29b2e2c2b21b17a440da4fede999`，
时间 `2026-10-08T16:47:14+02:00`。严格 `--deny warnings` 退出码 **1**：

- `glib 0.18.5`：RUSTSEC-2024-0429，Unsound。涉及特定迭代器未定义行为，
  修复版本为 >=0.20.0，不应描述成普通的停止维护提醒。
  [官方公告](https://rustsec.org/advisories/RUSTSEC-2024-0429.html)
- `proc-macro-error 1.0.4`：RUSTSEC-2024-0370，停止维护、无补丁版本；
  不等同于已确认可利用的攻击漏洞。
  [官方公告](https://rustsec.org/advisories/RUSTSEC-2024-0370.html)

`--target all` 离线反向图确认路径包括：

```text
tauri 2.12.1 → gtk 0.18.2 → glib 0.18.5
gtk 0.18.2 → gtk3-macros 0.18.2 → proc-macro-error 1.0.4
glib 0.18.5 → glib-macros 0.18.5 → proc-macro-error 1.0.4
```

Windows 实际图不含这两个包，不据此放宽全锁文件审计。等待稳定上游依赖线
消除告警；不忽略公告、不过滤平台、不使用 Alpha 或私有补丁绕过门禁。
本轮 Cargo.lock SHA256 前后均为
`34da087047c32c50ebdaf603e99a2715787aab169d3f40a13d4f196413010a84`。

## 安装包前的完成条件

逐项完成材料人工审查、确定实际分发范围与许可分支、保留完整法律文件和通知，
再设计明确的资源映射及随包可读入口。仍需严格审计零警告、完整测试、稳定构建
工具链，以及用户单独确认内部安装包构建、安装/卸载、签名和公开发布。
当前不设置任何“已审批”开关，也不改变原有安装器门禁。

## 本机固定输入的回归与材料一致性记录

2026-10-09：修补 Windows 路径别名后 53 项定向测试通过；隔离树普通 Python 全套为 **475 passed、
21 个 Ollama 集成用例按既有标记不在普通测试中执行**，耗时 9.11 秒，外层
硬限时 60 秒。另有一条现有 Starlette/AnyIO 弃用提示，不在本次许可证修改范围。
全树 Ruff 和 `git diff --check` 通过；没有运行 Rust 编译、UI 或安装验收。

Windows 别名拒绝检查前后的真实采集均为 267 项/476 份；476 份材料逐项
SHA256 校验零差异，所有 267 项仍待人工审查。本机固定输入输出哈希相同：

- `manifest.json`：`de31450393436100815db74b5966c53b4ef58517c08c687551f170c488264b73`
- `REVIEW_MATERIALS.txt`：`391708b485c256b6986c50aba2d57fa9157a7df977fdb1eb9936725f459c5d86`

上述材料只在忽略的 `artifacts` 下；原始 Cargo metadata 不提交、不公开。
