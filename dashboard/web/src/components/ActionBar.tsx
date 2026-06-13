/**
 * ActionBar — fixed bottom-center floating toolbar that appears when ≥1 card
 * is selected via modifier-click. Provides bulk Close, Priority, and Assignee
 * actions that fan out one mutation per selected ID via Promise.all.
 *
 * Animated: slides in from below and fades in when selection.size > 0.
 * Esc clears selection (wired in Board via useKeyboard).
 */
import { useState, useRef, useEffect } from 'react';
import { cn } from '@/lib/cn';
import { useSelection } from '@/lib/selection';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import type { Issue } from '@/lib/schemas';
import { type UpdateIssueInput } from '@/lib/schemas';

const PRIORITIES: Issue['priority'][] = ['P0', 'P1', 'P2', 'P3'];
// Use the UpdateIssueInput assignee type (the enum union) rather than Issue['assignee']
// (which is plain string) so bulk-assign calls match the API type.
type AssigneeValue = NonNullable<UpdateIssueInput['assignee']>;
const ASSIGNEES: AssigneeValue[] = [
  'claude',
  'agent',
  'alice',
  'bob',
];

// Priority badge colours reusing the same tokens as Card.tsx
const PRIO_COLOUR: Record<string, string> = {
  P0: 'text-p0',
  P1: 'text-p1',
  P2: 'text-p2',
  P3: 'text-p3',
};

function useClickOutside(
  ref: React.RefObject<HTMLElement | null>,
  onClickOutside: () => void,
) {
  useEffect(() => {
    function handlePointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClickOutside();
      }
    }
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [ref, onClickOutside]);
}

