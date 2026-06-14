import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useSearch(q: string) {
  return useQuery({
    queryKey: ['search', q],
    queryFn: () => api.search(q),
    enabled: q.trim().length >= 1,
    staleTime: 10_000,
  });
}
