import { useState, type FormEvent } from 'react';
import { useComment } from '@/hooks/useMutations';
import { Input } from './ui/input';
import { Button } from './ui/button';

export function CommentThread({ issueId }: { issueId: string }) {
  const [text, setText] = useState('');
  const m = useComment(issueId);

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    const msg = text.trim();
    if (!msg) return;
    m.mutate(
      { message: msg },
      { onSuccess: () => setText('') },
    );
  };

  return (
    <form onSubmit={submit} className="flex gap-2 pt-3 border-t border-border">
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Add a comment…"
        disabled={m.isPending}
        className="flex-1"
      />
      <Button
        type="submit"
        size="sm"
        variant="outline"
        disabled={m.isPending || !text.trim()}
      >
        {m.isPending ? '…' : 'Post'}
      </Button>
    </form>
  );
}
