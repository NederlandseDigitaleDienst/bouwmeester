"""Background worker for polling TK/EK APIs, importing parliamentary items,
and running the persistent Mattermost websocket."""

import asyncio
import logging
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from bouwmeester.core.config import get_settings
from bouwmeester.core.database import async_session, engine
from bouwmeester.core.worker_lock import WorkerLock
from bouwmeester.services.worker_health import tick as health_tick

# Note on stdout buffering: PYTHONUNBUFFERED=1 lives in the Dockerfile and
# entrypoint.sh runs us with `python -u`. Setting it from inside Python is
# pointless (the runtime reads the env var at startup, before this module
# runs).

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Het poll-ritme van tkconv volgt de Nederlandse kantooruren, dus de
# tijdzone is die van de Tweede Kamer en niet die van de server.
_AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def _short_error(exc: BaseException) -> str:
    """One-line summary of an exception for the heartbeat detail field."""
    tb = traceback.format_exception_only(type(exc), exc)
    return "".join(tb).strip()[:500]


async def _parlementair_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Poll TK/EK APIs for parliamentary items."""
    await health_tick("parlementair", status="starting")
    while True:
        try:
            async with async_session() as session:
                from bouwmeester.services.parlementair_import_service import (
                    ParlementairImportService,
                )

                service = ParlementairImportService(session)
                count = await service.poll_and_import()
                logger.info(f"Import cycle complete: {count} items imported")
            await health_tick("parlementair", detail=f"{count} items imported")
        except Exception as exc:
            logger.exception("Error in parlementair import cycle")
            await health_tick("parlementair", status="error", detail=_short_error(exc))

        await asyncio.sleep(settings.TK_POLL_INTERVAL_SECONDS)


def _tkconv_interval(settings, nu: datetime | None = None) -> int:  # type: ignore[no-untyped-def]
    """Hoe lang tot de volgende tkconv-ronde, naar het uur van de dag.

    Kamerstukken verschijnen tijdens kantooruren: een meting over 1010
    stukken in acht dagen gaf 08:00-18:00, met een piek om 16:00 (188
    stukken) en daarbuiten 2 stukken in acht dagen. Overdag kort pollen is
    dus waar de winst zit; 's nachts hetzelfde doen belast alleen Berts
    server.

    De grens is bewust niet hard op 18:00: de avondstaart is dun maar niet
    leeg, en een stuk dat om 20:00 verschijnt hoeft niet tot de volgende
    ochtend te wachten.
    """
    nu = nu or datetime.now(_AMSTERDAM)
    uur = nu.hour
    if settings.TKCONV_KANTOORUREN_START <= uur < settings.TKCONV_KANTOORUREN_EIND:
        return settings.TKCONV_POLL_INTERVAL_KANTOORUREN_SECONDS
    # De avond is het venster ná kantooruren, niet "alles vóór 23:00": zonder
    # de ondergrens zou 03:00 ook als avond tellen en 's nachts even vaak
    # gepolld worden als om 20:00.
    if settings.TKCONV_KANTOORUREN_EIND <= uur < settings.TKCONV_AVOND_EIND:
        return settings.TKCONV_POLL_INTERVAL_AVOND_SECONDS
    return settings.TKCONV_POLL_INTERVAL_NACHT_SECONDS


async def _tkconv_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Volg zoektermen in nieuwe kamerstukken via tkconv.

    Eigen loop, los van `_parlementair_loop`: de officiële TK-API is
    rijksinfrastructuur, tkconv is de privéserver van één persoon. Dezelfde
    frequentie opleggen omdat ze toevallig in dezelfde loop zitten, is geen
    keuze maar een bijwerking.

    De client houdt ETags vast, dus een ronde waarin niets is verschenen
    kost één HEAD met 0 bytes body.
    """
    await health_tick("tkconv", status="starting")
    while True:
        count = 0
        try:
            async with async_session() as session:
                from bouwmeester.services.parlementair_import_service import (
                    ParlementairImportService,
                )

                service = ParlementairImportService(session)
                count = await service.poll_and_import(item_types=["tkconv_document"])
                if count:
                    logger.info(f"tkconv-ronde: {count} kamerstukken geïmporteerd")
            await health_tick("tkconv", detail=f"{count} kamerstukken")
        except Exception as exc:
            logger.exception("Fout in tkconv-ronde")
            await health_tick("tkconv", status="error", detail=_short_error(exc))

        await asyncio.sleep(_tkconv_interval(settings))


