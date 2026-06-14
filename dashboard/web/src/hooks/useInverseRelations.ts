import { useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Issue } from '@/lib/schemas';

const ALL_STATUSES = ['todo', 'in_progress', 'scheduled', 'done', 'cancelled'];

/** Returns the inverse relation sets for a given issue ID.
 *
 *  - `children` is fetched authoritatively from the API (`?parent=<id>`)
 *    so that done/cancelled children — which the board excludes from cache —
 *    still show up under their epic.
 *  - `blocks` and `linkedFrom` are derived from whatever is already in the
 *    TanStack Query cache (board, search slices, individual issue queries).
 *    These cover active work; done blockers/links are best-effort.
 *
 *  Scans for cache-derived sets:
 *  - All `['issues', ...]` list query slices
 *  - All `['issue', id]` individual issue entries
 */
export function useInverseRelations(currentId: string): {
  blocks: Issue[];
  children: Issue[];
  linkedFrom: Issue[];
} {
  const qc = useQueryClient();

  const childrenQuery = useQuery({
    queryKey: ['issues', { parent: currentId, status: ALL_STATUSES, include_epics: true }],
    queryFn: () =>
      api.listIssues({
        parent: currentId,
        status: ALL_STATUSES,
        include_epics: true,
      }),
    enabled: !!currentId,
    staleTime: 5_000,
  });

  return useMemo(() => {
    // Collect every Issue object we have in cache (de-duped by ID).
    const seen = new Map<string, Issue>();

    // 1. All list slices: queryKey starts with 'issues'
    const listSlices = qc.getQueriesData<Issue[]>({ queryKey: ['issues'] });
    for (const [, data] of listSlices) {
      if (!Array.isArray(data)) continue;
      for (const issue of data) {
        if (!seen.has(issue.id)) seen.set(issue.id, issue);
      }
    }

    // 2. All individual issue entries: queryKey starts with 'issue'
    const singleEntries = qc.getQueriesData<Issue>({ queryKey: ['issue'] });
    for (const [, data] of singleEntries) {
      if (!data || typeof data !== 'object' || !('id' in data)) continue;
      if (!seen.has(data.id)) seen.set(data.id, data);
    }

    const blocks: Issue[] = [];
    const linkedFrom: Issue[] = [];

    for (const issue of seen.values()) {
      if (issue.id === currentId) continue;

      if (issue.blocked_by.includes(currentId)) {
        blocks.push(issue);
      }
      if (issue.linked_to.includes(currentId)) {
        linkedFrom.push(issue);
      }
    }

    const children = (childrenQuery.data ?? []).filter((c) => c.id !== currentId);

    // Sort by natural ID order (prefix-numeric): SYS-1 < SYS-2 < SYS-10
    const byId = (a: Issue, b: Issue) => {
      const [apfx, anum] = a.id.split('-');
      const [bpfx, bnum] = b.id.split('-');
      if (apfx !== bpfx) return apfx.localeCompare(bpfx);
      return Number(anum) - Number(bnum);
    };
    blocks.sort(byId);
    children.sort(byId);
    linkedFrom.sort(byId);

    return { blocks, children, linkedFrom };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, qc, childrenQuery.data]);
}
