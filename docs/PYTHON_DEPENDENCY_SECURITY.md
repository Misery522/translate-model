# Python 与网页依赖安全复验

日期：2026-10-08。基线：`049a86e0d2cfde20049316d60181c539a7991b2d`。

## 修复范围

- Python 锁仅将 `uv.lock` 中的 urllib3 `2.7.0` 定向更新为 `2.8.0`。
- 102 个锁条目逐项比较，只有 urllib3 的 `version`、`sdist`、`wheels` 改变；
  没有更新 Gradio、LangChain、Ollama、Rust 或其他直接核心依赖。
- 随后补齐主分支既有的两项网页间接依赖：`brace-expansion 2.1.4→2.1.7`
  和 `source-map-js 1.2.1→1.2.2`。`web/package-lock.json` 仅这两个条目的
  `version`、`resolved`、`integrity` 六行变化，与已验证的 PWA 修补一致；
  未运行全量 `npm audit fix`，未变更网页直接依赖。
- 未修改 TLS 验证、应用代码、全局配置、模型、活动服务及其虚拟环境。
  验证使用独立环境；未向外部服务发送原文、译文或凭据。

urllib3 2.8.0 于 2026-09-15 发布，修复 HTTPS 代理 TLS 配置隔离、
分块响应尺寸行无界缓冲和分块 Deflate 解码死循环三类问题。
对应最新 CI 报告中的 `PYSEC-2026-4177`、`PYSEC-2026-4176`、
`PYSEC-2026-4175`，不添加审计忽略项。
[官方发行说明](https://github.com/urllib3/urllib3/releases/tag/2.8.0)。

## 兼容性与网络边界

- PyPI 标明该版本要求 Python `>=3.10`，覆盖项目声明的 `>=3.11,<3.15`。
- 解析器完成全项目锁定依赖求解；独立环境中 Requests `2.34.2` 的活跃
  urllib3 约束为 `>=1.26,<3`，接受 `2.8.0`。
- Hugging Face Hub 的 `testing`、`all`、`dev` 可选 extras 含 `<2.0` 约束，
  本项目没有启用这些 extras，不能把它们误报为当前运行环境冲突。
- 应用没有直接配置 urllib3 的 `ProxyManager` 或 HTTPS 代理 TLS 覆盖参数；
  Ollama SDK 客户端继续使用回环地址、`trust_env=False` 和禁止重定向。
  启动诊断使用 Python 标准库，未被此锁更新替换。
- 依据代码与官方修复说明，当前本地推理路径无需改动。此判断不是企业
  HTTPS 转发代理的实网验收；将来新增此功能时，需要独立配置并验证代理
  `proxy_ssl_context`、代理身份和目标站点身份，不能关闭证书验证。
  [官方安全公告](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77)。

## 产物完整性

从 PyPI 官方 JSON 读取 URL 与摘要，再实际下载两个发布产物并计算 SHA256，
同时核对大小和锁文件；均一致。
[PyPI 2.8.0 元数据](https://pypi.org/pypi/urllib3/2.8.0/json)。

```text
urllib3-2.8.0-py3-none-any.whl / 135717 bytes
0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3

urllib3-2.8.0.tar.gz / 458972 bytes
63bf2ead4c879426ebf22ef2a781eeb4aa3b4ae798a0435506f8687fd5bb9b63

uv.lock
0543fdd22feea42541367815cb26c0b22ab50a44c5ca209f89db04c6615edec5
```

## 已通过与待完成

本机独立环境：Python `3.14.7`，按锁安装 dev 和 audit 依赖组。

- 非 Ollama 单元测试：`426 passed, 20 deselected`，耗时 `20.67s`。
  设有 60 秒硬上限，超时只终止自己启动的测试进程树。
- Ruff、`uv pip check`（100 个已安装包）和 OpenAPI 漂移检查通过。
- `git diff --check` 和上述精确锁条目、活跃约束、产物哈希校验通过。
- 存在一项既有 Starlette/AnyIO 弃用警告，未伪装为零警告测试。
- 本轮未运行真实 Ollama 模型测试，不以这些单元测试代替模型或手机验收。

Python 锁修补提交 `4be101356f22adca341e2c877e113037d02eec1b` 的
[新鲜 GitHub CI](https://github.com/Misery522/translate-model/actions/runs/37771197263)
已通过 **Dependency audit**，运行锁定 audit 环境及常规
`pip-audit --local --skip-editable --progress-spinner off`。
本地审计启动曾被执行层策略拒绝，未产生结果，也未绕过或重试；上述
通过结论来自该提交的 CI，不是本地执行结果。

同次 CI 的 **Private web client** 揭示主分支原有的两项 npm 依赖问题，
对应 `GHSA-q2hr-2g5m-vwhr`、`GHSA-qhr7-859c-m2p7`、
`GHSA-6j4f-fj2g-mc7p`、`GHSA-68fv-2mgg-jv7q`；本轮已按上述六行修补
定向补齐，不将 Python 审计通过误记为整次 CI 成功。

网页补齐后，在本工作树独立安装并验证（Node `24.18.1`、npm `11.16.0`）：

- `npm --prefix web ci --ignore-scripts --no-audit` 按锁安装成功。
- 73 项网页测试通过，耗时 `14.39s`，沿用脚本 60 秒硬上限。
- 格式检查、TypeScript 类型检查和生产构建通过。
- 新鲜 `npm --prefix web audit --audit-level=moderate`：0 项漏洞。
- 精确 JSON 比对确认只有上述两个锁条目的三个字段变化，直接依赖不变；
  `git diff --check` 通过。

包含网页修补的下一次提交仍需重新通过整套 GitHub CI；跨平台测试和发行
门禁以对应提交为准，不能复用旧提交的绿灯。

该记录只说明定向依赖修复，不授权合并、发布或签名。
