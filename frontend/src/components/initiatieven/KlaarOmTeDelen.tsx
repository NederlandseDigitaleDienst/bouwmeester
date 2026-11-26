import { useState, type ReactNode } from 'react';

import { CasusNaarBuiten } from '@/components/casussen/CasusNaarBuiten';
import { NaarBuiten } from '@/components/casussen/NaarBuiten';
import { OnderzoeksverslagBlok } from '@/components/casussen/OnderzoeksverslagBlok';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useKlaarOmTeDelen } from '@/hooks/useInitiatieven';
import { IssueStatus, type InitiatiefDetail, type KlaarCasus, type KlaarVraag } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import { InstellingenBlok } from './InstellingenBlok';

/** Zoveel afgeronde vragen staan er eerst; de rest achter een knop. */
const ZICHTBAAR = 5;

type Geopend = { soort: 'vraag'; id: string } | { soort: 'casus'; id: string } | null;

/** "32 afgerond · 2 vrijgegeven" */
function telling(items: { published_at: string | null }[]): string {
  const vrij = items.filter((i) => i.published_at).length;
  return `${items.length} afgerond${vrij ? ` · ${vrij} vrijgegeven` : ''}`;
}

/**
 * De stand van een vraag of casus. "In een update" alleen zolang hij buiten
 * is: na intrekken staat hij in geen update meer te lezen. De backend zegt
 * dat ook al (`in_gepubliceerde_update`), dit houdt het scherm gelijk.
 */
function Stand({ item }: { item: { published_at: string | null; in_gepubliceerde_update: boolean } }) {
  if (item.published_at && item.in_gepubliceerde_update) return <Badge color="groen">In een update</Badge>;
  if (item.published_at) return <Badge color="groen">Vrijgegeven</Badge>;
  return <Badge color="coolgray">Binnen</Badge>;
}

/**
 * Het begin van de tab Updates: wat er af is en waar een update op kan
 * voortbouwen. Afgeronde onderzoeksvragen (met hun verslag) en afgeronde
 * casussen met de lessen eruit. Per stuk open je een paneel om de tekst
 * voor buiten te schrijven en vrij te geven; wat vrijgegeven is, kun je in
 * een nieuwe update meenemen.
 *
 * Hier staan interne titels en lessen: alleen leden zien deze tab. Naar
 * buiten gaat alleen wat iemand in het paneel schrijft en vrijgeeft, en
 * vrijgeven kan alleen wie `canEdit` heeft (bijdrager of eigenaar).
 */
export function KlaarOmTeDelen({ initiatief, canEdit }: { initiatief: InitiatiefDetail; canEdit: boolean }) {
  const { data, isLoading } = useKlaarOmTeDelen(initiatief.id);
  const [geopend, setGeopend] = useState<Geopend>(null);
  const [alleVragen, setAlleVragen] = useState(false);
  if (isLoading || !data) return null;

  const vraag = geopend?.soort === 'vraag' ? data.vragen.find((v) => v.id === geopend.id) : undefined;
  const casus = geopend?.soort === 'casus' ? data.casussen.find((c) => c.id === geopend.id) : undefined;

  return (
    <nldd-container gap="8">
      <nldd-text size="sm" weight="medium">
        Klaar om te delen
      </nldd-text>
      <nldd-text size="xs" color="secondary">
        Wat er af is. Schrijf per stuk een tekst voor buiten en geef hem vrij; daarna kun je hem meenemen in een nieuwe
        update.
      </nldd-text>
      <nldd-container gap="12">
        <InstellingenBlok
          icon="check-mark-circle"
          titel="Beantwoorde onderzoeksvragen"
          samenvatting={data.vragen.length ? telling(data.vragen) : 'nog geen afgeronde vragen'}
          defaultOpen={data.vragen.length > 0}
        >
          {data.vragen.length === 0 ? (
            <nldd-text size="sm" color="secondary">
              Nog geen afgeronde onderzoeksvragen. Een vraag is af na de Definition of Done, in de Backlog.
            </nldd-text>
          ) : (
            <Lijst>
              {(alleVragen ? data.vragen : data.vragen.slice(0, ZICHTBAAR)).map((v, i) => (
                <VraagRij
                  key={v.id}
                  vraag={v}
                  eerste={i === 0}
                  onOpen={() => setGeopend({ soort: 'vraag', id: v.id })}
                />
              ))}
            </Lijst>
          )}
          {data.vragen.length > ZICHTBAAR && (
            <nldd-container padding-top="8">
              <NlddButton
                variant="neutral-transparent"
                size="sm"
                onClick={() => setAlleVragen((a) => !a)}
                text={alleVragen ? 'Toon alleen de nieuwste' : `Toon alle ${data.vragen.length}`}
              />
            </nldd-container>
          )}
        </InstellingenBlok>
        <InstellingenBlok
          icon="flag"
          titel="Afgeronde casussen en lessen"
          samenvatting={data.casussen.length ? telling(data.casussen) : 'nog geen afgeronde casussen'}
          defaultOpen={data.casussen.length > 0}
        >
          {data.casussen.length === 0 ? (
            <nldd-text size="sm" color="secondary">
              Nog geen afgeronde casussen. Een casus is af als hij in de laatste fase van de casusfunnel staat.
            </nldd-text>
          ) : (
            <Lijst>
              {data.casussen.map((c, i) => (
                <CasusRij
                  key={c.id}
                  casus={c}
                  eerste={i === 0}
                  onOpen={() => setGeopend({ soort: 'casus', id: c.id })}
                />
              ))}
            </Lijst>
          )}
        </InstellingenBlok>
      </nldd-container>

      {vraag && (
        <Modal
          open
          onClose={() => setGeopend(null)}
          title={vraag.titel}
          size="lg"
          placement="right"
          dismissText="Sluit"
        >
          <nldd-container gap="24">
            <nldd-text size="sm" color="secondary">{vraag.casus_titel ? `Casus: ${vraag.casus_titel}` : 'Zonder casus'}</nldd-text>
            <OnderzoeksverslagBlok issue={alsVraag(vraag, initiatief.id)} kanVrijgeven={canEdit} />
            <NaarBuiten key={vraag.id} issue={alsVraag(vraag, initiatief.id)} kanVrijgeven={canEdit} />
          </nldd-container>
        </Modal>
      )}
      {casus && (
        <Modal
          open
          onClose={() => setGeopend(null)}
          title={casus.titel}
          size="lg"
          placement="right"
          dismissText="Sluit"
        >
          <CasusNaarBuiten key={casus.id} casus={casus} kanWijzigen={canEdit} />
        </Modal>
      )}
    </nldd-container>
  );
}

