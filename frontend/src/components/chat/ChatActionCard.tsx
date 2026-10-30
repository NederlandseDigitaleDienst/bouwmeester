import { useCallback, useRef } from 'react';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNlddEvent } from '@/components/nldd/events';
import type { ChatAction } from '@/api/chat';

interface ChatActionCardProps {
  action: ChatAction;
}

export function ChatActionCard({ action }: ChatActionCardProps) {
  const { openNodeDetail } = useNodeDetail();
  const { openTaskDetail } = useTaskDetail();
  const ref = useRef<HTMLElement>(null);

  const canNavigate =
    action.entity_id &&
    (action.entity_type === 'node' || action.entity_type === 'task' || action.entity_type === 'tag');

  const handleClick = useCallback(() => {
    if (!action.entity_id) return;
    if (action.entity_type === 'node' || action.entity_type === 'tag') {
      openNodeDetail(action.entity_id);
    } else if (action.entity_type === 'task') {
      openTaskDetail(action.entity_id);
    }
  }, [action.entity_id, action.entity_type, openNodeDetail, openTaskDetail]);

  useNlddEvent(ref, 'click', canNavigate ? handleClick : undefined);

  return (
    <nldd-card
      ref={ref}
      {...(canNavigate ? { button: true, 'accessible-label': `${action.description} — bekijken` } : {})}
    >
      <nldd-container layout="row" gap="8" padding="12" vertical-alignment="top">
        <nldd-icon icon="check-mark" size="16" color="success" aria-hidden="true" />
        <nldd-text-cell
          size="sm"
          color="success"
          text={action.description}
          width="full"
          {...(action.result_summary && action.result_summary !== action.description
            ? { 'supporting-text': action.result_summary }
            : {})}
        />
        {canNavigate && (
          <nldd-icon icon="external-link" size="16" color="success" aria-hidden="true" />
        )}
      </nldd-container>
    </nldd-card>
  );
}
