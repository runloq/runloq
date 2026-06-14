import { useState, useMemo, useRef, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMeta } from '@/hooks/useMeta';
import { useCreate, useUpdate } from '@/hooks/useMutations';
import { api } from '@/lib/api';
import type { Issue } from '@/lib/schemas';

/** All-issues fetch for the relation comboboxes. Independent of the board's
 *  `showEpics` / status toggles — the form must always see active epics and
 *  tasks even when the board hides them. Done/cancelled excluded since those
 *  are non-actionable as relation targets. */
const RELATION_STATUSES = ['todo', 'in_progress', 'scheduled'];
import { Input } from './ui/input';
import { Select } from './ui/select';
import { Button } from './ui/button';
import { TicketCombobox } from './ui/ticket-combobox';
import { MarkdownEditor } from './ui/markdown-editor';
import { Markdown } from './Markdown';
import { cn } from '@/lib/cn';
import { toast } from 'sonner';

// Statuses shown when CREATING a ticket (not done/cancelled)
const CREATE_STATUSES = ['todo', 'in_progress', 'scheduled'] as const;

interface FormState {
  title: string;
  description: string;
  project: string;
  type: 'issue' | 'epic';
  priority: string;
  status?: string;
  assignee: string;
  agent: string;
  model: string;
  blocked_by: string[];
  linked_to: string[];
  parent_id: string | null;
  scheduled_at: string;
  recurrence: string;
  /** Children (epic-only): task IDs whose parent_id should be set to this epic. */
  children: string[];
}

function stateFromIssue(issue: Issue, children: string[] = []): FormState {
  return {
    title: issue.title,
    description: issue.description ?? '',
    project: issue.id.split('-')[0],
    type: issue.issue_type,
    priority: issue.priority,
    status: issue.status,
    assignee: issue.assignee,
    agent: issue.agent ?? '',
    model: issue.model ?? '',
    blocked_by: issue.blocked_by,
    linked_to: issue.linked_to,
    parent_id: issue.parent_id ?? null,
    scheduled_at: issue.scheduled_at?.slice(0, 16) ?? '',
    recurrence: issue.recurrence ?? '',
    children,
  };
}

const DEFAULT_STATE: FormState = {
  title: '',
  description: '',
  project: 'SYS',
  type: 'issue',
  priority: 'P0',
  assignee: 'claude',
  agent: '',
  model: 'opus',
  blocked_by: [],
  linked_to: [],
  parent_id: null,
  scheduled_at: '',
  recurrence: '',
  children: [],
};

