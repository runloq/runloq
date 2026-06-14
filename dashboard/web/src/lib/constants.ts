/** Shared label maps and type helpers for issue fields. */

export type IssueStatus = 'todo' | 'in_progress' | 'scheduled' | 'done' | 'cancelled';

export const STATUS_LABEL: Record<string, string> = {
  todo: 'Todo',
  in_progress: 'In progress',
  scheduled: 'Scheduled',
  done: 'Done',
  cancelled: 'Cancelled',
};
