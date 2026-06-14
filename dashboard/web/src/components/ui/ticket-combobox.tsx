/**
 * TicketCombobox — searchable chip multi-select for the tracker dashboard.
 *
 * Dashboard-local adaptation of the @strata/ui TicketCombobox primitive.
 * Uses the dashboard's own cmdk + design tokens (surface, border, muted, etc.).
 *
 * Modes:
 * - `multi` (default) — multiple chips (blocked_by / linked_to)
 * - `single`          — one chip at most (parent epic)
 *
 * Close strategy: pointerdown outside the wrapper (document listener).
 * This avoids the blur/focus race with cmdk items which are not naturally
 * focusable — if we relied on onBlur the dropdown would close before onSelect.
 */

import {
  forwardRef,
  useState,
  useCallback,
  useRef,
  useEffect,
  type KeyboardEvent,
} from 'react';
import { X } from 'lucide-react';
import { Command as CommandPrimitive } from 'cmdk';
import { cn } from '@/lib/cn';

export interface TicketComboboxItem {
  id: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

interface TicketComboboxProps {
  items: TicketComboboxItem[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  placeholder?: string;
  emptyMessage?: string;
  mode?: 'multi' | 'single';
  disabled?: boolean;
  className?: string;
  /** Accessible label forwarded to the combobox trigger (role="combobox").
   *  Set this when the visual label is a <span> that cannot use htmlFor. */
  'aria-label'?: string;
}

export const TicketCombobox = forwardRef<HTMLDivElement, TicketComboboxProps>(
  (
    {
      items,
      selectedIds,
      onChange,
      placeholder = 'Search…',
      emptyMessage = 'No results.',
      mode = 'multi',
      disabled = false,
      className,
      'aria-label': ariaLabel,
    },
    ref,
  ) => {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);

    // Sync forwarded ref
    useEffect(() => {
      if (typeof ref === 'function') ref(containerRef.current);
      else if (ref) ref.current = containerRef.current;
    }, [ref]);

    // Close on pointerdown outside the entire widget
    useEffect(() => {
      if (!open) return;
      const onPointerDown = (e: PointerEvent) => {
        if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
          setOpen(false);
        }
      };
      document.addEventListener('pointerdown', onPointerDown, { capture: true });
      return () => document.removeEventListener('pointerdown', onPointerDown, { capture: true });
    }, [open]);

    // Focus the search input whenever the dropdown opens
    useEffect(() => {
      if (open) {
        const t = setTimeout(() => inputRef.current?.focus(), 30);
        return () => clearTimeout(t);
      }
    }, [open]);

    const selectedItems = items.filter((i) => selectedIds.includes(i.id));

    /** Multi-token AND match across (label + description). Tokens are matched
     *  independently so order doesn't matter — "records acme create" hits
     *  the same items as "create acme records". Substring per token, so
     *  "051" matches any "XXX-051". */
    const filteredItems = (() => {
      if (search === '') {
        return items.filter((item) => !selectedIds.includes(item.id));
      }
      const tokens = search.toLowerCase().trim().split(/\s+/).filter(Boolean);
      if (tokens.length === 0) {
        return items.filter((item) => !selectedIds.includes(item.id));
      }
      return items.filter((item) => {
        if (selectedIds.includes(item.id)) return false;
        const hay = `${item.label} ${item.description ?? ''}`.toLowerCase();
        return tokens.every((tok) => hay.includes(tok));
      });
    })();

    const handleSelect = useCallback(
      (id: string) => {
        if (mode === 'single') {
          onChange([id]);
          setOpen(false);
        } else {
          onChange([...selectedIds, id]);
        }
        setSearch('');
        // Re-focus input for multi so user can keep picking
        if (mode === 'multi') {
          setTimeout(() => inputRef.current?.focus(), 10);
        }
      },
      [mode, selectedIds, onChange],
    );

    const handleRemove = useCallback(
      (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        onChange(selectedIds.filter((v) => v !== id));
      },
      [selectedIds, onChange],
    );

