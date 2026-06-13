import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { api, ApiError } from '@/lib/api';
import type {
  CreateIssueInput,
  Issue,
  UpdateIssueInput,
} from '@/lib/schemas';

function reportError(label: string) {
  return (e: unknown) => {
    const msg = e instanceof ApiError ? e.message : String(e);
    toast.error(`${label}: ${msg}`);
  };
}

export function useCreate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateIssueInput) => api.createIssue(body),
    onSuccess: (issue) => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      toast.success(`Created ${issue.id}`);
    },
    onError: reportError('Create failed'),
  });
}

export function useUpdate(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UpdateIssueInput) => api.updateIssue(id, body),
    onSuccess: ({ changes }) => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['issue', id] });
      qc.invalidateQueries({ queryKey: ['events', id] });
      if (changes.length === 0) {
        toast.message('No changes.');
      } else {
        toast.success(`Updated ${id}`);
      }
    },
    onError: reportError('Update failed'),
  });
}

export function useClose(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      status?: 'done' | 'cancelled';
      resolution?: string;
      files?: string[];
      refs?: string[];
    }) => api.closeIssue(id, body),
    onSuccess: (issue) => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['issue', id] });
      qc.invalidateQueries({ queryKey: ['events', id] });
      toast.success(`Closed ${id}: ${issue.status}`);
      if (issue._next_issue_id) {
        toast.info(`↻ Next iteration: ${issue._next_issue_id}`);
      }
    },
    onError: reportError('Close failed'),
  });
}

/** Optimistic status update — used by the drag-and-drop handler on Board.
 *  Snapshots the current issues list, updates it immediately in the cache,
 *  then rolls back on API failure. */
export function useStatusUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: Issue['status'] }) =>
      api.updateIssue(id, { status }),
    onMutate: async ({ id, status }) => {
      // Cancel in-flight refetches so they don't overwrite the optimistic update.
      await qc.cancelQueries({ queryKey: ['issues'] });
      // Also cancel any in-flight detail query for this issue.
      await qc.cancelQueries({ queryKey: ['issue', id] });
      // Snapshot the previous value for rollback.
      const previous = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
      const previousDetail = qc.getQueryData<Issue>(['issue', id]);
      // Optimistically update every cached issues list slice.
      qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (old) => {
        if (!old) return old;
        return old.map((issue) =>
          issue.id === id ? { ...issue, status } : issue,
        );
      });
      // Optimistically update the detail cache so the modal reflects the new
      // status immediately — without this the modal would show stale data
      // until the settled invalidation re-fetches.
      if (previousDetail) {
        qc.setQueryData<Issue>(['issue', id], { ...previousDetail, status });
      }
      return { previous, previousDetail };
    },
    onError: (_err, { id }, ctx) => {
      // Roll back all slices to their snapshots.
      if (ctx?.previous) {
        for (const [queryKey, data] of ctx.previous) {
          qc.setQueryData(queryKey, data);
        }
      }
      if (ctx?.previousDetail !== undefined) {
        qc.setQueryData(['issue', id], ctx.previousDetail);
      }
      toast.error('Status update failed — card restored.');
    },
    onSettled: (_data, _err, { id }) => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      // Invalidate the detail query so the modal and any other consumer
      // re-fetches the confirmed server state after the mutation settles.
      qc.invalidateQueries({ queryKey: ['issue', id] });
    },
  });
}

/** Optimistic priority update — used by the priority drag-and-drop handler on Board.
 *  Mirrors useStatusUpdate: snapshots, optimistically updates, rolls back on error. */
export function usePriorityUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, priority }: { id: string; priority: Issue['priority'] }) =>
      api.updateIssue(id, { priority }),
    onMutate: async ({ id, priority }) => {
      await qc.cancelQueries({ queryKey: ['issues'] });
      await qc.cancelQueries({ queryKey: ['issue', id] });
      const previous = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
      const previousDetail = qc.getQueryData<Issue>(['issue', id]);
      qc.setQueriesData<Issue[]>({ queryKey: ['issues'] }, (old) => {
        if (!old) return old;
        return old.map((issue) =>
          issue.id === id ? { ...issue, priority } : issue,
        );
      });
      // Optimistically update the detail cache so the modal reflects the new
      // priority immediately.
      if (previousDetail) {
        qc.setQueryData<Issue>(['issue', id], { ...previousDetail, priority });
      }
      return { previous, previousDetail };
    },
    onError: (_err, { id }, ctx) => {
      if (ctx?.previous) {
        for (const [queryKey, data] of ctx.previous) {
          qc.setQueryData(queryKey, data);
        }
      }
      if (ctx?.previousDetail !== undefined) {
        qc.setQueryData(['issue', id], ctx.previousDetail);
      }
      toast.error('Priority update failed — card restored.');
    },
    onSettled: (_data, _err, { id }) => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      // Invalidate the detail query so the modal re-fetches confirmed state.
      qc.invalidateQueries({ queryKey: ['issue', id] });
    },
  });
}

export function useComment(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { message: string; status?: string }) =>
      api.comment(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['events', id] });
      qc.invalidateQueries({ queryKey: ['issue', id] });
      qc.invalidateQueries({ queryKey: ['issues'] });
    },
    onError: reportError('Comment failed'),
  });
}
