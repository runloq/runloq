import { cn } from '@/lib/cn';
import type { Issue } from '@/lib/schemas';
import { useModalStack } from '@/lib/modalStack';
import { useEpicChildren, sortChildrenForCard } from '@/hooks/useEpicChildren';
import { ProjectChip } from './ProjectChip';
import { ScheduledBadge } from './ScheduledBadge';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useUpdate } from '@/hooks/useMutations';
import { useEffect, useRef, useState } from 'react';
import { useSelection } from '@/lib/selection';

/** Project → left-border color. Cards are sorted by priority within a column,
 *  so the border carries the project signal (more useful at-a-glance than
 *  re-deriving "what project is this?" from the ID prefix). */
const PROJECT_BORDER: Record<string, string> = {
  SYS: 'border-l-proj-sys',
  ARC: 'border-l-proj-arc',
  VER: 'border-l-proj-ver',
  PUR: 'border-l-proj-pur',
  DUC: 'border-l-proj-duc',
  FRG: 'border-l-proj-frg',
  PAR: 'border-l-proj-par',
  ATL: 'border-l-proj-atl',
};

/** Priority text tint — kept since the priority badge is the only thing
 *  carrying the priority signal now that the border moved to project. */
const PRIO_BADGE: Record<string, string> = {
  P0: 'text-p0',
  P1: 'text-p1',
  P2: 'text-p2',
  P3: 'text-p3',
};

/** A small clickable relation pill for the card's relations row. Each pill
 *  pushes its target onto the modal stack, stopping propagation so the card's
 *  own click handler (which opens the current ticket) doesn't fire. */
function RelationChip({
  id,
  prefix,
  tone = 'neutral',
  title,
}: {
  id: string;
  prefix: string;
  tone?: 'neutral' | 'warn' | 'epic';
  title?: string;
}) {
  const push = useModalStack((s) => s.push);
  const toneClass =
    tone === 'warn'
      ? 'text-p1 border-p1/40 hover:bg-p1/10'
      : tone === 'epic'
        ? 'text-accent border-accent/40 hover:bg-accent/10'
        : 'text-muted border-border hover:bg-surface-2 hover:text-fg';
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        push(id);
      }}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      title={title ?? id}
      className={cn(
        'font-mono text-[10px] px-1.5 py-[1px] rounded border transition-colors cursor-pointer',
        toneClass,
      )}
    >
      <span className="opacity-70 mr-0.5">{prefix}</span>
      {id}
    </button>
  );
}

function CountChip({
  count,
  prefix,
  tone,
  onClick,
  title,
}: {
  count: number;
  prefix: string;
  tone: 'epic' | 'warn';
  onClick: () => void;
  title: string;
}) {
  const toneClass =
    tone === 'warn'
      ? 'text-p1 border-p1/40 hover:bg-p1/10'
      : 'text-accent border-accent/40 hover:bg-accent/10';
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      title={title}
      className={cn(
        'font-mono text-[10px] px-1.5 py-[1px] rounded border transition-colors cursor-pointer',
        toneClass,
      )}
    >
      <span className="opacity-70 mr-0.5">{prefix}</span>
      {count}
    </button>
  );
}

const CHILD_CHIP_LIMIT = 9;

