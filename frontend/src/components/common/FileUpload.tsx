import { useCallback, useRef, useState, type DragEvent } from 'react';
import { useNlddEvent, orUndef } from '@/components/nldd/events';

interface FileUploadProps {
  accept?: string;
  onFileSelect: (file: File) => void;
  disabled?: boolean;
  label?: string;
}

/**
 * `nldd-file-field` with a drop target around it.
 *
 * The field itself is the picker, the chosen file, its size and the button to
 * clear it again. What it does not do is accept a dropped file, and this
 * component is reached by dragging a CSV onto it often enough to be worth a
 * drop target. So the field handles picking, the wrapper handles dropping, and
 * both end at the same callback.
 */
export function FileUpload({
  accept = '.csv',
  onFileSelect,
  disabled = false,
  label = 'Sleep een bestand hierheen of klik om te uploaden',
}: FileUploadProps) {
  const fieldRef = useRef<HTMLElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  useNlddEvent(fieldRef, 'change', (e) => {
    const file = (e as CustomEvent<{ files: File[] }>).detail?.files?.[0];
    if (file) onFileSelect(file);
  });

  const handleDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (!disabled) setIsDragging(true);
    },
    [disabled],
  );

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled) return;
      const file = e.dataTransfer.files[0];
      if (file) onFileSelect(file);
    },
    [disabled, onFileSelect],
  );

  return (
    <nldd-container gap="8">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        // A dashed outline that appears while a file hovers over the target.
        // Not a component: the design system has no drop zone, and this is the
        // one thing the field does not cover.
        style={{
          borderRadius: 'var(--primitives-corner-radius-lg)',
          outline: isDragging
            ? '2px dashed var(--primitives-color-accent-500)'
            : '2px dashed transparent',
          outlineOffset: '4px',
          transition: 'outline-color 150ms',
        }}
      >
        <nldd-file-field
          ref={fieldRef}
          accept={accept}
          accessible-label={label}
          disabled={orUndef(disabled)}
        />
      </div>
      <nldd-text size="xs" color="secondary">
        <p>Ondersteunde formaten: {accept}</p>
      </nldd-text>
    </nldd-container>
  );
}
