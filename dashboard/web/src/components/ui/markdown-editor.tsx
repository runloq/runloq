/**
 * MarkdownEditor — dashboard-local MD editor wrapper.
 *
 * Wraps @uiw/react-md-editor with the dashboard's design tokens.
 * Fires onBlur when focus leaves the component entirely (for viewer↔editor toggle).
 */

import { forwardRef, useEffect, useRef, useState } from 'react';
import MDEditor from '@uiw/react-md-editor';
import {
  bold,
  italic,
  strikethrough,
  divider,
  title,
  link,
  code,
  codeBlock,
  unorderedListCommand,
  orderedListCommand,
  quote,
} from '@uiw/react-md-editor/commands';

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  placeholder?: string;
  minHeight?: number;
  autoFocus?: boolean;
}

export const MarkdownEditor = forwardRef<HTMLDivElement, MarkdownEditorProps>(
  (
    {
      value,
      onChange,
      onBlur,
      placeholder = 'Write markdown…',
      minHeight = 180,
      autoFocus = false,
    },
    ref,
  ) => {
    const wrapperRef = useRef<HTMLDivElement | null>(null);

    // Sync forwarded ref
    useEffect(() => {
      if (typeof ref === 'function') {
        ref(wrapperRef.current);
      } else if (ref) {
        ref.current = wrapperRef.current;
      }
    }, [ref]);

    // Blur detection: fire onBlur when focus leaves the wrapper entirely
    useEffect(() => {
      if (!onBlur) return;
      const el = wrapperRef.current;
      if (!el) return;

      const handleFocusOut = (e: FocusEvent) => {
        const related = e.relatedTarget as Node | null;
        if (!related || !el.contains(related)) {
          onBlur();
        }
      };

      el.addEventListener('focusout', handleFocusOut);
      return () => el.removeEventListener('focusout', handleFocusOut);
    }, [onBlur]);

    // Reactive colorMode — tracks .dark class on <html> via MutationObserver
    // so the editor updates immediately when the theme toggle fires.
    const [colorMode, setColorMode] = useState<'dark' | 'light'>(() =>
      typeof document !== 'undefined' &&
      document.documentElement.classList.contains('dark')
        ? 'dark'
        : 'light',
    );

    useEffect(() => {
      const obs = new MutationObserver(() => {
        setColorMode(
          document.documentElement.classList.contains('dark') ? 'dark' : 'light',
        );
      });
      obs.observe(document.documentElement, { attributeFilter: ['class'] });
      return () => obs.disconnect();
    }, []);

    return (
      <div ref={wrapperRef} data-color-mode={colorMode}>
        <MDEditor
          value={value}
          onChange={(val) => onChange(val ?? '')}
          preview="edit"
          autoFocus={autoFocus}
          textareaProps={{ placeholder }}
          height={minHeight}
          visibleDragbar={false}
          commands={[
            bold,
            italic,
            strikethrough,
            divider,
            title,
            link,
            divider,
            code,
            codeBlock,
            divider,
            unorderedListCommand,
            orderedListCommand,
            quote,
          ]}
          extraCommands={[]}
        />
      </div>
    );
  },
);
MarkdownEditor.displayName = 'MarkdownEditor';
