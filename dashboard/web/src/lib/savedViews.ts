/**
 * Saved filter views — localStorage persistence.
 *
 * Key: 'tracker.savedViews'
 * Shape: SavedView[]
 *
 * A saved view captures the FULL board shape: the URL-resident filter fields
 * (project / assignee / priority / blocked / q) AND the column-visibility
 * toggles (showTodo / showInProgress / showScheduled / showDone / showCancelled
 * / showEpics). Visibility used to be excluded, which made any view whose intent
 * was "show the Done column" / "show Epics" restore nothing visible — clicking
 * it appeared to do nothing. Visibility is now part of the view contract.
 *
 * Visibility fields are optional on the type for backward-compat: views saved
 * before this change lack them and fall back to DEFAULT_VISIBILITY on restore.
 */

export interface VisibilityState {
  showTodo: boolean;
  showInProgress: boolean;
  showScheduled: boolean;
  showDone: boolean;
  showCancelled: boolean;
  showEpics: boolean;
}

export const DEFAULT_VISIBILITY: VisibilityState = {
  showTodo: true,
  showInProgress: true,
  showScheduled: true,
  showDone: false,
  showCancelled: false,
  showEpics: false,
};

export interface SavedFilterState extends Partial<VisibilityState> {
  project: string;
  assignee: string;
  priority: string;
  blocked: 'all' | 'blocked' | 'unblocked';
  q?: string;
}

/** Resolve a (possibly legacy) saved state's visibility, defaulting any missing flag. */
export function resolveVisibility(f: Partial<VisibilityState>): VisibilityState {
  return {
    showTodo: f.showTodo ?? DEFAULT_VISIBILITY.showTodo,
    showInProgress: f.showInProgress ?? DEFAULT_VISIBILITY.showInProgress,
    showScheduled: f.showScheduled ?? DEFAULT_VISIBILITY.showScheduled,
    showDone: f.showDone ?? DEFAULT_VISIBILITY.showDone,
    showCancelled: f.showCancelled ?? DEFAULT_VISIBILITY.showCancelled,
    showEpics: f.showEpics ?? DEFAULT_VISIBILITY.showEpics,
  };
}

export interface SavedView {
  name: string;
  filters: SavedFilterState;
  /** ISO timestamp of last save */
  savedAt: string;
}

const LS_KEY = 'tracker.savedViews';

// ── Read / write ─────────────────────────────────────────────────────────────

export function loadSavedViews(): SavedView[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SavedView[];
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

function writeSavedViews(views: SavedView[]): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(views));
  } catch {
    // storage unavailable (private browsing, quota)
  }
}

// ── CRUD helpers ─────────────────────────────────────────────────────────────

export function saveView(name: string, filters: SavedFilterState): SavedView[] {
  const views = loadSavedViews();
  const idx = views.findIndex((v) => v.name === name);
  const entry: SavedView = { name, filters, savedAt: new Date().toISOString() };
  if (idx >= 0) {
    views[idx] = entry;
  } else {
    views.push(entry);
  }
  writeSavedViews(views);
  return views;
}

export function deleteView(name: string): SavedView[] {
  const views = loadSavedViews().filter((v) => v.name !== name);
  writeSavedViews(views);
  return views;
}

export function renameView(oldName: string, newName: string): SavedView[] {
  const views = loadSavedViews().map((v) =>
    v.name === oldName ? { ...v, name: newName } : v,
  );
  writeSavedViews(views);
  return views;
}

// ── Utilities ─────────────────────────────────────────────────────────────────

/** Capture the full board shape (filters + visibility) from a Filters object. */
export function toSavedFilterState(filters: {
  project: string;
  assignee: string;
  priority: string;
  blocked: 'all' | 'blocked' | 'unblocked';
  q?: string;
} & Partial<VisibilityState>): SavedFilterState {
  return {
    project: filters.project,
    assignee: filters.assignee,
    priority: filters.priority,
    blocked: filters.blocked,
    q: filters.q,
    ...resolveVisibility(filters),
  };
}

/** True if the current state matches a saved view exactly (filters + visibility). */
export function matchesSavedView(
  current: SavedFilterState,
  views: SavedView[],
): SavedView | null {
  const cv = resolveVisibility(current);
  return (
    views.find((v) => {
      const vv = resolveVisibility(v.filters);
      return (
        v.filters.project === current.project &&
        v.filters.assignee === current.assignee &&
        v.filters.priority === current.priority &&
        v.filters.blocked === current.blocked &&
        (v.filters.q ?? '') === (current.q ?? '') &&
        vv.showTodo === cv.showTodo &&
        vv.showInProgress === cv.showInProgress &&
        vv.showScheduled === cv.showScheduled &&
        vv.showDone === cv.showDone &&
        vv.showCancelled === cv.showCancelled &&
        vv.showEpics === cv.showEpics
      );
    }) ?? null
  );
}

/** True if any filter OR any visibility toggle differs from the default board. */
export function hasActiveFilters(f: SavedFilterState): boolean {
  const v = resolveVisibility(f);
  return (
    f.project !== 'all' ||
    f.assignee !== 'all' ||
    f.priority !== 'all' ||
    f.blocked !== 'all' ||
    Boolean(f.q?.trim()) ||
    v.showTodo !== DEFAULT_VISIBILITY.showTodo ||
    v.showInProgress !== DEFAULT_VISIBILITY.showInProgress ||
    v.showScheduled !== DEFAULT_VISIBILITY.showScheduled ||
    v.showDone !== DEFAULT_VISIBILITY.showDone ||
    v.showCancelled !== DEFAULT_VISIBILITY.showCancelled ||
    v.showEpics !== DEFAULT_VISIBILITY.showEpics
  );
}

/** Build a full Filters-shaped object from a saved view (legacy-safe). */
export function savedViewToFilters(view: SavedView): SavedFilterState & VisibilityState {
  return {
    project: view.filters.project,
    assignee: view.filters.assignee,
    priority: view.filters.priority,
    blocked: view.filters.blocked,
    q: view.filters.q,
    ...resolveVisibility(view.filters),
  };
}
