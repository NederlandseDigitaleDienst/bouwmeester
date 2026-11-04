import { useCallback, useRef, useState, useMemo, type ReactNode } from 'react';
import { useAppConfig, useUpdateAppConfig, type AppConfigEntry } from '@/hooks/useAdmin';
import { NlddButton } from '@/components/nldd/NlddButton';
import { eventValue, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

interface ConfigGroup {
  label: string;
  description: string;
  icon: ReactNode;
  entries: AppConfigEntry[];
}

const GROUP_DEFS: { prefix: string[]; label: string; description: string; icon: ReactNode }[] = [
  {
    prefix: ['ANTHROPIC_', 'LLM_', 'VLAM_'],
    label: 'LLM-instellingen',
    description: 'API-sleutels en modelconfiguratie voor Claude en VLAM.',
    icon: <nldd-icon icon="sparkles" size="20" color="accent" box />,
  },
  {
    prefix: ['MATTERMOST_'],
    label: 'Mattermost',
    description: 'Configuratie voor de Mattermost-integratie (notificaties, slash-commando\u2019s).',
    icon: <nldd-icon icon="message-rectangle-text" size="20" color="accent" box />,
  },
];

function groupConfig(entries: AppConfigEntry[]): ConfigGroup[] {
  const groups: ConfigGroup[] = GROUP_DEFS.map((def) => ({
    label: def.label,
    description: def.description,
    icon: def.icon,
    entries: [],
  }));
  const other: AppConfigEntry[] = [];

  for (const entry of entries) {
    const idx = GROUP_DEFS.findIndex((def) =>
      def.prefix.some((p) => entry.key.startsWith(p)),
    );
    if (idx >= 0) {
      groups[idx].entries.push(entry);
    } else {
      other.push(entry);
    }
  }

  // Append ungrouped entries as "Overig" if any
  if (other.length > 0) {
    groups.push({
      label: 'Overig',
      description: 'Overige configuratie.',
      icon: null,
      entries: other,
    });
  }

  return groups.filter((g) => g.entries.length > 0);
}

export function ConfigManager() {
  const { data: config, isLoading } = useAppConfig();
  const groups = useMemo(() => groupConfig(config ?? []), [config]);

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  if (groups.length === 0) {
    return <nldd-inline-dialog text="Geen configuratie beschikbaar" />;
  }

  return (
    <nldd-container gap="24">
      <nldd-text size="xs" color="secondary">Wijzigingen worden direct actief.</nldd-text>

      {groups.map((group) => (
        <nldd-container key={group.label} gap="12">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            {group.icon}
            <nldd-container gap="0">
              <nldd-text size="sm" weight="bold">{group.label}</nldd-text>
              <nldd-text size="xs" color="secondary">{group.description}</nldd-text>
            </nldd-container>
          </nldd-container>
          <nldd-container gap="8">
            {group.entries.map((entry) => (
              <ConfigRow key={entry.id} entry={entry} />
            ))}
          </nldd-container>
        </nldd-container>
      ))}
    </nldd-container>
  );
}

function ConfigRow({ entry }: { entry: AppConfigEntry }) {
  const updateConfig = useUpdateAppConfig();
  const [value, setValue] = useState(entry.is_secret ? '' : entry.value);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const fieldRef = useRef<HTMLElement>(null);

  useNlddEvent(fieldRef, 'input', useCallback((e: Event) => setValue(eventValue(e)), []));
  useNlddValue(fieldRef, value);

  const handleSave = () => {
    updateConfig.mutate(
      { key: entry.key, value },
      {
        onSuccess: () => {
          setEditing(false);
          setSaved(true);
          setTimeout(() => setSaved(false), 2000);
        },
      },
    );
  };

  const handleStartEdit = () => {
    // When editing a secret, start with empty value (user must re-enter)
    setValue(entry.is_secret ? '' : entry.value);
    setEditing(true);
  };

  const displayValue = entry.is_secret ? entry.value : entry.value || '-';

  return (
    <nldd-card>
      <nldd-container gap="8" padding="16">
        <nldd-container layout="row" gap="16" horizontal-alignment="left" vertical-alignment="top">
          <nldd-container width="fit-content" className="row-fill" gap="4">
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <nldd-text size="sm" weight="medium">{entry.key}</nldd-text>
              {entry.is_secret && <nldd-tag text="geheim" color="warning" size="sm" />}
            </nldd-container>
            {entry.description && (
              <nldd-text size="xs" color="secondary">{entry.description}</nldd-text>
            )}

            {editing ? (
              <nldd-container layout="row" gap="8" vertical-alignment="center">
                <nldd-text-field
                  ref={fieldRef}
                  placeholder={entry.is_secret ? 'Voer nieuwe waarde in...' : 'Waarde...'}
                  accessible-label={`Waarde voor ${entry.key}`}
                />
                <NlddButton
                  text="Opslaan"
                  size="sm"
                  onClick={handleSave}
                  disabled={updateConfig.isPending}
                  loading={updateConfig.isPending}
                />
                <NlddButton
                  text="Annuleren"
                  variant="neutral-tinted"
                  size="sm"
                  onClick={() => setEditing(false)}
                />
              </nldd-container>
            ) : (
              <nldd-container layout="row" gap="8" vertical-alignment="center">
                <nldd-text size="xs" color="secondary">{displayValue}</nldd-text>
                {saved && <nldd-tag text="Opgeslagen" icon="check-mark" color="success" size="sm" />}
              </nldd-container>
            )}
          </nldd-container>

          {!editing && (
            <NlddButton text="Bewerken" variant="neutral-transparent" size="xs" onClick={handleStartEdit} />
          )}
        </nldd-container>

        {entry.updated_by && (
          <nldd-text size="xxs" color="secondary">
            Laatst gewijzigd door {entry.updated_by} op{' '}
            {new Date(entry.updated_at).toLocaleDateString('nl-NL', {
              day: 'numeric',
              month: 'short',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </nldd-text>
        )}
      </nldd-container>
    </nldd-card>
  );
}
