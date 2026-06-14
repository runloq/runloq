/** Left sidebar — all filter controls.
 *
 * Selection models:
 *   Project    → pill row, click chip to select, click active chip to clear
 *   Assignee   → same
 *   Priority   → same (P0 / P1 / P2 / P3)
 *   Blocked    → two chips (Blocked / Unblocked), click active chip to clear
 *   Visibility → Show epics / Show done / Show cancelled toggles
 *
 * No "All" chip in any row — the default (no selection) IS "all".
 */

import { useState } from 'react';
import { cn } from '@/lib/cn';
import type { Filters, BlockedState } from '@/lib/filterUrl';
import { useMeta } from '@/hooks/useMeta';
import {
  type SavedView,
  saveView,
  toSavedFilterState,
  matchesSavedView,
  hasActiveFilters,
} from '@/lib/savedViews';

// ── Color maps for filter chips ──────────────────────────────────────────────
// Each entry is [activeBg, activeText, activeBorder] Tailwind classes that
// match the token colors used on cards and badges.

const PROJECT_PILL: Record<string, string> = {
  SYS: 'bg-proj-sys/15 text-proj-sys border-proj-sys/50',
  ARC: 'bg-proj-arc/15 text-proj-arc border-proj-arc/50',
  VER: 'bg-proj-ver/15 text-proj-ver border-proj-ver/50',
  PUR: 'bg-proj-pur/15 text-proj-pur border-proj-pur/50',
  DUC: 'bg-proj-duc/15 text-proj-duc border-proj-duc/50',
  FRG: 'bg-proj-frg/15 text-proj-frg border-proj-frg/50',
  ATL: 'bg-proj-atl/15 text-proj-atl border-proj-atl/50',
};

const PRIORITY_PILL: Record<string, string> = {
  P0: 'bg-p0/15 text-p0 border-p0/50',
  P1: 'bg-p1/15 text-p1 border-p1/50',
  P2: 'bg-p2/15 text-p2 border-p2/50',
  P3: 'bg-p3/15 text-p3 border-p3/50',
};

// ── Primitive: pill button ───────────────────────────────────────────────────

function Pill({
  active,
  onClick,
  children,
  activeClass,
  className,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  /** Tailwind class(es) to apply when the pill is active. Defaults to accent. */
  activeClass?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'font-mono text-[11px] px-2 py-0.5 rounded-full border cursor-pointer',
        'transition-colors',
        active
          ? (activeClass ?? 'bg-accent/15 text-accent border-accent/50')
          : 'bg-surface text-muted border-border hover:border-border-strong hover:text-fg',
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  label,
  badge,
  children,
}: {
  label: string;
  badge?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
          {label}
        </span>
        {badge != null && badge > 0 && (
          <span className="font-mono text-[10px] tabular-nums bg-fg/10 text-fg rounded-full px-1.5 py-0 leading-4">
            {badge}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  );
}

// ── Pill row ─────────────────────────────────────────────────────────────────
// No "All" chip. Clicking the active chip clears selection back to 'all'.

function PillRow({
  label,
  values,
  selected,
  onSelect,
  formatLabel,
  colorMap,
}: {
  label: string;
  values: string[];
  selected: string;
  onSelect: (v: string) => void;
  formatLabel?: (v: string) => string;
  /** Optional map of value → active Tailwind class(es). */
  colorMap?: Record<string, string>;
}) {
  return (
    <Section label={label}>
      {values.map((v) => (
        <Pill
          key={v}
          active={selected === v}
          activeClass={colorMap?.[v]}
          onClick={() => onSelect(selected === v ? 'all' : v)}
        >
          {formatLabel ? formatLabel(v) : v}
        </Pill>
      ))}
    </Section>
  );
}

// ── Blocked filter — two chips, toggle-to-clear ──────────────────────────────

const BLOCKED_OPTIONS: { value: Exclude<BlockedState, 'all'>; label: string }[] = [
  { value: 'blocked', label: '⊘ Blocked' },
  { value: 'unblocked', label: 'Unblocked' },
];

function BlockedFilter({
  value,
  onChange,
}: {
  value: BlockedState;
  onChange: (v: BlockedState) => void;
}) {
  return (
    <Section label="Blocked">
      {BLOCKED_OPTIONS.map(({ value: v, label }) => (
        <Pill
          key={v}
          active={value === v}
          onClick={() => onChange(value === v ? 'all' : v)}
        >
          {label}
        </Pill>
      ))}
    </Section>
  );
}

// ── Toggle row ───────────────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer group">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      <span
        className={cn(
          'w-7 h-4 rounded-full border transition-colors flex-shrink-0',
          checked
            ? 'bg-accent border-accent'
            : 'bg-surface border-border group-hover:border-border-strong',
        )}
        aria-hidden="true"
      >
        <span
          className={cn(
            'block w-3 h-3 rounded-full transition-transform mt-[1px]',
            checked ? 'bg-accent-fg translate-x-[14px]' : 'bg-muted translate-x-[1px]',
          )}
        />
      </span>
      <span
        className={cn(
          'font-mono text-[11px] transition-colors',
          checked ? 'text-fg' : 'text-muted group-hover:text-fg',
        )}
      >
        {children}
      </span>
    </label>
  );
}

// ── Main Sidebar export ──────────────────────────────────────────────────────

