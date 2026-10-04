/** Scene/source identifiers are data keys, including names like constructor.
 * Only an own entry is a saved preference or a runtime source state. */
export function ownRecordValue<T>(record: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(record, key) ? record[key] : undefined;
}
