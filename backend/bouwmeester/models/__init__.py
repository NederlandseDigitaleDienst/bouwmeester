# Import all models here so that Base.metadata is populated
# and Alembic can detect them for autogenerate.

from bouwmeester.models.absence import Absence  # noqa: F401
from bouwmeester.models.access_request import AccessRequest  # noqa: F401
from bouwmeester.models.activity import Activity  # noqa: F401
from bouwmeester.models.app_config import AppConfig  # noqa: F401
from bouwmeester.models.beleidskader import Beleidskader  # noqa: F401
from bouwmeester.models.beleidsoptie import Beleidsoptie  # noqa: F401
from bouwmeester.models.bron import Bron  # noqa: F401
from bouwmeester.models.bron_bijlage import BronBijlage  # noqa: F401
from bouwmeester.models.chat_attachment import ChatAttachment  # noqa: F401
from bouwmeester.models.chat_conversation import ChatConversation  # noqa: F401
from bouwmeester.models.corpus_node import CorpusNode  # noqa: F401
from bouwmeester.models.debat_aankondiging import DebatAankondiging  # noqa: F401
from bouwmeester.models.debat_markering import (  # noqa: F401
    DebatMarkering,
    DebatMarkeringVermelding,
)
from bouwmeester.models.debat_sessie import (  # noqa: F401
    DebatOndertitel,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.models.doel import Doel  # noqa: F401
from bouwmeester.models.dossier import Dossier  # noqa: F401
from bouwmeester.models.edge import Edge  # noqa: F401
from bouwmeester.models.edge_schema_rule import EdgeSchemaRule  # noqa: F401
from bouwmeester.models.edge_type import EdgeType  # noqa: F401
from bouwmeester.models.eenheid_module import EenheidModule  # noqa: F401
from bouwmeester.models.effect import Effect  # noqa: F401
from bouwmeester.models.fcc_sync_log import FccSyncLog  # noqa: F401
from bouwmeester.models.github_link import GitHubLink  # noqa: F401
from bouwmeester.models.http_session import HttpSession  # noqa: F401
from bouwmeester.models.import_watermerk import ImportWatermerk  # noqa: F401
from bouwmeester.models.initiatief import Initiatief  # noqa: F401
from bouwmeester.models.initiatief_update import InitiatiefUpdatePost  # noqa: F401
from bouwmeester.models.instrument import Instrument  # noqa: F401
from bouwmeester.models.lead import Lead  # noqa: F401
from bouwmeester.models.lead_activity import LeadActivity  # noqa: F401
from bouwmeester.models.lead_attachment import LeadAttachment  # noqa: F401
from bouwmeester.models.lead_column import LeadColumn  # noqa: F401
from bouwmeester.models.lead_node import LeadNode  # noqa: F401
from bouwmeester.models.lead_update import LeadUpdatePost  # noqa: F401
from bouwmeester.models.maatregel import Maatregel  # noqa: F401
from bouwmeester.models.mattermost_channel_link import (  # noqa: F401
    MattermostChannelLink,
)
from bouwmeester.models.mattermost_post_link import MattermostPostLink  # noqa: F401
from bouwmeester.models.mattermost_user import (  # noqa: F401
    MattermostLinkCode,
    MattermostUser,
)
from bouwmeester.models.mention import Mention  # noqa: F401
from bouwmeester.models.node_status import CorpusNodeStatus  # noqa: F401
from bouwmeester.models.node_title import CorpusNodeTitle  # noqa: F401
from bouwmeester.models.notification import Notification  # noqa: F401
from bouwmeester.models.onboarding_dismissal import OnboardingDismissal  # noqa: F401
from bouwmeester.models.opdracht import Opdracht, OpdrachtNode  # noqa: F401
from bouwmeester.models.org_email_domein import OrganisatieEmailDomein  # noqa: F401
from bouwmeester.models.org_naam import OrganisatieEenheidNaam  # noqa: F401
from bouwmeester.models.org_parent import OrganisatieEenheidParent  # noqa: F401
from bouwmeester.models.org_placement_request import OrgPlacementRequest  # noqa: F401
from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid  # noqa: F401
from bouwmeester.models.parlementair_item import (  # noqa: F401
    ParlementairItem,
    SuggestedEdge,
)
from bouwmeester.models.pending_reconciliation import (  # noqa: F401
    PendingReconciliation,
)
from bouwmeester.models.person import Person  # noqa: F401
from bouwmeester.models.person_email import PersonEmail  # noqa: F401
from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid  # noqa: F401
from bouwmeester.models.person_phone import PersonPhone  # noqa: F401
from bouwmeester.models.persoon_samenwerkingsverband import (  # noqa: F401
    PersoonSamenwerkingsverband,
)
from bouwmeester.models.politieke_input import PolitiekeInput  # noqa: F401
from bouwmeester.models.probleem import Probleem  # noqa: F401
from bouwmeester.models.resource_permission import ResourcePermission  # noqa: F401
from bouwmeester.models.role import (  # noqa: F401
    Permission,
    PersonRole,
    Role,
    RolePermission,
)
from bouwmeester.models.samenwerkingsverband import Samenwerkingsverband  # noqa: F401
from bouwmeester.models.shared_access import SharedAccess  # noqa: F401
from bouwmeester.models.stakeholder_assessment import (
    StakeholderAssessment,  # noqa: F401
)
from bouwmeester.models.suggested_lead import SuggestedLead  # noqa: F401
from bouwmeester.models.tag import LeadTag, NodeTag, Tag  # noqa: F401
from bouwmeester.models.task import Task  # noqa: F401
from bouwmeester.models.task_attachment import TaskAttachment  # noqa: F401
from bouwmeester.models.task_comment import TaskComment  # noqa: F401
from bouwmeester.models.tooi_sync_log import TooiSyncLog  # noqa: F401
from bouwmeester.models.webauthn_credential import WebAuthnCredential  # noqa: F401
from bouwmeester.models.whitelist_email import WhitelistEmail  # noqa: F401
from bouwmeester.models.worker_heartbeat import WorkerHeartbeat  # noqa: F401

__all__ = [
    "AccessRequest",
    "Absence",
    "AppConfig",
    "Activity",
    "ChatAttachment",
    "ChatConversation",
    "Beleidskader",
    "Beleidsoptie",
    "Bron",
    "BronBijlage",
    "CorpusNode",
    "DebatMarkering",
    "DebatMarkeringVermelding",
    "DebatOndertitel",
    "DebatSessie",
    "DebatSpreekbeurt",
    "CorpusNodeStatus",
    "CorpusNodeTitle",
    "Doel",
    "Dossier",
    "EenheidModule",
    "Edge",
    "EdgeSchemaRule",
    "EdgeType",
    "Effect",
    "FccSyncLog",
    "GitHubLink",
    "HttpSession",
    "Initiatief",
    "InitiatiefUpdatePost",
    "Instrument",
    "Lead",
    "LeadActivity",
    "LeadAttachment",
    "LeadColumn",
    "LeadNode",
    "LeadUpdatePost",
    "LeadTag",
    "Maatregel",
    "MattermostChannelLink",
    "MattermostLinkCode",
    "MattermostPostLink",
    "MattermostUser",
    "Mention",
    "ParlementairItem",
    "NodeTag",
    "Notification",
    "OnboardingDismissal",
    "Opdracht",
    "OpdrachtNode",
    "OrgPlacementRequest",
    "OrganisatieEenheidNaam",
    "OrganisatieEenheidParent",
    "OrganisatieEenheid",
    "OrganisatieEmailDomein",
    "PendingReconciliation",
    "Permission",
    "Person",
    "PersonRole",
    "PersonEmail",
    "PersonOrganisatieEenheid",
    "PersonPhone",
    "PolitiekeInput",
    "Probleem",
    "ResourcePermission",
    "Role",
    "RolePermission",
    "SharedAccess",
    "StakeholderAssessment",
    "SuggestedEdge",
    "SuggestedLead",
    "Tag",
    "Task",
    "TooiSyncLog",
    "WebAuthnCredential",
    "WhitelistEmail",
    "WorkerHeartbeat",
    "ImportWatermerk",
]
