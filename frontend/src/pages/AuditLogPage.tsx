import { useEffect, useRef, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/hooks/usePermissions';
import { useActivityFeed } from '@/hooks/useActivity';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { Select } from '@/components/common/Select';
import { EmptyState } from '@/components/common/EmptyState';
import { useNlddEvent } from '@/components/nldd/events';
import { NlddActionText } from '@/components/nldd/NlddLink';
import {
  Activity,
  EVENT_TYPE_LABELS,
  EVENT_TYPE_CATEGORY_LABELS,
  NODE_TYPE_LABELS,
  STAKEHOLDER_ROL_LABELS,
  TASK_PRIORITY_LABELS,
  TASK_STATUS_LABELS,
} from '@/types';

const PAGE_SIZE = 25;

const CATEGORY_OPTIONS = [
  { value: '', label: 'Alle categorieën' },
  ...Object.entries(EVENT_TYPE_CATEGORY_LABELS).map(([value, label]) => ({
    value,
    label,
  })),
];

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('nl-NL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Translate known values to Dutch display labels. */
function humanizeValue(key: string, value: unknown): string {
  const str = String(value);

  if (key === 'node_type') {
    return NODE_TYPE_LABELS[str as keyof typeof NODE_TYPE_LABELS] || str;
  }

  if (
    key === 'rol' ||
    key === 'old_rol' ||
    key === 'new_rol'
  ) {
    return STAKEHOLDER_ROL_LABELS[str] || str;
  }

  if (key === 'priority') {
    return (TASK_PRIORITY_LABELS as Record<string, string>)[str] || str;
  }

  if (key === 'old_status' || key === 'new_status') {
    return (TASK_STATUS_LABELS as Record<string, string>)[str] || str;
  }

  return str;
}

/** Presentable detail chips: label → display value. */
function buildChips(
  item: Activity,
): Array<{ label: string; value: string; highlight?: boolean }> {
  const d = item.details || {};
  const chips: Array<{ label: string; value: string; highlight?: boolean }> = [];

  // Node type
  if (d.node_type) {
    chips.push({
      label: 'Type',
      value: humanizeValue('node_type', d.node_type),
    });
  }

  // Person name (stakeholder events)
  if (d.person_naam) {
    chips.push({ label: 'Persoon', value: String(d.person_naam) });
  }

  // Roles
  if (d.rol) {
    chips.push({
      label: 'Rol',
      value: humanizeValue('rol', d.rol),
    });
  }
  if (d.old_rol && d.new_rol) {
    chips.push({
      label: 'Rol',
      value: `${humanizeValue('old_rol', d.old_rol)} → ${humanizeValue('new_rol', d.new_rol)}`,
    });
  }

  // Tag name
  if (d.tag_name) {
    chips.push({ label: 'Tag', value: String(d.tag_name) });
  }

  // Edge node titles
  if (d.from_node_title && d.to_node_title) {
    chips.push({
      label: 'Relatie',
      value: `${d.from_node_title} → ${d.to_node_title}`,
    });
  }
  if (d.edge_type) {
    chips.push({ label: 'Type', value: String(d.edge_type) });
  }

  // Task-specific
  if (d.priority) {
    chips.push({
      label: 'Prioriteit',
      value: humanizeValue('priority', d.priority),
    });
  }
  if (d.assignee_naam) {
    chips.push({ label: 'Toegewezen aan', value: String(d.assignee_naam) });
  }
  if (d.new_assignee_naam) {
    chips.push({
      label: 'Nieuw toegewezen',
      value: String(d.new_assignee_naam),
    });
  }

  // Status change
  if (d.old_status && d.new_status) {
    chips.push({
      label: 'Status',
      value: `${humanizeValue('old_status', d.old_status)} → ${humanizeValue('new_status', d.new_status)}`,
      highlight: true,
    });
  }

  // Org placement
  if (d.organisatie_eenheid_naam) {
    chips.push({
      label: 'Eenheid',
      value: String(d.organisatie_eenheid_naam),
    });
  }
  if (d.dienstverband) {
    chips.push({
      label: 'Dienstverband',
      value: String(d.dienstverband),
    });
  }

  // Import count
  if (d.count != null) {
    chips.push({ label: 'Aantal', value: String(d.count) });
  }

  return chips;
}

/** Render the details column. */
function DetailCell({
  item,
  onOpenNode,
  onOpenTask,
}: {
  item: Activity;
  onOpenNode: (id: string) => void;
  onOpenTask: (id: string) => void;
}) {
  const d = item.details || {};
  const subject = (d.title || d.naam || d.name) as string | undefined;
  const chips = buildChips(item);

  // Determine what clicking the subject should do
  const handleClick = () => {
    if (item.task_id && item.event_type.startsWith('task.')) {
      onOpenTask(item.task_id);
    } else if (item.node_id) {
      onOpenNode(item.node_id);
    }
  };

  const isClickable =
    (item.task_id && item.event_type.startsWith('task.')) || item.node_id;

  return (
    <nldd-container gap="4">
      {subject && (
        isClickable ? (
          <NlddActionText text={String(subject)} onClick={handleClick} />
        ) : (
          <nldd-text weight="medium"><p>{String(subject)}</p></nldd-text>
        )
      )}
      {chips.length > 0 && (
        <nldd-container layout="wrap" gap="6">
          {chips.map((chip, i) => (
            <nldd-tag
              key={i}
              size="sm"
              color={chip.highlight ? 'accent' : 'neutral'}
              text={`${chip.label}: ${chip.value}`}
            />
          ))}
        </nldd-container>
      )}
      {!subject && chips.length === 0 && <nldd-text color="secondary"><p>—</p></nldd-text>}
    </nldd-container>
  );
}

export function AuditLogPage() {
  const { person, oidcConfigured, loading, viewAsNonAdmin } = useAuth();
  const { hasPermission } = usePermissions();
  const [page, setPage] = useState(0);
  const [category, setCategory] = useState('');
  const { openNodeDetail } = useNodeDetail();
  const { openTaskDetail } = useTaskDetail();
  const paginationRef = useRef<HTMLElement>(null);

  const { data, isLoading, isError } = useActivityFeed({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    event_type: category || undefined,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  // Clamp page when totalPages shrinks (e.g. after applying a filter)
  useEffect(() => {
    if (totalPages > 0 && page >= totalPages) {
      setPage(totalPages - 1);
    }
  }, [totalPages, page]);

  useNlddEvent(paginationRef, 'page-change', (e) => {
    const detail = (e as CustomEvent<{ page?: number }>).detail;
    if (detail?.page) setPage(detail.page - 1);
  });

  if (loading) return null;
  if (viewAsNonAdmin || (oidcConfigured && (!person || !hasPermission('audit:read')))) {
    return <Navigate to="/" replace />;
  }

  return (
    <nldd-container gap="24">
      {/* Filters */}
      <nldd-container max-width="320px">
        <Select
          value={category}
          aria-label="Filter op categorie"
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(0);
          }}
          options={CATEGORY_OPTIONS}
        />
      </nldd-container>

      {/* Table */}
      <nldd-table
        columns="160px 220px 160px minmax(240px,1fr)"
        sm-columns="minmax(0,1fr)"
        lg-columns="160px 220px 160px minmax(240px,1fr)"
        accessible-label="Auditlog"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Tijdstip" hide-below="lg" />
          <nldd-text-cell text="Actie" hide-below="lg" />
          <nldd-text-cell text="Actor" hide-below="lg" />
          <nldd-text-cell text="Details" hide-below="lg" />
          <nldd-text-cell text="Activiteit" hide-above="md" />
        </nldd-table-row>
        {isLoading || isError || !data?.items.length ? null : (
          data.items.map((item) => (
            <nldd-table-row key={item.id}>
              <nldd-text-cell text={formatDate(item.created_at)} color="secondary" hide-below="lg" />
              <nldd-text-cell text={EVENT_TYPE_LABELS[item.event_type] || item.event_type} hide-below="lg" />
              <nldd-text-cell text={item.actor_naam || '—'} color="secondary" hide-below="lg" />
              <nldd-cell hide-below="lg">
                <DetailCell item={item} onOpenNode={openNodeDetail} onOpenTask={openTaskDetail} />
              </nldd-cell>
              {/* Below lg (sm and md both fall back to sm-columns, one track)
                  the four columns collapse into this single cell instead. */}
              <nldd-cell hide-above="md">
                <nldd-container gap="6">
                  <nldd-container layout="row" gap="8" horizontal-alignment="left">
                    <nldd-text size="xs" color="secondary">
                      <p>{formatDate(item.created_at)}</p>
                    </nldd-text>
                    {item.actor_naam && (
                      <nldd-text size="xs" weight="medium">
                        <p>{item.actor_naam}</p>
                      </nldd-text>
                    )}
                  </nldd-container>
                  <nldd-text size="sm" weight="medium">
                    <p>{EVENT_TYPE_LABELS[item.event_type] || item.event_type}</p>
                  </nldd-text>
                  <DetailCell item={item} onOpenNode={openNodeDetail} onOpenTask={openTaskDetail} />
                </nldd-container>
              </nldd-cell>
            </nldd-table-row>
          ))
        )}
        <div slot="empty">
          {isLoading ? (
            <nldd-inline-dialog variant="loading" text="Activiteiten laden..." />
          ) : isError ? (
            <EmptyState icon="exclamation-triangle" title="Fout bij laden van activiteiten" />
          ) : category ? (
            <EmptyState
              icon="magnifier"
              title="Geen activiteit gevonden"
              description="Pas de categorie aan om andere activiteit te zien."
            />
          ) : (
            <EmptyState icon="inbox" title="Geen activiteit gevonden" />
          )}
        </div>
      </nldd-table>

      {/* Pagination. Stacked, so the pagination gets the full width: it is a
          size container that swaps its page buttons for a compact select
          below 400px, and inside a fit-content wrapper it had no width to
          measure, so the buttons ran off the side of a phone screen. */}
      {totalPages > 1 && (
        <nldd-container gap="8">
          <nldd-text size="sm" color="secondary">
            <p>{data?.total ?? 0} resultaten — pagina {page + 1} van {totalPages}</p>
          </nldd-text>
          <nldd-pagination ref={paginationRef} current={page + 1} total={totalPages} />
        </nldd-container>
      )}
    </nldd-container>
  );
}
