// Dashboard-local Dialog wrapper. Adds fullscreen-on-mobile (SYS-181),
// `showClose` and `bodyClass`. All Radix parts must come from a single
// @radix-ui/react-dialog module instance — mixing strata's re-export with
// the dashboard's local Portal/Content put Root and Portal in different
// React contexts and broke with "DialogPortal must be used within Dialog".
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';
import { cn } from '@/lib/cn';

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export const DialogOverlay = forwardRef<
  ElementRef<typeof DialogPrimitive.Overlay>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-bg/60 backdrop-blur-[2px]',
      'data-[state=open]:animate-in data-[state=closed]:animate-out',
      'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    showClose?: boolean;
    bodyClass?: string;
  }
>(({ className, children, showClose = true, bodyClass = 'p-5', ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        // Mobile (<md): fullscreen — top-12 sits below the sticky topbar (SYS-181),
        // no translate, no max-w, border-radius only at top.
        'fixed inset-x-0 bottom-0 top-12 z-[60]',
        'md:inset-x-auto md:bottom-auto md:left-1/2 md:top-[8vh] md:-translate-x-1/2',
        'w-full md:w-full md:max-w-[720px]',
        'flex flex-col max-h-[calc(100vh-3rem)] md:max-h-[84vh]',
        'bg-surface border-t border-border-strong md:border md:rounded-lg rounded-t-lg',
        'shadow-[var(--shadow-modal)]',
        'data-[state=open]:animate-in data-[state=closed]:animate-out',
        'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
        'data-[state=closed]:slide-out-to-bottom md:data-[state=closed]:slide-out-to-bottom-0',
        'data-[state=open]:slide-in-from-bottom md:data-[state=open]:slide-in-from-bottom-0',
        'md:data-[state=closed]:zoom-out-95 md:data-[state=open]:zoom-in-95',
        'duration-200',
        className,
      )}
      {...props}
    >
      <div className={cn('flex-1 overflow-y-auto', bodyClass)}>{children}</div>
      {showClose && (
        <DialogPrimitive.Close className="absolute right-3 top-3 z-10 rounded-md p-1 text-muted bg-surface/80 backdrop-blur-sm hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <X className="h-3.5 w-3.5" />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;
