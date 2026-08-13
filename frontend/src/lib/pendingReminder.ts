/**
 * Reminder choices held across a sign-in redirect.
 *
 * Google sign-in navigates the whole page away, so anything held in React state
 * is gone by the time the user comes back. Without this, someone who picked
 * their cadences and then signed in would return to a dashboard that had quietly
 * forgotten the whole thing — and would have to do it again, which is exactly
 * the friction the signed-out flow exists to avoid.
 */

const KEY = "ipo_pending_reminder";

export interface PendingReminder {
  ipoId: number;
  ipoName: string;
  cadences: string[];
  /** Discarded if stale, so a reminder can't be created weeks later. */
  savedAt: number;
}

const MAX_AGE_MS = 30 * 60 * 1000;

export function savePending(value: Omit<PendingReminder, "savedAt">): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...value, savedAt: Date.now() }));
  } catch {
    /* private mode or storage full — the flow still works, just without recall */
  }
}

export function takePending(): PendingReminder | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    sessionStorage.removeItem(KEY); // single use: never replay twice
    const parsed = JSON.parse(raw) as PendingReminder;
    if (!parsed?.ipoId || !Array.isArray(parsed.cadences) || !parsed.cadences.length) return null;
    if (Date.now() - (parsed.savedAt ?? 0) > MAX_AGE_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearPending(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}
