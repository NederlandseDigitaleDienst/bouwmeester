"""Repository voor rollen in een initiatief en het werk per persoon."""

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bouwmeester.core.org_context import OrgContext, apply_org_filter
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.initiatief_rol import (
    InitiatiefCirkel,
    InitiatiefPersoonFocus,
    InitiatiefRol,
    InitiatiefRolInteresse,
    InitiatiefRolRaakvlak,
)
from bouwmeester.models.issue import Issue
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.models.task import Task
from bouwmeester.schema.initiatief_rol import (
    WerkCasus,
    WerkInteresse,
    WerkIssue,
    WerkLead,
    WerkRol,
    WerkTaak,
)
from bouwmeester.schema.task import TaskStatus

# Velden die leeg mogen worden; de rest blijft staan bij null.
_WISBAAR = {"doel", "toelichting", "feedback"}
_VELDEN = ("naam", "doel", "aanspreekbaar_op", "domein", "toelichting", "feedback")


def raakvlak_paar(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    """Een paar rollen in vaste volgorde: de kleinste id eerst."""
    return (a, b) if str(a) < str(b) else (b, a)


class InitiatiefRolRepository:
    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------------
    # Cirkel
    # ------------------------------------------------------------------

    async def ankercirkel(self, initiatief: Initiatief) -> InitiatiefCirkel:
        """De ankercirkel van het initiatief; de eerste keer maakt hij hem."""
        stmt = select(InitiatiefCirkel).where(
            InitiatiefCirkel.initiatief_id == initiatief.id,
            InitiatiefCirkel.parent_id.is_(None),
        )
        cirkel = (await self.session.execute(stmt)).scalar_one_or_none()
        if cirkel is not None:
            return cirkel
        # Twee eerste verzoeken tegelijk: de tweede botst op de unieke index
        # en leest dan de cirkel van de eerste.
        await self.session.execute(
            pg_insert(InitiatiefCirkel)
            .values(initiatief_id=initiatief.id, naam=initiatief.naam)
            .on_conflict_do_nothing(
                index_elements=["initiatief_id"],
                index_where=InitiatiefCirkel.parent_id.is_(None),
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def zet_cirkel(
        self, cirkel: InitiatiefCirkel, waarden: dict
    ) -> InitiatiefCirkel:
        for key, value in waarden.items():
            if key == "focus" and value is None:
                continue
            setattr(cirkel, key, value)
        await self.session.flush()
        await self.session.refresh(cirkel)
        return cirkel

    # ------------------------------------------------------------------
    # Rollen
    # ------------------------------------------------------------------

    async def list_for_initiatief(self, initiatief_id: UUID) -> list[InitiatiefRol]:
        stmt = (
            select(InitiatiefRol)
            .where(InitiatiefRol.initiatief_id == initiatief_id)
            .order_by(InitiatiefRol.sort_order.asc(), InitiatiefRol.naam.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_in_initiatief(
        self, initiatief_id: UUID, rol_id: UUID
    ) -> InitiatiefRol | None:
        rol = await self.session.get(InitiatiefRol, rol_id)
        if rol is None or rol.initiatief_id != initiatief_id:
            return None
        return rol

    async def op_naam(self, initiatief_id: UUID, naam: str) -> InitiatiefRol | None:
        stmt = select(InitiatiefRol).where(
            InitiatiefRol.initiatief_id == initiatief_id,
            func.lower(InitiatiefRol.naam) == naam.lower(),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def naam_bestaat(
        self, initiatief_id: UUID, naam: str, behalve: UUID | None = None
    ) -> bool:
        rol = await self.op_naam(initiatief_id, naam)
        return rol is not None and rol.id != behalve

    async def create(
        self,
        initiatief: Initiatief,
        waarden: dict,
        *,
        status: str,
        vervuller_id: UUID | None,
    ) -> InitiatiefRol:
        cirkel = await self.ankercirkel(initiatief)
        max_stmt = select(func.coalesce(func.max(InitiatiefRol.sort_order), -1)).where(
            InitiatiefRol.initiatief_id == initiatief.id
        )
        volgende = (await self.session.execute(max_stmt)).scalar_one() + 1
        rol = InitiatiefRol(
            initiatief_id=initiatief.id,
            cirkel_id=cirkel.id,
            sort_order=volgende,
            status=status,
            vervuller_id=vervuller_id,
            **{k: v for k, v in waarden.items() if k in _VELDEN},
        )
        self.session.add(rol)
        await self.session.flush()
        return await self.ververs(rol)

    async def zet_velden(self, rol: InitiatiefRol, waarden: dict) -> None:
        for key, value in waarden.items():
            if key not in _VELDEN:
                continue
            if value is not None or key in _WISBAAR:
                setattr(rol, key, value)

    def wijs_toe(self, rol: InitiatiefRol, vervuller_id: UUID) -> None:
        rol.vervuller_id = vervuller_id
        rol.status = "belegd"

    def opnieuw_toewijzen(self, rol: InitiatiefRol) -> None:
        """Terug naar open met een nieuwe ronde: oude interesse is van eerder."""
        rol.vervuller_id = None
        rol.status = "open"
        rol.ronde += 1

    async def delete(self, rol: InitiatiefRol) -> None:
        await self.session.delete(rol)
        await self.session.flush()

    async def ververs(self, rol: InitiatiefRol) -> InitiatiefRol:
        await self.session.flush()
        await self.session.refresh(rol, ["vervuller", "interesse", "updated_at"])
        for i in rol.interesse:
            await self.session.refresh(i, ["person", "vastgelegd_door"])
        return rol

    # ------------------------------------------------------------------
    # Interesse
    # ------------------------------------------------------------------

    async def zet_interesse(
        self,
        rol: InitiatiefRol,
        person_id: UUID,
        invulling: str | None,
        door_id: UUID | None,
    ) -> InitiatiefRol:
        bestaand = next(
            (
                i
                for i in rol.interesse
                if i.person_id == person_id and i.ronde == rol.ronde
            ),
            None,
        )
        if bestaand is None:
            rol.interesse.append(
                InitiatiefRolInteresse(
                    person_id=person_id,
                    ronde=rol.ronde,
                    invulling=invulling,
                    vastgelegd_door_id=door_id,
                )
            )
        else:
            # Leeg opnieuw vastleggen wist wat er al stond niet.
            if invulling is not None:
                bestaand.invulling = invulling
            bestaand.vastgelegd_door_id = door_id
        return await self.ververs(rol)

    async def verwijder_interesse(
        self, rol: InitiatiefRol, person_id: UUID
    ) -> InitiatiefRol | None:
        bestaand = next(
            (
                i
                for i in rol.interesse
                if i.person_id == person_id and i.ronde == rol.ronde
            ),
            None,
        )
        if bestaand is None:
            return None
        rol.interesse.remove(bestaand)
        return await self.ververs(rol)

    # ------------------------------------------------------------------
    # Raakvlakken
    # ------------------------------------------------------------------

    async def raakvlakken_per_rol(
        self, initiatief_id: UUID
    ) -> dict[UUID, list[tuple[InitiatiefRolRaakvlak, UUID]]]:
        """Per rol: elk raakvlak met de id van de rol aan de andere kant."""
        stmt = (
            select(InitiatiefRolRaakvlak)
            .join(InitiatiefRol, InitiatiefRol.id == InitiatiefRolRaakvlak.rol_a_id)
            .where(InitiatiefRol.initiatief_id == initiatief_id)
            .order_by(InitiatiefRolRaakvlak.created_at.asc())
        )
        uit: dict[UUID, list[tuple[InitiatiefRolRaakvlak, UUID]]] = {}
        for rv in (await self.session.execute(stmt)).scalars().all():
            uit.setdefault(rv.rol_a_id, []).append((rv, rv.rol_b_id))
            uit.setdefault(rv.rol_b_id, []).append((rv, rv.rol_a_id))
        return uit

    async def raakvlak_tussen(self, a: UUID, b: UUID) -> InitiatiefRolRaakvlak | None:
        rol_a, rol_b = raakvlak_paar(a, b)
        stmt = select(InitiatiefRolRaakvlak).where(
            InitiatiefRolRaakvlak.rol_a_id == rol_a,
            InitiatiefRolRaakvlak.rol_b_id == rol_b,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def maak_raakvlak(
        self, a: UUID, b: UUID, omschrijving: str | None
    ) -> InitiatiefRolRaakvlak:
        rol_a, rol_b = raakvlak_paar(a, b)
        rv = InitiatiefRolRaakvlak(
            rol_a_id=rol_a, rol_b_id=rol_b, omschrijving=omschrijving
        )
        self.session.add(rv)
        await self.session.flush()
        return rv

    async def raakvlak_in_initiatief(
        self, initiatief_id: UUID, raakvlak_id: UUID
    ) -> InitiatiefRolRaakvlak | None:
        rv = await self.session.get(InitiatiefRolRaakvlak, raakvlak_id)
        if rv is None:
            return None
        rol = await self.session.get(InitiatiefRol, rv.rol_a_id)
        if rol is None or rol.initiatief_id != initiatief_id:
            return None
        return rv

    # ------------------------------------------------------------------
    # Focus en werk per persoon
    # ------------------------------------------------------------------

    async def focus_van(self, initiatief_id: UUID, person_id: UUID) -> list[str]:
        rij = await self.session.get(InitiatiefPersoonFocus, (initiatief_id, person_id))
        return list(rij.focus) if rij else []

    async def zet_focus(
        self, initiatief_id: UUID, person_id: UUID, focus: list[str]
    ) -> list[str]:
        rij = await self.session.get(InitiatiefPersoonFocus, (initiatief_id, person_id))
        if rij is None:
            rij = InitiatiefPersoonFocus(
                initiatief_id=initiatief_id, person_id=person_id, focus=focus
            )
            self.session.add(rij)
        else:
            rij.focus = focus
        await self.session.flush()
        return list(rij.focus)

    async def rollen_van(self, initiatief_id: UUID, person_id: UUID) -> list[WerkRol]:
        stmt = (
            select(InitiatiefRol)
            .where(
                InitiatiefRol.initiatief_id == initiatief_id,
                InitiatiefRol.vervuller_id == person_id,
            )
            .order_by(InitiatiefRol.sort_order.asc(), InitiatiefRol.naam.asc())
        )
        return [
            WerkRol(id=r.id, naam=r.naam, doel=r.doel)
            for r in (await self.session.execute(stmt)).scalars().all()
        ]

    async def interesse_van(
        self, initiatief_id: UUID, person_id: UUID
    ) -> list[WerkInteresse]:
        """Interesse in rollen die nu open zijn, in hun huidige ronde."""
        stmt = (
            select(InitiatiefRolInteresse, InitiatiefRol.naam)
            .join(InitiatiefRol, InitiatiefRol.id == InitiatiefRolInteresse.rol_id)
            .where(
                InitiatiefRol.initiatief_id == initiatief_id,
                InitiatiefRol.status == "open",
                InitiatiefRolInteresse.ronde == InitiatiefRol.ronde,
                InitiatiefRolInteresse.person_id == person_id,
            )
            .order_by(InitiatiefRol.sort_order.asc(), InitiatiefRol.naam.asc())
        )
        return [
            WerkInteresse(rol_id=i.rol_id, rol_naam=naam, invulling=i.invulling)
            for i, naam in (await self.session.execute(stmt)).all()
        ]

    async def leads_van(self, initiatief_id: UUID, person_id: UUID) -> list[WerkLead]:
        stmt = (
            select(Lead)
            .where(
                Lead.initiatief_id == initiatief_id,
                or_(Lead.assignee_id == person_id, Lead.brought_by_id == person_id),
            )
            .order_by(Lead.title.asc())
        )
        uit = []
        for lead in (await self.session.execute(stmt)).scalars().all():
            als = []
            if lead.assignee_id == person_id:
                als.append("eigenaar")
            if lead.brought_by_id == person_id:
                als.append("aanbrenger")
            uit.append(
                WerkLead(id=lead.id, title=lead.title, stage=lead.stage, als=als)
            )
        return uit

    async def casussen_van(
        self, initiatief_id: UUID, person_id: UUID
    ) -> list[WerkCasus]:
        stmt = (
            select(Casus, ResourcePermission.rol)
            .join(
                ResourcePermission,
                (ResourcePermission.resource_type == "casus")
                & (ResourcePermission.resource_id == Casus.id),
            )
            .where(
                Casus.initiatief_id == initiatief_id,
                ResourcePermission.person_id == person_id,
            )
            .order_by(Casus.title.asc())
        )
        per_casus: dict[UUID, WerkCasus] = {}
        for casus, rol in (await self.session.execute(stmt)).all():
            # Trekker gaat voor teamlid als iemand allebei is.
            if casus.id not in per_casus or rol == "trekker":
                per_casus[casus.id] = WerkCasus(
                    id=casus.id, title=casus.title, fase=casus.fase, rol=rol
                )
        return list(per_casus.values())

    async def issues_van(self, initiatief_id: UUID, person_id: UUID) -> list[WerkIssue]:
        # Ook een vraag van het initiatief zelf, zonder casus.
        stmt = (
            select(Issue, Casus.title)
            .outerjoin(Casus, Casus.id == Issue.casus_id)
            .where(
                or_(
                    Casus.initiatief_id == initiatief_id,
                    and_(
                        Issue.casus_id.is_(None), Issue.initiatief_id == initiatief_id
                    ),
                ),
                Issue.assignee_id == person_id,
                Issue.status != "done",
            )
            .order_by(Casus.title.asc().nulls_first(), Issue.sort_order.asc())
        )
        return [
            WerkIssue(
                id=i.id,
                title=i.title,
                status=i.status,
                is_onderzoeksvraag=i.is_onderzoeksvraag,
                casus_id=i.casus_id,
                casus_title=casus_title,
            )
            for i, casus_title in (await self.session.execute(stmt)).all()
        ]

    async def open_taken_van(
        self, initiatief_id: UUID, person_id: UUID, org_ctx: OrgContext
    ) -> list[WerkTaak]:
        # Ook taken onder een vraag zonder casus; subtaken niet, die staan
        # onder hun hoofdtaak.
        stmt = (
            select(Task, Casus.title)
            .outerjoin(Casus, Casus.id == Task.casus_id)
            .outerjoin(Issue, Issue.id == Task.issue_id)
            .where(
                or_(
                    Casus.initiatief_id == initiatief_id,
                    and_(
                        Task.casus_id.is_(None),
                        Issue.casus_id.is_(None),
                        Issue.initiatief_id == initiatief_id,
                    ),
                ),
                Task.parent_id.is_(None),
                Task.assignee_id == person_id,
                Task.status.in_([TaskStatus.open, TaskStatus.in_progress]),
            )
            .order_by(Task.deadline.asc().nulls_last(), Task.title.asc())
        )
        # Zelfde regel als get_by_assignee: je eigen taken zie je altijd.
        if org_ctx.person_id != person_id:
            stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        return [
            WerkTaak(
                id=t.id,
                title=t.title,
                status=t.status,
                priority=t.priority,
                deadline=t.deadline,
                casus_id=t.casus_id,
                casus_title=casus_title,
                issue_id=t.issue_id,
            )
            for t, casus_title in (await self.session.execute(stmt)).all()
        ]
