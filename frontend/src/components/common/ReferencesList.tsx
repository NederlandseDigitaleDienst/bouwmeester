import { Badge } from '@/components/common/Badge';
import { NlddListItemButton } from '@/components/nldd/NlddLink';
import { useReferences } from '@/hooks/useMentions';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';

interface ReferencesListProps {
  targetId: string;
}

function ReferenceRow({
  label,
  title,
  color,
  onOpen,
}: {
  label: string;
  title: string;
  color: 'geel' | 'lintblauw';
  onOpen: () => void;
}) {
  return (
    <NlddListItemButton onClick={onOpen} size="sm">
      <nldd-cell width="fit-content">
        <Badge color={color}>{label}</Badge>
      </nldd-cell>
      <nldd-text-cell text={title} />
    </NlddListItemButton>
  );
}

export function ReferencesList({ targetId }: ReferencesListProps) {
  const { data: references } = useReferences(targetId);
  const { openTaskDetail } = useTaskDetail();
  const { openNodeDetail } = useNodeDetail();

  if (!references || references.length === 0) return null;

  return (
    <nldd-container gap="8">
      <nldd-container layout="row" gap="4" vertical-alignment="center">
        <nldd-icon icon="link" size="16" aria-hidden="true" />
        <nldd-text size="xs" weight="bold" color="secondary">
          Verwijzingen ({references.length})
        </nldd-text>
      </nldd-container>
      <nldd-list appearance="simple" accessible-label="Verwijzingen">
        {references.map((ref) => (
          <ReferenceRow
            key={`${ref.source_type}-${ref.source_id}`}
            label={
              ref.source_type === 'node' ? 'Node' : ref.source_type === 'task' ? 'Taak' : ref.source_type
            }
            title={ref.source_title}
            color={ref.source_type === 'task' ? 'geel' : 'lintblauw'}
            onOpen={() => {
              if (ref.source_type === 'node') openNodeDetail(ref.source_id);
              else if (ref.source_type === 'task') openTaskDetail(ref.source_id);
            }}
          />
        ))}
      </nldd-list>
    </nldd-container>
  );
}
