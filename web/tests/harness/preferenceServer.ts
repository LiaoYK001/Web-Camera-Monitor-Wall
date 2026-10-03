// Fixture-only account store: match the existing backend merge contract, not
// the frontend's request compaction. Real HTTP/native checks run separately.
const object = (value: unknown): value is Record<string, any> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

export function savePreferenceFixture(current: unknown, request: { value: Record<string, any>; baseValue?: Record<string, any>; partial?: boolean; removedPaths?: string[][] }): Record<string, any> {
  if (!request.baseValue) return request.value;
  const merge = (stored: unknown, base: Record<string, any>, edited: Record<string, any>): Record<string, any> => {
    const result = new Map(Object.entries(object(stored) ? stored : base));
    for (const key of request.partial ? Object.keys(edited) : new Set([...Object.keys(base), ...Object.keys(edited)])) {
      if (!Object.hasOwn(edited, key)) result.delete(key);
      else if (!Object.hasOwn(base, key)) result.set(key, edited[key]);
      else if (JSON.stringify(base[key]) === JSON.stringify(edited[key])) continue;
      else if (object(base[key]) && object(edited[key])) result.set(key, merge(result.get(key), base[key], edited[key]));
      else result.set(key, edited[key]);
    }
    return Object.fromEntries(result);
  };
  const merged = merge(current, request.baseValue, request.value);
  const result = request.removedPaths?.length ? structuredClone(merged) : merged;
  for (const path of request.removedPaths ?? []) {
    let cursor: any = result;
    for (const key of path.slice(0, -1)) cursor = object(cursor) && Object.hasOwn(cursor, key) ? cursor[key] : undefined;
    if (object(cursor)) delete cursor[path[path.length - 1]];
  }
  return result;
}
