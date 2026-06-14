import { useState, useEffect } from 'react';
import { useModalStack } from '@/lib/modalStack';
import { useIssue } from '@/hooks/useIssue';
import { useEvents } from '@/hooks/useEvents';
import { useClose, useUpdate } from '@/hooks/useMutations';
import { useKeyboard } from '@/hooks/useKeyboard';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from './ui/dialog';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { ProjectChip } from './ProjectChip';
import { ActivityTimeline } from './ActivityTimeline';
import { CommentThread } from './CommentThread';
import { TicketForm } from './TicketForm';
import { IssueIdLink } from './IssueIdLink';
import { Markdown } from './Markdown';
import { useInverseRelations } from '@/hooks/useInverseRelations';
import { cn } from '@/lib/cn';
import { STATUS_LABEL, type IssueStatus } from '@/lib/constants';

function transitionsFor(current: IssueStatus): IssueStatus[] {
  // 'scheduled' is intentionally excluded — switching to scheduled requires
  // picking a datetime, which the Mark-as quick-action can't capture. Use the
  // Edit form for that.
  const nonTerminal: IssueStatus[] = ['todo', 'in_progress', 'done', 'cancelled'];
  if (current === 'done' || current === 'cancelled') {
    return ['todo', 'in_progress'];
  }
  return nonTerminal.filter((s) => s !== current);
}

