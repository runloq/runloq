import { useEffect } from 'react';

/** Return `false` from a handler to skip preventDefault and let the browser
 *  handle the event (e.g. cmd+C should still copy when text is selected). */
type Handler = (e: KeyboardEvent) => void | false;

/** True when running on macOS — used to select cmd vs ctrl as the modifier. */
export const isMac =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/.test(navigator.platform);

/**
 * Binding key format:
 *   - Bare key:              "c", "/", "Escape", "\\"
 *   - With meta/ctrl:        "mod+c", "mod+s"   (uses cmd on mac, ctrl elsewhere)
 *   - Explicit modifier:     "meta+n", "ctrl+n"
 *
 * Global keyboard bindings. Skipped when an editable element has focus.
 */
export function useKeyboard(bindings: Record<string, Handler>): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === 'INPUT' ||
          t.tagName === 'TEXTAREA' ||
          t.tagName === 'SELECT' ||
          t.isContentEditable)
      ) {
        return;
      }

      // Build a canonical key string for this event
      const key = e.key.toLowerCase();
      const candidates: string[] = [];

      if (e.metaKey || e.ctrlKey) {
        const modKey = e.metaKey ? 'meta' : 'ctrl';
        candidates.push(`${modKey}+${key}`);   // "meta+n" / "ctrl+n"
        candidates.push(`mod+${key}`);          // "mod+n" — matches both
        if (isMac && e.metaKey) candidates.push(`mod+${key}`);
        if (!isMac && e.ctrlKey) candidates.push(`mod+${key}`);
      } else {
        // No modifier — try exact case first (e.g. "Escape"), then lower
        candidates.push(e.key);
        if (e.key !== key) candidates.push(key);
      }

      for (const candidate of candidates) {
        const fn = bindings[candidate];
        if (fn) {
          const result = fn(e);
          if (result !== false) e.preventDefault();
          return;
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [bindings]);
}
