import { useState } from 'react';
import { Search, Plus, PanelLeftClose, PanelLeftOpen, Sun, Moon } from 'lucide-react';
import { Button } from './ui/button';
import { SavedViewsMenu } from './SavedViewsMenu';
import type { SavedView } from '@/lib/savedViews';
import type { Filters } from '@/lib/filterUrl';

// Theme toggle — reads/writes localStorage.theme and .dark class on <html>.
// Initial state sourced from the class (set synchronously by flash-prevention
// script in index.html before React mounts, so it's always accurate).
function ThemeToggle() {
  const [dark, setDark] = useState<boolean>(() =>
    document.documentElement.classList.contains('dark'),
  );

  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle('dark', next);
    // Add .light class when switching to light so the prefers-color-scheme
    // media query fallback (:root:not(.light)) doesn't override the choice.
    document.documentElement.classList.toggle('light', !next);
    localStorage.setItem('runloq.theme', next ? 'dark' : 'light');
    setDark(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className="text-muted hover:text-fg p-1 rounded-md hover:bg-surface-2 transition-colors cursor-pointer"
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

export function TopBar({
  sidebarOpen,
  onToggleSidebar,
  onSearchClick,
  onCreateClick,
  savedViews,
  onViewsChange,
  onSelectView,
}: {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onSearchClick: () => void;
  onCreateClick: () => void;
  savedViews: SavedView[];
  onViewsChange: (views: SavedView[]) => void;
  onSelectView: (filters: Filters) => void;
}) {
  return (
    <header className="sticky top-0 z-50 bg-bg/85 backdrop-blur-sm border-b border-border">
      <div className="flex h-12 items-center justify-between gap-2 px-3 md:px-4">
        <div className="flex items-center gap-2 md:gap-3">
          <button
            type="button"
            onClick={onToggleSidebar}
            className="text-muted hover:text-fg p-1 -ml-1 rounded-md hover:bg-surface-2 transition-colors cursor-pointer"
            title={sidebarOpen ? 'Hide sidebar (\\)' : 'Show sidebar (\\)'}
            aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-4 w-4" />
            ) : (
              <PanelLeftOpen className="h-4 w-4" />
            )}
          </button>
          <h1 className="font-mono text-[14px] font-medium tracking-tight">
            runloq
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <SavedViewsMenu
            views={savedViews}
            onViewsChange={onViewsChange}
            onSelectView={onSelectView}
          />
          <button
            type="button"
            onClick={onSearchClick}
            className="flex items-center gap-2 h-7 px-2.5 rounded-md border border-border bg-surface text-[12px] text-muted hover:border-border-strong hover:text-fg transition-colors cursor-pointer"
            title="Search (Ctrl+S)"
            aria-label="Search"
          >
            <Search className="h-3 w-3" />
            <span className="hidden md:inline">Search</span>
            <kbd className="hidden md:inline font-mono text-[10px] text-muted/70 border border-border rounded px-1 ml-2">
              Ctrl+S
            </kbd>
          </button>
          <Button size="sm" onClick={onCreateClick} title="Create issue (Ctrl+C)" aria-label="Create issue">
            <Plus className="h-3 w-3" />
            <span className="hidden md:inline">Create</span>
            <kbd className="hidden md:inline font-mono text-[10px] text-accent-fg/70 border border-accent-fg/30 rounded px-1 ml-1">
              Ctrl+C
            </kbd>
          </Button>
        </div>
      </div>
    </header>
  );
}
