import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Issue } from '@/lib/schemas';

const ALL_STATUSES = ['todo', 'in_progress', 'scheduled', 'done', 'cancelled'];

/** Fetches the full list of children for an epic, regardless of board filters.
 *
 *  Uses the same query key shape as `useInverseRelations` so the two share a
 *  cache entry — opening an epic's modal after the board has already loaded
 *  its children doesn't trigger a refetch. */
export function useEpicChildren(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ['issues', { parent: id, status: ALL_STATUSES, include_epics: true }],
    queryFn: () =>
      api.listIssues({
        parent: id,
        status: ALL_STATUSES,
        include_epics: true,
      }),
    enabled: enabled && !!id,
    staleTime: 5_000,
  });
}

/** Sort children by status (active first) then by natural ID order.
 *  This puts the most actionable items at the front of the chip row. */
const STATUS_ORDER: Record<string, number> = {
  in_progress: 0,
  todo: 1,
  scheduled: 2,
  done: 3,
  cancelled: 4,
};

export function sortChildrenForCard(children: Issue[]): Issue[] {
  return [...children].sort((a, b) => {
    const sa = STATUS_ORDER[a.status] ?? 9;
    const sb = STATUS_ORDER[b.status] ?? 9;
    if (sa !== sb) return sa - sb;
    const [apfx, anum] = a.id.split('-');
    const [bpfx, bnum] = b.id.split('-');
    if (apfx !== bpfx) return apfx.localeCompare(bpfx);
    return Number(anum) - Number(bnum);
  });
}
