/** Typed fetch wrapper for the dashboard API. Same-origin in production
 *  (FastAPI serves the SPA), Vite-proxied in dev. */
import type {
  CreateIssueInput,
  Event,
  Issue,
  Meta,
  UpdateIssueInput,
  UpdateResponse,
} from './schemas';

const BASE = '';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const body = (await r.json()) as { detail?: string };
      if (body.detail) msg = body.detail;
    } catch {
      // body wasn't JSON; keep statusText
    }
    throw new ApiError(r.status, msg);
  }
  if (r.status === 204) return undefined as unknown as T;
  return (await r.json()) as T;
}

function buildQuery(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === false) continue;
    if (Array.isArray(v)) {
      for (const item of v) q.append(k, String(item));
    } else if (typeof v === 'boolean') {
      q.set(k, v ? 'true' : 'false');
    } else {
      q.set(k, String(v));
    }
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

export interface ListIssuesParams {
  status?: string[];
  project?: string[];
  priority?: string[];
  assignee?: string[];
  agent?: string[];
  model?: string[];
  type?: string[];
  include_epics?: boolean;
  blocked_only?: boolean;
  scheduled_window?: 'due' | 'this_week' | 'all';
  parent?: string;
}

export const api = {
  listIssues: (params: ListIssuesParams = {}) =>
    req<Issue[]>(`/api/issues${buildQuery(params as Record<string, unknown>)}`),
  getIssue: (id: string) => req<Issue>(`/api/issues/${id}`),
  createIssue: (body: CreateIssueInput) =>
    req<Issue>(`/api/issues`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateIssue: (id: string, body: UpdateIssueInput) =>
    req<UpdateResponse>(`/api/issues/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  closeIssue: (
    id: string,
    body: {
      status?: 'done' | 'cancelled';
      resolution?: string;
      files?: string[];
      refs?: string[];
    },
  ) =>
    req<Issue & { _next_issue_id?: string; _next_scheduled_at?: string }>(
      `/api/issues/${id}/close`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  comment: (
    id: string,
    body: { message: string; status?: string; files?: string[]; refs?: string[] },
  ) =>
    req<Issue>(`/api/issues/${id}/comment`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  events: (id: string) => req<Event[]>(`/api/issues/${id}/events`),
  search: (q: string) => req<Issue[]>(`/api/search?q=${encodeURIComponent(q)}`),
  meta: () => req<Meta>(`/api/meta`),
};
