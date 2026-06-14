import { cn } from '@/lib/cn';
import type { Issue } from '@/lib/schemas';
import { Card } from './Card';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';

const PRIORITY_ORDER = ['P0', 'P1', 'P2', 'P3'] as const;
type Priority = (typeof PRIORITY_ORDER)[number];

const PRIORITY_LABEL: Record<Priority, string> = {
  P0: 'P0 — Critical',
  P1: 'P1 — High',
  P2: 'P2 — Medium',
  P3: 'P3 — Low',
};

const PRIORITY_CLASS: Record<Priority, string> = {
  P0: 'text-p0 border-p0/30',
  P1: 'text-p1 border-p1/30',
  P2: 'text-p2 border-p2/30',
  P3: 'text-p3 border-p3/30',
};

/** A droppable zone for a specific priority bucket within a column.
 *  The id encodes both status and priority so Board.onDragEnd can
 *  read both from `over.data.current`. */
function PriorityBucket({
  columnStatus,
  priority,
  issues,
  orderedIds,
}: {
  columnStatus: string;
  priority: Priority;
  issues: Issue[];
  /** Flat ordered list of all visible card IDs — forwarded to Card for range selection. */
  orderedIds: string[];
}) {
  const bucketId = `${columnStatus}::${priority}`;
  const { setNodeRef, isOver } = useDroppable({
    id: bucketId,
    data: { columnStatus, priority },
  });

  return (
    <SortableContext
      items={issues.map((i) => i.id)}
      strategy={verticalListSortingStrategy}
    >
      <div
        ref={setNodeRef}
        className={cn(
          'flex flex-col gap-1.5 min-h-[32px] rounded-sm transition-colors',
          isOver && 'bg-surface-2',
        )}
      >
        {issues.length === 0 ? (
          /* Invisible placeholder keeps the drop zone active even when empty */
          <div className="h-6" aria-hidden="true" />
        ) : (
          issues.map((i) => (
            <Card key={i.id} issue={i} orderedIds={orderedIds} />
          ))
        )}
      </div>
    </SortableContext>
  );
}

export function Column({
  title,
  accent,
  issues,
  orderedIds,
  emptyHint = 'Nothing here.',
}: {
  title: string;
  accent?: 'todo' | 'in_progress' | 'scheduled' | 'done';
  issues: Issue[];
  /** Flat ordered list of all visible card IDs — forwarded to Card for range selection. */
  orderedIds: string[];
  emptyHint?: string;
}) {
  // Group issues by priority, preserving P0→P3 order.
  const byPriority: Record<Priority, Issue[]> = {
    P0: [],
    P1: [],
    P2: [],
    P3: [],
  };
  for (const issue of issues) {
    const p = issue.priority as Priority;
    if (byPriority[p]) byPriority[p].push(issue);
    else byPriority.P3.push(issue);
  }

  return (
    <section className="flex flex-col min-w-[180px]">
      <header className="flex items-center justify-between px-1 pb-2 border-b border-border">
        <h2
          className={cn(
            'text-[11px] font-semibold uppercase tracking-wider',
            accent === 'in_progress' && 'text-status-active',
            accent === 'scheduled' && 'text-status-scheduled',
            accent === 'done' && 'text-muted',
          )}
        >
          {title}
        </h2>
        <span className="font-mono text-[11px] text-muted tabular-nums">
          {issues.length}
        </span>
      </header>

      {issues.length === 0 ? (
        /* Empty state: single droppable zone so cards can be dropped into empty columns */
        <div className="px-1 py-2">
          <p className="text-[12px] text-muted">{emptyHint}</p>
          <PriorityBucket
            columnStatus={accent ?? 'unknown'}
            priority="P3"
            issues={[]}
            orderedIds={orderedIds}
          />
        </div>
      ) : (
        <div className={cn('pt-1', accent === 'done' && '[&>div>button]:opacity-70')}>
          {PRIORITY_ORDER.map((p) => {
            const group = byPriority[p];
            // Always render each priority separator so users can drag into any bucket.
            return (
              <div key={p} className="mt-2 first:mt-1">
                {/* Priority section header — always visible */}
                <div
                  className={cn(
                    'flex items-center gap-1.5 mb-1 px-0.5',
                    'border-b',
                    PRIORITY_CLASS[p],
                  )}
                >
                  <span
                    className={cn(
                      'font-mono text-[10px] font-medium',
                      PRIORITY_CLASS[p].split(' ')[0], // just the text-* part
                    )}
                  >
                    {PRIORITY_LABEL[p]}
                  </span>
                  <span className="font-mono text-[10px] text-muted tabular-nums">
                    {group.length}
                  </span>
                </div>
                <PriorityBucket
                  columnStatus={accent ?? 'unknown'}
                  priority={p}
                  issues={group}
                  orderedIds={orderedIds}
                />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
