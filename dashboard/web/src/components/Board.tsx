import { cn } from '@/lib/cn';
import type { Issue } from '@/lib/schemas';
import { Card } from './Card';
import { Column } from './Column';
import { ActionBar } from './ActionBar';
import { useStatusUpdate, usePriorityUpdate } from '@/hooks/useMutations';
import { useSelection } from '@/lib/selection';
import { useKeyboard } from '@/hooks/useKeyboard';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { useState, useMemo } from 'react';

/**
 * Extended PointerSensor that ignores modifier-clicks (Cmd/Ctrl/Shift).
 * Modifier-clicks are reserved for multi-select in the selection store
 * and must not start a drag — they're handled in Card.onClick instead.
 */
class SelectionAwarePointerSensor extends PointerSensor {
  static activators: (typeof PointerSensor)['activators'] = [
    {
      eventName: 'onPointerDown',
      handler: ({ nativeEvent: event }: { nativeEvent: PointerEvent }) => {
        // Ignore modifier-clicks — let them fall through to the card's onClick
        if (event.metaKey || event.ctrlKey || event.shiftKey) return false;
        return true;
      },
    },
  ];
}

type ColumnStatus = 'todo' | 'in_progress' | 'scheduled' | 'done';
const COLUMN_STATUSES: ColumnStatus[] = ['todo', 'in_progress', 'scheduled', 'done'];

/** Labels shown in the mobile status pill row. */
const STATUS_PILL_LABELS: Record<ColumnStatus, string> = {
  todo: 'Todo',
  in_progress: 'In progress',
  scheduled: 'Scheduled',
  done: 'Done',
};

type ColumnGroups = {
  todo: Issue[];
  in_progress: Issue[];
  scheduled: Issue[];
  done: Issue[];
  cancelled: Issue[];
};

function buildGroups(issues: Issue[]): ColumnGroups {
  return {
    todo: issues.filter((i) => i.status === 'todo'),
    in_progress: issues.filter((i) => i.status === 'in_progress'),
    scheduled: issues.filter((i) => i.status === 'scheduled'),
    done: issues.filter((i) => i.status === 'done'),
    cancelled: issues.filter((i) => i.status === 'cancelled'),
  };
}

/** Renders a labelled board section (EPICS or ISSUES) with up to 5 status
 *  columns. Each column has an independent visibility flag so the grid
 *  shrinks/expands cleanly.
 *
 *  On mobile (<md): shows only the column matching `mobileStatus`; the pill
 *  row in Board handles the filter UI. On desktop: all visible columns shown
 *  in a grid sized by active column count. */
function BoardSection({
  label,
  issues,
  orderedIds,
  showTodo,
  showInProgress,
  showScheduled,
  showDone,
  showCancelled,
  capDone,
  mobileStatus,
}: {
  label: string;
  issues: Issue[];
  /** Flat ordered list of all visible card IDs — forwarded to Column for range selection. */
  orderedIds: string[];
  showTodo: boolean;
  showInProgress: boolean;
  showScheduled: boolean;
  showDone: boolean;
  showCancelled: boolean;
  /** If true, cap the Done column at 30 items (used for tasks). */
  capDone?: boolean;
  /** Status pill currently selected on mobile — only this column is visible on narrow viewports. */
  mobileStatus: ColumnStatus;
}) {
  const groups = buildGroups(issues);

  const activeCols = [showTodo, showInProgress, showScheduled, showDone, showCancelled].filter(
    Boolean,
  ).length;
  // Clamp to 1 so the grid is always valid even if everything is hidden.
  const cols = Math.max(1, activeCols) as 1 | 2 | 3 | 4 | 5;

  const doneIssues = capDone ? groups.done.slice(0, 30) : groups.done;
  const cancelledIssues = capDone ? groups.cancelled.slice(0, 30) : groups.cancelled;

  return (
    <section>
      <h2 className="font-mono text-[10px] uppercase tracking-wider text-muted mb-2">
        {label} ({issues.length})
      </h2>
      {/* Mobile (<md): single-column; each Column is hidden/shown based on mobileStatus.
          Desktop (md+): grid layout sized by active column count. */}
      <div
        className={cn(
          'grid gap-3 grid-cols-1',
          cols === 5 && 'md:grid-cols-5',
          cols === 4 && 'md:grid-cols-4',
          cols === 3 && 'md:grid-cols-3',
          cols === 2 && 'md:grid-cols-2',
        )}
      >
        {showTodo && (
          <div className={cn(mobileStatus !== 'todo' && 'hidden md:block')}>
            <Column title="Todo" accent="todo" issues={groups.todo} orderedIds={orderedIds} />
          </div>
        )}
        {showInProgress && (
          <div className={cn(mobileStatus !== 'in_progress' && 'hidden md:block')}>
            <Column
              title="In progress"
              accent="in_progress"
              issues={groups.in_progress}
              orderedIds={orderedIds}
              emptyHint="Pick something up."
            />
          </div>
        )}
        {showScheduled && (
          <div className={cn(mobileStatus !== 'scheduled' && 'hidden md:block')}>
            <Column
              title="Scheduled · this week"
              accent="scheduled"
              issues={groups.scheduled}
              orderedIds={orderedIds}
            />
          </div>
        )}
        {showDone && (
          <div className={cn(mobileStatus !== 'done' && 'hidden md:block')}>
            <Column
              title="Done"
              accent="done"
              issues={doneIssues}
              orderedIds={orderedIds}
              emptyHint="No closes yet."
            />
          </div>
        )}
        {showCancelled && (
          // Cancelled shares the 'done' pill on mobile (simplification)
          <div className={cn(mobileStatus !== 'done' && 'hidden md:block')}>
            <Column
              title="Cancelled"
              accent="done"
              issues={cancelledIssues}
              orderedIds={orderedIds}
              emptyHint="Nothing cancelled."
            />
          </div>
        )}
      </div>
    </section>
  );
}