    const handleTriggerKeyDown = useCallback(
      (e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Backspace' && search === '' && selectedIds.length > 0) {
          onChange(selectedIds.slice(0, -1));
        }
        if (e.key === 'Escape') {
          setOpen(false);
        }
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          if (!disabled && (mode === 'multi' || selectedIds.length === 0)) {
            setOpen(true);
          }
        }
      },
      [search, selectedIds, onChange, disabled, mode],
    );

    const canOpen = !disabled && (mode === 'multi' || selectedIds.length === 0);

    return (
      <div className="relative" ref={containerRef}>
        {/* Trigger chip container */}
        <div
          role="combobox"
          aria-expanded={open}
          aria-disabled={disabled}
          aria-label={ariaLabel}
          tabIndex={disabled ? -1 : 0}
          onClick={() => canOpen && setOpen(true)}
          onKeyDown={handleTriggerKeyDown}
          className={cn(
            'flex min-h-8 w-full flex-wrap items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-sm',
            'focus:outline-none focus:border-accent',
            'cursor-pointer',
            disabled && 'cursor-not-allowed opacity-50',
            className,
          )}
        >
          {selectedItems.map((item) => (
            <span
              key={item.id}
              className="inline-flex items-center gap-0.5 rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-fg"
            >
              {item.label}
              {!disabled && (
                <button
                  type="button"
                  aria-label={`Remove ${item.label}`}
                  onPointerDown={(e) => {
                    // Prevent the container's pointerdown-outside listener from
                    // seeing this as an "outside" click and closing the dropdown.
                    e.stopPropagation();
                  }}
                  onClick={(e) => handleRemove(item.id, e)}
                  className="ml-0.5 rounded-full outline-none focus:ring-1 focus:ring-accent"
                >
                  <X className="h-2.5 w-2.5 opacity-60 hover:opacity-100" />
                </button>
              )}
            </span>
          ))}
          {selectedItems.length === 0 && (
            <span className="text-muted text-[13px]">{placeholder}</span>
          )}
        </div>

        {/* Dropdown — positioned absolute inside the relative container */}
        {open && (
          <div className="absolute left-0 top-full z-50 mt-1 w-full rounded-md border border-border bg-surface shadow-lg">
            <CommandPrimitive shouldFilter={false} className="w-full">
              <div className="flex items-center border-b border-border px-2">
                <CommandPrimitive.Input
                  ref={inputRef}
                  value={search}
                  onValueChange={setSearch}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setOpen(false);
                  }}
                  placeholder="Type to filter…"
                  className="flex h-8 w-full bg-transparent py-1 text-[13px] outline-none placeholder:text-muted"
                />
              </div>
              <CommandPrimitive.List className="max-h-48 overflow-y-auto p-1">
                {filteredItems.length === 0 && (
                  <CommandPrimitive.Empty className="py-4 text-center text-[12px] text-muted">
                    {emptyMessage}
                  </CommandPrimitive.Empty>
                )}
                <CommandPrimitive.Group>
                  {filteredItems.map((item) => (
                    <CommandPrimitive.Item
                      key={item.id}
                      value={item.id}
                      disabled={item.disabled}
                      onSelect={() => !item.disabled && handleSelect(item.id)}
                      className={cn(
                        'relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] outline-none',
                        'data-[selected=true]:bg-surface-2',
                        item.disabled && 'pointer-events-none opacity-40',
                      )}
                    >
                      <span className="font-mono text-[11px] font-medium text-fg shrink-0">
                        {item.label}
                      </span>
                      {item.description && (
                        <span className="truncate text-[11px] text-muted">
                          {item.description}
                        </span>
                      )}
                    </CommandPrimitive.Item>
                  ))}
                </CommandPrimitive.Group>
              </CommandPrimitive.List>
            </CommandPrimitive>
          </div>
        )}
      </div>
    );
  },
);
TicketCombobox.displayName = 'TicketCombobox';
