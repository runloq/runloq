import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useEvents(id: string | null) {
  return useQuery({
    queryKey: ['events', id],
    queryFn: () => api.events(id!),
    enabled: id !== null,
  });
}
