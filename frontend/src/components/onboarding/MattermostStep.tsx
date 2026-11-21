import { useEffect } from 'react';
import { MattermostLinkSection } from '@/components/settings/MattermostLinkSection';
import { useMattermostLinkStatus } from '@/hooks/useMattermost';
import { useAuth } from '@/contexts/AuthContext';
import { NlddButton } from '@/components/nldd/NlddButton';

export function MattermostStep({ onComplete }: { onComplete: () => void }) {
  const { person: authPerson } = useAuth();
  const personId = authPerson?.id ?? undefined;
  const hasPersonId = !!personId;

  const { data: linkStatus } = useMattermostLinkStatus(true, hasPersonId, personId);
  const linked = linkStatus?.linked ?? false;

  // Auto-advance after a short delay so the user sees the success state.
  useEffect(() => {
    if (linked) {
      const timer = setTimeout(() => onComplete(), 3000);
      return () => clearTimeout(timer);
    }
  }, [linked, onComplete]);

  if (linked) {
    return (
      <nldd-container gap="12" horizontal-alignment="center" padding-block="32">
        <nldd-inline-dialog variant="success" text="Mattermost gekoppeld" supporting-text="Je ontvangt nu notificaties in Mattermost." />
        <NlddButton text="Doorgaan" onClick={onComplete} />
      </nldd-container>
    );
  }

  return (
    <nldd-container gap="16">
      <nldd-container gap="4">
        <nldd-text weight="medium"><p>Koppel Mattermost</p></nldd-text>
        <nldd-text size="sm" color="secondary">
          <p>
            Koppel je Mattermost-account om notificaties over taken en dossiers direct te ontvangen. Je kunt
            dit ook later doen via Instellingen.
          </p>
        </nldd-text>
      </nldd-container>
      <MattermostLinkSection compact />
    </nldd-container>
  );
}