export function Card({
  issue,
  orderedIds = [],
}: {
  issue: Issue;
  /** Flat ordered list of all visible card IDs — used for Shift-click range selection. */
  orderedIds?: string[];
}) {
  const open = useModalStack((s) => s.push);
  const isEpic = issue.issue_type === 'epic';

  // Selection store — derive isSelected via stable selector to avoid re-renders.
  const toggle = useSelection((s) => s.toggle);
  const addRange = useSelection((s) => s.addRange);
  const isSelected = useSelection((s) => s.selected.has(issue.id));
  const { data: epicChildren = [] } = useEpicChildren(issue.id, isEpic);
  const sortedChildren = isEpic ? sortChildrenForCard(epicChildren) : [];
  const childrenShown = sortedChildren.slice(0, CHILD_CHIP_LIMIT);
  const childrenOverflow = Math.max(0, sortedChildren.length - CHILD_CHIP_LIMIT);

  // Inline title editing state
  const [isEditing, setIsEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(issue.title);
  const inputRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdate(issue.id);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: issue.id,
    // Include priority in sortable data so Board.handleDragEnd can detect
    // priority-bucket changes (same column, different priority group).
    data: { columnStatus: issue.status, priority: issue.priority },
  });

  // Exit edit mode when a drag starts — must not conflict with SYS-176 DnD.
  useEffect(() => {
    if (isDragging && isEditing) {
      setIsEditing(false);
      setDraftTitle(issue.title);
    }
  }, [isDragging, isEditing, issue.title]);

  // Keep draftTitle in sync when issue.title changes externally (e.g. after
  // a mutation settles and React Query re-fetches the issues list).
  useEffect(() => {
    if (!isEditing) {
      setDraftTitle(issue.title);
    }
  }, [issue.title, isEditing]);

  function startEditing(e: React.MouseEvent | React.KeyboardEvent) {
    e.stopPropagation();
    setDraftTitle(issue.title);
    setIsEditing(true);
  }

  function commitEdit() {
    const trimmed = draftTitle.trim();
    if (trimmed && trimmed !== issue.title) {
      updateMutation.mutate({ title: trimmed });
    }
    setIsEditing(false);
  }

  function cancelEdit() {
    setDraftTitle(issue.title);
    setIsEditing(false);
  }

  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      commitEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      cancelEdit();
    } else {
      // Stop all other key events from bubbling to the card (e.g. Space starts
      // DnD via KeyboardSensor — we must prevent that while editing).
      e.stopPropagation();
    }
  }

  // Auto-focus + select-all when edit mode activates.
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };

  const hasRelations =
    !!issue.parent_id ||
    sortedChildren.length > 0 ||
    issue.blocked_by.length > 0 ||
    issue.linked_to.length > 0;

  function onCardClick(e: React.MouseEvent<HTMLDivElement>) {
    // Never open the modal while editing — the user is interacting with the
    // input, not requesting modal navigation.
    if (isEditing) return;

    // Modifier-click → selection, not modal
    const isModifier = e.metaKey || e.ctrlKey || e.shiftKey;
    if (isModifier) {
      e.preventDefault();
      e.stopPropagation();
      if (e.shiftKey) {
        addRange(issue.id, orderedIds);
      } else {
        toggle(issue.id);
      }
      return;
    }

    open(issue.id);
  }

  function onCardKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (isEditing) return;
    if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
      e.preventDefault();
      open(issue.id);
    }
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        'group w-full text-left bg-surface border border-border border-l-[3px] rounded-md',
        // min-h-[44px] ensures ≥44px tap target height on mobile (WCAG 2.5.5)
        'px-2.5 py-2 min-h-[44px] hover:border-border-strong hover:bg-surface-2 transition-colors cursor-pointer',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        isDragging && 'cursor-grabbing',
        PROJECT_BORDER[issue.id.split('-')[0]] ?? 'border-l-proj-duc',
        // Selection ring: 2px accent ring inside the card border
        isSelected && 'ring-2 ring-accent ring-inset bg-accent/5',
      )}
      {...attributes}
      {...listeners}
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onClick={onCardClick}
      onKeyDown={onCardKeyDown}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {/* Meta row — id, priority, agent/model OR assignee, scheduled.
              Single row keeps the visual rhythm consistent regardless of
              who's assigned (no split between left/right slots). */}
          <div className="flex items-center gap-1.5 flex-wrap text-[10px]">
            <span className="font-mono text-muted">{issue.id}</span>
            <span
              className={cn(
                'font-mono font-medium tabular-nums',
                PRIO_BADGE[issue.priority] ?? 'text-p3',
              )}
            >
              {issue.priority}
            </span>
            {issue.assignee === 'claude' ? (
              <>
                {issue.agent && (
                  <span className="font-mono text-muted">{issue.agent}</span>
                )}
                {issue.model && (
                  <span className="font-mono text-muted">·{issue.model}</span>
                )}
              </>
            ) : (
              <span className="font-mono text-muted">@{issue.assignee}</span>
            )}
            {issue.scheduled_at && <ScheduledBadge at={issue.scheduled_at} />}
          </div>
          <div className="relative group/title text-[13px] leading-snug mt-0.5">
            {issue.issue_type === 'epic' && !isEditing && (
              <span className="font-mono text-[10px] text-accent mr-1">▣</span>
            )}
            {isEditing ? (
              <input
                ref={inputRef}
                type="text"
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                onKeyDown={onInputKeyDown}
                onBlur={commitEdit}
                // Prevent DnD pointer sensor from capturing the pointer while
                // the user is typing — stopPropagation keeps the event local.
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
                className={cn(
                  'w-full bg-transparent border-0 border-b border-accent/60',
                  'text-[13px] leading-snug text-fg outline-none',
                  'focus:border-accent py-0 px-0',
                )}
                aria-label={`Edit title for ${issue.id}`}
              />
            ) : (
              <span
                className="truncate block pr-5"
                onDoubleClick={startEditing}
                title="Double-click to edit title"
              >
                {issue.title}
              </span>
            )}
            {/* Hover-revealed pencil — single-click to enter edit mode */}
            {!isEditing && (
              <button
                type="button"
                aria-label={`Edit title of ${issue.id}`}
                onClick={(e) => {
                  e.stopPropagation();
                  startEditing(e);
                }}
                onPointerDown={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                className={cn(
                  'absolute right-0 top-0 p-0.5 rounded',
                  'text-muted hover:text-fg transition-colors',
                  'opacity-0 group-hover/title:opacity-100',
                  'focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                )}
              >
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 12 12"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M8.5 1.5a1.414 1.414 0 0 1 2 2L3.5 10.5l-2.5.5.5-2.5L8.5 1.5Z"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            )}
          </div>
        </div>
        <ProjectChip project={issue.id.split('-')[0]} />
      </div>
      {hasRelations && (
        <div className="mt-1.5 flex items-center gap-1 flex-wrap">
          {issue.parent_id && (
            <RelationChip
              id={issue.parent_id}
              prefix="↑"
              tone="epic"
              title={`Parent: ${issue.parent_id}`}
            />
          )}
          {childrenShown.map((child) => (
            <RelationChip
              key={`c-${child.id}`}
              id={child.id}
              prefix="↳"
              tone="epic"
              title={`${child.id} · ${child.status} · ${child.title}`}
            />
          ))}
          {childrenOverflow > 0 && (
            <CountChip
              count={childrenOverflow}
              prefix="+"
              tone="epic"
              onClick={() => open(issue.id)}
              title={`${childrenOverflow} more (open epic to see all ${sortedChildren.length})`}
            />
          )}
          {issue.blocked_by.map((id) => (
            <RelationChip
              key={`b-${id}`}
              id={id}
              prefix="⊘"
              tone="warn"
              title={`Blocked by ${id}`}
            />
          ))}
          {issue.linked_to.map((id) => (
            <RelationChip
              key={`l-${id}`}
              id={id}
              prefix="⇄"
              title={`Linked to ${id}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