/** Een afgeronde vraag uit het overzicht, in de vorm die de blokken verwachten. */
function alsVraag(v: KlaarVraag, initiatiefId: string) {
  return {
    id: v.id,
    casus_id: v.casus_id,
    // Een vraag zonder casus staat onder het initiatief.
    initiatief_id: initiatiefId,
    is_onderzoeksvraag: true,
    status: IssueStatus.DONE,
    public_title: v.public_title,
    public_answer: v.public_answer,
    published_at: v.published_at,
  };
}

function Lijst({ children }: { children: ReactNode }) {
  return <nldd-container gap="0">{children}</nldd-container>;
}

function Rij({
  titel,
  onder,
  stand,
  onOpen,
  eerste,
}: {
  titel: string;
  onder: string;
  stand: ReactNode;
  onOpen: () => void;
  eerste?: boolean;
}) {
  return (
    <div
      style={
        eerste
          ? { paddingBottom: '8px' }
          : { borderTop: '1px solid var(--primitives-color-neutral-200)', padding: '8px 0' }
      }
    >
      <nldd-container layout="row" gap="8" vertical-alignment="center" width="full">
        <nldd-container gap="2" className="row-fill">
          <nldd-text size="sm">{titel}</nldd-text>
          <nldd-text size="xs" color="secondary">
            {onder}
          </nldd-text>
        </nldd-container>
        <div className="hug">{stand}</div>
        <div className="hug">
          <NlddButton variant="secondary" size="sm" onClick={onOpen} text="Naar buiten" />
        </div>
      </nldd-container>
    </div>
  );
}

function VraagRij({ vraag, eerste, onOpen }: { vraag: KlaarVraag; eerste: boolean; onOpen: () => void }) {
  const onder = vraag.published_at
    ? `Buiten: ${vraag.public_title ?? ''}${vraag.verslag_openbaar ? ' · met verslag' : ''}`
    : vraag.casus_titel
      ? `Casus: ${vraag.casus_titel}`
      : 'Zonder casus';
  return <Rij titel={vraag.titel} onder={onder} stand={<Stand item={vraag} />} onOpen={onOpen} eerste={eerste} />;
}

function CasusRij({ casus, eerste, onOpen }: { casus: KlaarCasus; eerste: boolean; onOpen: () => void }) {
  const lessen = richTextToPlain(casus.lessen ?? '').trim();
  const onder = casus.published_at
    ? `Buiten: ${casus.public_title ?? ''}`
    : lessen
      ? `Lessen: ${lessen.length > 120 ? `${lessen.slice(0, 120)}…` : lessen}`
      : 'Nog geen lessen vastgelegd';
  return <Rij titel={casus.titel} onder={onder} stand={<Stand item={casus} />} onOpen={onOpen} eerste={eerste} />;
}
