import { observeControl } from './diagnosticsRuntime';

export type ControlConnectionPhase = 'connecting' | 'online' | 'retrying' | 'offline' | 'paused';
export type ControlConnectionReason = '' | 'network_offline' | 'connection_timeout' | 'snapshot_timeout' | 'transport_error' | 'transport_closed' | 'constructor_failed' | 'resume' | 'manual';
export interface ControlConnectionStatus {
  id: number; phase: ControlConnectionPhase; reason: ControlConnectionReason;
  attempts: number; failures: number; rejectedMessages: number; messages: number;
  connectedAt: number | null; lastSnapshotAt: number | null; nextRetryAt: number | null;
}

// Session-only counters: never retain server URLs, scene data, close reasons,
// cookies, credentials or arbitrary exception messages in support diagnostics.
const connections = new Map<number, ControlConnectionStatus>();
const listeners = new Set<() => void>();
let sequence = 0;
let snapshot: readonly ControlConnectionStatus[] = [];
function publish() { snapshot = [...connections.values()]; listeners.forEach((listener) => listener()); }
export function createControlConnectionStatus() {
  const id = ++sequence;
  let current: ControlConnectionStatus = { id, phase: 'connecting', reason: '', attempts: 0, failures: 0,
    rejectedMessages: 0, messages: 0, connectedAt: null, lastSnapshotAt: null, nextRetryAt: null };
  const update = (change: Partial<Omit<ControlConnectionStatus, 'id'>>) => {
    current = { ...current, ...change };
    observeControl(current);
    // Product windows normally own one connection; keep diagnostics bounded.
    if (connections.has(id) || connections.size < 32) { connections.set(id, current); publish(); }
  };
  update({});
  return { update, remove: () => { observeControl(current, false); if (connections.delete(id)) publish(); } };
}
export const getControlConnections = () => snapshot;
export function subscribeControlConnections(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function reconnectControlConnections() { window.dispatchEvent(new Event('webobs:reconnect-control')); }
