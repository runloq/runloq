import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '@/lib/api';

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it('builds query string for array params', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.listIssues({
      status: ['todo', 'in_progress'],
      project: ['SYS'],
    });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toMatch(/status=todo/);
    expect(url).toMatch(/status=in_progress/);
    expect(url).toMatch(/project=SYS/);
  });

  it('omits undefined and false params', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.listIssues({ blocked_only: false, status: undefined });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toMatch(/blocked_only/);
    expect(url).not.toMatch(/status/);
  });

  it('throws ApiError on non-2xx with detail message', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: 'bad project' }), {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
    );
    await expect(api.listIssues()).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: 'bad project',
    });
  });

  it('createIssue posts JSON body', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            id: 'SYS-1',
            title: 't',
            status: 'todo',
            issue_type: 'issue',
            priority: 'P1',
            assignee: 'claude',
            blocked_by: [],
            linked_to: [],
            created_at: '2026-05-02',
            updated_at: '2026-05-02',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    vi.stubGlobal('fetch', fetchMock);
    const result = await api.createIssue({
      title: 't',
      project: 'SYS',
      type: 'issue',
      priority: 'P1',
      assignee: 'claude',
      blocked_by: [],
      linked_to: [],
    });
    expect(result.id).toBe('SYS-1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toMatchObject({ title: 't' });
  });
});