export function TicketModal() {
  const stack = useModalStack((s) => s.stack);
  const pop = useModalStack((s) => s.pop);
  const close = useModalStack((s) => s.close);
  const topId = stack.length ? stack[stack.length - 1] : null;
  const depth = stack.length;
  const isOpen = depth > 0;

  return (
    <Dialog open={isOpen} onOpenChange={(o) => { if (!o) close(); }}>
      <DialogContent
        showClose
        onEscapeKeyDown={(e) => {
          e.preventDefault();
          if (depth > 1) pop();
          else close();
        }}
      >
        {topId && (
          <ModalContent
            key={topId}
            issueId={topId}
            depth={depth}
            onBack={pop}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ModalContent({
  issueId,
  depth,
  onBack,
}: {
  issueId: string;
  depth: number;
  onBack: () => void;
}) {
  const { data: issue, isLoading, error } = useIssue(issueId);
  const { data: events = [] } = useEvents(issueId);
  const closeMut = useClose(issueId);
  const updateMut = useUpdate(issueId);
  const [editing, setEditing] = useState(false);
  const { blocks, children, linkedFrom } = useInverseRelations(issueId);

  function handleMarkAs(next: IssueStatus) {
    if (next === 'done' || next === 'cancelled') {
      closeMut.mutate({
        status: next,
        resolution: `Marked ${next} from dashboard`,
      });
    } else {
      updateMut.mutate({ status: next });
    }
  }

  // Reset editing state when the top of the stack changes
  useEffect(() => setEditing(false), [issueId]);

  // Update document.title when a ticket opens/closes
  useEffect(() => {
    const prevTitle = document.title;
    document.title = `${issueId} · runloq`;
    return () => {
      document.title = prevTitle;
    };
  }, [issueId]);

  // Keyboard shortcut: 'e' to enter edit mode (when not already editing)
  const keyBindings = {
    e: () => {
      if (!editing) setEditing(true);
    },
  };
  useKeyboard(keyBindings);

  if (isLoading) {
    return <div className="p-4 text-muted text-[12px]">Loading {issueId}…</div>;
  }
  if (error || !issue) {
    return (
      <div className="p-4 text-p0 text-[12px]">
        Couldn't load {issueId}: {error instanceof Error ? error.message : 'not found'}
      </div>
    );
  }

  if (editing) {
    return (
      <div>
        <DialogTitle className="font-mono text-[12px] text-muted mb-3">
          Editing {issue.id}
        </DialogTitle>
        <TicketForm
          mode="edit"
          initial={issue}
          onSaved={() => setEditing(false)}
          onCancel={() => setEditing(false)}
        />
      </div>
    );
  }

  const status = issue.status as IssueStatus;
  const transitions = transitionsFor(status);
  const mutating = closeMut.isPending || updateMut.isPending;

  return (
    <div className="space-y-4">
      {depth > 1 && (
        <button
          type="button"
          onClick={onBack}
          className="text-[11px] text-muted hover:text-fg flex items-center gap-1 cursor-pointer"
        >
          ← Back
        </button>
      )}
      <header className="space-y-2">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-mono text-[11px] text-muted">{issue.id}</span>
          <ProjectChip project={issue.id.split('-')[0]} />
          <Badge
            variant={
              issue.status === 'done' || issue.status === 'cancelled'
                ? 'default'
                : issue.status === 'in_progress'
                ? 'accent'
                : 'default'
            }
          >
            {STATUS_LABEL[issue.status] ?? issue.status}
          </Badge>
          <Badge variant={issue.priority === 'P0' ? 'danger' : 'default'}>
            {issue.priority}
          </Badge>
          {issue.issue_type === 'epic' && <Badge variant="accent">epic</Badge>}
          <div className="ml-auto flex gap-2 pr-8">
            <select
              value=""
              onChange={(e) => {
                const v = e.target.value as IssueStatus | '';
                if (v) handleMarkAs(v);
                e.target.value = '';
              }}
              disabled={mutating || transitions.length === 0}
              className={cn(
                'h-7 rounded-md border border-border bg-surface px-2 text-[12px]',
                'cursor-pointer hover:border-border-strong',
                'focus-visible:outline-none focus-visible:border-accent',
                'disabled:cursor-not-allowed disabled:opacity-60',
              )}
              aria-label="Mark as"
            >
              <option value="">Mark as</option>
              {transitions.map((t) => (
                <option key={t} value={t}>
                  {STATUS_LABEL[t]}
                </option>
              ))}
            </select>
            <Button size="sm" variant="default" onClick={() => setEditing(true)} title="Edit (press e)">
              Edit
            </Button>
          </div>
        </div>
        <DialogTitle className="text-[15px] font-medium leading-snug">
          {issue.title}
        </DialogTitle>
        <DialogDescription className="text-[12px] text-muted">
          @{issue.assignee}
          {issue.agent && <> · {issue.agent}</>}
          {issue.model && <> · {issue.model}</>}
          {issue.scheduled_at && (
            <> · scheduled {issue.scheduled_at.slice(0, 16).replace('T', ' ')}</>
          )}
          {issue.recurrence && <> · recurs {issue.recurrence}</>}
        </DialogDescription>
      </header>

      {issue.description && (
        <div
          className={cn(
            'bg-surface-2 border border-border rounded-md p-3 max-h-[28vh] overflow-y-auto',
          )}
        >
          <Markdown>{issue.description}</Markdown>
        </div>
      )}

      {(issue.blocked_by.length > 0 ||
        issue.linked_to.length > 0 ||
        issue.parent_id ||
        blocks.length > 0 ||
        children.length > 0 ||
        linkedFrom.length > 0) && (
        <section className="space-y-1.5 text-[12px]">
          {issue.parent_id && (
            <div className="flex items-baseline gap-2">
              <span className="text-[10px] uppercase tracking-wider text-muted w-20">
                Parent
              </span>
              <IssueIdLink id={issue.parent_id} />
            </div>
          )}
          {children.length > 0 && (
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted w-20">
                Children
              </span>
              {children.map((child) => (
                <IssueIdLink key={child.id} id={child.id} />
              ))}
            </div>
          )}
          {issue.blocked_by.length > 0 && (
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted w-20">
                Blocked by
              </span>
              {issue.blocked_by.map((id) => (
                <IssueIdLink key={id} id={id} />
              ))}
            </div>
          )}
          {blocks.length > 0 && (
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted w-20">
                Blocks
              </span>
              {blocks.map((dep) => (
                <IssueIdLink key={dep.id} id={dep.id} />
              ))}
            </div>
          )}
          {(issue.linked_to.length > 0 || linkedFrom.length > 0) && (
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted w-20">
                Linked
              </span>
              {[
                ...issue.linked_to,
                ...linkedFrom
                  .map((i) => i.id)
                  .filter((id) => !issue.linked_to.includes(id)),
              ].map((id) => (
                <IssueIdLink key={id} id={id} />
              ))}
            </div>
          )}
        </section>
      )}

      {issue.resolution && (
        <section className="text-[12px]">
          <span className="text-[10px] uppercase tracking-wider text-muted block mb-1">
            Resolution
          </span>
          <p className="text-fg/90">{issue.resolution}</p>
        </section>
      )}

      <ActivityTimeline events={events} />
      <CommentThread issueId={issue.id} />
    </div>
  );
}
