import { useQuery } from '@tanstack/react-query';
import { api, type ListIssuesParams } from '@/lib/api';

export function useIssues(params: ListIssuesParams = {}) {
  return useQuery({
    queryKey: ['issues', params],
    queryFn: () => api.listIssues(params),
  });
}