export function Board({
  issues,
  showTodo = true,
  showInProgress = true,
  showScheduled = true,
  showDone = false,
  showCancelled = false,
  showEpics = false,
}: {
  issues: Issue[];
  showTodo?: boolean;
  showInProgress?: boolean;
  showScheduled?: boolean;
  showDone?: boolean;
  showCancelled?: boolean;
  showEpics?: boolean;
}) {
  const epics = showEpics ? issues.filter((i) => i.issue_type === 'epic') : [];
  const tasks = issues.filter((i) => i.issue_type !== 'epic');
  const statusUpdate = useStatusUpdate();
  const priorityUpdate = usePriorityUpdate();

  // Mobile status pill filter — only the selected status column is shown on
  // narrow viewports. Desktop always shows all visible columns (no pill row).
  const [mobileStatus, setMobileStatus] = useState<ColumnStatus>('todo');

  // Flat ordered list of all visible task IDs — used by Card for Shift-click range
  // selection. Derived from the tasks array preserving render order.
  const orderedIds = useMemo(() => tasks.map((i) => i.id), [tasks]);

  // Selection store — used for Cmd+A (select all) and Esc (clear).
  const { selectAll, clear: clearSelection } = useSelection();

  // Keyboard: Esc clears selection; Cmd+A selects all visible task cards.
  const bindings = useMemo(
    () => ({
      Escape: () => clearSelection(),
      'mod+a': () => selectAll(orderedIds),
    }),
    [clearSelection, selectAll, orderedIds],
  );
  useKeyboard(bindings);

  // Track the active (dragged) card to render the DragOverlay correctly.
  // Search both epics and tasks so the overlay works for any dragged item.
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeIssue = activeId
    ? (issues.find((t) => t.id === activeId) ?? null)
    : null;

  // SelectionAwarePointerSensor ignores modifier-clicks (Cmd/Ctrl/Shift) so
  // those events fall through to the card's onClick selection handler.
  // 5px distance threshold so plain clicks still fire without triggering drag.
  // TouchSensor uses a 250ms long-press + 5px tolerance so touch scrolling is
  // not blocked — the user can scroll freely; drag only starts on held press.
  // KeyboardSensor enables Space → arrow-key → Space drag for accessibility.
  const sensors = useSensors(
    useSensor(SelectionAwarePointerSensor, {
      activationConstraint: { distance: 5 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 250, tolerance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  function handleDragStart({ active }: DragStartEvent) {
    setActiveId(String(active.id));
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    setActiveId(null);
    if (!over) return;

    // Resolve destination column status and priority — the drop target can be:
    //   • a priority bucket (useDroppable, data.{columnStatus, priority})
    //   • a sibling card (useSortable, data.{columnStatus, priority})
    const overData = over.data.current as
      | { columnStatus?: ColumnStatus; priority?: string }
      | undefined;
    const activeData = active.data.current as
      | { columnStatus?: ColumnStatus; priority?: string }
      | undefined;

    const destStatus = overData?.columnStatus;
    const srcStatus = activeData?.columnStatus;
    const destPriority = overData?.priority;
    const srcPriority = activeData?.priority;

    if (!destStatus || !srcStatus) return;

    const statusChanged = destStatus !== srcStatus;
    const priorityChanged = destPriority && srcPriority && destPriority !== srcPriority;

    // Status change (column-to-column drag)
    if (statusChanged) {
      if (!COLUMN_STATUSES.includes(destStatus)) return;
      statusUpdate.mutate({ id: String(active.id), status: destStatus });
      return;
    }

    // Priority change within the same column (bucket-to-bucket drag)
    if (priorityChanged) {
      priorityUpdate.mutate({
        id: String(active.id),
        priority: destPriority as Issue['priority'],
      });
    }
  }

  // Derive which statuses are visible from props, for the mobile pill row.
  const visibleStatuses = useMemo(
    () =>
      (
        [
          showTodo && 'todo',
          showInProgress && 'in_progress',
          showScheduled && 'scheduled',
          showDone && 'done',
        ] as Array<ColumnStatus | false>
      ).filter((s): s is ColumnStatus => Boolean(s)),
    [showTodo, showInProgress, showScheduled, showDone],
  );

  // If the currently-selected mobile status becomes invisible (e.g. column
  // toggled off), fall back to the first visible status.
  const activeMobileStatus = visibleStatuses.includes(mobileStatus)
    ? mobileStatus
    : (visibleStatuses[0] ?? 'todo');

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      {/* Mobile status pill row — visible only on narrow viewports (<md).
          Tapping a pill filters the single-column board to that status. */}
      {visibleStatuses.length > 0 && (
        <div
          className="md:hidden sticky top-12 z-20 bg-bg/90 backdrop-blur-sm border-b border-border px-3 py-2 flex gap-1.5 overflow-x-auto"
          role="tablist"
          aria-label="Filter by status"
        >
          {visibleStatuses.map((s) => (
            <button
              key={s}
              type="button"
              role="tab"
              aria-selected={activeMobileStatus === s}
              onClick={() => setMobileStatus(s)}
              className={cn(
                'font-mono text-[11px] px-3 py-1 rounded-full border whitespace-nowrap transition-colors cursor-pointer',
                'min-h-[36px] flex items-center',
                activeMobileStatus === s
                  ? s === 'in_progress'
                    ? 'bg-status-active/15 text-status-active border-status-active/50'
                    : s === 'scheduled'
                      ? 'bg-status-scheduled/15 text-status-scheduled border-status-scheduled/50'
                      : 'bg-accent/15 text-accent border-accent/50'
                  : 'bg-surface text-muted border-border hover:border-border-strong hover:text-fg',
              )}
            >
              {STATUS_PILL_LABELS[s]}
            </button>
          ))}
        </div>
      )}

      <div className="px-3 pt-4 pb-6 md:px-6 flex flex-col gap-6 overflow-x-auto">
        {/* EPICS section — only when showEpics is on AND there are epics in view */}
        {showEpics && epics.length > 0 && (
          <>
            <BoardSection
              label="Epics"
              issues={epics}
              orderedIds={epics.map((i) => i.id)}
              showTodo={showTodo}
              showInProgress={showInProgress}
              showScheduled={showScheduled}
              showDone={showDone}
              showCancelled={showCancelled}
              mobileStatus={activeMobileStatus}
            />
            {/* Subtle divider between EPICS and ISSUES sections */}
            <hr className="border-border" />
          </>
        )}

        {/* ISSUES section — always rendered */}
        <BoardSection
          label="Issues"
          issues={tasks}
          orderedIds={orderedIds}
          showTodo={showTodo}
          showInProgress={showInProgress}
          showScheduled={showScheduled}
          showDone={showDone}
          showCancelled={showCancelled}
          capDone
          mobileStatus={activeMobileStatus}
        />
      </div>

      {/* DragOverlay renders a floating copy of the card while dragging.
          This keeps the original card in the list (at reduced opacity)
          while showing a crisp ghost that follows the cursor. */}
      <DragOverlay>
        {activeIssue ? <Card issue={activeIssue} /> : null}
      </DragOverlay>

      {/* Bulk action bar — appears when ≥1 card is selected */}
      <ActionBar />
    </DndContext>
  );
}