async def _opdracht_task_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Daily check for deadline-approaching and budget-preparation tasks."""
    await health_tick("opdracht_task", status="starting")
    while True:
        try:
            async with async_session() as session:
                from bouwmeester.services.opdracht_task_service import (
                    OpdrachtTaskService,
                )

                service = OpdrachtTaskService(session)
                deadline_count = await service.check_deadlines()
                budget_count = await service.check_budget_preparation()
                await session.commit()
                logger.info(
                    f"Opdracht task cycle complete: "
                    f"{deadline_count} deadline, {budget_count} budget tasks"
                )
            await health_tick(
                "opdracht_task",
                detail=f"{deadline_count} deadline, {budget_count} budget",
            )
        except Exception as exc:
            logger.exception("Error in opdracht task cycle")
            await health_tick("opdracht_task", status="error", detail=_short_error(exc))

        await asyncio.sleep(settings.OPDRACHT_TASK_INTERVAL_SECONDS)


async def _mattermost_retry_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Bied Mattermost-posts opnieuw aan die de LLM niet kon beoordelen.

    Bij een VLAM-storing komt de lead-classificatie niet door en wordt de
    post weggeschreven als ``llm_unavailable``. Zonder deze loop blijft zo'n
    bericht definitief liggen, want ``ingest_post`` slaat alles over wat al
    een ``mattermost_post_link`` heeft. Een echte lead die tijdens een
    storing langskwam zou dus nooit meer opgepikt worden.
    """
    interval_seconds = settings.MATTERMOST_RETRY_INTERVAL_SECONDS
    await health_tick("mattermost_retry", status="starting")
    while True:
        try:
            from bouwmeester.services.mattermost_ingest_service import (
                retry_llm_unavailable,
            )

            # Elke post krijgt binnen deze call een eigen sessie en commit,
            # zodat één mislukking de rest van de ronde niet terugdraait.
            processed, leads = await retry_llm_unavailable()
            await health_tick(
                "mattermost_retry",
                detail=f"{processed} herverwerkt, {leads} suggesties",
            )
        except Exception as exc:
            logger.exception("Error in Mattermost retry cycle")
            await health_tick(
                "mattermost_retry", status="error", detail=_short_error(exc)
            )

        await asyncio.sleep(interval_seconds)


