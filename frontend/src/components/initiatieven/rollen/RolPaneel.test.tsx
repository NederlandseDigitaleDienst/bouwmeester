import { describe, it, expect, vi } from 'vitest';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders, getByNlddLabel } from '@/test/utils';
import type { InitiatiefCirkel, InitiatiefDetail, InitiatiefRol } from '@/types';
import { CirkelPaneel } from './CirkelPaneel';
import { RolPaneel } from './RolPaneel';

vi.mock('@/hooks/useInitiatieven', () => ({ useInitiatiefPersonen: () => ({ data: [] }) }));

const rol: InitiatiefRol = {
  id: 'r1',
  initiatief_id: 'i1',
  cirkel_id: 'c1',
  naam: 'Spelverdeler',
  status: 'open',
  doel: null,
  aanspreekbaar_op: [],
  domein: [],
  toelichting: null,
  feedback: null,
  vervuller: null,
  vervuller_is_lid: true,
  ronde: 1,
  interesse: [],
  eerdere_interesse: [],
  raakvlakken: [],
  sort_order: 0,
  created_at: '2026-11-27T00:00:00Z',
  updated_at: null,
};

describe('Bewerken in de zijpanelen', () => {
  it('zet de knop in de titelbalk van een rol', () => {
    renderWithProviders(
      <ToastProvider>
      <RolPaneel
        initiatief={{ id: 'i1' } as InitiatiefDetail}
        rollen={[rol]}
        rol={rol}
        nieuw={false}
        canEdit
        onClose={vi.fn()}
        onKiesRol={vi.fn()}
      />
      </ToastProvider>,
    );
    expect(getByNlddLabel('Bewerken').getAttribute('slot')).toBe('toolbar');
  });

  it('zet de knop in de titelbalk van de cirkel', () => {
    const cirkel: InitiatiefCirkel = { id: 'c1', initiatief_id: 'i1', parent_id: null, naam: 'Regelrecht', doel: null, focus: [] };
    renderWithProviders(
      <ToastProvider>
        <CirkelPaneel initiatiefId="i1" cirkel={cirkel} canEdit onClose={vi.fn()} />
      </ToastProvider>,
    );
    expect(getByNlddLabel('Bewerken').getAttribute('slot')).toBe('toolbar');
  });
});