export function Sidebar({
  value,
  onChange,
  savedViews,
  onViewsChange,
}: {
  value: Filters;
  onChange: (next: Filters) => void;
  savedViews: SavedView[];
  onViewsChange: (views: SavedView[]) => void;
}) {
  const { data: meta } = useMeta();
  const [saveNameDraft, setSaveNameDraft] = useState('');
  const [savingAs, setSavingAs] = useState(false);

  const projects = meta?.projects ?? ['TASK'];
  const assignees = meta?.assignees ?? ['agent', 'alice', 'bob'];
  const priorities = meta?.priorities ?? ['P0', 'P1', 'P2', 'P3'];

  const hasAnyFilter =
    value.project !== 'all' ||
    value.assignee !== 'all' ||
    value.priority !== 'all' ||
    value.blocked !== 'all' ||
    !value.showTodo ||
    !value.showInProgress ||
    !value.showScheduled ||
    value.showDone ||
    value.showCancelled ||
    value.showEpics;

  // "Save as…" is shown when URL-resident filters are active AND the current
  // state doesn't already match an existing saved view.
  const currentState = toSavedFilterState(value);
  const isFiltersActive = hasActiveFilters(currentState);
  const alreadySavedAs = matchesSavedView(currentState, savedViews);
  const showSaveAs = isFiltersActive && !alreadySavedAs;

  function set<K extends keyof Filters>(key: K, val: Filters[K]) {
    onChange({ ...value, [key]: val });
  }

  function clearAll() {
    onChange({
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
    });
  }

  function commitSaveAs() {
    const name = saveNameDraft.trim();
    if (!name) return;
    const next = saveView(name, currentState);
    onViewsChange(next);
    setSavingAs(false);
    setSaveNameDraft('');
  }

  return (
    <aside
      className={cn(
        // Mobile (<md): bottom sheet — slides up from bottom, max 80% of
        // viewport height, scrollable, rounded top corners.
        'fixed inset-x-0 bottom-0 z-40 w-full max-h-[80vh] overflow-y-auto',
        'bg-bg border-t border-border rounded-t-xl px-4 py-4 space-y-5',
        'animate-in slide-in-from-bottom duration-200',
        // Desktop (md+): inline left rail in the flex layout.
        'md:static md:inset-auto md:bottom-auto md:z-auto md:max-h-none md:h-full',
        'md:w-48 md:flex-shrink-0 md:border-r md:border-t-0 md:border-border md:rounded-none md:px-3 md:animate-none',
      )}
    >
      {/* Drag handle — mobile bottom sheet affordance, hidden on desktop */}
      <div className="md:hidden flex justify-center mb-1 -mt-1" aria-hidden="true">
        <div className="w-10 h-1 rounded-full bg-border" />
      </div>

      {/* Project — radio */}
      <PillRow
        label="Project"
        values={projects}
        selected={value.project}
        onSelect={(v) => set('project', v)}
        colorMap={PROJECT_PILL}
      />

      {/* Assignee — radio */}
      <PillRow
        label="Assignee"
        values={assignees}
        selected={value.assignee}
        onSelect={(v) => set('assignee', v)}
      />

      {/* Priority — radio (single selection) */}
      <PillRow
        label="Priority"
        values={priorities}
        selected={value.priority}
        onSelect={(v) => set('priority', v)}
        colorMap={PRIORITY_PILL}
      />

      {/* Blocked — tri-state radio */}
      <BlockedFilter
        value={value.blocked}
        onChange={(v) => set('blocked', v)}
      />

      {/* Divider */}
      <div className="border-t border-border" />

      {/* Visibility — one toggle per board column. */}
      <div className="space-y-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted block">
          Columns
        </span>
        <Toggle checked={value.showTodo} onChange={(v) => set('showTodo', v)}>
          Todo
        </Toggle>
        <Toggle checked={value.showInProgress} onChange={(v) => set('showInProgress', v)}>
          In progress
        </Toggle>
        <Toggle checked={value.showScheduled} onChange={(v) => set('showScheduled', v)}>
          Scheduled
        </Toggle>
        <Toggle checked={value.showDone} onChange={(v) => set('showDone', v)}>
          Done
        </Toggle>
        <Toggle checked={value.showCancelled} onChange={(v) => set('showCancelled', v)}>
          Cancelled
        </Toggle>
        <Toggle checked={value.showEpics} onChange={(v) => set('showEpics', v)}>
          Epics
        </Toggle>
      </div>

      {/* Save as… — only when URL-resident filters are active and not already saved */}
      {showSaveAs && (
        <div className="space-y-1.5">
          {savingAs ? (
            <div className="space-y-1">
              <input
                autoFocus
                value={saveNameDraft}
                onChange={(e) => setSaveNameDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitSaveAs();
                  if (e.key === 'Escape') {
                    setSavingAs(false);
                    setSaveNameDraft('');
                  }
                }}
                placeholder="View name…"
                className="w-full bg-surface-2 border border-border rounded px-2 py-1 text-[11px] font-mono text-fg outline-none focus:border-accent placeholder:text-muted/60"
                aria-label="Name for saved view"
              />
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={commitSaveAs}
                  disabled={!saveNameDraft.trim()}
                  className="text-[11px] font-mono text-accent hover:text-accent/80 transition-colors disabled:opacity-40 disabled:pointer-events-none"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSavingAs(false);
                    setSaveNameDraft('');
                  }}
                  className="text-[11px] font-mono text-muted hover:text-fg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setSavingAs(true)}
              className="text-[11px] font-mono text-muted hover:text-fg underline-offset-2 hover:underline transition-colors"
            >
              Save as…
            </button>
          )}
        </div>
      )}

      {/* Clear all — only visible when any filter is active */}
      {hasAnyFilter && (
        <button
          type="button"
          onClick={clearAll}
          className="text-[11px] text-muted hover:text-fg underline-offset-2 hover:underline transition-colors"
        >
          Clear all
        </button>
      )}
    </aside>
  );
}
