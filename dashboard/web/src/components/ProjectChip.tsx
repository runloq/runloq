import { cn } from '@/lib/cn';

const PROJECT_LABEL: Record<string, string> = {
  SYS: 'sys',
  ARC: 'arc',
  VER: 'ver',
  PUR: 'pur',
  DUC: 'duc',
  FRG: 'frg',
  PAR: 'par',
};

/** Project-tinted classes — matches the card left-border color so the project
 *  signal is consistent across the chip and the card edge. */
const PROJECT_CHIP: Record<string, string> = {
  SYS: 'text-proj-sys border-proj-sys/40 bg-proj-sys/10',
  ARC: 'text-proj-arc border-proj-arc/40 bg-proj-arc/10',
  VER: 'text-proj-ver border-proj-ver/40 bg-proj-ver/10',
  PUR: 'text-proj-pur border-proj-pur/40 bg-proj-pur/10',
  DUC: 'text-proj-duc border-proj-duc/40 bg-proj-duc/10',
  FRG: 'text-proj-frg border-proj-frg/40 bg-proj-frg/10',
  PAR: 'text-proj-par border-proj-par/40 bg-proj-par/10',
};

export function ProjectChip({ project }: { project: string }) {
  const label = PROJECT_LABEL[project] ?? project.toLowerCase();
  const tone = PROJECT_CHIP[project] ?? 'text-muted border-border';
  return (
    <span
      className={cn(
        'font-mono text-[10px] uppercase tracking-wider',
        'border rounded px-1.5 py-px',
        tone,
      )}
    >
      {label}
    </span>
  );
}