async def _fcc_sync_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Bidirectional sync with Fortes Change Cloud."""
    await health_tick("fcc_sync", status="starting")
    while True:
        try:
            async with async_session() as session:
                from sqlalchemy import select

                from bouwmeester.core.encryption import decrypt_value
                from bouwmeester.models.app_config import AppConfig

                result = await session.execute(
                    select(AppConfig).where(AppConfig.key == "FCC_SYNC_ENABLED")
                )
                entry = result.scalar_one_or_none()
                if not entry or decrypt_value(entry.value) != "true":
                    await health_tick(
                        "fcc_sync",
                        status="disabled",
                        detail="FCC_SYNC_ENABLED is false",
                    )
                    await asyncio.sleep(settings.FCC_POLL_INTERVAL_SECONDS)
                    continue

                from bouwmeester.services.fcc_import_service import FccImportService

                import_service = FccImportService(session)
                pull_count = await import_service.poll_and_import()

                push_count = 0
                if await import_service.is_push_enabled():
                    from bouwmeester.services.fcc_export_service import (
                        FccExportService,
                    )

                    export_service = FccExportService(session)
                    push_count = await export_service.push_pending()

                await session.commit()
                logger.info(
                    "FCC sync cycle complete: %d pulled, %d pushed",
                    pull_count,
                    push_count,
                )

                # Match contacts for newly imported opdrachten
                if pull_count > 0:
                    try:
                        async with async_session() as match_session:
                            from bouwmeester.services.opdracht_matching_service import (
                                OpdrachtMatchingService,
                            )

                            svc = OpdrachtMatchingService(match_session)
                            result = await svc.match_all_unlinked()
                            await match_session.commit()
                            logger.info(
                                "Contact matching: %d matched, %d skipped",
                                result["matched"],
                                result["skipped"],
                            )
                    except Exception:
                        logger.exception("Error in contact matching after FCC sync")
            await health_tick(
                "fcc_sync",
                detail=f"{pull_count} pulled, {push_count} pushed",
            )
        except Exception as exc:
            logger.exception("Error in FCC sync cycle")
            await health_tick("fcc_sync", status="error", detail=_short_error(exc))

        await asyncio.sleep(settings.FCC_POLL_INTERVAL_SECONDS)


async def _mattermost_websocket_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Persistent Mattermost websocket voor het meelezen in gekoppelde kanalen.

    Service heeft eigen reconnect/backoff binnen ``run()``. Deze loop vangt
    alleen onverwachte exceptions op en herstart dan na een korte pauze.
    """
    await health_tick("mattermost_websocket", status="starting")
    while True:
        try:
            from bouwmeester.services.mattermost_websocket_service import (
                MattermostWebsocketService,
            )

            service = MattermostWebsocketService()
            await service.run()
            # run() only returns when stop() is called from the outside.
            await health_tick("mattermost_websocket", status="stopped")
        except Exception as exc:
            logger.exception("Mattermost websocket loop crashed, restart in 5s")
            await health_tick(
                "mattermost_websocket", status="error", detail=_short_error(exc)
            )
        await asyncio.sleep(5)


async def _debat_tijdlijn_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Post who speaks when, in the channels of debates that are on today."""
    if not settings.DEBAT_TIJDLIJN_ENABLED:
        logger.info("Debat-tijdlijn staat uit (DEBAT_TIJDLIJN_ENABLED=false)")
        return
    from bouwmeester.services.debat_tijdlijn_service import DebatTijdlijnService

    await health_tick("debat_tijdlijn", status="starting")
    last_heartbeat = 0.0
    while True:
        detail = None
        try:
            async with async_session() as session:
                service = DebatTijdlijnService(session)
                try:
                    result = await service.tick()
                finally:
                    await service.close()
            if result.berichten or result.gekoppeld or result.fouten:
                logger.info("Debat-tijdlijn: %s", result.summary())
            detail = result.summary()
            status = "error" if result.fouten else "ok"
        except Exception as exc:
            logger.exception("Error in debat-tijdlijn tick")
            detail = _short_error(exc)
            status = "error"

        # The loop ticks every few seconds; the heartbeat does not have to.
        if status == "error" or time.monotonic() - last_heartbeat > 60.0:
            last_heartbeat = time.monotonic()
            await health_tick("debat_tijdlijn", status=status, detail=detail)

        await asyncio.sleep(settings.DEBAT_TIJDLIJN_INTERVAL_SECONDS)


async def _debat_vragen_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Mark the questions to the bewindspersoon in turns that are finished.

    Not in the tick of the timeline: a model reads a turn for seconds, and
    the timeline has to say who speaks now.
    """
    if not settings.DEBAT_VRAGEN_ENABLED:
        logger.info("Debatvragen staan uit (DEBAT_VRAGEN_ENABLED=false)")
        # Off is the default, and must not show up as a loop that died.
        await health_tick("debat_vragen", status="disabled")
        return
    from bouwmeester.services.debat_vraag_worker import DebatVraagWorker

    await health_tick("debat_vragen", status="starting")
    last_heartbeat = 0.0
    # What the TK API says about each debate, asked once per debate for as
    # long as this process lives.
    contexts: dict = {}
    while True:
        detail = None
        try:
            async with async_session() as session:
                service = DebatVraagWorker(session, contexts=contexts)
                try:
                    result = await service.tick()
                finally:
                    await service.close()
            if result.beoordeeld or result.fouten:
                logger.info("Debatvragen: %s", result.summary())
            detail = result.summary()
            status = "error" if result.fouten else "ok"
        except Exception as exc:
            logger.exception("Error in debatvragen tick")
            detail = _short_error(exc)
            status = "error"

        if status == "error" or time.monotonic() - last_heartbeat > 60.0:
            last_heartbeat = time.monotonic()
            await health_tick("debat_vragen", status=status, detail=detail)

        await asyncio.sleep(settings.DEBAT_VRAGEN_INTERVAL_SECONDS)


