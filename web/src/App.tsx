import { useState } from 'react';
import type { TranslationApi } from './api';
import { Pet } from './Pet';
import type { AgentResult, Options, Turn } from './types';
import { characterCount, useTranslator } from './useTranslator';

const languages = [ ['zh-Hans', '简体中文'], ['zh-Hant', '繁体中文'], ['en', '英语'], ['ja', '日语'], ['ko', '韩语'], ['fr', '法语'], ['de', '德语'], ['es', '西班牙语'], ['ru', '俄语'], ['pt-BR', '葡萄牙语（巴西）'], ['ar', '阿拉伯语'], ['it', '意大利语'] ];
const routeNames: Record<AgentResult['route'], string> = { translate_text: '文字翻译', annotate_code: '代码注释', annotate_special: '内容说明', mixed_document: '混合文档' };
const languageName = (code: string) => languages.find(([key]) => key === code)?.[1] ?? (code === 'und' ? '不确定' : code);

function Settings({ options, update }: { options: Options; update: (value: Options) => void }) {
  return <aside className="settings-card" aria-label="翻译设置">
    <div className="section-heading"><span className="section-kicker">为你表达</span><span className="auto-badge">自动识别原文</span></div>
    <div className="settings-grid">
      <label>目标语言<select value={options.target_language} onChange={(event) => update({ ...options, target_language: event.target.value })}>{languages.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
      <label>表达风格<select value={options.style} onChange={(event) => update({ ...options, style: event.target.value as Options['style'] })}><option value="standard">自然 · 标准</option><option value="formal">严谨 · 正式</option><option value="colloquial">轻松 · 口语</option></select></label>
      <label>专业领域<select value={options.domain} onChange={(event) => update({ ...options, domain: event.target.value as Options['domain'] })}>{[['general', '日常通用'], ['technology', '技术'], ['business', '商务'], ['finance', '金融'], ['legal', '法律'], ['medical', '医疗'], ['academic', '学术']].map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
      <label>任务模式<select value={options.task_mode} onChange={(event) => update({ ...options, task_mode: event.target.value as Options['task_mode'] })}><option value="auto">智能判断</option><option value="translate">强制文字翻译</option><option value="annotate_code">代码注释</option><option value="annotate_special">特殊内容说明</option></select></label>
    </div>
    <div className="settings-note"><span className="leaf-mark" aria-hidden="true">✧</span><p>表达可以不同，意思始终如一。<br />术语沿用电脑上保存的词库。</p></div>
    <p className="small-note">设置应用于下一轮。每轮独立翻译，不会把本页历史传给模型。</p>
  </aside>;
}

function ResultDetails({ result }: { result: AgentResult }) {
  const annotations = result.annotations ?? [];
  const warnings = result.warnings ?? [];
  const terms = result.applied_terms ?? [];
  return <>
    {(result.annotated_copy || annotations.length > 0) && <details className="result-details"><summary>查看注释与说明 <span>{annotations.length} 项</span></summary>
      {result.annotated_copy && <><h4>目标语言注释副本</h4><pre dir="auto">{result.annotated_copy}</pre></>}
      {annotations.map((annotation, index) => <section key={index} className="annotation"><h4>{annotation.location || annotation.kind}</h4><pre dir="auto">{annotation.source_fragment}</pre><p dir="auto">{annotation.explanation}</p>{annotation.risk && <p className="risk">{annotation.risk}</p>}</section>)}
      <details><summary>保留的原文</summary><pre dir="auto">{result.preserved_source}</pre></details>
    </details>}
    {warnings.length > 0 && <details className="result-details warning-details"><summary>请留意 · {warnings.length} 条提示</summary><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    {terms.length > 0 ? <details className="result-details"><summary>已应用 {terms.length} 个术语</summary><ul>{terms.map((term, index) => <li key={index}><span>{term.source}</span> → <span>{term.target}</span> <small>× {term.count}</small></li>)}</ul></details> : <p className="terms-empty">本轮未命中自定义术语</p>}
  </>;
}

function ConversationTurn({ turn, busy, retry, copy }: { turn: Turn; busy: boolean; retry: () => void; copy: (text: string) => void }) {
  return <article className="conversation-turn" aria-label="一轮翻译">
    <div className="source-label">你 · 原文</div>
    <div className="source-bubble"><pre dir="auto">{turn.request.text}</pre></div>
    <div className="reply-row"><Pet state={turn.status === 'pending' ? 'thinking' : 'idle'} /><div className="reply-content">
      <div className="reply-label">小译 <span>{languageName(turn.request.target_language)}</span></div>
      <div className={`reply-bubble ${turn.status === 'error' ? 'reply-bubble--error' : ''}`}>
        {turn.status === 'pending' && <p className="thinking"><span className="thinking-dots" aria-hidden="true">•••</span> 正在理解与翻译…</p>}
        {turn.status === 'cancelled' && <p className="muted">此轮已停止接收结果。</p>}
        {turn.status === 'error' && <><p>{turn.error}</p><button className="text-button" disabled={busy} onClick={retry}>重试此轮 <span aria-hidden="true">↗</span></button></>}
        {turn.status === 'done' && turn.result && <>
          {turn.result.translated_text ? <pre className="translation-text" dir="auto">{turn.result.translated_text}</pre> : <p>已保留原文，并生成目标语言说明。</p>}
          <div className="result-meta"><span>{routeNames[turn.result.route]} · {languageName(turn.result.detected_language)}{turn.result.detection_status === 'mixed' ? '（混合语言）' : turn.result.detection_status === 'uncertain' ? '（不确定）' : ''}</span><span>{(turn.result.elapsed_ms / 1000).toFixed(1)} 秒</span></div>
          <ResultDetails result={turn.result} />
          <div className="result-actions"><button className="text-button" onClick={() => copy(turn.result!.translated_text || turn.result!.annotated_copy || (turn.result!.annotations ?? []).map((item) => item.explanation).join('\n'))}>复制译文 <span aria-hidden="true">⧉</span></button><button className="text-button" disabled={busy} onClick={retry}>重试此轮 <span aria-hidden="true">↻</span></button></div>
        </>}
      </div>
    </div></div>
  </article>;
}

export default function App({ api }: { api?: TranslationApi }) {
  const app = useTranslator(api);
  const [pairCode, setPairCode] = useState('');
  const count = characterCount(app.draft);
  const offline = !app.browserOnline || app.connection === 'offline';
  const petState = offline ? 'offline' : app.busy ? 'thinking' : 'idle';
  const canSend = Boolean(app.auth && app.session && !app.busy && !app.canCancel && !offline && app.draft.trim() && count <= 4000);

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">跳到翻译区域</a>
    <header className="app-header"><a href="/" className="brand" aria-label="译境首页"><Pet /><span>译境<small>让表达，自在一点。</small></span></a>
      <div className="header-actions"><span className={`connection-pill ${offline ? 'connection-pill--offline' : ''}`}><i aria-hidden="true" />{offline ? '电脑暂未连接' : app.auth ? '私人电脑 · 已配对' : '私人翻译空间'}</span>{app.auth && <button className="text-button" onClick={() => void app.logout()} disabled={app.activity === 'logging-out'}>退出</button>}</div>
    </header>

    <main id="main-content">
      <div className="page-heading"><div><div className="eyebrow">A LITTLE SPACE FOR YOUR WORDS</div><h1>一句话，通往另一种表达。</h1><p>你好，我是小译。把想说的交给我，把理解留给彼此。</p></div><span className="page-edition">随手翻译 <span>01</span></span></div>
      <div className={`status-bar ${offline ? 'status-bar--offline' : ''}`} role="status" aria-live="polite" aria-atomic="true"><span className="status-spark" aria-hidden="true">{offline ? '○' : app.busy ? '◌' : '✧'}</span><span>{app.notice}</span>{!app.busy && (offline || (app.auth && !app.session)) && <button className="text-button" onClick={() => void app.connect()}>重新连接</button>}</div>

      {!app.auth ? <section className="pair-layout" aria-labelledby="pair-title"><div className="pair-welcome"><Pet large state={petState} /><h2>你的语言小伙伴，<br />在这里等你。</h2><p>连接自己的电脑，开始一个<br />不被语言打断的日常。</p><span className="paper-note">文字在本机模型中处理</span></div>
        <form className="pair-card" onSubmit={(event) => { event.preventDefault(); void app.pair(pairCode); }}><span className="section-kicker">第一次见面</span><h2 id="pair-title">与你的电脑配对</h2><p>在电脑上获取一次性配对码，<br />然后把这台设备连接到译境。</p><label htmlFor="pair-code">12 位配对码</label><input id="pair-code" name="pair-code" className="pair-code" value={pairCode} onChange={(event) => setPairCode(event.target.value)} autoComplete="one-time-code" spellCheck={false} placeholder="XXXX XXXX XXXX" maxLength={20} disabled={app.busy} aria-describedby="pair-help" /><p id="pair-help" className="small-note">配对码只使用一次，过期后请从电脑重新获取。</p><button className="primary-button" type="submit" disabled={app.busy || offline || pairCode.replace(/[\s-]/g, '').length !== 12}>{app.busy ? '正在连接…' : '连接，开始翻译'} <span aria-hidden="true">↗</span></button><p className="pair-privacy">设备凭据由浏览器保护。翻译记录只留在本页。</p></form>
      </section> : <div className="workspace-layout"><Settings options={app.options} update={app.setOptions} /><section className="chat-card" aria-label="翻译对话">
        <div className="chat-header"><div><span className="chat-dot" aria-hidden="true" /><strong>和小译说一句</strong><span className="chat-subtitle">一来一往，意思更明白</span></div><button className="text-button" onClick={() => void app.clear()} disabled={app.activity === 'logging-out'}>清空</button></div>
        <div className="conversation" aria-label="本页翻译记录" aria-busy={app.activity === 'translating'}>
          {app.turns.length === 0 ? <div className="empty-conversation"><Pet large state={petState} /><h2>从一句「你好」开始。</h2><p>日常消息、工作邮件，或是一段代码，<br />小译会选择合适的方式帮你理解。</p><div className="example-chips"><button onClick={() => app.editDraft('Could you please send me the meeting notes?')}>一封工作消息 <span aria-hidden="true">↗</span></button><button onClick={() => app.editDraft('今日はいい天気ですね。')}>一句日常问候 <span aria-hidden="true">↗</span></button></div></div> : app.turns.map((turn) => <ConversationTurn key={turn.id} turn={turn} busy={app.busy || app.canCancel || !app.session || offline} retry={() => void app.send(turn.request)} copy={(text) => void app.copy(text)} />)}
        </div>
        <form className="composer" onSubmit={(event) => { event.preventDefault(); if (canSend) void app.send(); }}>
          <label className="sr-only" htmlFor="source-text">原文</label><textarea id="source-text" value={app.draft} onChange={(event) => app.editDraft(event.target.value)} onKeyDown={(event) => { if (event.ctrlKey && event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); if (canSend) void app.send(); } }} placeholder="在这里写下想翻译的话…" rows={3} aria-describedby="character-count composer-help" aria-invalid={count > 4000} disabled={app.activity === 'logging-out'} />
          <div className="composer-bottom"><div><span id="character-count" className={count > 4000 ? 'over-limit' : ''}>{count} / 4000 字符</span><span id="composer-help">Ctrl + Enter 发送</span></div>{app.canCancel ? <button type="button" className="stop-button" disabled={app.activity === 'cancelling'} onClick={() => void app.cancel()}>{app.activity === 'cancelling' ? '停止中…' : '停止此轮'} <span aria-hidden="true">■</span></button> : <button type="submit" className="primary-button send-button" disabled={!canSend}>{app.busy ? '请稍等' : '开始翻译'} <span aria-hidden="true">↑</span></button>}</div>
        </form>
        <p className="history-note">本页最多保留最近 20 轮，刷新后清空。断网不会自动重新发送。</p>
      </section></div>}
      <footer className="app-footer"><span>小译是当前页面中的文字伙伴。语音与桌面悬浮功能尚在开发中。</span><span>由你的电脑理解 · 由你决定表达</span></footer>
    </main>
  </div>;
}
