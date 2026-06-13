import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/cn';

interface MarkdownProps {
  children: string;
  className?: string;
}

/**
 * Renders markdown content with our design system typography.
 * - Uses react-markdown (no dangerouslySetInnerHTML, raw HTML escaped by default)
 * - remark-gfm adds GFM: tables, strikethrough, task lists, autolinks
 * - Headings are scaled down (h1 = text-sm font-medium) so they don't overpower the modal
 * - Code blocks and inline code use JetBrains Mono
 * - Links get accent color + underline
 */
export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={cn('markdown-body text-sm leading-relaxed', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings — sized down so h1 doesn't dominate a dense modal
          h1: ({ children }) => (
            <h1 className="text-sm font-medium text-fg mt-3 mb-1 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-[13px] font-medium text-fg mt-3 mb-1 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-[12px] font-medium text-muted uppercase tracking-wider mt-3 mb-1 first:mt-0">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-[11px] font-medium text-muted uppercase tracking-wider mt-2 mb-0.5 first:mt-0">{children}</h4>
          ),
          h5: ({ children }) => (
            <h5 className="text-[11px] font-medium text-muted mt-2 mb-0.5 first:mt-0">{children}</h5>
          ),
          h6: ({ children }) => (
            <h6 className="text-[11px] text-muted mt-2 mb-0.5 first:mt-0">{children}</h6>
          ),
          // Paragraphs
          p: ({ children }) => (
            <p className="text-fg/90 mb-2 last:mb-0">{children}</p>
          ),
          // Lists
          ul: ({ children }) => (
            <ul className="list-disc list-outside pl-4 mb-2 space-y-0.5 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-outside pl-4 mb-2 space-y-0.5 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="text-fg/90">{children}</li>
          ),
          // Inline code — JetBrains Mono, subtle background
          code: ({ className: cls, children, ...props }) => {
            // Block code gets a different treatment (handled by `pre`)
            const isInline = !cls;
            return isInline ? (
              <code
                className="font-mono text-[12px] bg-surface-2 border border-border rounded px-1 py-0.5 text-fg"
                {...props}
              >
                {children}
              </code>
            ) : (
              <code className={cn('font-mono text-[12px]', cls)} {...props}>
                {children}
              </code>
            );
          },
          // Code blocks
          pre: ({ children }) => (
            <pre className="font-mono text-[12px] bg-surface-2 border border-border rounded-md p-3 overflow-x-auto mb-2 last:mb-0">
              {children}
            </pre>
          ),
          // Links — accent color, underline, open in new tab
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline underline-offset-2 hover:opacity-80"
            >
              {children}
            </a>
          ),
          // Blockquotes
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-border pl-3 text-muted italic mb-2 last:mb-0">
              {children}
            </blockquote>
          ),
          // Horizontal rule
          hr: () => <hr className="border-border my-3" />,
          // Strong / em
          strong: ({ children }) => (
            <strong className="font-medium text-fg">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic">{children}</em>
          ),
          // Tables (GFM)
          table: ({ children }) => (
            <div className="overflow-x-auto mb-2 last:mb-0">
              <table className="w-full text-[12px] border-collapse border border-border">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-surface-2">{children}</thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => (
            <tr className="border-b border-border">{children}</tr>
          ),
          th: ({ children }) => (
            <th className="text-left font-medium px-2 py-1 text-fg border-r border-border last:border-r-0">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-2 py-1 text-fg/90 border-r border-border last:border-r-0">
              {children}
            </td>
          ),
          // Task list items (GFM checkboxes)
          input: ({ type, checked, disabled }) =>
            type === 'checkbox' ? (
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                readOnly
                className="mr-1.5 accent-accent"
              />
            ) : null,
          // Strikethrough (GFM)
          del: ({ children }) => (
            <del className="opacity-60">{children}</del>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