async def _debat_aankondiging_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Remind the channels of an initiatief of the debates announced there."""
    from bouwmeester.services.debat_aankondiging_service import (
        DebatAankondigingService,
    )

    await health_tick("debat_aankondiging", status="starting")
    while True:
        try:
            async with async_session() as session:
                service = DebatAankondigingService(session)
                try:
                    result = await service.tick()
                finally:
                    await service.close()
            if result.herinnerd or result.afgelast or result.verzet or result.fouten:
                logger.info("Debat-aankondigingen: %s", result.summary())
            await health_tick(
                "debat_aankondiging",
                status="error" if result.fouten else "ok",
                detail=result.summary(),
            )
        except Exception as exc:
            logger.exception("Error in debat-aankondiging tick")
            await health_tick(
                "debat_aankondiging", status="error", detail=_short_error(exc)
            )

        await asyncio.sleep(settings.DEBAT_AANKONDIGING_INTERVAL_SECONDS)


async def _cleanup_obsolete_heartbeats() -> None:
    """Verwijder heartbeat-rijen van loops die niet meer bestaan.

    De ``mattermost_link``-rij bleef hangen toen we die loop schrapten,
    waardoor de admin-UI 'm als 'unexpected, down' bleef tonen. Run-once
    bij worker-startup is genoeg — best-effort, fout wordt gelogd.
    """
    from sqlalchemy import delete

    from bouwmeester.models.worker_heartbeat import WorkerHeartbeat

    obsolete = ["mattermost_link"]
    try:
        async with async_session() as session:
            await session.execute(
                delete(WorkerHeartbeat).where(WorkerHeartbeat.loop_name.in_(obsolete))
            )
            await session.commit()
    except Exception:
        logger.exception("Cleanup obsolete heartbeats faalde")


async def _overheidsorganisaties_dagelijks_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Dagelijkse sync van fast-changing data: TK-leden, kabinet, ABD-feeds.

    Deze data verandert vaker (kamerleden rotaties, ABD-benoemingen)
    dan TOOI/organogram. Default 24h.
    """
    interval_seconds = getattr(
        settings, "OVERHEIDSORG_DAILY_INTERVAL_SECONDS", 24 * 3600
    )
    await health_tick("overheidsorganisaties_daily", status="starting")
    while True:
        try:
            async with async_session() as session:
                from bouwmeester.core.storage import kabinet_yaml_path
                from bouwmeester.services.kabinet_scrape import write_kabinet_yaml
                from bouwmeester.services.kabinet_sync import sync_kabinet
                from bouwmeester.services.tk_persoon_sync import sync_tk_personen

                tk_stats = await sync_tk_personen(session)

                kab_yaml = kabinet_yaml_path()
            async with async_session() as session2:
                await write_kabinet_yaml(session2, str(kab_yaml))
                kab_stats = await sync_kabinet(session2, kab_yaml)

            # ABD-scrape via Playwright (separaat session ivm browser-lifecycle)
            abd_added = 0
            try:
                from bouwmeester.services.abd_scrape import sync_abd

                async with async_session() as session3:
                    abd_stats = await sync_abd(session3)
                    abd_added = abd_stats.new_placements
            except Exception as exc:  # noqa: BLE001
                logger.warning("ABD-scrape gefaald: %s", _short_error(exc))

            await health_tick(
                "overheidsorganisaties_daily",
                detail=(
                    f"tk+{tk_stats.new_placements} "
                    f"kab+{kab_stats.new_placements} abd+{abd_added}"
                ),
            )
        except Exception as exc:
            logger.exception("Error in daily overheidsorg sync")
            await health_tick(
                "overheidsorganisaties_daily",
                status="error",
                detail=_short_error(exc),
            )

        await asyncio.sleep(interval_seconds)


