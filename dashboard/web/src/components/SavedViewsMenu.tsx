/**
 * SavedViewsMenu — TopBar dropdown for named filter views.
 *
 * Features:
 *  - Lists saved views; clicking one restores filters.
 *  - "Manage…" dialog: rename + delete.
 *
 * "Save current as…" lives in the Sidebar (Sidebar.tsx) so it's
 * contextually close to the filter controls.
 */

import { useState, useCallback } from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { BookMarked, Pencil, Trash2, Check, X } from 'lucide-react';
import { cn } from '@/lib/cn';
import {
  type SavedView,
  deleteView,
  renameView,
  savedViewToFilters,
} from '@/lib/savedViews';
import type { Filters } from '@/lib/filterUrl';

// ── Inline rename row ─────────────────────────────────────────────────────────

function RenameRow({
  view,
  onDone,
}: {
  view: SavedView;
  onDone: (views: SavedView[]) => void;
}) {
  const [draft, setDraft] = useState(view.name);

  function commit() {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === view.name) {
      onDone([]); // no-op — signal cancel by passing empty
      return;
    }
    const next = renameView(view.name, trimmed);
    onDone(next);
  }

  return (
    <div className="flex items-center gap-1 px-2 py-1">
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') onDone([]);
        }}
        className="flex-1 bg-surface-2 border border-border rounded px-1.5 py-0.5 text-[11px] font-mono text-fg outline-none focus:border-accent"
        aria-label={`Rename view ${view.name}`}
      />
      <button
        type="button"
        onClick={commit}
        className="p-0.5 text-muted hover:text-fg rounded transition-colors"
        aria-label="Confirm rename"
      >
        <Check className="h-3 w-3" />
      </button>
      <button
        type="button"
        onClick={() => onDone([])}
        className="p-0.5 text-muted hover:text-fg rounded transition-colors"
        aria-label="Cancel rename"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SavedViewsMenu({
  views,
  onViewsChange,
  onSelectView,
}: {
  /** Current list of saved views (parent holds state). */
  views: SavedView[];
  /** Called with the updated views list after any mutation. */
  onViewsChange: (views: SavedView[]) => void;
  /** Called when user clicks a view to restore it. */
  onSelectView: (filters: Filters) => void;
}) {
  const [open, setOpen] = useState(false);
  const [renamingName, setRenamingName] = useState<string | null>(null);

  const handleDelete = useCallback(
    (name: string) => {
      const next = deleteView(name);
      onViewsChange(next);
    },
    [onViewsChange],
  );

  const handleRenameCommit = useCallback(
    (next: SavedView[]) => {
      setRenamingName(null);
      if (next.length > 0) onViewsChange(next);
    },
    [onViewsChange],
  );

  const handleSelectView = useCallback(
    (view: SavedView) => {
      // Restore the full board shape: filters AND column visibility. Legacy
      // views (saved before visibility was captured) fall back to defaults.
      onSelectView(savedViewToFilters(view) as Filters);
      setOpen(false);
    },
    [onSelectView],
  );

  const isEmpty = views.length === 0;

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(
            'flex items-center gap-1.5 h-7 px-2.5 rounded-md border text-[12px] transition-colors cursor-pointer',
            views.length > 0
              ? 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg'
              : 'border-border bg-surface text-muted/50 hover:text-muted',
          )}
          aria-label="Saved views"
          title="Saved views"
        >
          <BookMarked className="h-3 w-3 flex-shrink-0" />
          <span className="hidden md:inline">Views</span>
          {views.length > 0 && (
            <span className="hidden md:inline font-mono text-[10px] tabular-nums bg-fg/10 rounded-full px-1.5 leading-4">
              {views.length}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className={cn(
            'z-[70] min-w-[200px] max-w-[280px] rounded-lg border border-border-strong bg-surface',
            'shadow-[var(--shadow-modal)] p-1',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'duration-100 origin-top-right',
          )}
        >
          {isEmpty ? (
            <div className="px-3 py-2 text-[11px] text-muted font-mono italic">
              No saved views yet.
              <br />
              Set filters and use "Save as…" in the sidebar.
            </div>
          ) : (
            <>
              <DropdownMenu.Label className="px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
                Views
              </DropdownMenu.Label>

              {views.map((view) =>
                renamingName === view.name ? (
                  <RenameRow
                    key={view.name}
                    view={view}
                    onDone={handleRenameCommit}
                  />
                ) : (
                  <div
                    key={view.name}
                    className="flex items-center gap-1 group rounded-md"
                  >
                    <DropdownMenu.Item
                      onSelect={() => handleSelectView(view)}
                      className={cn(
                        'flex-1 flex items-center gap-2 px-2 py-1.5 rounded-md',
                        'font-mono text-[12px] text-fg cursor-pointer',
                        'outline-none select-none',
                        'data-[highlighted]:bg-surface-2',
                      )}
                    >
                      <BookMarked className="h-3 w-3 text-muted flex-shrink-0" />
                      <span className="truncate">{view.name}</span>
                    </DropdownMenu.Item>

                    {/* Rename + Delete — only shown on hover via group */}
                    <div className="flex items-center gap-0.5 pr-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setRenamingName(view.name);
                        }}
                        className="p-1 rounded text-muted hover:text-fg transition-colors"
                        aria-label={`Rename ${view.name}`}
                        title="Rename"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(view.name);
                        }}
                        className="p-1 rounded text-muted hover:text-p0 transition-colors"
                        aria-label={`Delete ${view.name}`}
                        title="Delete"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                ),
              )}
            </>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
