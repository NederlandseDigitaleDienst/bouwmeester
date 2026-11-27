import type { KeyboardEvent } from 'react';

import { entityColorVar } from '@/types';
import type { InitiatiefCirkel, InitiatiefRol } from '@/types';
import { cirkelLayout, initialen, labelRegels } from './cirkelLayout';
import { isBelegd, isOpen } from './rollenFilter';

const BREED = 640;
const MIDDEN = { x: 320, y: 345 };
const STRAAL = 300;

interface Props {
  cirkel: InitiatiefCirkel | undefined;
  rollen: InitiatiefRol[];
  /** Rollen die bij zoeken of filter passen; de rest wordt gedimd. */
  zichtbaar: Set<string>;
  gekozen: string | null;
  onKies: (rolId: string) => void;
  onKiesCirkel: () => void;
}

function kleuren(rol: InitiatiefRol) {
  if (isBelegd(rol)) return { vul: entityColorVar('paars', 50), rand: entityColorVar('paars', 500), streep: undefined };
  if (isOpen(rol)) return { vul: entityColorVar('oranje', 50), rand: entityColorVar('oranje', 500), streep: undefined };
  return { vul: entityColorVar('coolgray', 50), rand: entityColorVar('coolgray', 400), streep: '6 4' };
}

function onderschrift(rol: InitiatiefRol): string {
  if (isBelegd(rol) && rol.vervuller) return initialen(rol.vervuller.naam);
  if (isOpen(rol)) return 'open';
  return 'concept';
}

function omschrijving(rol: InitiatiefRol): string {
  const delen = [rol.naam];
  if (isBelegd(rol) && rol.vervuller) delen.push(`vervuld door ${rol.vervuller.naam}`);
  else if (isOpen(rol)) delen.push('open');
  else delen.push('concept');
  if (rol.interesse.length) delen.push(`${rol.interesse.length} met interesse`);
  if (rol.raakvlakken.length) delen.push(`${rol.raakvlakken.length} raakvlakken`);
  return delen.join(', ');
}

/**
 * De cirkel van het initiatief met de rollen erin, zoals GlassFrog het
 * tekent: kleur per status, een bolletje bij interesse. Kies je een rol,
 * dan lopen er lijnen naar zijn raakvlakken. Elke rol is met het
 * toetsenbord te kiezen; de lijst ernaast is de toegankelijke weergave.
 */
export function CirkelKaart({ cirkel, rollen, zichtbaar, gekozen, onKies, onKiesCirkel }: Props) {
  const plekken = cirkelLayout(rollen.length, MIDDEN.x, MIDDEN.y, STRAAL);
  const plekVan = new Map(rollen.map((r, i) => [r.id, plekken[i]]));
  const gekozenRol = rollen.find((r) => r.id === gekozen);
  const naam = cirkel?.naam ?? '';

  const toets = (e: KeyboardEvent, actie: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      actie();
    }
  };

  return (
    <svg
      className="rollen-kaart"
      viewBox={`0 0 ${BREED} 720`}
      role="group"
      aria-label={`Cirkel van ${naam} met ${rollen.length} rollen`}
    >
      <g
        className="rollen-kaart-rol"
        role="button"
        tabIndex={0}
        aria-label={`Cirkel ${naam}: doel en focus`}
        onClick={onKiesCirkel}
        onKeyDown={(e) => toets(e, onKiesCirkel)}
      >
        <circle
          className="rollen-kaart-rand"
          cx={MIDDEN.x}
          cy={MIDDEN.y}
          r={STRAAL}
          fill={entityColorVar('lintblauw', 50)}
          stroke={entityColorVar('lintblauw', 500)}
          strokeWidth={2}
        />
        <text x={MIDDEN.x} y={30} textAnchor="middle" fontSize={18} fontWeight="bold" fill="currentColor">
          {naam}
        </text>
      </g>

      {gekozenRol &&
        gekozenRol.raakvlakken.map((rv) => {
          const a = plekVan.get(gekozenRol.id);
          const b = plekVan.get(rv.rol.id);
          if (!a || !b) return null;
          return (
            <line
              key={rv.id}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={entityColorVar('lintblauw', 500)}
              strokeWidth={3}
              strokeDasharray="8 5"
            />
          );
        })}

      {rollen.map((rol, i) => {
        const p = plekken[i];
        const k = kleuren(rol);
        const fs = Math.max(10, Math.min(15, p.r * 0.2));
        const regels = labelRegels(rol.naam, Math.max(6, Math.floor((p.r * 1.6) / (fs * 0.55))));
        const top = p.y - ((regels.length - 1) * fs * 1.15) / 2 - fs * 0.5;
        const isGekozen = rol.id === gekozen;
        return (
          <g
            key={rol.id}
            className={`rollen-kaart-rol${zichtbaar.has(rol.id) ? '' : ' rollen-kaart-gedimd'}`}
            role="button"
            tabIndex={0}
            aria-label={omschrijving(rol)}
            aria-pressed={isGekozen}
            onClick={() => onKies(rol.id)}
            onKeyDown={(e) => toets(e, () => onKies(rol.id))}
          >
            <title>{omschrijving(rol)}</title>
            <circle
              className="rollen-kaart-rand"
              cx={p.x}
              cy={p.y}
              r={p.r}
              fill={k.vul}
              stroke={isGekozen ? entityColorVar('donkerblauw', 500) : k.rand}
              strokeWidth={isGekozen ? 4 : 2}
              strokeDasharray={k.streep}
            />
            {regels.map((regel, j) => (
              <text
                key={j}
                x={p.x}
                y={top + j * fs * 1.15}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={fs}
                fill="currentColor"
              >
                {regel}
              </text>
            ))}
            <text
              x={p.x}
              y={top + regels.length * fs * 1.15 + fs * 0.4}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={fs * 0.85}
              fontWeight="bold"
              fill={k.rand}
            >
              {onderschrift(rol)}
            </text>
            {rol.interesse.length > 0 && (
              <circle
                cx={p.x + p.r * 0.72}
                cy={p.y - p.r * 0.72}
                r={Math.max(6, p.r * 0.13)}
                fill={entityColorVar('mosgroen', 500)}
                stroke={entityColorVar('mosgroen', 50)}
                strokeWidth={2}
              />
            )}
          </g>
        );
      })}

      <Legenda />
    </svg>
  );
}

function Legenda() {
  const y = 700;
  const items = [
    { label: 'belegd', vul: entityColorVar('paars', 50), rand: entityColorVar('paars', 500) },
    { label: 'open', vul: entityColorVar('oranje', 50), rand: entityColorVar('oranje', 500) },
    { label: 'concept', vul: entityColorVar('coolgray', 50), rand: entityColorVar('coolgray', 400), streep: '3 2' },
    { label: 'interesse', vul: entityColorVar('mosgroen', 500), rand: entityColorVar('mosgroen', 500) },
  ];
  return (
    <g aria-hidden="true" fontSize={13} fill="currentColor">
      {items.map((it, i) => (
        <g key={it.label} transform={`translate(${20 + i * 110}, ${y})`}>
          <circle cx={8} cy={-4} r={7} fill={it.vul} stroke={it.rand} strokeDasharray={it.streep} />
          <text x={20} y={0}>
            {it.label}
          </text>
        </g>
      ))}
      <line
        x1={460}
        y1={y - 4}
        x2={490}
        y2={y - 4}
        stroke={entityColorVar('lintblauw', 500)}
        strokeWidth={3}
        strokeDasharray="8 5"
      />
      <text x={498} y={y}>
        raakvlak
      </text>
    </g>
  );
}
