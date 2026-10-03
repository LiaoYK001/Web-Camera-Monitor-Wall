import type { SceneEvent } from './types';
import { isSupportedSceneSchema } from './sceneSchema';
import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import { createControlConnectionStatus, type ControlConnectionReason } from './controlConnectionStatus';

const CONNECT_TIMEOUT_MS = 15_000;
const SNAPSHOT_TIMEOUT_MS = 15_000;
const STABLE_CONNECTION_MS = 30_000;
const MAX_MESSAGE_CHARACTERS = 1_048_576;

/** Validate the envelope and bounded scene shape before it reaches React. */
function sceneEvent(value: unknown): value is SceneEvent {
  if (!value || typeof value !== 'object') return false;
  const event = value as Partial<SceneEvent>;
  const scene = event.scene;
  return (event.type === 'scene.snapshot' || event.type === 'scene.updated') && !!scene &&
    isSupportedSceneSchema(scene.schemaVersion) && Number.isSafeInteger(scene.revision) && scene.revision >= 0 &&
    typeof scene.id === 'string' && /^[A-Za-z0-9._-]{1,64}$/.test(scene.id) &&
    typeof scene.name === 'string' && scene.name.length <= 256 && !!scene.canvas &&
    Number.isFinite(scene.canvas.width) && scene.canvas.width > 0 && scene.canvas.width <= 16_384 &&
    Number.isFinite(scene.canvas.height) && scene.canvas.height > 0 && scene.canvas.height <= 16_384 &&
    typeof scene.canvas.backgroundColor === 'string' &&
    Array.isArray(scene.sources) && scene.sources.length <= 256 &&
    scene.sources.every((source) => source && typeof source === 'object' && typeof source.id === 'string' &&
      typeof source.kind === 'string' && Array.isArray(source.filters)) &&
    Array.isArray(scene.items) && scene.items.length <= 512 &&
    scene.items.every((item) => item && typeof item === 'object' && typeof item.sourceId === 'string' && !!item.crop);
}

/** Control synchronization is independent of video, audio and recording lifetimes. */
export function connectSceneEvents(onEvent: (event: SceneEvent) => void, onState: (connected: boolean) => void): () => void {
  let closed = false, socket: WebSocket | undefined;
  let deadline: number | undefined, retry: number | undefined, stable: number | undefined;
  let attempt = 0, failures = 0, messages = 0, rejectedMessages = 0;
  let lastSnapshotAt: number | null = null;
  let hiddenAt: number | null = isPageVisible() ? null : Date.now();
  let online = false, reported: boolean | undefined;
  const status = createControlConnectionStatus();
  const setOnline = (value: boolean) => { online = value; if (reported !== value) { reported = value; onState(value); } };
  const clearTimers = () => {
    window.clearTimeout(deadline); window.clearTimeout(retry); window.clearTimeout(stable);
    deadline = retry = stable = undefined;
  };
  const retire = () => {
    clearTimers();
    const previous = socket; socket = undefined;
    // Detach first: a late event from an old socket must not close its successor.
    if (previous) { previous.onopen = previous.onmessage = previous.onerror = previous.onclose = null;
      try { previous.close(); } catch { /* Already closed by the browser. */ } }
  };
  const canConnect = () => navigator.onLine !== false && isPageVisible();
  const wait = (reason: ControlConnectionReason) => {
    if (closed) return;
    retire(); setOnline(false); failures++;
    if (!canConnect()) { status.update({ phase: navigator.onLine === false ? 'offline' : 'paused', reason,
      failures, nextRetryAt: null, connectedAt: null }); return; }
    const delay = Math.round(Math.min(30_000, 500 * 2 ** Math.min(attempt++, 6) * (.8 + Math.random() * .4)));
    status.update({ phase: 'retrying', reason, failures, nextRetryAt: Date.now() + delay, connectedAt: null });
    retry = window.setTimeout(() => { retry = undefined; connect(); }, delay);
  };
  const connect = (reason: ControlConnectionReason = '') => {
    if (closed) return;
    retire(); if (online) setOnline(false);
    if (!canConnect()) { setOnline(false); status.update({ phase: navigator.onLine === false ? 'offline' : 'paused',
      reason: navigator.onLine === false ? 'network_offline' : reason, nextRetryAt: null, connectedAt: null }); return; }
    status.update({ phase: 'connecting', reason, attempts: ++attempts, nextRetryAt: null, connectedAt: null });
    let current: WebSocket;
    try { current = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/api/v1/ws'); }
    catch { wait('constructor_failed'); return; }
    socket = current;
    deadline = window.setTimeout(() => { if (socket === current) wait('connection_timeout'); }, CONNECT_TIMEOUT_MS);
    current.onopen = () => {
      if (closed || socket !== current) return;
      window.clearTimeout(deadline);
      // The HTTP upgrade alone does not prove authenticated scene delivery.
      deadline = window.setTimeout(() => { if (socket === current && !online) wait('snapshot_timeout'); }, SNAPSHOT_TIMEOUT_MS);
    };
    current.onmessage = (message) => {
      if (closed || socket !== current) return;
      let event: unknown;
      try { if (typeof message.data !== 'string' || message.data.length > MAX_MESSAGE_CHARACTERS) throw new Error(); event = JSON.parse(message.data); }
      catch { status.update({ rejectedMessages: ++rejectedMessages }); return; }
      if (!sceneEvent(event)) { status.update({ rejectedMessages: ++rejectedMessages }); return; }
      window.clearTimeout(deadline); deadline = undefined;
      lastSnapshotAt = Date.now();
      if (!online) {
        setOnline(true);
        status.update({ phase: 'online', reason: '', connectedAt: lastSnapshotAt, nextRetryAt: null });
        stable = window.setTimeout(() => { if (!closed && socket === current && online) attempt = 0; }, STABLE_CONNECTION_MS);
      }
      status.update({ messages: ++messages, lastSnapshotAt });
      onEvent(event);
    };
    current.onerror = () => { if (!closed && socket === current) wait('transport_error'); };
    current.onclose = () => { if (!closed && socket === current) wait('transport_closed'); };
  };
  let attempts = 0;
  const offline = () => { if (closed) return; retire(); setOnline(false);
    status.update({ phase: 'offline', reason: 'network_offline', nextRetryAt: null, connectedAt: null }); };
  const wake = (reason: ControlConnectionReason) => {
    if (!closed && canConnect() && (reason === 'manual' || !socket ||
      (hiddenAt !== null && Date.now() - hiddenAt >= STABLE_CONNECTION_MS))) connect(reason);
  };
  const networkOnline = () => wake('resume');
  const visibility = () => {
    if (!isPageVisible()) {
      hiddenAt ??= Date.now();
      // Leave an established subscription running for desktop projectors. Only
      // failed retries pause; recording and media continue independently.
      if (!online) { retire(); status.update({ phase: navigator.onLine === false ? 'offline' : 'paused', nextRetryAt: null }); }
    } else { wake('resume'); hiddenAt = null; }
  };
  const manual = () => wake('manual');
  window.addEventListener('offline', offline); window.addEventListener('online', networkOnline);
  window.addEventListener('webobs:reconnect-control', manual);
  const unsubscribeVisibility = subscribePageVisibility(visibility);
  connect();
  return () => { if (closed) return; closed = true; retire(); status.remove();
    window.removeEventListener('offline', offline); window.removeEventListener('online', networkOnline);
    window.removeEventListener('webobs:reconnect-control', manual); unsubscribeVisibility(); };
}