async def _overheidsorganisaties_wekelijks_loop(settings) -> None:  # type: ignore[no-untyped-def]
    """Wekelijkse sync van slow-changing data: TOOI-spine, RIO, organogram.

    TOOI/RIO/organogram-mutaties zijn zeldzaam (gemeente-fusie,
    ministerie-reshuffle). Default 7 dagen om bandwidth + parsing
    overhead te beperken. Volgorde: TOOI eerst zodat URI's bestaan
    voor CSV/RIO matching.
    """
    interval_seconds = getattr(
        settings, "OVERHEIDSORG_WEEKLY_INTERVAL_SECONDS", 7 * 24 * 3600
    )
    await health_tick("overheidsorganisaties_weekly", status="starting")
    while True:
        try:
            async with async_session() as session:
                from bouwmeester.services.ministeries_csv_sync import (
                    sync_ministeries_csv,
                )
                from bouwmeester.services.organogram_scrape import sync_organogram
                from bouwmeester.services.rio_sync import sync_rio
                from bouwmeester.services.tooi_sync import sync_tooi

                tooi_stats = await sync_tooi(session)
                csv_stats = await sync_ministeries_csv(session)
                rio_stats = await sync_rio(session)
                org_stats = await sync_organogram(session)

            await health_tick(
                "overheidsorganisaties_weekly",
                detail=(
                    f"tooi+{tooi_stats.added} csv+{csv_stats.enriched} "
                    f"rio+{rio_stats.domeinen_added} dg+{org_stats.dgs_added}"
                ),
            )
        except Exception as exc:
            logger.exception("Error in weekly overheidsorg sync")
            await health_tick(
                "overheidsorganisaties_weekly",
                status="error",
                detail=_short_error(exc),
            )

        await asyncio.sleep(interval_seconds)


_SINGLETON_LOCK_RETRY_SECONDS = 5.0


async def _acquire_singleton_lock_or_wait(lock: WorkerLock) -> None:
    """Blokkeert tot deze instantie de worker-singleton-lock krijgt.

    Bij een overlappende deploy (oude pod's worker nog niet gestopt,
    nieuwe pod al gestart) mag maar één instantie de achtergrond-loops
    (met name de Mattermost-websocket) draaien — anders verwerken beide
    dezelfde posts en ontstaan dubbele Mattermost-suggesties. Deze
    instantie wacht gewoon tot de lock vrijkomt (oude pod stopt of
    crasht) in plaats van zelf ook te gaan draaien."""
    logged_waiting = False
    while not await lock.acquire():
        if not logged_waiting:
            logger.warning(
                "Worker-singleton-lock is al in gebruik door een andere "
                "instantie, wacht tot die vrijkomt..."
            )
            await health_tick(
                "worker_singleton",
                status="waiting",
                detail="lock in gebruik door andere instantie",
            )
            logged_waiting = True
        await asyncio.sleep(_SINGLETON_LOCK_RETRY_SECONDS)

    if logged_waiting:
        logger.info("Worker-singleton-lock verkregen, start achtergrond-loops")
    await health_tick("worker_singleton", status="ok", detail="lock verkregen")


async def main() -> None:
    settings = get_settings()
    logger.info(
        f"Worker started. Parlementair poll interval: "
        f"{settings.TK_POLL_INTERVAL_SECONDS}s"
    )

    lock = WorkerLock(engine)
    await _acquire_singleton_lock_or_wait(lock)

    await _cleanup_obsolete_heartbeats()

    tasks = [
        asyncio.create_task(_parlementair_loop(settings)),
        asyncio.create_task(_tkconv_loop(settings)),
        asyncio.create_task(_mattermost_websocket_loop(settings)),
        asyncio.create_task(_opdracht_task_loop(settings)),
        asyncio.create_task(_fcc_sync_loop(settings)),
        asyncio.create_task(_mattermost_retry_loop(settings)),
        asyncio.create_task(_overheidsorganisaties_dagelijks_loop(settings)),
        asyncio.create_task(_overheidsorganisaties_wekelijks_loop(settings)),
        asyncio.create_task(_debat_tijdlijn_loop(settings)),
        asyncio.create_task(_debat_vragen_loop(settings)),
        asyncio.create_task(_debat_aankondiging_loop(settings)),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
