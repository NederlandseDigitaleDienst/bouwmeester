import type { InitiatiefRol } from '@/types';

/** De naam van de tab: de rollen horen bij dit initiatief, bijvoorbeeld "RegelRecht-rollen". */
export function rollenTabLabel(naam: string): string {
  return `${naam}-rollen`;
}

export type RollenFilter = 'alle' | 'open' | 'mijn';

/** Belegd is een rol met een vervuller die het initiatief nog kan zien. */
export function isBelegd(rol: InitiatiefRol): boolean {
  return rol.status === 'belegd' && !!rol.vervuller && rol.vervuller_is_lid;
}

/**
 * Open is een rol die een vervuller zoekt: bekendgemaakt, of belegd bij
 * iemand die het initiatief niet meer kan zien. Een concept nog niet.
 */
export function isOpen(rol: InitiatiefRol): boolean {
  return rol.status === 'open' || (rol.status === 'belegd' && !isBelegd(rol));
}

/** Of een rol past bij de zoekterm; ook doel, domein en aanspreekbaar op tellen. */
export function pastBijZoek(rol: InitiatiefRol, zoek: string): boolean {
  const term = zoek.trim().toLocaleLowerCase('nl');
  if (!term) return true;
  const velden = [rol.naam, rol.doel ?? '', rol.vervuller?.naam ?? '', ...rol.domein, ...rol.aanspreekbaar_op];
  return velden.some((v) => v.toLocaleLowerCase('nl').includes(term));
}

/**
 * Zoeken gaat ook door doel, domein en aanspreekbaar op, zodat "wie gaat
 * over de teamagenda?" de rol met dat domein vindt.
 */
export function filterRollen(
  rollen: InitiatiefRol[],
  zoek: string,
  filter: RollenFilter,
  mijnId: string | null,
): InitiatiefRol[] {
  return rollen.filter((rol) => {
    if (filter === 'open' && !isOpen(rol)) return false;
    if (filter === 'mijn' && (!mijnId || rol.vervuller?.id !== mijnId)) return false;
    return pastBijZoek(rol, zoek);
  });
}
