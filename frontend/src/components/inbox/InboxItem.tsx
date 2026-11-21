import { NlddListItemButton } from '@/components/nldd/NlddLink';
import { Icon } from '@/components/nldd/Icon';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { formatDateTimeShort } from '@/utils/dates';
import { richTextToPlain } from '@/utils/richtext';
import type { InboxItem as InboxItemType } from '@/types';

interface InboxItemProps {
  item: InboxItemType;
  onOpenThread?: (id: string) => void;
  onMarkRead?: (id: string) => void;
}

/**
 * One icon per notification type. The icon carries the type, so the row needs
 * no separate type badge: a coloured tag under every title repeated what the
 * title already said and made each row a line taller.
 */
const NOTIFICATION_ICONS: Record<string, string> = {
  task_assigned: 'check-list',
  task_reassigned: 'check-list',
  task_completed: 'check-mark-circle',
  task_overdue: 'clock',
  node_updated: 'file-text-pencil',
  edge_created: 'link',
  stakeholder_added: 'person-2',
  stakeholder_role_changed: 'person-2',
  coverage_needed: 'person-badge-plus',
  politieke_input_imported: 'megaphone',
  mention: 'at',
  direct_message: 'message-rectangle-text',
  agent_prompt: 'sparkles',
  opdracht_created: 'clipboard',
  opdracht_status_changed: 'clipboard',
  access_request: 'key',
  placement_request: 'person-badge-plus',
  placement_approved: 'check-mark-circle',
  placement_denied: 'dismiss-circle',
  emoji_reaction: 'face-smiling',
};

/**
 * Types whose message only restates the title. A mention says "Je bent genoemd
 * in: X" as title and "Je bent vermeld in 'X'." as message; showing both gives
 * two lines of the same fact. For those the second line names the sender.
 */
const MESSAGE_REPEATS_TITLE = new Set(['mention']);

const SUPPORTING_MAX = 160;

function supportingText(item: InboxItemType): string {
  const parts: string[] = [];
  if (item.notification_type && MESSAGE_REPEATS_TITLE.has(item.notification_type)) {
    if (item.sender_name) parts.push(`Door ${item.sender_name}`);
  } else {
    const plain = richTextToPlain(item.description).replace(/\s+/g, ' ').trim();
    if (plain) {
      parts.push(plain.length > SUPPORTING_MAX ? `${plain.slice(0, SUPPORTING_MAX).trimEnd()}…` : plain);
    }
  }
  if (item.reply_count) {
    parts.push(`${item.reply_count} ${item.reply_count === 1 ? 'reactie' : 'reacties'}`);
  }
  return parts.join(' · ');
}

/** `**` is the cell's bold syntax, so it must not come in with the title. */
function cellText(text: string): string {
  return text.replace(/\*\*/g, '');
}

export function InboxItemCard({ item, onOpenThread, onMarkRead }: InboxItemProps) {
  const { openTaskDetail } = useTaskDetail();
  const { openNodeDetail } = useNodeDetail();
  const { openLeadDetail } = useLeadDetail();

  const handleClick = () => {
    if (!item.read && onMarkRead) {
      onMarkRead(item.id);
    }
    if (item.type === 'message' && onOpenThread) {
      onOpenThread(item.id);
    } else if (item.task_id) {
      openTaskDetail(item.task_id);
    } else if (item.node_id) {
      openNodeDetail(item.node_id);
    } else if (item.lead_id) {
      openLeadDetail(item.lead_id);
    }
  };

  const icon = (item.notification_type && NOTIFICATION_ICONS[item.notification_type]) || 'bell';
  const title = cellText(item.title);
  const supporting = supportingText(item);

  // Read and unread differ in weight, not in layout. The unread dot sits in a
  // fixed column at the end, with an equally wide spacer on read rows, so the
  // titles of both kinds start on the same line; a dot in front of the title
  // pushed unread titles 30px to the right of read ones.
  return (
    <NlddListItemButton onClick={handleClick} size="sm">
      <nldd-icon-cell
        icon={icon}
        size="20"
        vertical-alignment="top"
        color={item.read ? 'secondary' : 'accent'}
      />
      <nldd-spacer-cell size="12" />
      <nldd-text-cell
        text={item.read ? title : `**${title}**`}
        {...(supporting ? { 'supporting-text': supporting } : {})}
        vertical-alignment="top"
        {...(item.read ? { color: 'secondary' } : {})}
      />
      {/* The date is metadata, so it is set a step smaller than the title, and
          it never wraps: a text cell at the row's own size put it at title
          size and broke "19 sep., 14:22" over two lines in a narrow window. */}
      <nldd-cell vertical-alignment="top" width="fit-content" horizontal-alignment="right">
        <nldd-text size="xs" color="secondary" style={{ whiteSpace: 'nowrap' }}>
          <p>{formatDateTimeShort(item.created_at)}</p>
        </nldd-text>
      </nldd-cell>
      <nldd-spacer-cell size="8" />
      {item.read ? (
        <nldd-spacer-cell size="16" />
      ) : (
        // A cell rather than nldd-icon-cell: the dot is the only place the row
        // says it is unread, so it needs a label, and the icon cell has none.
        <nldd-cell vertical-alignment="top">
          <Icon name="circle-filled-small" size="16" color="accent" label="Ongelezen" />
        </nldd-cell>
      )}
    </NlddListItemButton>
  );
}
