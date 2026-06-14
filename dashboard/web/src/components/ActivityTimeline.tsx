import type { Event } from '@/lib/schemas';
import { cn } from '@/lib/cn';
import { Markdown } from './Markdown';

const TYPE_COLOR: Record<string, string> = {
  created: 'text-muted',
  updated: 'text-fg',
  closed: 'text-accent',
  comment: 'text-fg',
  spawned_next: 'text-p1',
};

export function ActivityTimeline({ events }: { events: Event[] }) {
  if (events.length === 0) return null;

  // API returns ASC (oldest first); display DESC (newest at top).
  const ordered = [...events].reverse();

  return (
    <section>
      <h3 className="text-[10px] uppercase tracking-wider text-muted mb-2">
        Activity ({events.length})
      </h3>
      <ol className="space-y-1.5 text-[12px] font-sans border-l border-border pl-3">
        {ordered.map((e) => (
          <li key={e.id} className={cn('flex gap-2', e.type === 'comment' ? 'items-start' : 'items-baseline')}>
            <span className="font-mono text-[10px] text-muted tabular-nums shrink-0">
              {e.created_at.slice(5, 16).replace('T', ' ')}
            </span>
            <span
              className={cn(
                'font-mono text-[10px] uppercase tracking-wider shrink-0',
                TYPE_COLOR[e.type] ?? 'text-muted',
              )}
            >
              {e.type}
            </span>
            {e.type === 'comment' ? (
              <div className="min-w-0 break-words">
                <Markdown className="text-[12px]">{e.message}</Markdown>
              </div>
            ) : (
              <span className="text-fg/90 break-words min-w-0">{e.message}</span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
