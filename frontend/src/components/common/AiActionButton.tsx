import { useCallback, useRef } from 'react';
import { orUndef, useNlddEvent } from '@/components/nldd/events';

interface AiActionButtonProps {
  label: string;
  loading: boolean;
  onClick: () => void;
  disabled?: boolean;
  /** Compact style for inline use within step rows */
  compact?: boolean;
}

/**
 * Reusable AI-action button with sparkle icon and loading spinner.
 * Used by TagSuggestions, GapAnalysisPanel, KompasStepSuggestions.
 */
export function AiActionButton({
  label,
  loading,
  onClick,
  disabled = false,
  compact = false,
}: AiActionButtonProps) {
  const ref = useRef<HTMLElement>(null);
  const handleClick = useCallback(() => onClick(), [onClick]);
  useNlddEvent(ref, 'click', handleClick);

  return (
    <nldd-button
      ref={ref}
      type="button"
      appearance={compact ? 'neutral-transparent' : 'secondary'}
      size="xs"
      text={label}
      start-icon={loading ? undefined : 'sparkles'}
      loading={orUndef(loading)}
      {...(disabled ? { disabled: true } : {})}
    />
  );
}
