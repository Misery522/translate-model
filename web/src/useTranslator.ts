import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, describeError, pause, TranslationApi } from './api';
import type { DeviceAuth, Options, TranslationRequest, Turn, WorkSession } from './types';

const defaultApi = new TranslationApi();
export const defaultOptions: Options = { target_language: 'zh-Hans', style: 'standard', domain: 'general', task_mode: 'auto' };
export const characterCount = (text: string) => Array.from(text).length;
type Activity = 'idle' | 'connecting' | 'translating' | 'resetting' | 'cancelling' | 'logging-out';
type Connection = 'checking' | 'paired' | 'unpaired' | 'offline';
interface Operation { generation: number; controller: AbortController; turnId?: string; jobId?: string; }

export function useTranslator(api = defaultApi) {
  const [auth, setAuth] = useState<DeviceAuth | null>(null);
  const [connection, setConnection] = useState<Connection>('checking');
  const [activity, setActivity] = useState<Activity>('connecting');
  const [session, setSession] = useState<WorkSession | null>(null);
  const [draft, setDraft] = useState('');
  const [options, setOptions] = useState<Options>(defaultOptions);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [notice, setNotice] = useState('正在连接你的电脑…');
  const [canCancel, setCanCancel] = useState(false);
  const [browserOnline, setBrowserOnline] = useState(navigator.onLine);
  const authRef = useRef<DeviceAuth | null>(null);
  const sessionRef = useRef<WorkSession | null>(null);
  const generationRef = useRef(0);
  const operationRef = useRef<Operation | null>(null);
  const busyRef = useRef(true);
  const mountedRef = useRef(true);
  const pendingSessionCleanup = useRef(new Set<string>());
  const canCancelRef = useRef(false);

  const updateCanCancel = useCallback((value: boolean) => { canCancelRef.current = value; setCanCancel(value); }, []);

  const current = useCallback((operation: Operation) => mountedRef.current && generationRef.current === operation.generation, []);
  const begin = useCallback((next: Activity): Operation => {
    operationRef.current?.controller.abort();
    const operation = { generation: ++generationRef.current, controller: new AbortController() };
    operationRef.current = operation;
    busyRef.current = true;
    setActivity(next);
    return operation;
  }, []);
  const finish = useCallback((operation: Operation) => {
    if (!current(operation)) return;
    busyRef.current = false;
    setActivity('idle');
  }, [current]);
  const updateAuth = useCallback((value: DeviceAuth | null) => {
    if (value && authRef.current && value.device_id !== authRef.current.device_id) pendingSessionCleanup.current.clear();
    authRef.current = value;
    setAuth(value);
  }, []);
  const updateSession = useCallback((value: WorkSession | null) => { sessionRef.current = value; setSession(value); }, []);
  const fail = useCallback((error: unknown, operation: Operation, prefix = '') => {
    if (!current(operation)) return;
    if (error instanceof ApiError && error.status === 401) {
      updateAuth(null);
      updateSession(null);
      updateCanCancel(false);
      setConnection('unpaired');
      setNotice('设备配对已过期，请在电脑上获取新配对码。');
    } else {
      if (error instanceof ApiError && error.problem.code === 'NETWORK_UNCONFIRMED') setConnection('offline');
      setNotice(prefix + describeError(error));
    }
  }, [current, updateAuth, updateSession, updateCanCancel]);
  const openSession = useCallback(async (device: DeviceAuth, operation: Operation) => {
    const next = await api.createSession(device.csrf_token, operation.controller.signal);
    if (!current(operation)) return;
    updateSession(next);
    setConnection('paired');
  }, [api, current, updateSession]);

  const cleanupSessions = useCallback(async (device: DeviceAuth, operation: Operation) => {
    for (const id of [...pendingSessionCleanup.current]) {
      try { await api.deleteSession(id, device.csrf_token, operation.controller.signal); }
      catch (error) { if (!(error instanceof ApiError && error.status === 404)) throw error; }
      if (!current(operation)) return;
      pendingSessionCleanup.current.delete(id);
    }
  }, [api, current]);

  const connect = useCallback(async () => {
    if (sessionRef.current) pendingSessionCleanup.current.add(sessionRef.current.session_id);
    const operation = begin('connecting');
    updateCanCancel(false);
    updateSession(null);
    setNotice('正在连接你的电脑…');
    try {
      const device = await api.auth(operation.controller.signal);
      if (!current(operation)) return;
      updateAuth(device);
      await cleanupSessions(device, operation);
      if (!current(operation)) return;
      await openSession(device, operation);
      if (!current(operation)) return;
      setNotice('已连接。说不清的话，换种语言也可以。');
    } catch (error) {
      if (!current(operation)) return;
      if (error instanceof ApiError && error.status === 401) {
        updateAuth(null);
        setConnection('unpaired');
        setNotice('先与你的电脑配对，开始随手翻译。');
      } else fail(error, operation);
    } finally { finish(operation); }
  }, [api, begin, cleanupSessions, current, fail, finish, openSession, updateAuth, updateSession, updateCanCancel]);

  useEffect(() => {
    mountedRef.current = true;
    void connect();
    const online = () => setBrowserOnline(true);
    const offline = () => { setBrowserOnline(false); setNotice('当前离线，只能打开界面。电脑恢复连接后再继续翻译。'); };
    const hide = () => {
      const work = sessionRef.current;
      const device = authRef.current;
      generationRef.current += 1;
      operationRef.current?.controller.abort();
      if (work && device) {
        pendingSessionCleanup.current.add(work.session_id);
        api.leaveSession(work.session_id, device.csrf_token);
      }
    };
    const show = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      setTurns([]);
      setDraft('');
      void connect();
    };
    window.addEventListener('online', online);
    window.addEventListener('offline', offline);
    window.addEventListener('pagehide', hide);
    window.addEventListener('pageshow', show);
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      operationRef.current?.controller.abort();
      window.removeEventListener('online', online);
      window.removeEventListener('offline', offline);
      window.removeEventListener('pagehide', hide);
      window.removeEventListener('pageshow', show);
    };
  }, [api, connect]);

  async function pair(code: string) {
    if (busyRef.current) return;
    const normalized = code.replace(/[\s-]/g, '');
    if (!/^[A-Za-z0-9]{12}$/.test(normalized)) { setNotice('请输入电脑上显示的 12 位配对码。'); return; }
    const operation = begin('connecting');
    setNotice('正在安全连接…');
    try {
      const device = await api.pair(normalized, operation.controller.signal);
      if (!current(operation)) return;
      // 新配对身份不拥有先前身份的会话，由服务器撤销/到期机制清理。
      pendingSessionCleanup.current.clear();
      updateAuth(device);
      setTurns([]);
      await openSession(device, operation);
      if (!current(operation)) return;
      setNotice('配对成功，欢迎来到译境。');
    } catch (error) { fail(error, operation); }
    finally { finish(operation); }
  }

  async function clear() {
    const oldSession = sessionRef.current;
    const device = authRef.current;
    const operation = begin('resetting');
    updateCanCancel(false);
    if (oldSession) pendingSessionCleanup.current.add(oldSession.session_id);
    // 清空先发生于本机，所有迟到网络结果再通过请求代次过滤。
    setDraft('');
    setTurns([]);
    updateSession(null);
    setNotice('已清空，正在准备新对话…');
    if (!device) { setNotice('等待配对'); finish(operation); return; }
    try {
      await cleanupSessions(device, operation);
      if (!current(operation)) return;
      await openSession(device, operation);
      if (!current(operation)) return;
      setNotice('等待翻译');
    } catch (error) { fail(error, operation, '界面已清空；未确认服务端停止。'); }
    finally { finish(operation); }
  }

  function editDraft(value: string) {
    setDraft(value);
    if (value === '' && activity === 'translating') void clear();
  }

  async function send(requestOverride?: TranslationRequest) {
    if (busyRef.current || canCancelRef.current || !authRef.current || !sessionRef.current) return;
    const request = requestOverride ?? { ...options, text: draft, source_language: 'auto' as const };
    if (!request.text.trim()) { setNotice('先写下一句想翻译的话吧。'); return; }
    if (characterCount(request.text) > 4000) { setNotice('原文超过 4000 字符，请缩短后再发送。'); return; }
    if (!navigator.onLine) { setNotice('当前离线。内容不会自动排队或重新发送。'); return; }
    const device = authRef.current;
    const work = sessionRef.current;
    const operation = begin('translating');
    const turnId = crypto.randomUUID();
    operation.turnId = turnId;
    updateCanCancel(true);
    setTurns((previous) => [...previous, { id: turnId, request, status: 'pending' as const }].slice(-20));
    setDraft('');
    setNotice('小译正在认真理解这句话…');
    let accepted = false;
    try {
      let job = await api.translate(work.session_id, turnId, request, device.csrf_token, operation.controller.signal);
      if (!current(operation)) return;
      accepted = true;
      operation.jobId = job.job_id;
      const started = Date.now();
      while (job.status === 'queued' || job.status === 'running') {
        setNotice(job.status === 'queued' ? '已加入电脑的处理队列…' : '正在翻译，请稍等片刻…');
        if (Date.now() - started > 240_000) throw new ApiError({ code: 'WAIT_TIMEOUT', message: '等待已超过 4 分钟。服务端状态尚未确认，请停止或清空此轮后重试。', retryable: true });
        await pause(800, operation.controller.signal);
        if (!current(operation)) return;
        try { job = await api.job(job.job_id, operation.controller.signal); }
        catch (error) {
          if (!current(operation)) return;
          if (error instanceof ApiError && error.status === 429) {
            setNotice('电脑请求较多，正在按提示稍后查询…');
            await pause(error.retryAfter * 1000, operation.controller.signal);
            if (!current(operation)) return;
            continue;
          }
          throw error;
        }
        if (!current(operation)) return;
      }
      updateCanCancel(false);
      if (job.status === 'succeeded' && job.result) {
        setTurns((previous) => previous.map((turn) => turn.id === turnId ? { ...turn, status: 'done', result: job.result! } : turn));
        setNotice('翻译完成。');
        setConnection('paired');
      } else if (job.status === 'cancelled') {
        setTurns((previous) => previous.map((turn) => turn.id === turnId ? { ...turn, status: 'cancelled' } : turn));
        setNotice('此轮已取消。');
      } else {
        throw new ApiError(job.error ?? { code: 'MODEL_FAILED', message: '这次没有得到可用结果，请重试或调整任务模式。', retryable: true });
      }
    } catch (error) {
      if (!current(operation)) return;
      // 仅提交阶段的 404 表示工作会话不存在；查询过期结果不得触发自动重投。
      if (!accepted && error instanceof ApiError && error.status === 404) {
        updateSession(null);
        error = new ApiError({ code: 'SESSION_EXPIRED', message: '工作会话已过期，原文已保留在本轮。请重新连接后手动重试此轮。', retryable: true }, 404);
      }
      if (!(error instanceof ApiError && ['NETWORK_UNCONFIRMED', 'WAIT_TIMEOUT'].includes(error.problem.code))) updateCanCancel(false);
      setTurns((previous) => previous.map((turn) => turn.id === turnId ? { ...turn, status: 'error', error: describeError(error) } : turn));
      fail(error, operation);
    } finally { finish(operation); }
  }

  async function cancel() {
    const previous = operationRef.current;
    const device = authRef.current;
    const work = sessionRef.current;
    if (!device || !previous?.turnId) return;
    const operation = begin('cancelling');
    operation.turnId = previous.turnId;
    operation.jobId = previous.jobId;
    setNotice('正在停止此轮…');
    setTurns((turns) => turns.map((turn) => turn.id === previous.turnId ? { ...turn, status: 'cancelled' } : turn));
    try {
      if (previous.jobId) {
        await api.cancel(previous.jobId, device.csrf_token, operation.controller.signal);
        if (!current(operation)) return;
      } else if (work || pendingSessionCleanup.current.size > 0) {
        if (work) pendingSessionCleanup.current.add(work.session_id);
        updateSession(null);
        await cleanupSessions(device, operation);
        if (!current(operation)) return;
        await openSession(device, operation);
        if (!current(operation)) return;
      }
      updateCanCancel(false);
      setNotice('已停止接收此轮结果。');
    } catch (error) { fail(error, operation, '已停止等待，未确认服务端停止。'); }
    finally { finish(operation); }
  }

  async function logout() {
    const device = authRef.current;
    const work = sessionRef.current;
    if (!device) return;
    const operation = begin('logging-out');
    updateCanCancel(false);
    if (work) pendingSessionCleanup.current.add(work.session_id);
    setTurns([]);
    setDraft('');
    updateSession(null);
    setNotice('正在退出设备连接…');
    try {
      if (pendingSessionCleanup.current.size > 0) {
        try { await cleanupSessions(device, operation); }
        catch { /* 撤销设备凭据仍然继续；不把取消确认等同于退出确认。 */ }
        if (!current(operation)) return;
      }
      await api.logout(device.csrf_token, operation.controller.signal);
      if (!current(operation)) return;
      updateAuth(null);
      pendingSessionCleanup.current.clear();
      setConnection('unpaired');
      setNotice('已退出设备连接，本页内容已清空。');
    } catch (error) { fail(error, operation, '本页内容已清空，但尚未确认设备凭据撤销。'); }
    finally { finish(operation); }
  }

  async function copy(text: string) {
    const generation = generationRef.current;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      if (!mountedRef.current || generation !== generationRef.current) return;
      setNotice('译文已复制。');
    } catch {
      if (!mountedRef.current || generation !== generationRef.current) return;
      setNotice('浏览器未允许复制，请手动选择译文。');
    }
  }

  return { auth, connection, activity, session, draft, options, turns, notice, browserOnline,
    busy: activity !== 'idle', canCancel, setOptions, editDraft, pair, send, clear, cancel, logout, copy, connect };
}
