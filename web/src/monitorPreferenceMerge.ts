import { normalizeMonitorView, type MonitorView } from './monitorView';

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

/** Compact the wire pair, keeping complete control baselines for each changed
 * source so first-time controls retain inherited Scene/global defaults. The
 * private pending cache continues to store the complete original documents. */
export function compactMonitorPreference(value: MonitorView, baseValue: MonitorView): {
  value: Record<string, unknown>; baseValue: Record<string, unknown>; partial: true; removedPaths: string[][];
} {
  const changed = (base: Record<string, unknown>, edited: Record<string, unknown>) => {
    const before = new Map<string, unknown>(), after = new Map<string, unknown>();
    for (const key of new Set([...Object.keys(base), ...Object.keys(edited)])) {
      if (Object.hasOwn(base, key) && Object.hasOwn(edited, key) && JSON.stringify(base[key]) === JSON.stringify(edited[key])) continue;
      if (Object.hasOwn(base, key)) before.set(key, base[key]);
      if (Object.hasOwn(edited, key)) after.set(key, edited[key]);
    }
    return { baseValue: Object.fromEntries(before), value: Object.fromEntries(after) };
  };
  const pair = changed(baseValue as unknown as Record<string, unknown>, value as unknown as Record<string, unknown>);
  for (const key of ['sourceAudio', 'sourceDecorations'] as const) {
    if (object(pair.baseValue[key]) && object(pair.value[key])) {
      const sources = changed(pair.baseValue[key], pair.value[key]);
      pair.baseValue[key] = sources.baseValue; pair.value[key] = sources.value;
    }
  }
  const removedPaths: string[][] = [];
  const leaves = (base: Record<string, unknown>, edited: Record<string, unknown>, path: string[] = []): Record<string, unknown> => {
    const result = new Map<string, unknown>();
    for (const key of new Set([...Object.keys(base), ...Object.keys(edited)])) {
      if (!Object.hasOwn(edited, key)) removedPaths.push([...path, key]);
      else if (!Object.hasOwn(base, key)) result.set(key, edited[key]);
      else if (JSON.stringify(base[key]) === JSON.stringify(edited[key])) continue;
      else if (object(base[key]) && object(edited[key])) result.set(key, leaves(base[key], edited[key], [...path, key]));
      else result.set(key, edited[key]);
    }
    return Object.fromEntries(result);
  };
  return { ...pair, value: leaves(pair.baseValue, pair.value), partial: true, removedPaths };
}

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
