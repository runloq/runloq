/** Modal navigation stack. Clicking an issue card pushes its ID;
 *  clicking an ID badge inside an open modal pushes that ID on top.
 *  Esc pops one; closing the modal entirely empties the stack.
 *  URL reflects the stack as ?modal=ID1,ID2,ID3 for deep links. */
import { create } from 'zustand';

interface ModalState {
  stack: string[];
  push: (id: string) => void;
  pop: () => void;
  close: () => void;
  reset: () => void;
  top: () => string | null;
  setStack: (ids: string[]) => void;
}

export const useModalStack = create<ModalState>((set, get) => ({
  stack: [],
  push: (id) => set((s) => (s.stack[s.stack.length - 1] === id ? s : { stack: [...s.stack, id] })),
  pop: () => set((s) => ({ stack: s.stack.slice(0, -1) })),
  close: () => set({ stack: [] }),
  reset: () => set({ stack: [] }),
  top: () => {
    const s = get().stack;
    return s.length ? s[s.length - 1] : null;
  },
  setStack: (ids) => set({ stack: ids }),
}));
