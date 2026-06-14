import { useModalStack } from '@/lib/modalStack';
import { cn } from '@/lib/cn';

/** Clickable issue ID — pushes the target onto the modal stack. */
export function IssueIdLink({ id, className }: { id: string; className?: string }) {
  const push = useModalStack((s) => s.push);
  return (
    <button
      type="button"
      onClick={() => push(id)}
      className={cn(
        'font-mono text-[12px] text-accent hover:underline underline-offset-2 cursor-pointer',
        className,
      )}
    >
      {id}
    </button>
  );
}
