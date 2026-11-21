import { useChat } from '@/contexts/ChatContext';
import { useUIStore } from '@/store/ui';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';

export function ChatHeader() {
  const { clearConversation } = useChat();
  const setChatOpen = useUIStore((s) => s.setChatOpen);

  return (
    <nldd-container
      layout="row"
      gap="8"
      padding="12"
      padding-inline="16"
      vertical-alignment="center"

    >
      <nldd-container width="full">
        <nldd-text size="sm" weight="bold"><p>Assistent</p></nldd-text>
      </nldd-container>
      <div className="hug">
        <NlddIconButton
          icon="trash"
          accessibleLabel="Gesprek wissen"
          variant="neutral-transparent"
          size="sm"
          onClick={clearConversation}
        />
        <NlddIconButton
          icon="close"
          accessibleLabel="Sluiten"
          variant="neutral-transparent"
          size="sm"
          onClick={() => setChatOpen(false)}
        />
      </div>
    </nldd-container>
  );
}
