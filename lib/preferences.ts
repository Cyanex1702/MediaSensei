// Preferences must never prevent loading or completing a server-side operation.
export function readPreference(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function writePreference(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* Storage can be disabled or full. */ }
}

export function readStringList(key: string): string[] {
  try {
    const value: unknown = JSON.parse(readPreference(key) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch { return []; }
}
