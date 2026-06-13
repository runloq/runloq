import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useIssue(id: string | null) {
  return useQuery({
    queryKey: ['issue', id],
    queryFn: () => api.getIssue(id!),
    enabled: id !== null,
  });
}
