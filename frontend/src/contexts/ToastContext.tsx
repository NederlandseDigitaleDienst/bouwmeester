import { createContext, useCallback, useContext, useEffect, useState } from 'react';

/** An action offered alongside the message, e.g. undoing what just happened. */
export interface ToastAction {
  label: string;
  onAction: () => void;
}

interface Toast {
  id: number;
  message: string;
  variant: 'error' | 'success' | 'warning';
  action?: ToastAction;
}

interface ToastContextValue {
  showError: (message: string, action?: ToastAction) => void;
  showSuccess: (message: string, action?: ToastAction) => void;
  showWarning: (message: string, action?: ToastAction) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 0;

/** Our variants in the design system's terms. */
const VARIANTS = {
  error: 'critical',
  warning: 'warning',
  success: 'success',
} as const;

/**
 * One notification.
 *
 * The element runs its own clock and dismisses itself, then fires `dismiss`
 * for the consumer to remove it; this provider keeps no timers of its own. A
 * `critical` notification ignores the clock and waits for the user, so an error
 * never disappears on its own.
 *
 * Created here rather than rendered as JSX. nldd-notification places itself:
 * on connect it moves into the design system's shared region (or into the
 * topmost open overlay), wherever it was written. React would still remove it
 * from the parent it rendered it into, and once it has moved that removeChild
 * throws NotFoundError and unmounts the app. So React owns only the lifetime
 * and the element owns its place.
 */
function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const el = document.createElement('nldd-notification');
    el.setAttribute('variant', VARIANTS[toast.variant]);
    el.setAttribute('text', toast.message);
    el.setAttribute('duration', String(toast.variant === 'warning' ? 8000 : 5000));
    el.addEventListener('dismiss', () => onDismiss(toast.id));

    if (toast.action) {
      const { label, onAction } = toast.action;
      const button = document.createElement('nldd-button');
      button.setAttribute('slot', 'actions');
      button.setAttribute('variant', 'content-tinted');
      button.setAttribute('size', 'sm');
      button.setAttribute('text', label);
      button.addEventListener('click', () => {
        onAction();
        onDismiss(toast.id);
      });
      el.append(button);
    }

    // Anywhere connected will do: it moves itself into the region from here.
    document.body.append(el);
    return () => el.remove();
  }, [toast, onDismiss]);

  return null;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (message: string, variant: Toast['variant'], action?: ToastAction) => {
      const id = nextId++;
      setToasts((prev) => [...prev, { id, message, variant, action }]);
    },
    [],
  );

  const showError = useCallback(
    (message: string, action?: ToastAction) => addToast(message, 'error', action),
    [addToast],
  );
  const showSuccess = useCallback(
    (message: string, action?: ToastAction) => addToast(message, 'success', action),
    [addToast],
  );
  const showWarning = useCallback(
    (message: string, action?: ToastAction) => addToast(message, 'warning', action),
    [addToast],
  );

  return (
    <ToastContext.Provider value={{ showError, showSuccess, showWarning }}>
      {children}
      {/* No wrapper: nldd-notification positions and stacks itself. */}
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
      ))}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
