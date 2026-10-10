export function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`fsp-demo:v1:${key}`);
    return raw ? JSON.parse(raw) as T : fallback;
  } catch { return fallback; }
}

export function writeStorage(key: string, value: unknown): boolean {
  try { localStorage.setItem(`fsp-demo:v1:${key}`, JSON.stringify(value)); return true; }
  catch { return false; }
}
