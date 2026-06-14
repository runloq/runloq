import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border font-mono text-[10px] uppercase tracking-wider',
  {
    variants: {
      variant: {
        default: 'border-border bg-surface text-fg px-2 py-0.5',
        accent:
          'border-accent/30 bg-accent/10 text-accent px-2 py-0.5',
        warning:
          'border-p1/30 bg-p1/10 text-p1 px-2 py-0.5',
        danger:
          'border-p0/30 bg-p0/10 text-p0 px-2 py-0.5',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}
