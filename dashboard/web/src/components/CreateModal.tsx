import { Dialog, DialogContent, DialogTitle } from './ui/dialog';
import { TicketForm } from './TicketForm';

export function CreateModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle className="font-mono text-[12px] text-muted mb-3">
          New ticket
        </DialogTitle>
        <TicketForm
          mode="create"
          onSaved={() => onOpenChange(false)}
          onCancel={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
