import type { OperationalIssue } from './types';

type Listener = (issues: OperationalIssue[]) => void;

const issues = new Map<string, OperationalIssue>();
const listeners = new Set<Listener>();

const safeDetails = (details: Record<string, unknown> = {}) => Object.fromEntries(
  Object.entries(details).filter(([key, value]) =>
    ['adapter', 'transportMode', 'codec', 'httpStatus', 'retryCount', 'lastFrameAgeMs', 'topology', 'reason'].includes(key)
      && ['string', 'number', 'boolean'].includes(typeof value))
    .map(([key, value]) => [key, typeof value === 'string' ? value.slice(0, 96) : value]),
) as Record<string, string | number | boolean>;

const emit = () => {
  const snapshot = [...issues.values()].sort((left, right) => right.lastSeenAt - left.lastSeenAt);
  listeners.forEach((listener) => listener(snapshot));
  window.dispatchEvent(new CustomEvent('webobs:issues-changed', { detail: snapshot }));
};

const identifier = (code: string, scopeId: string, component: string) =>
  `local-${[code, scopeId, component].join('-').replace(/[^a-zA-Z0-9._-]/g, '-').slice(0, 110)}`;

export function reportLocalIssue(input: {
  code: string; severity?: OperationalIssue['severity']; scopeKind?: OperationalIssue['scopeKind'];
  scopeId: string; component: string; summary: string; explanation: string;
  recommendedActions?: string[]; technicalDetails?: Record<string, unknown>;
}): void {
  const id = identifier(input.code, input.scopeId, input.component);
  const now = Date.now();
  const current = issues.get(id);
  issues.set(id, {
    id, code: input.code.slice(0, 64), severity: input.severity ?? 'warning', state: 'open',
    scopeKind: input.scopeKind ?? 'source', scopeId: input.scopeId.slice(0, 64),
    component: input.component.slice(0, 64), firstSeenAt: current?.firstSeenAt ?? now,
    lastSeenAt: now, occurrences: (current?.occurrences ?? 0) + 1,
    summary: input.summary.slice(0, 160), explanation: input.explanation.slice(0, 400),
    recommendedActions: (input.recommendedActions ?? []).slice(0, 4).map((value) => value.slice(0, 160)),
    technicalDetails: safeDetails(input.technicalDetails),
  });
  if (issues.size > 256) {
    const oldest = [...issues.values()].sort((left, right) => left.lastSeenAt - right.lastSeenAt)[0];
    if (oldest) issues.delete(oldest.id);
  }
  emit();
}

export function resolveLocalIssue(code: string, scopeId: string, component: string): void {
  const id = identifier(code, scopeId, component);
  const current = issues.get(id);
  if (!current || current.state === 'resolved') return;
  issues.set(id, { ...current, state: 'resolved', lastSeenAt: Date.now() });
  emit();
}

export function subscribeLocalIssues(listener: Listener): () => void {
  listeners.add(listener);
  listener([...issues.values()]);
  return () => listeners.delete(listener);
}

export function openIssueCenter(scopeId = ''): void {
  window.dispatchEvent(new CustomEvent('webobs:open-issues', { detail: { scopeId } }));
}