export function TicketForm({
  mode,
  initial,
  onSaved,
  onCancel,
}: {
  mode: 'create' | 'edit';
  initial?: Issue;
  onSaved?: (issueId: string) => void;
  onCancel?: () => void;
}) {
  const { data: meta } = useMeta();
  const qc = useQueryClient();

  const [s, setS] = useState<FormState>(() => {
    if (!initial) return DEFAULT_STATE;
    // Pre-populate children from the query cache for epic edit mode
    if (initial.issue_type === 'epic') {
      const seen = new Map<string, Issue>();
      const listSlices = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
      for (const [, data] of listSlices) {
        if (!Array.isArray(data)) continue;
        for (const issue of data) {
          if (!seen.has(issue.id)) seen.set(issue.id, issue);
        }
      }
      const childIds = Array.from(seen.values())
        .filter((i) => i.parent_id === initial.id)
        .map((i) => i.id);
      return stateFromIssue(initial, childIds);
    }
    return stateFromIssue(initial);
  });
  const create = useCreate();
  const update = useUpdate(initial?.id ?? '');
  const pending = create.isPending || update.isPending;

  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const descriptionViewerRef = useRef<HTMLDivElement>(null);

  const isEpic = s.type === 'epic';
  const isClaude = s.assignee === 'claude' && !isEpic;

  const set = <K extends keyof FormState>(k: K, v: FormState[K]): void => {
    setS((cur) => {
      const next = { ...cur, [k]: v };
      // When switching to epic, clear epic-incompatible fields
      if (k === 'type' && v === 'epic') {
        next.assignee = 'claude';
        next.agent = '';
        next.model = '';
        next.parent_id = null;
      }
      // When switching back to issue, restore defaults for blank fields
      if (k === 'type' && v === 'issue') {
        if (!next.assignee) next.assignee = 'claude';
        if (!next.model) next.model = 'opus';
      }
      // When assignee leaves claude, clear claude-only fields
      if (k === 'assignee' && v !== 'claude') {
        next.agent = '';
        next.model = '';
      }
      // When scheduled_at clears, also clear recurrence
      if (k === 'scheduled_at' && !v) {
        next.recurrence = '';
      }
      return next;
    });
  };

  // Authoritative fetch for combobox sources — never depends on the board's
  // showEpics/status toggles. Done/cancelled excluded since they aren't
  // useful as relation targets.
  const { data: relationIssues = [] } = useQuery({
    queryKey: ['issues', { status: RELATION_STATUSES, include_epics: true, _src: 'form-relations' }],
    queryFn: () =>
      api.listIssues({
        status: RELATION_STATUSES,
        include_epics: true,
      }),
    staleTime: 5_000,
  });

  // Build combobox items, merging the authoritative fetch with whatever else
  // is in the cache (board, search, single-issue queries) so freshly-created
  // tickets show up immediately. Cache entries are filtered to RELATION_STATUSES
  // — done/cancelled tickets pulled in by a previous "Show done" board query
  // would otherwise stick around after the toggle is turned off (TanStack
  // creates new query keys instead of evicting old ones).
  const allowedStatus = new Set<string>(RELATION_STATUSES);
  const acceptForRelations = (issue: Issue) => allowedStatus.has(issue.status);

  const { allItems, epicItems, taskItems } = useMemo(() => {
    const seen = new Map<string, Issue>();
    for (const issue of relationIssues) {
      if (!seen.has(issue.id)) seen.set(issue.id, issue);
    }

    const listSlices = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
    for (const [, data] of listSlices) {
      if (!Array.isArray(data)) continue;
      for (const issue of data) {
        if (seen.has(issue.id)) continue;
        if (!acceptForRelations(issue)) continue;
        seen.set(issue.id, issue);
      }
    }
    const singleEntries = qc.getQueriesData<Issue>({ queryKey: ['issue'] });
    for (const [, data] of singleEntries) {
      if (!data || typeof data !== 'object' || !('id' in data)) continue;
      if (seen.has(data.id)) continue;
      if (!acceptForRelations(data)) continue;
      seen.set(data.id, data);
    }

    const sortById = (a: Issue, b: Issue) => {
      const [apfx, anum] = a.id.split('-');
      const [bpfx, bnum] = b.id.split('-');
      if (apfx !== bpfx) return apfx.localeCompare(bpfx);
      return Number(anum) - Number(bnum);
    };

    const toItem = (i: Issue) => ({
      id: i.id,
      label: i.id,
      description: i.title,
      disabled: false,
    });

    const currentId = initial?.id;
    const all = Array.from(seen.values())
      .filter((i) => i.id !== currentId)
      .sort(sortById)
      .map(toItem);

    const epics = Array.from(seen.values())
      .filter((i) => i.id !== currentId && i.issue_type === 'epic')
      .sort(sortById)
      .map(toItem);

    // Tasks only (no epics, no self) — used for the children multi-select
    const tasks = Array.from(seen.values())
      .filter((i) => i.id !== currentId && i.issue_type !== 'epic')
      .sort(sortById)
      .map(toItem);

    return { allItems: all, epicItems: epics, taskItems: tasks };
    // acceptForRelations + allowedStatus are derived from a constant — safe to omit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qc, initial?.id, relationIssues]);

  /** Reconcile children for an epic: PATCH each child's parent_id as needed. */
  const reconcileChildren = async (epicId: string, newChildren: string[], oldChildren: string[]) => {
    const toAdd = newChildren.filter((id) => !oldChildren.includes(id));
    const toRemove = oldChildren.filter((id) => !newChildren.includes(id));
    if (toAdd.length === 0 && toRemove.length === 0) return;

    const patches = [
      ...toAdd.map((id) => api.updateIssue(id, { parent_id: epicId })),
      ...toRemove.map((id) => api.updateIssue(id, { parent_id: null })),
    ];

    const results = await Promise.allSettled(patches);
    const failed = results.filter((r) => r.status === 'rejected').length;
    if (failed > 0) {
      toast.error(`Failed to update ${failed} child(ren) — refresh to see consistent state.`);
    }
    // Invalidate all issues so the board reflects updated parent_id values
    qc.invalidateQueries({ queryKey: ['issues'] });
  };

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();

    if (mode === 'create') {
      try {
        const created = await create.mutateAsync({
          title: s.title,
          project: s.project as 'SYS' | 'ARC' | 'VER' | 'PUR' | 'DUC' | 'FRG' | 'PAR',
          type: s.type,
          priority: s.priority as 'P0' | 'P1' | 'P2' | 'P3',
          assignee: isEpic
            ? 'claude'
            : (s.assignee as 'claude' | 'agent' | 'alice' | 'bob'),
          agent: isClaude ? s.agent || null : null,
          model: isClaude
            ? ((s.model || null) as 'opus' | 'sonnet' | 'haiku' | null)
            : null,
          description: s.description || null,
          blocked_by: s.blocked_by,
          linked_to: s.linked_to,
          parent_id: isEpic ? null : s.parent_id || null,
          scheduled_at: s.scheduled_at || null,
          recurrence:
            (s.recurrence || null) as 'daily' | 'weekly' | 'biweekly' | 'monthly' | null,
        });
        // Reconcile children: for a newly created epic, add the selected children
        if (isEpic && s.children.length > 0) {
          await reconcileChildren(created.id, s.children, []);
        }
        onSaved?.(created.id);
      } catch {
        // toast already shown by useCreate.onError
      }
    } else if (initial) {
      const initialState = stateFromIssue(initial, s.children); // use current children as baseline for diff
      // Re-derive old children from cache for proper reconciliation
      const seen = new Map<string, Issue>();
      const listSlices = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
      for (const [, data] of listSlices) {
        if (!Array.isArray(data)) continue;
        for (const issue of data) {
          if (!seen.has(issue.id)) seen.set(issue.id, issue);
        }
      }
      const oldChildren = Array.from(seen.values())
        .filter((i) => i.parent_id === initial.id)
        .map((i) => i.id);

      try {
        await update.mutateAsync({
          title: s.title !== initial.title ? s.title : undefined,
          description:
            s.description !== (initial.description ?? '')
              ? s.description || null
              : undefined,
          status:
            s.status && s.status !== initial.status
              ? (s.status as 'todo' | 'in_progress' | 'scheduled' | 'done' | 'cancelled')
              : undefined,
          type: s.type !== initial.issue_type ? s.type : undefined,
          priority:
            s.priority !== initial.priority
              ? (s.priority as 'P0' | 'P1' | 'P2' | 'P3')
              : undefined,
          assignee:
            !isEpic && s.assignee !== initial.assignee
              ? (s.assignee as 'claude' | 'agent' | 'alice' | 'bob')
              : undefined,
          agent:
            isClaude && s.agent !== (initial.agent ?? '')
              ? s.agent || null
              : undefined,
          model:
            isClaude && s.model !== (initial.model ?? '')
              ? ((s.model || null) as 'opus' | 'sonnet' | 'haiku' | null)
              : undefined,
          blocked_by:
            s.blocked_by.join(',') !== initialState.blocked_by.join(',')
              ? s.blocked_by
              : undefined,
          linked_to:
            s.linked_to.join(',') !== initialState.linked_to.join(',')
              ? s.linked_to
              : undefined,
          parent_id:
            !isEpic && s.parent_id !== (initial.parent_id ?? null)
              ? s.parent_id || null
              : undefined,
          scheduled_at:
            s.scheduled_at !== (initial.scheduled_at?.slice(0, 16) ?? '')
              ? s.scheduled_at || null
              : undefined,
          recurrence:
            s.recurrence !== (initial.recurrence ?? '')
              ? ((s.recurrence || null) as 'daily' | 'weekly' | 'biweekly' | 'monthly' | null)
              : undefined,
        });
        // Reconcile children for epic edit
        if (isEpic) {
          await reconcileChildren(initial.id, s.children, oldChildren);
        }
        onSaved?.(initial.id);
      } catch {
        // toast already shown
      }
    }
  };

  // Status options: filter done+cancelled for create mode
  const allStatuses = meta?.statuses ?? ['todo', 'in_progress', 'scheduled', 'done', 'cancelled'];
  const visibleStatuses =
    mode === 'create'
      ? allStatuses.filter((st) => CREATE_STATUSES.includes(st as (typeof CREATE_STATUSES)[number]))
      : allStatuses;

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label htmlFor="tf-title" className="text-[10px] uppercase tracking-wider text-muted block mb-1">
          Title
        </label>
        <Input
          id="tf-title"
          value={s.title}
          onChange={(e) => set('title', e.target.value)}
          placeholder="Short imperative summary…"
          required
          autoFocus
        />
      </div>

      {/* Description — viewer↔editor toggle */}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-muted block mb-1">
          Description
        </label>
        {isEditingDescription ? (
          <MarkdownEditor
            value={s.description}
            onChange={(val) => set('description', val)}
            onBlur={() => setIsEditingDescription(false)}
            placeholder="Standing brief — read by /work cold."
            minHeight={160}
            autoFocus
          />
        ) : (
          <div
            ref={descriptionViewerRef}
            role="button"
            tabIndex={0}
            aria-label="Click to edit description"
            onClick={() => setIsEditingDescription(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setIsEditingDescription(true);
              }
            }}
            className={cn(
              'min-h-[3rem] rounded-md border border-border px-2.5 py-2 cursor-text',
              'hover:border-accent/60 hover:bg-surface-2/40 transition-colors',
              'focus:outline-none focus:border-accent',
            )}
          >
            {s.description ? (
              <Markdown>{s.description}</Markdown>
            ) : (
              <span className="text-muted text-[13px] italic">
                Click to add description…
              </span>
            )}
          </div>
        )}
      </div>

      {/* ── Stable top section (always visible regardless of type) ─────── */}
      <div className="grid grid-cols-4 gap-2">
        <FormField label="Project" htmlFor="tf-project">
          <Select id="tf-project" value={s.project} onChange={(e) => set('project', e.target.value)}>
            {(meta?.projects ?? ['SYS']).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </Select>
        </FormField>
        <FormField label="Type" htmlFor="tf-type">
          <Select id="tf-type" value={s.type} onChange={(e) => set('type', e.target.value as 'issue' | 'epic')}>
            <option value="issue">issue</option>
            <option value="epic">epic</option>
          </Select>
        </FormField>
        <FormField label="Priority" htmlFor="tf-priority">
          <Select id="tf-priority" value={s.priority} onChange={(e) => set('priority', e.target.value)}>
            {(meta?.priorities ?? ['P0', 'P1', 'P2', 'P3']).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </Select>
        </FormField>
        <FormField label={mode === 'create' ? 'Status' : 'Status'} htmlFor="tf-status">
          <Select id="tf-status" value={s.status ?? 'todo'} onChange={(e) => set('status', e.target.value)}>
            {visibleStatuses.map((st) => (
              <option key={st} value={st}>{st}</option>
            ))}
          </Select>
        </FormField>
      </div>

      {/* Relation fields — always visible for both task and epic */}
      <div className="grid grid-cols-2 gap-2">
        <FormField label="Blocked by">
          <TicketCombobox
            items={allItems}
            selectedIds={s.blocked_by}
            onChange={(ids) => set('blocked_by', ids)}
            placeholder="Search tickets…"
            emptyMessage="No tickets found."
            mode="multi"
            aria-label="Blocked by"
          />
        </FormField>
        <FormField label="Linked to">
          <TicketCombobox
            items={allItems}
            selectedIds={s.linked_to}
            onChange={(ids) => set('linked_to', ids)}
            placeholder="Search tickets…"
            emptyMessage="No tickets found."
            mode="multi"
            aria-label="Linked to"
          />
        </FormField>
      </div>

      {/* ── Type-conditional section ──────────────────────────────────── */}
      {!isEpic ? (
        <>
          {/* Task-only: assignee / agent / model */}
          <div className="grid grid-cols-3 gap-2">
            <FormField label="Assignee" htmlFor="tf-assignee">
              <Select
                id="tf-assignee"
                value={s.assignee}
                onChange={(e) => set('assignee', e.target.value)}
              >
                {(meta?.assignees ?? ['claude']).map((a) => (
                  <option key={a} value={a}>@{a}</option>
                ))}
              </Select>
            </FormField>
            <FormField label={isClaude ? 'Agent' : 'Agent (claude only)'}>
              <TicketCombobox
                mode="single"
                aria-label={isClaude ? 'Agent' : 'Agent (claude only)'}
                items={(meta?.agents ?? []).map((a) => ({
                  id: a.name,
                  label: a.name,
                  description: a.description ?? undefined,
                }))}
                selectedIds={s.agent ? [s.agent] : []}
                onChange={(ids) => set('agent', ids[0] ?? '')}
                placeholder="Search agent…"
                emptyMessage="No matching agent."
                disabled={!isClaude}
              />
            </FormField>
            <FormField label={isClaude ? 'Model' : 'Model (claude only)'} htmlFor="tf-model">
              <Select
                id="tf-model"
                value={s.model}
                onChange={(e) => set('model', e.target.value)}
                disabled={!isClaude}
              >
                <option value="">—</option>
                {(meta?.models ?? ['opus', 'sonnet', 'haiku']).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </Select>
            </FormField>
          </div>

          {/* Task-only: parent epic / scheduled_at / recurrence */}
          <div className="grid grid-cols-3 gap-2">
            <FormField label="Parent epic">
              <TicketCombobox
                items={epicItems}
                selectedIds={s.parent_id ? [s.parent_id] : []}
                onChange={(ids) => set('parent_id', ids[0] ?? null)}
                placeholder="Search epics…"
                emptyMessage="No epics found."
                mode="single"
                aria-label="Parent epic"
              />
            </FormField>
            <FormField label="Scheduled at" htmlFor="tf-scheduled-at">
              <Input
                id="tf-scheduled-at"
                type="datetime-local"
                value={s.scheduled_at}
                onChange={(e) => set('scheduled_at', e.target.value)}
              />
            </FormField>
            {s.scheduled_at ? (
              <FormField label="Recurrence" htmlFor="tf-recurrence">
                <Select id="tf-recurrence" value={s.recurrence} onChange={(e) => set('recurrence', e.target.value)}>
                  <option value="">—</option>
                  {(meta?.recurrences ?? ['daily', 'weekly', 'biweekly', 'monthly']).map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </Select>
              </FormField>
            ) : (
              <div /> /* placeholder to keep the grid stable when recurrence is hidden */
            )}
          </div>
        </>
      ) : (
        /* Epic-only: children */
        <FormField label="Children">
          <TicketCombobox
            items={taskItems}
            selectedIds={s.children}
            onChange={(ids) => set('children', ids)}
            placeholder="Add child tasks…"
            emptyMessage="No tasks found."
            mode="multi"
            aria-label="Children"
          />
        </FormField>
      )}

      <div className="flex justify-end gap-2 pt-2 border-t border-border">
        {onCancel && (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" size="sm" disabled={pending || !s.title.trim()}>
          {pending ? '…' : mode === 'create' ? 'Create' : 'Save'}
        </Button>
      </div>
    </form>
  );
}

/**
 * FormField — WCAG 1.3.1 / 3.3.2 label association fix.
 *
 * When `htmlFor` is provided (native <select> / <input> children):
 *   → renders a semantic <label htmlFor> so screen readers announce the label.
 *
 * When `htmlFor` is omitted (TicketCombobox children):
 *   → renders a <label> with `onMouseDown` preventDefault to block the browser's
 *     click-forwarding that would otherwise dispatch a synthetic click on the
 *     first interactive child (which lands on the chip's X button and
 *     immediately removes the chip). The TicketCombobox trigger carries an
 *     `aria-label` prop for screen-reader association.
 */
function FormField({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="block">
      <label
        htmlFor={htmlFor}
        onMouseDown={htmlFor ? undefined : (e) => e.preventDefault()}
        className="text-[10px] uppercase tracking-wider text-muted block mb-1"
      >
        {label}
      </label>
      {children}
    </div>
  );
}
