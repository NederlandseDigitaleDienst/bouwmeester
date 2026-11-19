import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getPublicInitiatief, getPubliekVerslagUrl } from '@/api/publicInitiatief';
import { ApiError } from '@/api/client';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import type {
  PublicCasus,
  PublicInitiatief,
  PublicInitiatiefUpdate,
  PublicVraag,
  PublicAfgerondeCasus,
} from '@/types';

import { initiatiefAccentVar, initiatiefIconColor } from '@/components/initiatieven/initiatiefColors';
import { bestandsgrootte } from '@/utils/bestandsgrootte';

type Status = 'loading' | 'ok' | 'not-found' | 'error';

/**
 * The only page outside the auth shell and outside `nldd-shell`
 * (`/c/:slug` in App.tsx), so it needs its own `nldd-shell` wrapper for
 * the color-scheme context that every other page gets from AppLayout.
 */
export function PublicInitiatiefPage() {
  const { slug } = useParams<{ slug: string }>();
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<PublicInitiatief | null>(null);

  useEffect(() => {
    // Voorkom indexering door zoekmachines: een initiatief kan ooit publiek
    // hebben gestaan en daarna weer worden gedimd; cached search-results
    // mogen geen interne info blijven serveren.
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex, nofollow, noarchive';
    document.head.appendChild(meta);
    return () => {
      document.head.removeChild(meta);
    };
  }, []);

  useEffect(() => {
    if (data?.naam) document.title = `${data.naam} · Bouwmeester`;
  }, [data?.naam]);

  useEffect(() => {
    if (!slug) {
      setStatus('not-found');
      return;
    }
    let cancelled = false;
    setStatus('loading');
    getPublicInitiatief(slug)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setStatus('ok');
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setStatus('not-found');
        } else {
          setStatus('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (status === 'loading') {
    return (
      <nldd-shell background="tinted">
        <nldd-simple-section horizontal-alignment="center" vertical-alignment="center" height="100dvh">
          <LoadingSpinner />
        </nldd-simple-section>
      </nldd-shell>
    );
  }

  if (status === 'not-found') {
    return (
      <PublicMessage
        title="Pagina niet gevonden"
        body="Deze pagina bestaat niet of is niet (meer) publiek toegankelijk."
      />
    );
  }

  if (status === 'error' || !data) {
    return <PublicMessage title="Er ging iets mis" body="Probeer het later opnieuw." />;
  }

  // The stored kleur is an nldd color name. The bars need a CSS color, so they
  // read the token the name stands for; the dots are icons, which take the
  // name itself.
  const accent = initiatiefAccentVar(data.kleur);
  const accentIcon = initiatiefIconColor(data.kleur);

  return (
    <nldd-shell background="tinted">
      {/* Top accent stripe — subtiele kleur-identiteit per initiatief. A full-
          bleed bar is not a component the system has, so it stays a plain div
          painted from the initiative's own category token. */}
      <div aria-hidden style={{ height: '6px', width: '100%', backgroundColor: accent }} />

      <nldd-full-bleed-section width="768px" padding-top="64" padding-bottom="48">
        <nldd-container gap="16">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <nldd-icon icon="circle-filled-small" size="16" color={accentIcon} />
            <nldd-text size="xs" weight="medium" color="secondary">
              Community
            </nldd-text>
          </nldd-container>
          <nldd-title size={1}>
            <h1>{data.naam}</h1>
          </nldd-title>
          {data.beschrijving && (
            <nldd-container max-width="640px">
              <RichTextDisplay content={data.beschrijving} />
            </nldd-container>
          )}
        </nldd-container>
      </nldd-full-bleed-section>

      <nldd-simple-section width="768px" padding-bottom="80">
        <nldd-container gap="48">
          {data.casussen.length > 0 && (
            <section>
              <nldd-container layout="row" gap="8" vertical-alignment="bottom" padding-bottom="24">
                <nldd-title size={4}>
                  <h2>Lopende casussen</h2>
                </nldd-title>
                <nldd-spacer size="flexible" direction="horizontal" />
                <nldd-text size="sm" color="secondary">
                  {data.casussen.length} {data.casussen.length === 1 ? 'casus' : 'casussen'}
                </nldd-text>
              </nldd-container>
              <nldd-collection layout="grid" item-min-width="280px" gap="16">
                {data.casussen.map((c, idx) => (
                  <CasusCard key={idx} casus={c} accentIcon={accentIcon} />
                ))}
              </nldd-collection>
            </section>
          )}

          {(data.afgeronde_casussen ?? []).length > 0 && (
            <section>
              <nldd-container layout="row" gap="8" vertical-alignment="bottom" padding-bottom="24">
                <nldd-title size={4}>
                  <h2>Afgeronde casussen</h2>
                </nldd-title>
                <nldd-spacer size="flexible" direction="horizontal" />
                <nldd-text size="sm" color="secondary">
                  {data.afgeronde_casussen!.length} {data.afgeronde_casussen!.length === 1 ? 'casus' : 'casussen'}
                </nldd-text>
              </nldd-container>
              <nldd-card>
                <nldd-container padding="24" sm-padding-inline="32" gap="16">
                  {data.afgeronde_casussen!.map((c, idx) => (
                    <nldd-container key={idx} gap="16">
                      {idx > 0 && <nldd-divider />}
                      <AfgerondeCasus casus={c} />
                    </nldd-container>
                  ))}
                </nldd-container>
              </nldd-card>
            </section>
          )}

          {data.beantwoorde_vragen.length > 0 && (
            <section>
              <nldd-container layout="row" gap="8" vertical-alignment="bottom" padding-bottom="24">
                <nldd-title size={4}>
                  <h2>Beantwoorde vragen</h2>
                </nldd-title>
                <nldd-spacer size="flexible" direction="horizontal" />
                <nldd-text size="sm" color="secondary">
                  {data.beantwoorde_vragen.length} {data.beantwoorde_vragen.length === 1 ? 'vraag' : 'vragen'}
                </nldd-text>
              </nldd-container>
              <nldd-card>
                <nldd-container padding="24" sm-padding-inline="32" gap="16">
                  {data.beantwoorde_vragen.map((v, idx) => (
                    <nldd-container key={idx} gap="16">
                      {idx > 0 && <nldd-divider />}
                      <BeantwoordeVraag vraag={v} slug={data.slug} />
                    </nldd-container>
                  ))}
                </nldd-container>
              </nldd-card>
            </section>
          )}

          <section>
            <nldd-container layout="row" gap="8" vertical-alignment="bottom" padding-bottom="24">
              <nldd-title size={4}>
                <h2>Updates</h2>
              </nldd-title>
              <nldd-spacer size="flexible" direction="horizontal" />
              {data.updates.length > 0 && (
                <nldd-text size="sm" color="secondary">
                  {data.updates.length} {data.updates.length === 1 ? 'bericht' : 'berichten'}
                </nldd-text>
              )}
            </nldd-container>

            {data.updates.length === 0 ? (
              <UpdatesEmptyState naam={data.naam} />
            ) : (
              <nldd-container gap="32">
                {data.updates.map((u, idx) => (
                  <UpdateCard key={idx} update={u} accent={accent} slug={data.slug} />
                ))}
              </nldd-container>
            )}
          </section>
        </nldd-container>
      </nldd-simple-section>

      <nldd-page-footer width="768px">
        <nldd-container layout="wrap" gap="8" vertical-alignment="center">
          <nldd-text size="sm" color="secondary">
            Publieke pagina van <strong>{data.naam}</strong>
          </nldd-text>
          <nldd-spacer size="flexible" direction="horizontal" />
          <nldd-text size="xs" color="secondary">
            Gepubliceerd via Bouwmeester
          </nldd-text>
        </nldd-container>
      </nldd-page-footer>
    </nldd-shell>
  );
}

function UpdateCard({
  update,
  accent,
  slug,
}: {
  update: PublicInitiatiefUpdate;
  accent: string;
  slug: string;
}) {
  const date = new Date(update.published_at);
  const formattedDate = date.toLocaleDateString('nl-NL', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });

  return (
    <nldd-card>
      {/* Left accent rail: nldd-card/nldd-box have no accent edge, so it stays a positioned div. */}
      <div style={{ position: 'relative' }}>
        <nldd-container padding="24" sm-padding-inline="32" sm-padding-block="28">
          <div
            aria-hidden
            style={{
              position: 'absolute',
              left: 0,
              top: '24px',
              bottom: '24px',
              width: '4px',
              borderRadius: '0 9999px 9999px 0',
              backgroundColor: accent,
            }}
          />
          <nldd-container layout="wrap" gap="8" vertical-alignment="center" padding-bottom="12">
            <nldd-text size="xs" weight="medium" color="secondary">
              <time dateTime={update.published_at}>{formattedDate}</time>
            </nldd-text>
            {update.published_by_naam && (
              <nldd-text size="xs" color="secondary">
                · {update.published_by_naam}
              </nldd-text>
            )}
          </nldd-container>
          <nldd-title size={3}>
            <h3>{update.titel}</h3>
          </nldd-title>
          {update.body && (
            <nldd-container padding-top="16">
              <RichTextDisplay content={update.body} />
            </nldd-container>
          )}
          {update.vragen.length > 0 && (
            <nldd-container padding-top="16" gap="12">
              <nldd-text size="sm" weight="medium" color="secondary">
                Beantwoorde onderzoeksvragen
              </nldd-text>
              {update.vragen.map((v, idx) => (
                <BeantwoordeVraag key={idx} vraag={v} slug={slug} kop={4} />
              ))}
            </nldd-container>
          )}
          {(update.casussen ?? []).length > 0 && (
            <nldd-container padding-top="16" gap="12">
              <nldd-text size="sm" weight="medium" color="secondary">
                Afgeronde casussen
              </nldd-text>
              {update.casussen!.map((c, idx) => (
                <AfgerondeCasus key={idx} casus={c} kop={4} />
              ))}
            </nldd-container>
          )}
        </nldd-container>
      </div>
    </nldd-card>
  );
}

/**
 * Eén beantwoorde onderzoeksvraag: alleen de publieke vraag en het antwoord
 * die het team vrijgaf, en het onderzoeksverslag als het openbaar is. In het
 * overzicht een h3, onder een update een h4.
 */
/**
 * Een afgeronde casus zoals het team hem voor buiten beschreef: een naam,
 * wat het opleverde en eventueel de lessen. Niets van de casus zelf.
 */
function AfgerondeCasus({ casus, kop = 3 }: { casus: PublicAfgerondeCasus; kop?: 3 | 4 }) {
  const Kop = kop === 3 ? 'h3' : 'h4';
  return (
    <nldd-container gap="4">
      <nldd-title size={5}>
        <Kop>{casus.titel}</Kop>
      </nldd-title>
      <RichTextDisplay content={casus.resultaat} />
      {casus.lessen && (
        <nldd-container gap="2" padding-top="4">
          <nldd-text size="sm" weight="medium">
            Wat we leerden
          </nldd-text>
          <RichTextDisplay content={casus.lessen} />
        </nldd-container>
      )}
      <nldd-text size="xs" color="secondary">
        Afgerond, gedeeld op{' '}
        <time dateTime={casus.published_at}>
          {new Date(casus.published_at).toLocaleDateString('nl-NL', { day: 'numeric', month: 'long', year: 'numeric' })}
        </time>
      </nldd-text>
    </nldd-container>
  );
}

function BeantwoordeVraag({ vraag, slug, kop = 3 }: { vraag: PublicVraag; slug: string; kop?: 3 | 4 }) {
  const Kop = kop === 3 ? 'h3' : 'h4';
  return (
    <nldd-container gap="4">
      <nldd-title size={5}>
        <Kop>{vraag.vraag}</Kop>
      </nldd-title>
      <RichTextDisplay content={vraag.antwoord} />
      {vraag.verslag && (
        <nldd-link
          href={getPubliekVerslagUrl(slug, vraag.verslag.id)}
          size="sm"
          start-icon="download"
          text={`Onderzoeksverslag (${vraag.verslag.bestandsnaam}, ${bestandsgrootte(vraag.verslag.bestandsgrootte)})`}
        />
      )}
      <nldd-text size="xs" color="secondary">
        Beantwoord op{' '}
        <time dateTime={vraag.published_at}>
          {new Date(vraag.published_at).toLocaleDateString('nl-NL', { day: 'numeric', month: 'long', year: 'numeric' })}
        </time>
      </nldd-text>
    </nldd-container>
  );
}

function CasusCard({
  casus,
  accentIcon,
}: {
  casus: PublicCasus;
  accentIcon: React.ComponentProps<'nldd-icon'>['color'];
}) {
  return (
    <nldd-card>
      <nldd-container padding="20">
        <nldd-container layout="row" gap="8" vertical-alignment="center" padding-bottom="8">
          <nldd-icon icon="circle-filled-small" size="16" color={accentIcon} />
          <nldd-text size="xs" weight="medium" color="secondary">
            Casus
          </nldd-text>
        </nldd-container>
        <nldd-title size={5}>
          <h3>{casus.titel}</h3>
        </nldd-title>
        {casus.samenvatting && (
          <nldd-container padding-top="8">
            <nldd-text size="sm" color="secondary">
              {casus.samenvatting}
            </nldd-text>
          </nldd-container>
        )}
        {casus.updates.length > 0 && (
          <nldd-container gap="12" padding-top="16">
            <nldd-divider />
            {casus.updates.map((u, idx) => (
              <div key={idx}>
                <nldd-container layout="row" gap="8" vertical-alignment="center">
                  <nldd-text size="sm" weight="medium">
                    {u.titel}
                  </nldd-text>
                  <nldd-text size="xs" color="secondary">
                    {new Date(u.published_at).toLocaleDateString('nl-NL', {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                    })}
                  </nldd-text>
                </nldd-container>
                {u.body_public && (
                  <nldd-text size="sm" color="secondary">
                    {u.body_public}
                  </nldd-text>
                )}
              </div>
            ))}
          </nldd-container>
        )}
      </nldd-container>
    </nldd-card>
  );
}

function UpdatesEmptyState({ naam }: { naam: string }) {
  return (
    <nldd-inline-dialog
      icon="megaphone"
      icon-color="accent"
      text="Nog geen updates"
      supporting-text={`Hier verschijnen updates die het team van ${naam} publiceert. Kom later terug, of bookmark deze pagina.`}
    />
  );
}

function PublicMessage({ title, body }: { title: string; body: string }) {
  return (
    <nldd-shell background="tinted">
      <nldd-simple-section horizontal-alignment="center" vertical-alignment="center" height="100dvh">
        <nldd-container gap="12" horizontal-alignment="center">
          <nldd-title size={2}>
            <h2>{title}</h2>
          </nldd-title>
          <nldd-text color="secondary" horizontal-alignment="center">
            {body}
          </nldd-text>
        </nldd-container>
      </nldd-simple-section>
    </nldd-shell>
  );
}
