import { describe, it, expect, vi } from 'vitest';

import { renderWithProviders, getByNlddLabel } from '@/test/utils';
import type { InitiatiefDetail } from '@/types';
import { PersoonWerkScherm } from './PersoonWerkScherm';

const getPersoonWerk = vi.fn();
vi.mock('@/api/initiatiefRollen', () => ({
  getPersoonWerk: (...args: unknown[]) => getPersoonWerk(...args),
}));
vi.mock('@/contexts/LeadDetailContext', () => ({ useLeadDetail: () => ({ openLeadDetail: vi.fn() }) }));
vi.mock('@/contexts/TaskDetailContext', () => ({ useTaskDetail: () => ({ openTaskDetail: vi.fn() }) }));

describe('PersoonWerkScherm', () => {
  it('vraagt niets op voor een persoon-id uit de URL dat geen UUID is', () => {
    getPersoonWerk.mockReturnValue(new Promise(() => {}));
    renderWithProviders(
      <PersoonWerkScherm
        initiatief={{ id: 'i1' } as InitiatiefDetail}
        personId="../../../auth/status?"
        canEdit={false}
        onTerug={vi.fn()}
        onKiesRol={vi.fn()}
      />,
    );
    expect(getPersoonWerk).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Deze persoon is niet gevonden.');
    expect(getByNlddLabel('Alle rollen')).toBeTruthy();
  });
});
