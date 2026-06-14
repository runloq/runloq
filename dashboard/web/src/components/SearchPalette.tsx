import { useState, useEffect } from 'react';
import { useSearch } from '@/hooks/useSearch';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useModalStack } from '@/lib/modalStack';
import { STATUS_LABEL } from '@/lib/constants';
import { Dialog, DialogContent } from './ui/dialog';
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from './ui/command';
import type { Issue } from '@/lib/schemas';

/** Matches a complete ticket ID — e.g. "SYS-395", "PAR-441". */
const ID_RE = /^[A-Z]+-\d+$/;

function normaliseId(q: string): string {
  return q.trim().toUpperCase();
}

export function SearchPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [q, setQ] = useState('');
  const trimmed = q.trim();

  // FTS / LIKE search (1-char minimum)
  const { data: ftsResults = [], isFetching: ftsFetching } = useSearch(q);

  // ID fast-path: only fires when the query exactly matches ^[A-Z]+-\d+$
  const idQuery = ID_RE.test(normaliseId(trimmed)) ? normaliseId(trimmed) : '';
  const { data: idResult, isFetching: idFetching } = useQuery({
    queryKey: ['issue', idQuery],
    queryFn: () => api.getIssue(idQuery),
    enabled: idQuery.length > 0,
    staleTime: 30_000,
    retry: false,
  });

  const push = useModalStack((s) => s.push);

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);

  const select = (id: string): void => {
    push(id);
    onOpenChange(false);
  };

  // Merge: exact ID result first, then FTS results (deduped)
  const mergedResults: Issue[] = [];
  if (idResult) mergedResults.push(idResult);
  for (const r of ftsResults) {
    if (!mergedResults.some((m) => m.id === r.id)) mergedResults.push(r);
  }

  const isFetching = ftsFetching || idFetching;
  const hasQuery = trimmed.length >= 1;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showClose={false}
        bodyClass="p-2"
        className="max-w-[560px] top-[20vh]"
      >
        <Command
          shouldFilter={false}
          className="border border-border rounded-md"
        >
          <CommandInput
            placeholder="Search by title, description, or ticket ID…"
            value={q}
            onValueChange={setQ}
          />
          <CommandList>
            {!hasQuery ? (
              <CommandEmpty>Type to search.</CommandEmpty>
            ) : isFetching && mergedResults.length === 0 ? (
              <CommandEmpty>Searching…</CommandEmpty>
            ) : mergedResults.length === 0 ? (
              <CommandEmpty>No matches.</CommandEmpty>
            ) : (
              <CommandGroup heading={`${mergedResults.length} result${mergedResults.length === 1 ? '' : 's'}`}>
                {mergedResults.map((r) => (
                  <CommandItem
                    key={r.id}
                    value={r.id}
                    onSelect={() => select(r.id)}
                  >
                    <span className="font-mono text-[10px] text-muted w-16 shrink-0">
                      {r.id}
                    </span>
                    <span className="font-mono text-[10px] text-muted w-8 shrink-0">
                      {r.priority}
                    </span>
                    <span className="font-mono text-[10px] text-muted w-24 shrink-0">
                      {STATUS_LABEL[r.status] ?? r.status}
                    </span>
                    <span className="truncate min-w-0 flex-1">{r.title}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
