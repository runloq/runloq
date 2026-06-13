/** Subscribe to /sse and invalidate TanStack Query caches on server push.
 *
 * Two event types:
 *   - `issue-changed` {id, action}: surgical invalidation — only the affected
 *     issue's queries plus the list (membership may have changed). Avoids a
 *     full board refetch.
 *   - `db-changed`: fallback for out-of-process CLI writes detected by the
 *     watchdog. Invalidates everything (current behavior, no regression).
 */
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

interface IssueChangedPayload {
  type: 'issue-changed';
  id: string;
  action: 'create' | 'update' | 'close' | 'comment';
}

interface DbChangedPayload {
  type: 'db-changed';
}

type SSEPayload = IssueChangedPayload | DbChangedPayload | { type?: string };

export function useSSE(): void {
  const qc = useQueryClient();
  useEffect(() => {
    let es: EventSource | null = null;
    let backoff = 500;
    let stopped = false;

    const connect = (): void => {
      if (stopped) return;
      es = new EventSource('/sse');
      es.onopen = () => {
        backoff = 500;
      };
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as SSEPayload;
          if (data.type === 'issue-changed') {
            const { id } = data as IssueChangedPayload;
            // Surgical invalidation: refresh only the affected issue's queries
            // and the issues list (status/membership may have changed).
            void qc.invalidateQueries({ queryKey: ['issue', id] });
            void qc.invalidateQueries({ queryKey: ['events', id] });
            void qc.invalidateQueries({ queryKey: ['issues'] });
          } else if (data.type === 'db-changed') {
            // Fallback for out-of-process writes (CLI). Refetch everything.
            void qc.invalidateQueries();
          }
        } catch {
          // ignore malformed payloads
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
        if (!stopped) {
          setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 10_000);
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      es?.close();
    };
  }, [qc]);
}
