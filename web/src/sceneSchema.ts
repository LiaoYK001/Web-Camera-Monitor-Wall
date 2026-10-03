/** Core accepts legacy v5 and emits v6 for explicit multi-track audio inputs. */
export function isSupportedSceneSchema(value: unknown): value is 5 | 6 { return value === 5 || value === 6; }
