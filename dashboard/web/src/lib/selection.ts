import { create } from 'zustand';

/** IDs of all issues currently selected on the board. */
export interface SelectionState {
  selected: Set<string>;
  /** Anchor for Shift-click range selection — the last toggled item. */
  anchor: string | null;

  /** Toggle a single ID. Updates the anchor. */
  toggle: (id: string) => void;
  /** Add a range of IDs from the anchor to `id` (inclusive), using the
   *  `orderedIds` list to determine order. Updates the anchor. */
  addRange: (id: string, orderedIds: string[]) => void;
  /** Clear all selected IDs and reset the anchor. */
  clear: () => void;
  /** Whether the given ID is selected. */
  has: (id: string) => boolean;
  /** Number of selected IDs. */
  size: () => number;
  /** Select all IDs in the given list (replaces current selection). */
  selectAll: (ids: string[]) => void;
}

export const useSelection = create<SelectionState>((set, get) => ({
  selected: new Set<string>(),
  anchor: null,

  toggle(id: string) {
    set((s) => {
      const next = new Set(s.selected);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return { selected: next, anchor: id };
    });
  },

  addRange(id: string, orderedIds: string[]) {
    set((s) => {
      const next = new Set(s.selected);
      const anchor = s.anchor;

      if (!anchor || !orderedIds.includes(anchor) || !orderedIds.includes(id)) {
        // No valid anchor — fall back to toggle
        if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return { selected: next, anchor: id };
      }

      const anchorIdx = orderedIds.indexOf(anchor);
      const targetIdx = orderedIds.indexOf(id);
      const [lo, hi] = anchorIdx < targetIdx
        ? [anchorIdx, targetIdx]
        : [targetIdx, anchorIdx];

      for (let i = lo; i <= hi; i++) {
        next.add(orderedIds[i]);
      }
      // Anchor stays at the first point; target becomes the new end
      return { selected: next, anchor: id };
    });
  },

  clear() {
    set({ selected: new Set<string>(), anchor: null });
  },

  has(id: string) {
    return get().selected.has(id);
  },

  size() {
    return get().selected.size;
  },

  selectAll(ids: string[]) {
    set({ selected: new Set(ids), anchor: ids.at(-1) ?? null });
  },
}));
