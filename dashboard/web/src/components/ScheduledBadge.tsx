import { Badge } from './ui/badge';

function relative(at: string): { label: string; overdue: boolean } {
  const dt = new Date(at);
  const now = new Date();
  const diffMs = dt.getTime() - now.getTime();
  const diffDays = Math.round(diffMs / (24 * 60 * 60 * 1000));
  if (diffMs < -60_000) {
    const days = Math.abs(diffDays);
    return { label: days >= 1 ? `overdue ${days}d` : 'overdue today', overdue: true };
  }
  if (diffDays === 0) return { label: 'today', overdue: false };
  if (diffDays === 1) return { label: 'tomorrow', overdue: false };
  return { label: `in ${diffDays}d`, overdue: false };
}

export function ScheduledBadge({ at }: { at: string }) {
  const { label, overdue } = relative(at);
  return (
    <Badge
      variant={overdue ? 'danger' : 'warning'}
      title={`Scheduled for ${at.slice(0, 16).replace('T', ' ')}`}
    >
      ⏰ {label}
    </Badge>
  );
}
