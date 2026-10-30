import { useState } from 'react';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { Input } from '@/components/common/Input';
import { DetailSection } from '@/components/common/DetailSection';
import { ApiError } from '@/api/client';
import {
  useAddLeadGitHubLink,
  useUpdateLeadGitHubLink,
  useDeleteLeadGitHubLink,
} from '@/hooks/useLeads';
import type { LeadGitHubLink, GitHubLinkType } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

interface Props {
  leadId: string;
  links: LeadGitHubLink[];
}

/** nldd-icon names. `repo` has no dedicated glyph in the closed set, so it
 *  falls back to the nearest honest neighbour (a code/terminal icon). */
const TYPE_ICONS: Record<GitHubLinkType, string> = {
  branch: 'git-branch',
  pull_request: 'git-pull-request',
  issue: 'circle',
  repo: 'terminal',
  workflow_run: 'media-play',
  other: 'external-link',
};

const TYPE_LABELS: Record<GitHubLinkType, string> = {
  branch: 'branch',
  pull_request: 'PR',
  issue: 'issue',
  repo: 'repo',
  workflow_run: 'run',
  other: 'link',
};

function shortRef(link: LeadGitHubLink): string {
  if (link.link_type === 'pull_request' || link.link_type === 'issue') {
    return `#${link.ref ?? '?'}`;
  }
  if (link.link_type === 'workflow_run') {
    return `run ${link.ref ?? '?'}`;
  }
  if (link.link_type === 'branch') {
    return link.ref ?? '?';
  }
  return '';
}

export function LeadGitHubLinks({ leadId, links }: Props) {
  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  const addLink = useAddLeadGitHubLink();
  const updateLink = useUpdateLeadGitHubLink();
  const deleteLink = useDeleteLeadGitHubLink();

  const submit = async () => {
    setError(null);
    const trimmed = url.trim();
    if (!trimmed) {
      setError('Plak een GitHub-URL.');
      return;
    }
    try {
      await addLink.mutateAsync({
        leadId,
        url: trimmed,
        title: title.trim() || null,
      });
      setUrl('');
      setTitle('');
      setShowForm(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError('Geen geldige GitHub-URL.');
      } else if (e instanceof ApiError && e.status === 409) {
        setError('Deze link is al gekoppeld.');
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Kon link niet toevoegen.');
      }
    }
  };

  const startEdit = (link: LeadGitHubLink) => {
    setEditingId(link.id);
    setEditingTitle(link.title ?? '');
  };

  const saveEdit = async (link: LeadGitHubLink) => {
    await updateLink.mutateAsync({
      leadId,
      linkId: link.id,
      title: editingTitle.trim() || null,
    });
    setEditingId(null);
  };

  return (
    <DetailSection
      title="GitHub-werk"
      icon={<Icon name="terminal" size="sm" />}
      count={links.length}
      separated
      action={
        <NlddButton variant="neutral-transparent" size="sm" startIcon="plus" onClick={() => setShowForm((v) => !v)} text="Link toevoegen" />
      }
    >
      {showForm && (
        <nldd-card background="tinted">
          <nldd-container gap="8" padding="12">
            <Input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/owner/repo/pull/123"
              autoFocus
            />
            <Input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Titel (optioneel)"
            />
            {error && (
              <nldd-validation-list>
                <nldd-validation-item>{error}</nldd-validation-item>
              </nldd-validation-list>
            )}
            <nldd-container layout="row" gap="8" horizontal-alignment="right">
              <NlddButton
                variant="neutral-transparent"
                size="sm"
                onClick={() => {
                  setShowForm(false);
                  setUrl('');
                  setTitle('');
                  setError(null);
                }}
                text="Annuleren"
              />
              <NlddButton variant="primary" size="sm" onClick={submit} disabled={addLink.isPending} text="Toevoegen" />
            </nldd-container>
          </nldd-container>
        </nldd-card>
      )}

      {links.length > 0 ? (
        <nldd-list appearance="simple" dividers="never" accessible-label="GitHub-werk">
          {links.map((link) => (
            <GitHubLinkRow
              key={link.id}
              link={link}
              editing={editingId === link.id}
              editingTitle={editingTitle}
              onEditingTitleChange={setEditingTitle}
              onStartEdit={() => startEdit(link)}
              onCancelEdit={() => setEditingId(null)}
              onSaveEdit={() => saveEdit(link)}
              onDelete={() => deleteLink.mutate({ leadId, linkId: link.id })}
            />
          ))}
        </nldd-list>
      ) : (
        !showForm && (
          <nldd-text size="sm" color="secondary">
            Nog geen GitHub-werk gekoppeld. Plak een URL van een branch, PR of
            issue.
          </nldd-text>
        )
      )}
    </DetailSection>
  );
}

interface GitHubLinkRowProps {
  link: LeadGitHubLink;
  editing: boolean;
  editingTitle: string;
  onEditingTitleChange: (value: string) => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onDelete: () => void;
}

function GitHubLinkRow({
  link,
  editing,
  editingTitle,
  onEditingTitleChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}: GitHubLinkRowProps) {
  const ref = shortRef(link);
  const display =
    link.title ?? (ref ? `${link.owner}/${link.repo} ${ref}` : `${link.owner}/${link.repo}`);

  if (editing) {
    return (
      <nldd-list-item>
        <nldd-icon-cell icon={TYPE_ICONS[link.link_type]} size="16" />
        <nldd-text-cell width="full">
          <Input
            type="text"
            value={editingTitle}
            onChange={(e) => onEditingTitleChange(e.target.value)}
            autoFocus
          />
        </nldd-text-cell>
        <NlddIconButton icon="check-mark" accessibleLabel="Opslaan" variant="neutral-transparent" size="sm" onClick={onSaveEdit} />
        <NlddIconButton icon="close" accessibleLabel="Annuleren" variant="neutral-transparent" size="sm" onClick={onCancelEdit} />
      </nldd-list-item>
    );
  }

  return (
    <nldd-list-item>
      <nldd-icon-cell icon={TYPE_ICONS[link.link_type]} size="16" />
      <nldd-list-item-segment href={link.url} target="_blank" rel="noreferrer" width="full" accessible-label={display}>
        {display}
      </nldd-list-item-segment>
      <nldd-tag text={TYPE_LABELS[link.link_type]} color="neutral" size="sm" />
      <NlddIconButton icon="pencil" accessibleLabel="Titel bewerken" variant="neutral-transparent" size="sm" onClick={onStartEdit} />
      <NlddIconButton icon="trash" accessibleLabel="Verwijderen" variant="neutral-transparent" size="sm" onClick={onDelete} />
    </nldd-list-item>
  );
}
