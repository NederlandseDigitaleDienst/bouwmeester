/**
 * Waar de rollen in de cirkel van het initiatief staan.
 *
 * Tot zes rollen op één ring. Meer: één in het midden en ringen eromheen
 * van 6, 12, 18 plekken, zoals bolletjes in een honingraat. De afstand op
 * elke ring is minstens 2,2 keer de straal van een rol, zodat er niets
 * overlapt, en de buitenste rol blijft binnen de grote cirkel.
 */

export interface Plek {
  x: number;
  y: number;
  r: number;
}

/** Tussenruimte tussen rollen, als factor van hun straal. */
const AFSTAND = 2.2;
/** Hoeveel van de grote cirkel de rollen mogen gebruiken. */
const RUIMTE = 0.92;

export function cirkelLayout(aantal: number, cx: number, cy: number, straal: number): Plek[] {
  if (aantal <= 0) return [];
  if (aantal === 1) return [{ x: cx, y: cy, r: straal * 0.32 }];

  if (aantal <= 6) {
    const ring = straal * 0.55;
    const r = Math.min(straal * 0.3, (ring * Math.sin(Math.PI / aantal) * 2) / AFSTAND);
    return opRing(aantal, cx, cy, ring, r);
  }

  // Midden plus ringen van 6k plekken.
  let ringen = 0;
  let plekken = 1;
  while (plekken < aantal) {
    ringen += 1;
    plekken += 6 * ringen;
  }
  const r = (straal * RUIMTE) / (AFSTAND * ringen + 1);
  const uit: Plek[] = [{ x: cx, y: cy, r }];
  let over = aantal - 1;
  for (let k = 1; k <= ringen && over > 0; k++) {
    const hier = Math.min(over, 6 * k);
    uit.push(...opRing(hier, cx, cy, AFSTAND * k * r, r));
    over -= hier;
  }
  return uit;
}

function opRing(aantal: number, cx: number, cy: number, ring: number, r: number): Plek[] {
  // De eerste rol bovenaan, dan met de klok mee.
  return Array.from({ length: aantal }, (_, i) => {
    const hoek = -Math.PI / 2 + (2 * Math.PI * i) / aantal;
    return { x: cx + ring * Math.cos(hoek), y: cy + ring * Math.sin(hoek), r };
  });
}

/**
 * Een naam in regels voor in een rolcirkel: hooguit drie, op woorden
 * afgebroken, met een beletselteken als het niet past.
 */
export function labelRegels(naam: string, maxTekens: number, maxRegels = 3): string[] {
  const woorden = naam.trim().split(/\s+/).filter(Boolean);
  const regels: string[] = [];
  let huidig = '';
  for (const woord of woorden) {
    const kandidaat = huidig ? `${huidig} ${woord}` : woord;
    if (kandidaat.length <= maxTekens || !huidig) {
      huidig = kandidaat;
    } else {
      regels.push(huidig);
      huidig = woord;
    }
  }
  if (huidig) regels.push(huidig);
  const kort = regels.map((r) => (r.length > maxTekens ? `${r.slice(0, maxTekens - 1)}…` : r));
  if (kort.length <= maxRegels) return kort;
  const laatste = kort[maxRegels - 1];
  return [...kort.slice(0, maxRegels - 1), laatste.endsWith('…') ? laatste : `${laatste.slice(0, maxTekens - 1)}…`];
}

/** Initialen voor in een rolcirkel: "Persoon Dgdoo" wordt "PD". */
export function initialen(naam: string): string {
  return naam
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toLocaleUpperCase('nl') ?? '')
    .join('');
}
