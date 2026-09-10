import { useEffect, useRef, useState } from 'react';
import { describeError } from './api';
import { Pet } from './Pet';
import { languages } from './languages';
import type { AgentResult, Options, Turn } from './types';
import { characterCount, useTranslator } from './useTranslator';
import { NativeTranslationApi, normalizeBackendOrigin, type BackendStatus } from './nativeApi';
import { nativeApi, petWindowControls, type PetWindowControls } from './tauriRuntime';
import './pet.css';

function Details({ result }: { result: AgentResult }) {
  return (
    <>
      {(result.annotated_copy || (result.annotations ?? []).length > 0) && (
        <details className="pet-result-details">
          <summary>注释副本与说明</summary>
          {result.annotated_copy && <pre dir="auto">{result.annotated_copy}</pre>}
          {(result.annotations ?? []).map((item, index) => (
            <section key={index}>
              <strong>{item.location || item.kind}</strong>
              <pre dir="auto">{item.source_fragment}</pre>
              <p dir="auto">{item.explanation}</p>
              {item.risk && <p className="pet-warning">{item.risk}</p>}
            </section>
          ))}
          <details>
            <summary>保留的原文</summary>
            <pre dir="auto">{result.preserved_source}</pre>
          </details>
        </details>
      )}
      {(result.warnings ?? []).length > 0 && (
        <details className="pet-result-details pet-warning">
          <summary>使用前请留意</summary>
          <ul>
            {result.warnings!.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
      {(result.applied_terms ?? []).length > 0 && (
        <details className="pet-result-details">
          <summary>本轮应用的术语</summary>
          <ul>
            {result.applied_terms!.map((term, index) => (
              <li key={index}>
                {term.source} → {term.target} × {term.count}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function MiniTurn({
  turn,
  disabled,
  retry,
  copy,
}: {
  turn: Turn;
  disabled: boolean;
  retry: () => void;
  copy: (text: string) => void;
}) {
  const result = turn.result;
  const copyText =
    result?.translated_text ||
    result?.annotated_copy ||
    (result?.annotations ?? []).map((item) => item.explanation).join('\n');
  return (
    <article className="pet-turn" aria-label="一轮独立翻译">
      <span className="pet-bubble-label">你 · 原文</span>
      <pre className="pet-source-bubble" dir="auto">
        {turn.request.text}
      </pre>
      <span className="pet-bubble-label">
        小译 ·{' '}
        {languages.find(([code]) => code === turn.request.target_language)?.[1] ||
          turn.request.target_language}
      </span>
      <div
        className={`pet-answer-bubble ${turn.status === 'error' ? 'pet-answer-bubble--error' : ''}`}
      >
        {turn.status === 'pending' && <p>正在理解与翻译…</p>}
        {turn.status === 'cancelled' && <p>已停止接收此轮结果。</p>}
        {turn.status === 'error' && <p>{turn.error}</p>}
        {turn.status === 'done' && result && (
          <>
            {result.translated_text ? (
              <pre dir="auto">{result.translated_text}</pre>
            ) : (
              <p>已保留原文，目标语言说明见下方。</p>
            )}
            <Details result={result} />
            <small>
              {result.detection_status === 'mixed'
                ? '混合语言'
                : result.detection_status === 'uncertain'
                  ? '语言不确定'
                  : result.detected_language}{' '}
              · {(result.elapsed_ms / 1000).toFixed(1)} 秒
            </small>
          </>
        )}
        {turn.status !== 'pending' && (
          <div className="pet-result-actions">
            {turn.status === 'done' && copyText && (
              <button type="button" onClick={() => copy(copyText)}>
                复制结果
              </button>
            )}
            <button type="button" disabled={disabled} onClick={retry}>
              重试此轮
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

function PetConversation({ api }: { api: NativeTranslationApi }) {
  // 原文、会话、取消、清空、迟到结果与退出均复用网页状态机，不建立桌面副本。
  const app = useTranslator(api);
  const [pairCode, setPairCode] = useState('');
  const count = characterCount(app.draft);
  const offline = app.connection === 'offline' || !app.browserOnline;
  const canSend = Boolean(
    app.auth &&
    app.session &&
    !app.busy &&
    !app.canCancel &&
    !offline &&
    app.draft.trim() &&
    count <= 4000,
  );
  const petState = offline ? 'offline' : app.busy ? 'thinking' : 'idle';
  const retryDisabled = app.busy || app.canCancel || !app.session || offline;

  return (
    <section className="pet-conversation" aria-label="小译文字翻译">
      <div
        className={`pet-live-status ${offline ? 'pet-warning' : ''}`}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <span>{app.notice}</span>
        {!app.busy && (offline || (app.auth && !app.session)) && (
          <button type="button" onClick={() => void app.connect()}>
            重新连接
          </button>
        )}
      </div>
      {!app.auth ? (
        <form
          className="pet-pair-form"
          onSubmit={(event) => {
            event.preventDefault();
            const code = pairCode;
            setPairCode('');
            void app.pair(code);
          }}
        >
          <Pet large state={petState} />
          <h2>让小译连接你的电脑</h2>
          <label htmlFor="pet-pair-code">一次性配对码</label>
          <input
            id="pet-pair-code"
            name="pet-pair-code"
            value={pairCode}
            onChange={(event) => setPairCode(event.target.value)}
            placeholder="XXXX XXXX XXXX"
            maxLength={20}
            autoComplete="off"
            spellCheck={false}
            aria-describedby="pet-pair-help"
            disabled={app.busy}
          />
          <p id="pet-pair-help">
            输入电脑终端显示的 12 位配对码。配对凭据只在桌面宿主内存中，不会保存到磁盘。
          </p>
          <button
            type="submit"
            className="pet-primary"
            disabled={app.busy || offline || pairCode.replace(/[\s-]/g, '').length !== 12}
          >
            配对并开始翻译
          </button>
        </form>
      ) : (
        <>
          <div className="pet-session-actions">
            <span>已配对 · 每轮独立翻译</span>
            <button
              type="button"
              onClick={() => void app.logout()}
              disabled={app.activity === 'logging-out'}
            >
              退出配对
            </button>
          </div>
          <div className="pet-settings">
            <label htmlFor="pet-target">目标语言</label>
            <select
              id="pet-target"
              value={app.options.target_language}
              onChange={(event) =>
                app.setOptions({
                  ...app.options,
                  target_language: event.target.value,
                })
              }
            >
              {languages.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
            <details className="pet-advanced">
              <summary>风格与任务模式</summary>
              <label>
                表达风格
                <select
                  value={app.options.style}
                  onChange={(event) =>
                    app.setOptions({
                      ...app.options,
                      style: event.target.value as Options['style'],
                    })
                  }
                >
                  <option value="standard">标准</option>
                  <option value="formal">正式</option>
                  <option value="colloquial">口语</option>
                </select>
              </label>
              <label>
                专业领域
                <select
                  value={app.options.domain}
                  onChange={(event) =>
                    app.setOptions({
                      ...app.options,
                      domain: event.target.value as Options['domain'],
                    })
                  }
                >
                  {[
                    ['general', '通用'],
                    ['technology', '技术'],
                    ['business', '商务'],
                    ['finance', '金融'],
                    ['legal', '法律'],
                    ['medical', '医疗'],
                    ['academic', '学术'],
                  ].map(([code, name]) => (
                    <option key={code} value={code}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                任务模式
                <select
                  value={app.options.task_mode}
                  onChange={(event) =>
                    app.setOptions({
                      ...app.options,
                      task_mode: event.target.value as Options['task_mode'],
                    })
                  }
                >
                  <option value="auto">智能判断</option>
                  <option value="translate">文字翻译</option>
                  <option value="annotate_code">代码注释</option>
                  <option value="annotate_special">特殊内容说明</option>
                </select>
              </label>
              <p>设置仅用于下一轮；术语沿用电脑的词库。</p>
            </details>
          </div>
          <div
            className="pet-turns"
            aria-label="本次打开的翻译记录"
            aria-busy={app.activity === 'translating'}
          >
            {app.turns.length === 0 ? (
              <div className="pet-empty">
                <Pet large state={petState} />
                <p>
                  写一句话，或贴上一段代码。
                  <br />
                  小译会帮你翻译或注解。
                </p>
              </div>
            ) : (
              app.turns.map((turn) => (
                <MiniTurn
                  key={turn.id}
                  turn={turn}
                  disabled={retryDisabled}
                  retry={() => void app.send(turn.request)}
                  copy={(text) => void app.copy(text)}
                />
              ))
            )}
          </div>
          <form
            className="pet-composer"
            onSubmit={(event) => {
              event.preventDefault();
              if (canSend) void app.send();
            }}
          >
            <label htmlFor="pet-source">想翻译什么？</label>
            <textarea
              id="pet-source"
              value={app.draft}
              onChange={(event) => app.editDraft(event.target.value)}
              rows={3}
              onKeyDown={(event) => {
                if (event.ctrlKey && event.key === 'Enter' && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  if (canSend) void app.send();
                }
              }}
              placeholder="每轮独立翻译；暂未开启语音"
              aria-invalid={count > 4000}
              aria-describedby="pet-count pet-composer-help"
              disabled={app.activity === 'logging-out'}
            />
            <div className="pet-composer-meta">
              <span id="pet-count" className={count > 4000 ? 'pet-warning' : ''}>
                {count} / 4000 字符
              </span>
              <span id="pet-composer-help">Ctrl + Enter</span>
            </div>
            <div className="pet-composer-actions">
              <button
                type="button"
                onClick={() => void app.clear()}
                disabled={app.activity === 'logging-out'}
              >
                清空
              </button>
              {app.canCancel ? (
                <button
                  type="button"
                  className="pet-stop"
                  onClick={() => void app.cancel()}
                  disabled={app.activity === 'cancelling'}
                >
                  {app.activity === 'cancelling' ? '停止中…' : '停止此轮'}
                </button>
              ) : (
                <button type="submit" className="pet-primary" disabled={!canSend}>
                  {app.busy ? '请稍等' : '开始翻译'}
                </button>
              )}
            </div>
          </form>
          <p className="pet-footnote">
            仅内存保留最近 20 轮；断网不自动重发。隐藏窗口不会停止正在运行的任务。
          </p>
        </>
      )}
    </section>
  );
}

interface ConfigurationOperation {
  generation: number;
  controller: AbortController;
}

export default function PetApp({
  api = nativeApi,
  windowControls = petWindowControls,
}: {
  api?: NativeTranslationApi;
  windowControls?: PetWindowControls;
}) {
  const [backend, setBackend] = useState<BackendStatus | null>(null);
  const [originDraft, setOriginDraft] = useState('http://127.0.0.1:8765');
  const [pendingOrigin, setPendingOrigin] = useState<string | null>(null);
  const [configurationNotice, setConfigurationNotice] = useState('正在读取桌面连接状态…');
  const [windowNotice, setWindowNotice] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [configuring, setConfiguring] = useState(true);
  const [conversationEpoch, setConversationEpoch] = useState(0);
  const generationRef = useRef(0);
  const configurationBusyRef = useRef(true);
  const activeRef = useRef<ConfigurationOperation | null>(null);
  const mountedRef = useRef(true);

  const current = (operation: ConfigurationOperation) =>
    mountedRef.current && generationRef.current === operation.generation;

  useEffect(() => {
    mountedRef.current = true;
    const operation = {
      generation: ++generationRef.current,
      controller: new AbortController(),
    };
    activeRef.current = operation;
    void api
      .backendStatus(operation.controller.signal)
      .then((value) => {
        if (!mountedRef.current || generationRef.current !== operation.generation) return;
        setBackend(value);
        if (value.origin) setOriginDraft(value.origin);
        setSettingsOpen(!value.origin);
        setConfigurationNotice(
          value.origin
            ? '连接地址由你指定；翻译通过桌面安全桥发送。'
            : '先明确设置服务地址，小译才会发起网络请求。',
        );
      })
      .catch((error: unknown) => {
        if (!mountedRef.current || generationRef.current !== operation.generation) return;
        setSettingsOpen(true);
        setConfigurationNotice(describeError(error));
      })
      .finally(() => {
        if (!mountedRef.current || generationRef.current !== operation.generation) return;
        configurationBusyRef.current = false;
        setConfiguring(false);
      });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      activeRef.current?.controller.abort();
    };
  }, [api]);

  async function switchBackend(input: string, abandonUnconfirmedLogout = false) {
    if (configurationBusyRef.current) return;
    let candidate: string;
    try {
      candidate = normalizeBackendOrigin(input);
    } catch (error) {
      setConfigurationNotice(describeError(error));
      return;
    }
    configurationBusyRef.current = true;
    activeRef.current?.controller.abort();
    const operation = {
      generation: ++generationRef.current,
      controller: new AbortController(),
    };
    activeRef.current = operation;
    setConfiguring(true);
    // 卸载共享 hook，使此刻之前的操作失效；重建后不能恢复旧原文、任务或结果。
    setConversationEpoch((epoch) => epoch + 1);
    setConfigurationNotice('正在关闭旧连接并设置新地址…');
    try {
      const previous = await api.backendStatus(operation.controller.signal);
      if (!current(operation)) return;
      if (previous.origin && !abandonUnconfirmedLogout) {
        try {
          await api.logout(null, operation.controller.signal);
        } catch {
          if (!current(operation)) return;
          setPendingOrigin(candidate);
          setConfigurationNotice(
            '未确认旧电脑的设备凭据已撤销。桌面已停止使用旧凭据；可重试退出，或明确确认仍然切换。旧服务器记录会按其到期策略清理。',
          );
          return;
        }
        if (!current(operation)) return;
      }
      const next = await api.configureBackend(candidate, operation.controller.signal);
      if (!current(operation)) return;
      setBackend(next);
      setOriginDraft(next.origin || candidate);
      setPendingOrigin(null);
      setSettingsOpen(false);
      setConfigurationNotice(
        abandonUnconfirmedLogout
          ? '新地址已设置。旧服务器撤销仍未确认，请留意其设备会话到期或在旧电脑上撤销。'
          : '地址已设置；请用该电脑终端的新配对码建立连接。',
      );
      try {
        await api.health(operation.controller.signal);
      } catch (error) {
        if (!current(operation)) return;
        const oldWarning = abandonUnconfirmedLogout ? '旧服务器的凭据撤销仍未确认。' : '';
        setConfigurationNotice(
          `${oldWarning}地址已设置，但暂未确认电脑服务可用。${describeError(error)}`,
        );
      }
      if (!current(operation)) return;
    } catch (error) {
      if (!current(operation)) return;
      // 配置命令可能已送达而其响应丢失。此时不能用旧地址标签呈现新连接。
      setBackend(null);
      setConfigurationNotice(
        `连接配置未确认，翻译已暂停。请核对地址并重新应用。${describeError(error)}`,
      );
      setSettingsOpen(true);
    } finally {
      if (current(operation)) {
        configurationBusyRef.current = false;
        setConfiguring(false);
      }
    }
  }

  async function hide() {
    try {
      await windowControls.hide();
    } catch {
      if (mountedRef.current) setWindowNotice('暂时无法隐藏窗口；可继续在此翻译。');
    }
  }

  const showSettings = settingsOpen || !backend?.origin || pendingOrigin !== null;
  return (
    <main className="desktop-pet" aria-label="译境文字宠物">
      <header className="pet-window-header">
        <div
          className="pet-drag-handle"
          title="拖动这里移动小译"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            void windowControls.startDragging().catch(() => {
              if (mountedRef.current) setWindowNotice('暂时无法拖动窗口；翻译功能不受影响。');
            });
          }}
        >
          <Pet />
          <div>
            <h1>小译</h1>
            <span>你的文字翻译伙伴 · 拖动此处移动</span>
          </div>
        </div>
        <button
          type="button"
          className="pet-hide"
          onClick={() => void hide()}
          aria-label="隐藏到托盘，不停止当前任务"
          title="隐藏到托盘，不停止当前任务"
        >
          −
        </button>
      </header>
      <div className="pet-host-toolbar">
        <span>
          {backend?.shortcut_available
            ? 'Ctrl + Shift + T 唤回'
            : backend
              ? '快捷键不可用，请从托盘唤回'
              : '托盘与快捷键状态尚未确认'}
        </span>
        <button
          type="button"
          onClick={() => setSettingsOpen((value) => !value)}
          disabled={configuring || pendingOrigin !== null}
        >
          服务地址
        </button>
      </div>
      <p className="pet-config-notice" role="status" aria-live="polite">
        {configurationNotice}
      </p>
      {windowNotice && (
        <p className="pet-warning" role="status">
          {windowNotice}
        </p>
      )}
      {showSettings && (
        <form
          className="pet-origin-form"
          onSubmit={(event) => {
            event.preventDefault();
            void switchBackend(originDraft);
          }}
        >
          <label htmlFor="pet-origin">电脑服务源地址</label>
          <input
            id="pet-origin"
            type="url"
            value={originDraft}
            onChange={(event) => setOriginDraft(event.target.value)}
            placeholder="http://127.0.0.1:8765"
            autoComplete="off"
            spellCheck={false}
            maxLength={1024}
            disabled={configuring || pendingOrigin !== null}
            aria-describedby="pet-origin-help"
          />
          <p id="pet-origin-help">
            同一电脑可用本机 HTTP；连接其他电脑必须使用可信 HTTPS 地址。不要填 Ollama 的 11434
            端口，不要填配对码或令牌。
          </p>
          {!pendingOrigin && (
            <button type="submit" className="pet-primary" disabled={configuring}>
              {configuring ? '处理中…' : backend?.origin ? '退出旧连接并应用' : '设置地址并连接'}
            </button>
          )}
          {pendingOrigin && (
            <div className="pet-switch-confirm" aria-label="旧连接撤销尚未确认">
              <p>
                待切换地址：<bdi>{pendingOrigin}</bdi>
              </p>
              <button
                type="button"
                disabled={configuring}
                onClick={() => void switchBackend(pendingOrigin)}
              >
                重试退出并切换
              </button>
              <button
                type="button"
                className="pet-confirm-warning"
                disabled={configuring}
                onClick={() => void switchBackend(pendingOrigin, true)}
              >
                确认仍然切换
              </button>
            </div>
          )}
        </form>
      )}
      {!configuring && !pendingOrigin && backend?.origin && (
        <PetConversation key={conversationEpoch} api={api} />
      )}
      {!backend?.origin && !configuring && (
        <div className="pet-empty">
          <Pet large state="offline" />
          <p>先连接电脑，小译再开始工作。</p>
        </div>
      )}
      <footer className="pet-shell-footer">
        这是文字翻译与代码注释，不是自由聊天。语音尚未开启；电脑需开机并运行私人 API 服务。
      </footer>
    </main>
  );
}
