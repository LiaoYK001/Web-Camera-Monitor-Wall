// Compare stable product versions numerically; never order patches as strings.
export function stableVersion(value) {
  if (typeof value !== 'string' || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value)) return null;
  const parts = value.split('.').map(Number);
  return parts.every(Number.isSafeInteger) && parts.join('.') === value ? parts : null;
}

export function updateKind(installed, candidate) {
  const current = stableVersion(installed), next = stableVersion(candidate);
  if (!current || !next) return null;
  for (let index = 0; index < 3; index++) {
    if (next[index] < current[index]) return null;
    if (next[index] > current[index]) return ['major', 'minor', 'patch'][index];
  }
  return null;
}
