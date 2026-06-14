/** Zod mirrors of the FastAPI pydantic schemas. Used for client-side
 *  form validation; the server re-validates with pydantic as the
 *  authoritative source of truth. */
import { z } from 'zod';

export const Project = z.enum(['SYS', 'ARC', 'VER', 'PUR', 'DUC', 'FRG', 'PAR']);
export const Priority = z.enum(['P0', 'P1', 'P2', 'P3']);
export const Status = z.enum([
  'todo',
  'in_progress',
  'scheduled',
  'done',
  'cancelled',
]);
export const Assignee = z.enum([
  'claude',
  'agent',
  'alice',
  'bob',
]);
export const Model = z.enum(['opus', 'sonnet', 'haiku']);
export const Recurrence = z.enum(['daily', 'weekly', 'biweekly', 'monthly']);
export const IssueType = z.enum(['issue', 'epic']);

export const Issue = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().nullable().optional(),
  status: Status,
  issue_type: IssueType,
  priority: Priority,
  assignee: z.string(),
  agent: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  blocked_by: z.array(z.string()),
  linked_to: z.array(z.string()),
  parent_id: z.string().nullable().optional(),
  scheduled_at: z.string().nullable().optional(),
  recurrence: Recurrence.nullable().optional(),
  resolution: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  closed_at: z.string().nullable().optional(),
});
export type Issue = z.infer<typeof Issue>;

export const CreateIssueInput = z.object({
  title: z.string().min(1, 'Title required'),
  project: Project.default('SYS'),
  type: IssueType.default('issue'),
  priority: Priority.default('P1'),
  assignee: Assignee.default('claude'),
  agent: z.string().nullable().optional(),
  model: Model.nullable().optional(),
  description: z.string().nullable().optional(),
  blocked_by: z.array(z.string()).default([]),
  linked_to: z.array(z.string()).default([]),
  parent_id: z.string().nullable().optional(),
  scheduled_at: z.string().nullable().optional(),
  recurrence: Recurrence.nullable().optional(),
  status: Status.optional(),
});
export type CreateIssueInput = z.infer<typeof CreateIssueInput>;

export const UpdateIssueInput = z.object({
  title: z.string().min(1).optional(),
  description: z.string().nullable().optional(),
  status: Status.optional(),
  type: IssueType.optional(),
  priority: Priority.optional(),
  assignee: Assignee.optional(),
  agent: z.string().nullable().optional(),
  model: Model.nullable().optional(),
  blocked_by: z.array(z.string()).optional(),
  linked_to: z.array(z.string()).optional(),
  parent_id: z.string().nullable().optional(),
  scheduled_at: z.string().nullable().optional(),
  recurrence: Recurrence.nullable().optional(),
  resolution: z.string().nullable().optional(),
  clear_agent: z.boolean().optional(),
  clear_model: z.boolean().optional(),
  clear_scheduled_at: z.boolean().optional(),
  clear_recurrence: z.boolean().optional(),
});
export type UpdateIssueInput = z.infer<typeof UpdateIssueInput>;

export const Event = z.object({
  id: z.number(),
  issue_id: z.string().nullable().optional(),
  type: z.string(),
  message: z.string(),
  metadata: z.string().nullable().optional(),
  created_at: z.string(),
});
export type Event = z.infer<typeof Event>;

export const AgentInfo = z.object({
  name: z.string(),
  description: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
});
export type AgentInfo = z.infer<typeof AgentInfo>;

export const Meta = z.object({
  projects: z.array(z.string()),
  priorities: z.array(z.string()),
  statuses: z.array(z.string()),
  assignees: z.array(z.string()),
  models: z.array(z.string()),
  recurrences: z.array(z.string()),
  agents: z.array(AgentInfo),
});
export type Meta = z.infer<typeof Meta>;

export const UpdateResponse = z.object({
  issue: Issue,
  changes: z.array(z.string()),
});
export type UpdateResponse = z.infer<typeof UpdateResponse>;
