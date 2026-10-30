import { TaskStatus } from '@/types';

/**
 * Is alles onder een onderzoeksvraag af als deze ene taak de nieuwe status
 * krijgt? Geannuleerde taken tellen niet mee, net als in de backend
 * (IssueRepository.sync_status). Zonder taken is er niets af te ronden.
 *
 * `taken` moet de volledige lijst zijn, niet een gefilterde: met het filter
 * op taakeigenaar ziet het kanban maar een deel.
 */
export function allesAfNa(
  taken: { id: string; status: TaskStatus | string }[],
  taakId: string,
  nieuweStatus: TaskStatus | string,
): boolean {
  if (nieuweStatus !== TaskStatus.DONE) return false;
  const tellend = taken
    .map((t) => (t.id === taakId ? { ...t, status: nieuweStatus } : t))
    .filter((t) => t.status !== TaskStatus.CANCELLED);
  return tellend.length > 0 && tellend.every((t) => t.status === TaskStatus.DONE);
}