export function ActionBar() {
  const { selected, clear, size } = useSelection();
  const count = size();
  const qc = useQueryClient();

  // Close dropdown
  const [closeOpen, setCloseOpen] = useState(false);
  // Priority dropdown
  const [prioOpen, setPrioOpen] = useState(false);
  // Assignee dropdown
  const [assigneeOpen, setAssigneeOpen] = useState(false);

  const [loading, setLoading] = useState(false);

  const closeRef = useRef<HTMLDivElement>(null);
  const prioRef = useRef<HTMLDivElement>(null);
  const assigneeRef = useRef<HTMLDivElement>(null);

  useClickOutside(closeRef, () => setCloseOpen(false));
  useClickOutside(prioRef, () => setPrioOpen(false));
  useClickOutside(assigneeRef, () => setAssigneeOpen(false));

  if (count === 0) return null;

  /** Fan out bulk close mutations, optimistic per-card. */
  async function handleClose(status: 'cancelled' | 'done') {
    const ids = Array.from(selected);
    setLoading(true);
    setCloseOpen(false);

    // Optimistic: update all cards immediately in the cache
    await qc.cancelQueries({ queryKey: ['issues'] });
    const previous = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
    qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (old) => {
      if (!old) return old;
      return old.map((issue) =>
        ids.includes(issue.id) ? { ...issue, status } : issue,
      );
    });

    const results = await Promise.allSettled(
      ids.map((id) => api.closeIssue(id, { status })),
    );

    const failed = results
      .map((r, i) => (r.status === 'rejected' ? ids[i] : null))
      .filter(Boolean) as string[];

    if (failed.length > 0) {
      // Roll back failures only — restore those cards from the snapshot
      qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (current) => {
        if (!current) return current;
        return current.map((issue) => {
          if (!failed.includes(issue.id)) return issue;
          // Find the original from snapshot
          for (const [, data] of previous) {
            const orig = (data as Issue[])?.find?.((i) => i.id === issue.id);
            if (orig) return orig;
          }
          return issue;
        });
      });
      toast.error(`Failed to close ${failed.length} issue(s): ${failed.join(', ')}`);
    } else {
      toast.success(
        `Closed ${ids.length} issue${ids.length === 1 ? '' : 's'} as ${status}`,
      );
    }

    // Invalidate to sync confirmed server state
    qc.invalidateQueries({ queryKey: ['issues'] });
    setLoading(false);
    clear();
  }

  /** Fan out bulk priority updates, optimistic per-card. */
  async function handlePriority(priority: Issue['priority']) {
    const ids = Array.from(selected);
    setLoading(true);
    setPrioOpen(false);

    await qc.cancelQueries({ queryKey: ['issues'] });
    const previous = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
    qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (old) => {
      if (!old) return old;
      return old.map((issue) =>
        ids.includes(issue.id) ? { ...issue, priority } : issue,
      );
    });

    const results = await Promise.allSettled(
      ids.map((id) => api.updateIssue(id, { priority })),
    );

    const failed = results
      .map((r, i) => (r.status === 'rejected' ? ids[i] : null))
      .filter(Boolean) as string[];

    if (failed.length > 0) {
      qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (current) => {
        if (!current) return current;
        return current.map((issue) => {
          if (!failed.includes(issue.id)) return issue;
          for (const [, data] of previous) {
            const orig = (data as Issue[])?.find?.((i) => i.id === issue.id);
            if (orig) return orig;
          }
          return issue;
        });
      });
      toast.error(`Failed to update priority for ${failed.join(', ')}`);
    } else {
      toast.success(
        `Set ${ids.length} issue${ids.length === 1 ? '' : 's'} to ${priority}`,
      );
    }

    qc.invalidateQueries({ queryKey: ['issues'] });
    setLoading(false);
    clear();
  }

  /** Fan out bulk assignee updates, optimistic per-card. */
  async function handleAssignee(assignee: AssigneeValue) {
    const ids = Array.from(selected);
    setLoading(true);
    setAssigneeOpen(false);

    await qc.cancelQueries({ queryKey: ['issues'] });
    const previous = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
    qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (old) => {
      if (!old) return old;
      return old.map((issue) =>
        ids.includes(issue.id) ? { ...issue, assignee } : issue,
      );
    });

    const results = await Promise.allSettled(
      ids.map((id) => api.updateIssue(id, { assignee })),
    );

    const failed = results
      .map((r, i) => (r.status === 'rejected' ? ids[i] : null))
      .filter(Boolean) as string[];

    if (failed.length > 0) {
      qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (current) => {
        if (!current) return current;
        return current.map((issue) => {
          if (!failed.includes(issue.id)) return issue;
          for (const [, data] of previous) {
            const orig = (data as Issue[])?.find?.((i) => i.id === issue.id);
            if (orig) return orig;
          }
          return issue;
        });
      });
      toast.error(`Failed to reassign ${failed.join(', ')}`);
    } else {
      toast.success(
        `Assigned ${ids.length} issue${ids.length === 1 ? '' : 's'} to @${assignee}`,
      );
    }

    qc.invalidateQueries({ queryKey: ['issues'] });
    setLoading(false);
    clear();
  }

  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className={cn(
        'fixed bottom-6 left-1/2 -translate-x-1/2 z-50',
        'flex items-center gap-2 px-3 py-2',
        'bg-surface border border-border rounded-xl shadow-lg',
        'animate-in slide-in-from-bottom-4 fade-in duration-200',
        loading && 'pointer-events-none opacity-70',
      )}
    >
      {/* Count badge */}
      <span className="font-mono text-xs text-muted pr-1 select-none">
        {count} selected
      </span>

      <div className="w-px h-4 bg-border" aria-hidden />

      {/* Close dropdown */}
      <div className="relative" ref={closeRef}>
        <button
          type="button"
          aria-haspopup="true"
          aria-expanded={closeOpen}
          onClick={() => {
            setCloseOpen((o) => !o);
            setPrioOpen(false);
            setAssigneeOpen(false);
          }}
          className={cn(
            'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium',
            'bg-surface-2 hover:bg-surface-3 border border-border transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          )}
        >
          Close
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="none"
            aria-hidden="true"
            className="ml-0.5 opacity-60"
          >
            <path d="M2 3.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        {closeOpen && (
          <div
            role="menu"
            className={cn(
              'absolute bottom-full mb-1 left-0 min-w-[120px]',
              'bg-surface border border-border rounded-lg shadow-lg py-1 z-10',
            )}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => handleClose('cancelled')}
              className="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-2 transition-colors"
            >
              Cancelled
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => handleClose('done')}
              className="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-2 transition-colors"
            >
              Done
            </button>
          </div>
        )}
      </div>

      {/* Priority dropdown */}
      <div className="relative" ref={prioRef}>
        <button
          type="button"
          aria-haspopup="true"
          aria-expanded={prioOpen}
          onClick={() => {
            setPrioOpen((o) => !o);
            setCloseOpen(false);
            setAssigneeOpen(false);
          }}
          className={cn(
            'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium',
            'bg-surface-2 hover:bg-surface-3 border border-border transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          )}
        >
          Priority
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="none"
            aria-hidden="true"
            className="ml-0.5 opacity-60"
          >
            <path d="M2 3.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        {prioOpen && (
          <div
            role="menu"
            className={cn(
              'absolute bottom-full mb-1 left-0 min-w-[80px]',
              'bg-surface border border-border rounded-lg shadow-lg py-1 z-10',
            )}
          >
            {PRIORITIES.map((p) => (
              <button
                key={p}
                type="button"
                role="menuitem"
                onClick={() => handlePriority(p)}
                className={cn(
                  'w-full text-left px-3 py-1.5 text-xs hover:bg-surface-2 transition-colors font-mono font-medium',
                  PRIO_COLOUR[p],
                )}
              >
                {p}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Assignee dropdown */}
      <div className="relative" ref={assigneeRef}>
        <button
          type="button"
          aria-haspopup="true"
          aria-expanded={assigneeOpen}
          onClick={() => {
            setAssigneeOpen((o) => !o);
            setCloseOpen(false);
            setPrioOpen(false);
          }}
          className={cn(
            'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium',
            'bg-surface-2 hover:bg-surface-3 border border-border transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          )}
        >
          Assign
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="none"
            aria-hidden="true"
            className="ml-0.5 opacity-60"
          >
            <path d="M2 3.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        {assigneeOpen && (
          <div
            role="menu"
            className={cn(
              'absolute bottom-full mb-1 left-0 min-w-[110px]',
              'bg-surface border border-border rounded-lg shadow-lg py-1 z-10',
            )}
          >
            {ASSIGNEES.map((a) => (
              <button
                key={a}
                type="button"
                role="menuitem"
                onClick={() => handleAssignee(a)}
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-2 transition-colors font-mono"
              >
                @{a}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="w-px h-4 bg-border" aria-hidden />

      {/* Clear selection */}
      <button
        type="button"
        aria-label="Clear selection (Esc)"
        onClick={clear}
        title="Clear selection (Esc)"
        className={cn(
          'p-1.5 rounded-lg text-muted hover:text-fg transition-colors',
          'hover:bg-surface-2',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        )}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M2 2l8 8M10 2l-8 8"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>
    </div>
  );
}
