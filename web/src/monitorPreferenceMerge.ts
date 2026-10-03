import { normalizeMonitorView, type MonitorView } from './monitorView';

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

/** Reconcile a server acknowledgement with edits made while that save was in flight. */
export function mergeMonitorEdits(server: MonitorView, submitted: MonitorView, latest: MonitorView): MonitorView {
  const merge = (current: unknown, base: Record<string, unknown>, edited: Record<string, unknown>): Record<string, unknown> => {
    const entries = new Map(Object.entries(object(current) ? current : base));
    for (const key of new Set([...Object.keys(base), ...Object.keys(edited)])) {
      if (!Object.hasOwn(edited, key)) entries.delete(key);
      else if (!Object.hasOwn(base, key)) entries.set(key, edited[key]);
      else if (JSON.stringify(base[key]) === JSON.stringify(edited[key])) continue;
      else if (object(base[key]) && object(edited[key])) entries.set(key, merge(entries.get(key), base[key], edited[key]));
      else entries.set(key, edited[key]);
    }
    return Object.fromEntries(entries);
  };
  return normalizeMonitorView(merge(server, submitted as unknown as Record<string, unknown>, latest as unknown as Record<string, unknown>), 16);
}
