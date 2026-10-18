"""Handlers for Mattermost slash commands and interactive button actions."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.core.config import get_settings
from bouwmeester.core.query_utils import escape_like
from bouwmeester.models.corpus_node import CorpusNode
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    SCOPE_LEAD,
)
from bouwmeester.models.task import Task
from bouwmeester.repositories.mattermost_channel_link import (
    MattermostChannelLinkRepository,
)
from bouwmeester.repositories.mattermost_user import MattermostUserRepository
from bouwmeester.repositories.parlementair_abonnement import (
    ParlementairAbonnementRepository,
)
from bouwmeester.repositories.search import SearchRepository
from bouwmeester.services.mattermost_utils import escape_mattermost_md as _escape_md

logger = logging.getLogger(__name__)


@dataclass
class _ChannelCtx:
    channel_id: str | None
    channel_name: str | None
    team_id: str | None


class MattermostSlashService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MattermostUserRepository(session)

    async def _resolve_person_id(self, mattermost_user_id: str) -> UUID | None:
        """Resolve a Mattermost user ID to a Bouwmeester person ID."""
        mapping = await self.repo.get_by_mattermost_user_id(mattermost_user_id)
        return mapping.person_id if mapping else None

    async def handle_command(
        self,
        mattermost_user_id: str,
        command_text: str,
        *,
        channel_id: str | None = None,
        channel_name: str | None = None,
        team_id: str | None = None,
    ) -> dict:
        """Route a /bouwmeester slash command to the right handler."""
        parts = command_text.split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "help"
        args = parts[1].strip() if len(parts) > 1 else ""

        ch_ctx = _ChannelCtx(channel_id, channel_name, team_id)
        handlers = {
            "taken": self._handle_taken,
            "zoek": self._handle_zoek,
            "status": self._handle_status,
            "help": self._handle_help,
            "koppel": self._handle_koppel,
            "ontkoppel": self._handle_ontkoppel,
            "kanaal": self._handle_kanaal_status,
            "volg": self._handle_volg,
            "ontvolg": self._handle_ontvolg,
            "volgt": self._handle_volgt,
        }

        handler = handlers.get(subcommand, self._handle_help)
        return await handler(mattermost_user_id, args, ch_ctx)

    async def _handle_taken(
        self, mattermost_user_id: str, args: str, _ch: _ChannelCtx
    ) -> dict:
        """List the user's open tasks, optionally filtered by deadline."""
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _ephemeral(
                "Je Mattermost-account is niet gekoppeld aan Bouwmeester. "
                "Ga naar Instellingen in Bouwmeester om te koppelen."
            )

        today = date.today()

        stmt = (
            select(Task)
            .where(
                Task.assignee_id == person_id,
                Task.status.in_(["open", "in_progress"]),
            )
            .options(selectinload(Task.node))
            .order_by(Task.deadline.asc().nulls_last())
        )

        # Apply deadline filter.
        filter_arg = args.lower() if args else "alles"
        if filter_arg == "vandaag":
            stmt = stmt.where(Task.deadline <= today)
        elif filter_arg == "week":
            stmt = stmt.where(Task.deadline <= today + timedelta(days=7))
        # "alles" = no deadline filter

        result = await self.session.execute(stmt)
        tasks = result.scalars().all()

        if not tasks:
            return _ephemeral("Geen open taken gevonden.")

        frontend_url = get_settings().FRONTEND_URL.rstrip("/")
        lines = [f"**Jouw taken** ({len(tasks)}):\n"]
        for t in tasks[:20]:
            deadline_str = (
                t.deadline.strftime("%d-%m") if t.deadline else "geen deadline"
            )
            status_icon = (
                ":red_circle:"
                if t.deadline and t.deadline < today
                else ":large_blue_circle:"
            )
            node_name = _escape_md(t.node.title) if t.node else ""
            link = f"{frontend_url}/taken?task={t.id}"
            lines.append(
                f"{status_icon} [{_escape_md(t.title)}]({link}) — {deadline_str}"
                + (f" ({node_name})" if node_name else "")
            )

        if len(tasks) > 20:
            lines.append(f"\n_...en {len(tasks) - 20} meer_")

        return _ephemeral("\n".join(lines))

    async def _handle_zoek(
        self, mattermost_user_id: str, args: str, _ch: _ChannelCtx
    ) -> dict:
        """Full-text search in the corpus."""
        if not args:
            return _ephemeral("Gebruik: `/bouwmeester zoek <zoekterm>`")

        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _ephemeral(
                "Je account is niet gekoppeld. Ga naar Instellingen in Bouwmeester."
            )

        search_repo = SearchRepository(self.session)
        results = await search_repo.full_text_search(
            query=args, result_types=["corpus_node"], limit=10
        )

        if not results:
            return _ephemeral(f"Geen resultaten gevonden voor '{_escape_md(args)}'.")

        frontend_url = get_settings().FRONTEND_URL.rstrip("/")
        lines = [f"**Zoekresultaten** voor '{_escape_md(args)}':\n"]
        for r in results:
            url = f"{frontend_url}{r['url']}"
            subtitle = f" ({_escape_md(r['subtitle'])})" if r.get("subtitle") else ""
            lines.append(f"- [{_escape_md(r['title'])}]({url}){subtitle}")

        return _ephemeral("\n".join(lines))

    async def _handle_status(
        self, mattermost_user_id: str, args: str, _ch: _ChannelCtx
    ) -> dict:
        """Show status of a dossier (open/total task counts)."""
        if not args:
            return _ephemeral("Gebruik: `/bouwmeester status <dossiernaam>`")

        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _ephemeral(
                "Je account is niet gekoppeld. Ga naar Instellingen in Bouwmeester."
            )

        # Find dossier by title search.
        escaped_args = escape_like(args)
        stmt = (
            select(CorpusNode)
            .where(
                CorpusNode.node_type == "dossier",
                CorpusNode.title.ilike(f"%{escaped_args}%", escape="\\"),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        dossier = result.scalar_one_or_none()

        if not dossier:
            return _ephemeral(f"Geen dossier gevonden met '{_escape_md(args)}'.")

        # Count tasks for this dossier.
        from sqlalchemy import func

        task_stats = await self.session.execute(
            select(
                func.count(Task.id).label("total"),
                func.count(Task.id)
                .filter(Task.status.in_(["open", "in_progress"]))
                .label("open"),
            ).where(Task.node_id == dossier.id)
        )
        row = task_stats.one()

        frontend_url = get_settings().FRONTEND_URL.rstrip("/")
        link = f"{frontend_url}/nodes/{dossier.id}"

        return _ephemeral(
            f"**[{_escape_md(dossier.title)}]({link})**\n"
            f"- Open taken: {row.open}\n"
            f"- Totaal taken: {row.total}\n"
        )

    async def _handle_help(
        self, mattermost_user_id: str, args: str, _ch: _ChannelCtx
    ) -> dict:
        """Show available commands."""
        return _ephemeral(
            "**Bouwmeester commando's:**\n"
            "- `/bouwmeester taken [vandaag|week|alles]` — Jouw open taken\n"
            "- `/bouwmeester zoek <term>` — Zoek in het corpus\n"
            "- `/bouwmeester status <dossier>` — Status van een dossier\n"
            "- `/bouwmeester koppel initiatief <slug-of-naam>` — "
            "koppel dit kanaal aan een initiatief\n"
            "- `/bouwmeester koppel lead <id-of-titel>` — "
            "koppel dit kanaal aan een lead\n"
            "- `/bouwmeester ontkoppel` — verwijder de kanaal-koppeling\n"
            "- `/bouwmeester kanaal` — toon de huidige koppeling\n"
            "- `/bouwmeester volg <zoekterm>` — "
            "volg een term in nieuwe kamerstukken\n"
            "- `/bouwmeester ontvolg <zoekterm>` — "
            "verwijder de term (inclusief telling)\n"
            "- `/bouwmeester volgt` — welke termen dit initiatief volgt\n"
            "- `/bouwmeester help` — Dit overzicht\n"
        )

    # ---------------------------------------------------------------------
    # Kanaal-koppelen
    # ---------------------------------------------------------------------

    async def _handle_koppel(
        self, mattermost_user_id: str, args: str, ch: _ChannelCtx
    ) -> dict:
        """Koppel het kanaal waarin het commando staat aan initiatief/lead."""
        if not ch.channel_id or not ch.channel_name:
            return _ephemeral("Ik kan dit kanaal niet bepalen vanuit het commando.")
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _ephemeral(
                "Je Mattermost-account is niet gekoppeld aan Bouwmeester. "
                "Ga naar Instellingen om te koppelen."
            )

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return _ephemeral(
                "Gebruik: `/bouwmeester koppel initiatief <slug-of-naam>` of "
                "`/bouwmeester koppel lead <id-of-titel>`."
            )
        kind = parts[0].lower()
        query = parts[1].strip()
        if kind not in ("initiatief", "lead"):
            return _ephemeral("Eerste argument moet `initiatief` of `lead` zijn.")

        link_repo = MattermostChannelLinkRepository(self.session)
        existing = await link_repo.get_by_channel_id(ch.channel_id)
        if existing is not None:
            return _ephemeral(
                "Dit kanaal is al gekoppeld. Gebruik `/bouwmeester ontkoppel` "
                "om de bestaande koppeling te verwijderen."
            )

        if kind == "initiatief":
            target = await self._lookup_initiatief(query, person_id)
            if target is None:
                return _ephemeral(
                    f"Geen initiatief gevonden voor '{_escape_md(query)}' "
                    "(of geen toegang)."
                )
            await link_repo.create(
                channel_id=ch.channel_id,
                channel_name=ch.channel_name,
                channel_display_name=ch.channel_name,
                team_id=ch.team_id,
                scope_type=SCOPE_INITIATIEF,
                scope_id=target.id,
                auto_note_enabled=False,
                suggest_leads_enabled=True,
                created_by_id=person_id,
            )
            return _ephemeral(
                f":link: Kanaal gekoppeld aan **{_escape_md(target.naam)}**. "
                "Nieuwe berichten worden voortaan voorgesteld als lead."
            )

        target_lead = await self._lookup_lead(query, person_id)
        if target_lead is None:
            return _ephemeral(
                f"Geen lead gevonden voor '{_escape_md(query)}' (of geen toegang)."
            )
        await link_repo.create(
            channel_id=ch.channel_id,
            channel_name=ch.channel_name,
            channel_display_name=ch.channel_name,
            team_id=ch.team_id,
            scope_type=SCOPE_LEAD,
            scope_id=target_lead.id,
            auto_note_enabled=True,
            suggest_leads_enabled=False,
            created_by_id=person_id,
        )
        return _ephemeral(
            f":link: Kanaal gekoppeld aan lead **{_escape_md(target_lead.title)}**. "
            "Berichten in dit kanaal worden notities op de lead."
        )

    async def _handle_ontkoppel(
        self, mattermost_user_id: str, args: str, ch: _ChannelCtx
    ) -> dict:
        if not ch.channel_id:
            return _ephemeral("Ik kan dit kanaal niet bepalen.")
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _ephemeral("Je account is niet gekoppeld.")

        link_repo = MattermostChannelLinkRepository(self.session)
        link = await link_repo.get_by_channel_id(ch.channel_id)
        if link is None:
            return _ephemeral("Dit kanaal is niet gekoppeld.")
        await link_repo.delete(link)
        return _ephemeral(":wastebasket: Koppeling verwijderd.")

    async def _handle_kanaal_status(
        self, mattermost_user_id: str, args: str, ch: _ChannelCtx
    ) -> dict:
        if not ch.channel_id:
            return _ephemeral("Ik kan dit kanaal niet bepalen.")
        link_repo = MattermostChannelLinkRepository(self.session)
        link = await link_repo.get_by_channel_id(ch.channel_id)
        if link is None:
            return _ephemeral(
                "Dit kanaal is niet gekoppeld. Gebruik "
                "`/bouwmeester koppel initiatief|lead <…>` om te koppelen."
            )
        if link.scope_type == SCOPE_INITIATIEF:
            init = await self.session.get(Initiatief, link.scope_id)
            naam = init.naam if init else str(link.scope_id)
            return _ephemeral(
                f":link: Gekoppeld aan initiatief **{_escape_md(naam)}**. "
                f"Auto-note: {'aan' if link.auto_note_enabled else 'uit'} · "
                f"Suggesties: {'aan' if link.suggest_leads_enabled else 'uit'}"
            )
        lead = await self.session.get(Lead, link.scope_id)
        titel = lead.title if lead else str(link.scope_id)
        return _ephemeral(
            f":link: Gekoppeld aan lead **{_escape_md(titel)}**. "
            f"Auto-note: {'aan' if link.auto_note_enabled else 'uit'} · "
            f"Suggesties: {'aan' if link.suggest_leads_enabled else 'uit'}"
        )

    async def _resolve_abonnement_scope(
        self, mattermost_user_id: str, ch: _ChannelCtx
    ) -> tuple[UUID | None, object, str]:
        """Bepaal namens welk initiatief/lead dit kanaal abonnementen beheert.

        Geeft (person_id, link, foutmelding) terug; bij een fout is `link`
        None en draagt de string de reden. De scope komt uit de bestaande
        kanaalkoppeling, zodat een abonnement bij het initiatief hoort en
        niet bij het kanaal: kanalen worden ontkoppeld, initiatieven niet.
        """
        if not ch.channel_id:
            return None, None, "Ik kan dit kanaal niet bepalen vanuit het commando."
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return (
                None,
                None,
                "Je Mattermost-account is niet gekoppeld aan Bouwmeester. "
                "Ga naar Instellingen om te koppelen.",
            )
        link_repo = MattermostChannelLinkRepository(self.session)
        link = await link_repo.get_by_channel_id(ch.channel_id)
        if link is None:
            return (
                person_id,
                None,
                "Dit kanaal is nog niet gekoppeld. Gebruik eerst "
                "`/bouwmeester koppel initiatief <naam>`; de zoektermen "
                "horen bij het initiatief, niet bij het kanaal.",
            )

        # Toegang tot het kanaal is niet hetzelfde als toegang tot het
        # initiatief: in Mattermost kan iedereen een open kanaal joinen,
        # terwijl het initiatief in Bouwmeester op een beperkte kring kan
        # staan. Zonder deze check zou `volgt` de zoektermen en tellingen
        # van zo'n dossier prijsgeven, en `ontvolg` ze stil kunnen
        # weghalen. `koppel` doet deze check al via `_lookup_initiatief`.
        if not await self._mag_scope_zien(link, person_id):
            return (
                person_id,
                None,
                "Dit kanaal is gekoppeld aan een initiatief waar je geen "
                "toegang toe hebt.",
            )
        return person_id, link, ""

    async def _mag_scope_zien(self, link, person_id: UUID) -> bool:
        """Mag deze persoon het initiatief/de lead achter dit kanaal zien?"""
        from bouwmeester.core.initiatief_context import build_initiatief_context
        from bouwmeester.models.person import Person

        person = await self.session.get(Person, person_id)
        if person is None:
            return False
        ctx = await build_initiatief_context(self.session, person)
        if ctx.is_admin:
            return True

        if link.scope_type == SCOPE_INITIATIEF:
            return link.scope_id in ctx.visible_initiatief_ids

        # Een lead erft de zichtbaarheid van zijn initiatief; een lead
        # zonder initiatief is voor iedereen zichtbaar, net als in
        # `_lookup_lead`.
        lead = await self.session.get(Lead, link.scope_id)
        if lead is None:
            return False
        return (
            lead.initiatief_id is None
            or lead.initiatief_id in ctx.visible_initiatief_ids
        )

    async def _scope_naam(self, link) -> str:
        if link.scope_type == SCOPE_INITIATIEF:
            init = await self.session.get(Initiatief, link.scope_id)
            return init.naam if init else str(link.scope_id)
        lead = await self.session.get(Lead, link.scope_id)
        return lead.title if lead else str(link.scope_id)

    async def _handle_volg(
        self, mattermost_user_id: str, args: str, ch: _ChannelCtx
    ) -> dict:
        """Voeg een zoekterm toe aan het initiatief achter dit kanaal."""
        person_id, link, fout = await self._resolve_abonnement_scope(
            mattermost_user_id, ch
        )
        if fout:
            return _ephemeral(fout)

        term = args.strip().strip('"').strip()
        if not term:
            return _ephemeral(
                "Gebruik: `/bouwmeester volg <zoekterm>`, bijvoorbeeld "
                "`/bouwmeester volg Nederlandse Digitale Dienst`."
            )
        if len(term) < 3:
            return _ephemeral(
                "Een zoekterm van minder dan drie tekens levert te veel ruis op."
            )

        repo = ParlementairAbonnementRepository(self.session)
        bestaand = await repo.get_by_term(link.scope_type, link.scope_id, term)
        if bestaand is not None:
            if not bestaand.actief:
                bestaand.actief = True
                await self.session.commit()
                return _ephemeral(f":mag: **{_escape_md(bestaand.term)}** weer actief.")
            return _ephemeral(f"**{_escape_md(bestaand.term)}** wordt al gevolgd.")

        abonnement = await repo.create(
            scope_type=link.scope_type,
            scope_id=link.scope_id,
            term=term,
            # Meerdere woorden worden als frase gezocht. Een ongequote
            # meerwoordsterm OR't de woorden en levert willekeurige
            # treffers op; dat is bijna nooit de bedoeling.
            is_frase=True,
            created_by_id=person_id,
        )
        await self.session.commit()

        naam = await self._scope_naam(link)
        return _ephemeral(
            f":mag: **{_escape_md(abonnement.term)}** wordt nu gevolgd voor "
            f"**{_escape_md(naam)}**. Nieuwe kamerstukken met deze term in de "
            "volledige tekst verschijnen in dit kanaal. Bestaande stukken van "
            "voor nu worden niet opnieuw gemeld."
        )

    async def _handle_ontvolg(
        self, mattermost_user_id: str, args: str, ch: _ChannelCtx
    ) -> dict:
        person_id, link, fout = await self._resolve_abonnement_scope(
            mattermost_user_id, ch
        )
        if fout:
            return _ephemeral(fout)

        term = args.strip().strip('"').strip()
        if not term:
            return _ephemeral("Gebruik: `/bouwmeester ontvolg <zoekterm>`.")

        repo = ParlementairAbonnementRepository(self.session)
        abonnement = await repo.get_by_term(link.scope_type, link.scope_id, term)
        if abonnement is None:
            return _ephemeral(
                f"**{_escape_md(term)}** wordt niet gevolgd. "
                "`/bouwmeester volgt` toont wat er wel staat."
            )
        bewaard = abonnement.term
        await repo.delete(abonnement)
        await self.session.commit()
        return _ephemeral(
            f":wastebasket: **{_escape_md(bewaard)}** verwijderd, inclusief "
            "de telling. Wil je hem alleen tijdelijk stilzetten, gebruik "
            "dan de pauzeknop op de initiatief-pagina."
        )

    async def _handle_volgt(
        self, mattermost_user_id: str, args: str, ch: _ChannelCtx
    ) -> dict:
        """Toon de zoektermen van dit initiatief, met wat ze opleveren."""
        person_id, link, fout = await self._resolve_abonnement_scope(
            mattermost_user_id, ch
        )
        if fout:
            return _ephemeral(fout)

        repo = ParlementairAbonnementRepository(self.session)
        abonnementen = await repo.list_for_scope(link.scope_type, link.scope_id)
        naam = await self._scope_naam(link)

        if not abonnementen:
            return _ephemeral(
                f"**{_escape_md(naam)}** volgt nog geen zoektermen. "
                "Voeg er een toe met `/bouwmeester volg <zoekterm>`."
            )

        tellingen = await repo.telling_per_abonnement(link.scope_type, link.scope_id)
        regels = [f"**Zoektermen voor {_escape_md(naam)}**", ""]
        regels.append("| Term | Treffers | Weggeklikt | Laatste |")
        regels.append("|---|---:|---:|---|")
        for a in abonnementen:
            laatste = (
                a.laatste_treffer_op.strftime("%d-%m-%Y")
                if a.laatste_treffer_op
                else "—"
            )
            term = _escape_md(a.term)
            if not a.actief:
                term = f"~~{term}~~"
            regels.append(
                f"| {term} | {tellingen.get(a.id, 0)} | "
                f"{a.weggeklikt_totaal} | {laatste} |"
            )
        regels.append("")
        regels.append(
            "_Een term die niets oplevert is niet per se fout; een term die "
            "vaak wordt weggeklikt is te breed._"
        )
        return _ephemeral("\n".join(regels))

    async def _lookup_initiatief(
        self, query: str, person_id: UUID
    ) -> Initiatief | None:
        """Zoek initiatief op slug of naam, gerespecteerd door visibility."""
        from bouwmeester.core.initiatief_context import build_initiatief_context
        from bouwmeester.models.person import Person

        person = await self.session.get(Person, person_id)
        if person is None:
            return None
        ctx = await build_initiatief_context(self.session, person)
        if not ctx.is_admin and not ctx.visible_initiatief_ids:
            return None

        escaped = escape_like(query)
        stmt = select(Initiatief).where(
            or_(
                Initiatief.slug == query,
                Initiatief.naam.ilike(f"%{escaped}%", escape="\\"),
            )
        )
        if not ctx.is_admin:
            stmt = stmt.where(Initiatief.id.in_(ctx.visible_initiatief_ids))
        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _lookup_lead(self, query: str, person_id: UUID) -> Lead | None:
        """Zoek lead op id of titel; respecteer initiatief-visibility."""
        # Probeer eerst exact UUID-match.
        try:
            lead_uuid = UUID(query)
        except ValueError:
            lead_uuid = None

        from bouwmeester.core.initiatief_context import build_initiatief_context
        from bouwmeester.models.person import Person

        person = await self.session.get(Person, person_id)
        if person is None:
            return None
        ctx = await build_initiatief_context(self.session, person)

        if lead_uuid is not None:
            lead = await self.session.get(Lead, lead_uuid)
            if lead is None:
                return None
            if ctx.is_admin:
                return lead
            if (
                lead.initiatief_id is None
                or lead.initiatief_id in ctx.visible_initiatief_ids
            ):
                return lead
            return None

        escaped = escape_like(query)
        stmt = select(Lead).where(
            Lead.title.ilike(f"%{escaped}%", escape="\\"),
        )
        if not ctx.is_admin:
            stmt = stmt.where(
                or_(
                    Lead.initiatief_id.is_(None),
                    Lead.initiatief_id.in_(ctx.visible_initiatief_ids),
                )
            )
        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ---------------------------------------------------------------------------
    # Reaction-driven actions on suggested-lead bot-replies
    # ---------------------------------------------------------------------------

    async def handle_action(
        self, mattermost_user_id: str, action: str, context: dict
    ) -> dict:
        """Handle a reaction-triggered action on a suggested-lead bot-reply.

        Returns ``{"ephemeral_text": "..."}`` voor in-line feedback. Sinds
        we van interactive buttons naar emoji-reactions zijn geswitcht
        wordt deze method alleen nog vanuit
        ``MattermostWebsocketService._dispatch_reaction_added`` aangeroepen,
        en is de keyset beperkt tot suggested-lead approvals.
        """
        if action == "create_lead_from_suggestion":
            return await self._action_create_lead_from_suggestion(
                mattermost_user_id, context
            )
        if action == "link_lead_to_suggestion":
            return await self._action_link_lead_to_suggestion(
                mattermost_user_id, context
            )
        if action == "reject_suggestion":
            return await self._action_reject_suggestion(mattermost_user_id, context)
        return {"ephemeral_text": "Onbekende actie."}

    # ------------------------------------------------------------------
    # Suggested-lead approval
    # ------------------------------------------------------------------

    async def _action_create_lead_from_suggestion(
        self, mattermost_user_id: str, context: dict
    ) -> dict:
        """Klik 'Maak lead aan' onder een MM-suggestie."""
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _action_msg("Je account is niet gekoppeld.")

        suggested = await self._lock_suggestion(context)
        if isinstance(suggested, dict):
            return suggested
        if suggested.status != "pending":
            return _action_msg("Deze suggestie is al verwerkt.")
        if not await self._has_initiatief_access(person_id, suggested.initiatief_id):
            return _action_msg("Je hebt geen toegang tot dit initiatief.")

        from bouwmeester.models.lead import Lead

        lead = Lead(
            title=suggested.proposed_title or "Nieuwe lead vanuit Mattermost",
            description=suggested.proposed_description or None,
            initiatief_id=suggested.initiatief_id,
            stage="inbox",
            raw_intake_text=suggested.raw_text,
            brought_by_id=person_id,
        )
        self.session.add(lead)
        await self.session.flush()
        await self.session.refresh(lead)

        # Eerste activiteit: het oorspronkelijke MM-bericht.
        from bouwmeester.models.lead_activity import LeadActivity

        self.session.add(
            LeadActivity(
                lead_id=lead.id,
                author_id=person_id,
                content=suggested.raw_text or "",
                activity_type="note",
                metadata_={
                    "source": "mattermost",
                    "mm_post_id": suggested.source_post_id,
                    "mm_channel_id": suggested.source_channel_id,
                },
            )
        )

        self._mark_reviewed(suggested, person_id, status="approved_new")
        suggested.approved_lead_id = lead.id
        await self.session.flush()

        await self._update_thread_post(
            suggested,
            text=f":white_check_mark: Lead aangemaakt: **{_escape_md(lead.title)}**",
            color="#22C55E",
        )
        return _action_msg("Lead aangemaakt in Bouwmeester.")

    async def _action_link_lead_to_suggestion(
        self, mattermost_user_id: str, context: dict
    ) -> dict:
        """Klik 'Koppel aan bestaande lead' — gebruikt match_existing_lead_id
        van de suggestie. (Een echte multi-keuze-dialog houden we voor later.)"""
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _action_msg("Je account is niet gekoppeld.")

        suggested = await self._lock_suggestion(context)
        if isinstance(suggested, dict):
            return suggested
        if suggested.status != "pending":
            return _action_msg("Deze suggestie is al verwerkt.")
        if not await self._has_initiatief_access(person_id, suggested.initiatief_id):
            return _action_msg("Je hebt geen toegang tot dit initiatief.")
        if suggested.match_existing_lead_id is None:
            return _action_msg(
                "Geen kandidaat-lead bekend. Maak een nieuwe lead aan of negeer."
            )

        from bouwmeester.models.lead import Lead
        from bouwmeester.models.lead_activity import LeadActivity

        lead = await self.session.get(Lead, suggested.match_existing_lead_id)
        if lead is None:
            return _action_msg("De gekoppelde lead bestaat niet meer.")
        # Verifieer dat de lead nog bij hetzelfde initiatief hoort — voorkomt
        # cross-initiatief-leak via een geknoeide context of LLM-suggestie.
        if lead.initiatief_id != suggested.initiatief_id:
            return _action_msg("Lead hoort niet bij dit initiatief.")

        self.session.add(
            LeadActivity(
                lead_id=lead.id,
                author_id=person_id,
                content=suggested.raw_text or "",
                activity_type="note",
                metadata_={
                    "source": "mattermost",
                    "mm_post_id": suggested.source_post_id,
                    "mm_channel_id": suggested.source_channel_id,
                },
            )
        )

        self._mark_reviewed(suggested, person_id, status="approved_linked")
        suggested.approved_lead_id = lead.id
        await self.session.flush()

        await self._update_thread_post(
            suggested,
            text=f":link: Gekoppeld aan lead **{_escape_md(lead.title)}**",
            color="#3B82F6",
        )
        return _action_msg("Bericht gekoppeld als notitie aan de lead.")

    async def _action_reject_suggestion(
        self, mattermost_user_id: str, context: dict
    ) -> dict:
        person_id = await self._resolve_person_id(mattermost_user_id)
        if not person_id:
            return _action_msg("Je account is niet gekoppeld.")
        suggested = await self._lock_suggestion(context)
        if isinstance(suggested, dict):
            return suggested
        if suggested.status != "pending":
            return _action_msg("Deze suggestie is al verwerkt.")
        if not await self._has_initiatief_access(person_id, suggested.initiatief_id):
            return _action_msg("Je hebt geen toegang tot dit initiatief.")

        self._mark_reviewed(suggested, person_id, status="rejected")
        await self.session.flush()

        await self._update_thread_post(
            suggested,
            text=":no_entry_sign: Suggestie genegeerd.",
            color="#94A3B8",
        )
        return _action_msg("Suggestie genegeerd.")

    @staticmethod
    def _mark_reviewed(suggested, person_id: UUID, *, status: str) -> None:
        from datetime import UTC, datetime

        suggested.status = status
        suggested.review_source = "mattermost"
        suggested.reviewed_by_id = person_id
        suggested.reviewed_at = datetime.now(UTC)

    async def _lock_suggestion(self, context: dict):
        """Lock-and-load: voorkomt dat twee gelijktijdige knop-clicks tegelijk
        twee Lead-records aanmaken. ``with_for_update`` blokkeert tot de
        andere transactie commit/rollback doet, en daarna leest de tweede
        de bijgewerkte status (pending → approved_*) en valt netjes om in
        "Deze suggestie is al verwerkt."""
        from bouwmeester.models.suggested_lead import SuggestedLead

        sid_str = context.get("suggested_lead_id")
        if not sid_str:
            return _action_msg("Geen suggestie-id meegegeven.")
        try:
            sid = UUID(sid_str)
        except (ValueError, AttributeError):
            return _action_msg("Ongeldig suggestie-id.")
        stmt = select(SuggestedLead).where(SuggestedLead.id == sid).with_for_update()
        suggested = (await self.session.execute(stmt)).scalar_one_or_none()
        if suggested is None:
            return _action_msg("Suggestie niet gevonden.")
        return suggested

    async def _has_initiatief_access(
        self, person_id: UUID, initiatief_id: UUID
    ) -> bool:
        from bouwmeester.core.initiatief_context import build_initiatief_context
        from bouwmeester.models.person import Person

        person = await self.session.get(Person, person_id)
        if person is None:
            return False
        ctx = await build_initiatief_context(self.session, person)
        return ctx.is_admin or initiatief_id in ctx.visible_initiatief_ids

    async def _update_thread_post(self, suggested, *, text: str, color: str) -> None:
        if not suggested.mm_thread_post_id:
            return
        from bouwmeester.services.mattermost_service import MattermostService

        service = MattermostService(self.session)
        try:
            if not await service.is_enabled():
                return
            ok = await service.update_post(
                suggested.mm_thread_post_id,
                text,
                props={
                    "attachments": [
                        {
                            "color": color,
                            "text": text,
                            "footer": "Bouwmeester · suggestie verwerkt",
                        }
                    ]
                },
            )
            if not ok:
                logger.warning(
                    "Update van thread-post %s gaf geen success terug",
                    suggested.mm_thread_post_id,
                )
        finally:
            await service.close()


def _ephemeral(text: str) -> dict:
    """Slash-command response — alleen zichtbaar voor de uitvoerder.

    Mattermost interpreteert ``response_type: ephemeral`` voor
    slash-commando's. Voor button-action responses verwacht MM een ander
    veld (``ephemeral_text``); gebruik daarvoor :func:`_action_msg`.
    """
    return {"response_type": "ephemeral", "text": text}


def _action_msg(text: str) -> dict:
    """Interactive button action response — alleen zichtbaar voor de klikker."""
    return {"ephemeral_text": text}
