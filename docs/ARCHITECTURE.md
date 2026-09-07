# 核心服务架构

## M1 边界

```text
agent.py (Gradio)
  → yijing.service.TranslationService
    → InferenceProvider / OllamaProvider
      → yijing.workflow.TranslationWorkflow
        → yijing.translation.Translator
    → GlossaryRepository / yijing.glossary.GlossaryStore
```

`TranslationService.run(AgentRequest)` 是 UI 和后续 API 共用的入口，返回
`AgentResult`。服务不依赖 Gradio、不绑定 HTTP，不执行用户提供的代码或命令。
模型只能进入原有白名单流程；本次服务化不改变模型提示、格式保护或 AST 校验。

服务实例串行执行整轮工作流。取得执行权后，通过词库仓储建立本轮深拷贝快照；
推理期间保存的新词条从下一轮开始生效。快照在正常返回或异常后清除。
工作流和模型客户端惰性创建并复用，不逐轮创建 HTTP 客户端。

词库读取和保存使用独立锁；该锁仅保证单进程服务实例内的线程安全，不是跨进程锁。
后续 API 模式必须统一词库写入口，不能同时让独立 Gradio 进程编辑同一词库。
服务没有翻译历史存储。已知业务异常保持类型，未知异常映射为固定、脱敏的消息。

## 目录与入口

核心位于 `yijing/`；`agent.py` 保留原启动方式，`smoke_model.py` 保留验收入口。
源码运行仍使用项目 `data/`，wheel 安装使用当前用户数据目录；
`YIJING_DATA_DIR` 显式配置优先。不再提供旧扁平模块的重复兼容实现。

## 验证边界

M1 新增 41 项服务测试，覆盖串行请求、词库快照、客户端复用、异常脱敏、协议替身和
无 Gradio 导入。迁包后全部 371 项非模型回归通过。真实模型验收与发布 CI 的结果
记录在对应 PR；普通测试不触发 Ollama、不下载模型。

M2 的认证 API、M3 宠物和后续语音／手机离线推理并非 M1 已交付能力。
