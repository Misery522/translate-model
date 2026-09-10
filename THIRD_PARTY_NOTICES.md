# 第三方依赖与模型许可

本项目源码按 Apache-2.0 发布。以下依赖通过包管理器安装，不包含在源码发行包中；
各依赖保留自身版权和许可。模型权重不属于本仓库，不随源码、wheel 或安装包发布。

| 直接运行依赖 | 本次基线版本 | 上游许可 | 上游 |
| --- | --- | --- | --- |
| Gradio | 6.26.0 | Apache-2.0 | https://github.com/gradio-app/gradio |
| LangChain | 1.3.18 | MIT | https://github.com/langchain-ai/langchain |
| langchain-ollama | 1.1.0 | MIT | https://github.com/langchain-ai/langchain |
| LangGraph | 1.2.11 | MIT | https://github.com/langchain-ai/langgraph |
| LangSmith SDK | 以 uv.lock 为准 | MIT | https://github.com/langchain-ai/langsmith-sdk |
| Pydantic | 以 uv.lock 为准 | MIT | https://github.com/pydantic/pydantic |
| platformdirs | 以 uv.lock 为准 | MIT | https://github.com/tox-dev/platformdirs |
| FastAPI | 0.141.1 | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | 0.52.4 | BSD-3-Clause | https://github.com/encode/uvicorn |

许可标识已核对安装包中的 `License-Expression` 或 `License` 元数据；完整条文请查阅
对应版本安装包的 `licenses` 目录和上游 LICENSE。完整的传递依赖版本、来源及哈希
记录在 `uv.lock`；发布验证生成 CycloneDX SBOM，避免把本表误认为全部传递依赖清单。

## 会话式网页

`web/package-lock.json` 固定前端依赖。React 与 react-dom 为 19.2.8，均采用 MIT；
生产构建还包含它们使用的 scheduler。构建流程从安装包中收集上述运行时的完整
LICENSE 文本，生成 `web/dist/THIRD_PARTY_LICENSES.txt`；分发构建产物时必须一并保留。
前端使用系统字体和项目原创 SVG 角色，没有下载第三方宠物图片或网络字体。
Vite、TypeScript、Vitest 等为构建和测试工具，不等同于已内嵌的运行时列表。

## 外部运行时及模型

- Ollama 为用户独立安装的运行时。使用前查看对应版本的
  [上游许可](https://github.com/ollama/ollama/blob/main/LICENSE)。
- `qwen3.5:4b` 为用户独立下载的模型，使用前查看
  [Qwen3.5-4B 模型许可](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE)
  和模型卡。Ollama 标签更新可能指向不同内容，集成验收应记录实际模型 digest。
- 后续 ASR、TTS、宠物形象、字体和端侧模型必须分别审核具体下载产物的许可，
  不能用运行库许可代替模型或素材许可。

## 发布边界

本次源码发行没有内嵌第三方二进制和模型。未来若发布自包含桌面或移动安装包，
必须随包保留其中所有第三方版权声明和完整许可，并重新审查传递依赖、模型、
字体与素材的再分发条件。SBOM 是清单，不代替许可证文本。
