import { Badge } from './ui/badge';

export function BlockedByBadge({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null;
  return (
    <Badge variant="warning" title={`Blocked by: ${ids.join(', ')}`}>
      ⊘ {ids.length}
    </Badge>
  );
}
