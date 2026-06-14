import { useState, useEffect, useMemo } from 'react';
import { TicketModal } from '@/components/TicketModal';
import { SearchPalette } from '@/components/SearchPalette';
import { CreateModal } from '@/components/CreateModal';
import { Board } from '@/components/Board';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { useKeyboard } from '@/hooks/useKeyboard';
import { useSSE } from '@/hooks/useSSE';
import { useIssues } from '@/hooks/useIssues';
import { useModalStack } from '@/lib/modalStack';
import {
  type Filters,
  readFilters,
  saveFilters,
  syncFiltersToUrl,
} from '@/lib/filterUrl';
import { type SavedView, loadSavedViews } from '@/lib/savedViews';
import type { ListIssuesParams } from '@/lib/api';

/** Compute the status[] array to send to the API.
 *
 * We always fetch todo + in_progress + scheduled so the board has all active
 * data regardless of which columns are visible. Done/cancelled are added only
 * when their toggle is ON (they can be large, so avoid fetching them by default).
 * Column visibility is handled client-side in Board.tsx — the API just needs
 * to supply the right data set. */
function computeStatusParam(
  showDone: boolean,
  showCancelled: boolean,
): string[] | undefined {
  if (!showDone && !showCancelled) return undefined;
  const base = ['todo', 'in_progress', 'scheduled'];
  if (showDone) base.push('done');
  if (showCancelled) base.push('cancelled');
  return base;
}

function toListParams(f: Filters): ListIssuesParams {
  return {
    status: computeStatusParam(f.showDone, f.showCancelled),
    project: f.project !== 'all' ? [f.project] : undefined,
    priority: f.priority !== 'all' ? [f.priority] : undefined,
    assignee: f.assignee !== 'all' ? [f.assignee] : undefined,
    blocked_only: f.blocked === 'blocked' ? true : undefined,
    // 'unblocked' is handled client-side (API doesn't have unblocked_only)
    include_epics: f.showEpics,
  };
}

const SIDEBAR_LS_KEY = 'dashboard.sidebar.open';

export function App() {
  useSSE();

  const [filters, setFilters] = useState<Filters>(() => readFilters());
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => loadSavedViews());
  const [searchOpen, setSearchOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    const stored = localStorage.getItem(SIDEBAR_LS_KEY);
    if (stored !== null) return stored === 'true';
    // First load: default closed on mobile so it doesn't cover the board,
    // open on desktop so the filters are immediately discoverable.
    if (typeof window !== 'undefined' && window.matchMedia) {
      return !window.matchMedia('(max-width: 767px)').matches;
    }
    return true;
  });

  const closeStack = useModalStack((s) => s.close);

  /** True when viewport is below the `md:` breakpoint (768px). */
  const isMobile = () =>
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(max-width: 767px)').matches;

  // Persist to localStorage + URL on every filter change
  useEffect(() => {
    saveFilters(filters);
    syncFiltersToUrl(filters);
  }, [filters]);

  useEffect(() => {
    localStorage.setItem(SIDEBAR_LS_KEY, String(sidebarOpen));
  }, [sidebarOpen]);

  // Keyboard: `\` toggles the sidebar (matches Linear / VS Code muscle memory).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== '\\' || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === 'INPUT' ||
          t.tagName === 'TEXTAREA' ||
          t.isContentEditable)
      )
        return;
      e.preventDefault();
      setSidebarOpen((o) => !o);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useKeyboard({
    // ctrl+C → new task. Bound to ctrl on both mac and non-mac (no cmd
    // mapping). On non-mac ctrl+C is the system copy shortcut, so we yield
    // to the browser when there's an active text selection.
    'ctrl+c': () => {
      if ((window.getSelection()?.toString() ?? '').length > 0) return false;
      setCreateOpen(true);
    },
    // ctrl+S → search. Bound to ctrl on both platforms. Browser default
    // (Save Page As on non-mac) is preventDefault'd by useKeyboard.
    'ctrl+s': () => setSearchOpen(true),
    Escape: () => {
      // Esc has multiple targets — let the dialog primitives handle their own
      // first; this one fires only when no editable element is focused AND
      // no modal has its own escape handler (TicketModal handles its own).
      if (!searchOpen && !createOpen && !useModalStack.getState().stack.length) return;
      closeStack();
    },
  });

  /** Restore a saved view: filters AND column visibility (the full board shape). */
  function handleSelectView(view: Filters) {
    setFilters((prev) => ({
      ...prev,
      project: view.project,
      assignee: view.assignee,
      priority: view.priority,
      blocked: view.blocked,
      q: view.q,
      showTodo: view.showTodo,
      showInProgress: view.showInProgress,
      showScheduled: view.showScheduled,
      showDone: view.showDone,
      showCancelled: view.showCancelled,
      showEpics: view.showEpics,
    }));
  }

  const params = useMemo(() => toListParams(filters), [filters]);
  const { data: rawIssues = [], isLoading, error } = useIssues(params);

  // Client-side: apply 'unblocked' filter (API only has blocked_only)
  const issues = useMemo(() => {
    if (filters.blocked !== 'unblocked') return rawIssues;
    return rawIssues.filter((i) => i.blocked_by.length === 0);
  }, [rawIssues, filters.blocked]);

  return (
    <>
      <div className="flex flex-col h-screen overflow-hidden">
        <TopBar
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((o) => !o)}
          onSearchClick={() => setSearchOpen(true)}
          onCreateClick={() => setCreateOpen(true)}
          savedViews={savedViews}
          onViewsChange={setSavedViews}
          onSelectView={handleSelectView}
        />
        <div className="flex flex-1 min-h-0 relative">
          {sidebarOpen && (
            <>
              {/* Mobile-only backdrop — tap to dismiss the overlay sidebar.
                  Hidden at md+ where the sidebar is part of the flex layout. */}
              <div
                className="fixed inset-0 top-12 z-30 bg-bg/40 backdrop-blur-[1px] md:hidden"
                onClick={() => setSidebarOpen(false)}
                aria-hidden="true"
              />
              <Sidebar
                value={filters}
                onChange={(next) => {
                  setFilters(next);
                  // Auto-close after a filter pick on mobile so the user sees
                  // the result. Desktop sidebar stays open as expected.
                  if (isMobile()) setSidebarOpen(false);
                }}
                savedViews={savedViews}
                onViewsChange={setSavedViews}
              />
            </>
          )}
          <main className="flex-1 overflow-auto">
            {isLoading ? (
              <div className="px-6 py-8 text-muted text-[12px]">Loading…</div>
            ) : error ? (
              <div className="px-6 py-8 text-p0 text-[12px]">
                Couldn't load tickets:{' '}
                {error instanceof Error ? error.message : 'unknown error'}
              </div>
            ) : (
              <Board
                issues={issues}
                showTodo={filters.showTodo}
                showInProgress={filters.showInProgress}
                showScheduled={filters.showScheduled}
                showDone={filters.showDone}
                showCancelled={filters.showCancelled}
                showEpics={filters.showEpics}
              />
            )}
          </main>
        </div>
        <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />
        <CreateModal open={createOpen} onOpenChange={setCreateOpen} />
      </div>
      <TicketModal />
    </>
  );
}
