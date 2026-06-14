import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: () => api.meta(),
    staleTime: 5 * 60 * 1000, // agents list changes rarely
  });
}
