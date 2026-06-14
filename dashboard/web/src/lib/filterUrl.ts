/** Filter state model with localStorage persistence + URL sync.
 *
 * Selection models per filter:
 *   project   → radio   (single: 'all' | project code)
 *   assignee  → radio   (single: 'all' | assignee slug)
 *   priority  → radio   (single: 'all' | 'P0' | 'P1' | 'P2' | 'P3')
 *   blocked   → tri-state ('all' | 'blocked' | 'unblocked')
 *                — UI exposes only the two non-default chips; clicking the
 *                  active one toggles back to 'all'
 *
 * Column visibility toggles (localStorage only — never in URL):
 *   showTodo        → boolean (default ON)
 *   showInProgress  → boolean (default ON)
 *   showScheduled   → boolean (default ON)
 *   showDone        → boolean (default OFF)
 *   showCancelled   → boolean (default OFF)
 *   showEpics       → boolean (default OFF)
 *
 * URL serialization rules:
 *   - Only project / assignee / priority / blocked / q are URL-serialized.
 *   - Visibility flags are localStorage only. The default view ('/') has zero
 *     query params (for the URL-persisted fields).
 *   - `blocked` is encoded as `blocked=true` (only blocked) or
 *     `blocked=false` (only unblocked). Omitted means default ('all').
 *   - Backward-compat: old `show_done` / `show_cancelled` / `show_epics` URL
 *     params are silently ignored on decode (no longer written).
 */

export type BlockedState = 'all' | 'blocked' | 'unblocked';

export interface Filters {
  project: string; // 'all' | <project code from config>
  assignee: string; // 'all' | <assignee from config>, e.g. 'claude' | 'agent' | 'alice' | 'bob'
  priority: string; // 'all' | 'P0' | 'P1' | 'P2' | 'P3'
  blocked: BlockedState;
  // Column visibility — persisted in localStorage, not in URL
  showTodo: boolean;
  showInProgress: boolean;
  showScheduled: boolean;
  showDone: boolean;
  showCancelled: boolean;
  showEpics: boolean;
  q?: string;
}

export const DEFAULT_FILTERS: Filters = {
  project: 'all',
  assignee: 'all',
  priority: 'all',
  blocked: 'all',
  showTodo: true,
  showInProgress: true,
  showScheduled: true,
  showDone: false,
  showCancelled: false,
  showEpics: false,
};

// Bumped to v6 to force-reset stale v5 state that lacks the new visibility keys.
const LS_KEY = 'tracker_filters_v6';

// ── localStorage persistence ─────────────────────────────────────────────────

export function saveFilters(f: Filters): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(f));
  } catch {
    // storage might be unavailable (private browsing, quota)
  }
}

export function loadFilters(): Filters {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return { ...DEFAULT_FILTERS };
    const parsed = JSON.parse(raw) as Partial<Filters>;
    return {
      ...DEFAULT_FILTERS,
      ...parsed,
      priority: typeof parsed.priority === 'string' ? parsed.priority : 'all',
    };
  } catch {
    return { ...DEFAULT_FILTERS };
  }
}

// ── URL sync (shareable links — visibility flags excluded) ───────────────────

export function encodeFilters(f: Filters): string {
  const p = new URLSearchParams();
  if (f.project !== 'all') p.set('project', f.project);
  if (f.assignee !== 'all') p.set('assignee', f.assignee);
  if (f.priority !== 'all') p.set('priority', f.priority);
  if (f.blocked === 'blocked') p.set('blocked', 'true');
  else if (f.blocked === 'unblocked') p.set('blocked', 'false');
  if (f.q?.trim()) p.set('q', f.q.trim());
  return p.toString();
}

export function decodeFilters(p: URLSearchParams): Partial<Filters> | null {
  // Only decode the URL-resident fields. Visibility is handled by loadFilters.
  const hasUrlFields =
    p.has('project') ||
    p.has('assignee') ||
    p.has('priority') ||
    p.has('blocked') ||
    p.has('q');
  if (!hasUrlFields) return null;

  const blockedRaw = p.get('blocked');
  const blocked: BlockedState =
    blockedRaw === 'true' || blockedRaw === 'blocked'
      ? 'blocked'
      : blockedRaw === 'false' || blockedRaw === 'unblocked'
        ? 'unblocked'
        : 'all';
  return {
    project: p.get('project') ?? 'all',
    assignee: p.get('assignee') ?? 'all',
    priority: p.get('priority') ?? 'all',
    blocked,
    q: p.get('q') ?? undefined,
  };
}

export function syncFiltersToUrl(filters: Filters): void {
  const qs = encodeFilters(filters);
  const url = qs ? `?${qs}` : window.location.pathname;
  window.history.replaceState(null, '', url);
}

export function readFilters(): Filters {
  // Start from localStorage (which holds visibility state + last URL-synced
  // filter values as a fallback). Then overlay URL params on top so that
  // shareable links override the stored project/assignee/priority/blocked.
  const stored = loadFilters();
  const urlOverrides = decodeFilters(new URLSearchParams(window.location.search));
  if (urlOverrides) return { ...stored, ...urlOverrides };
  return stored;
}
