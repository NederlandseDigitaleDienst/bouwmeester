"""API router registry -- includes all sub-routers under /api."""

from fastapi import APIRouter

from bouwmeester.api.routes.activity import router as activity_router
from bouwmeester.api.routes.admin import router as admin_router
from bouwmeester.api.routes.admin_sync import router as admin_sync_router
from bouwmeester.api.routes.auth import router as auth_router
from bouwmeester.api.routes.bijlage import router as bijlage_router
from bouwmeester.api.routes.casus_soorten import router as casus_soorten_router
from bouwmeester.api.routes.casussen import router as casussen_router
from bouwmeester.api.routes.chat import router as chat_router
from bouwmeester.api.routes.debat_aankondiging import (
    router as debat_aankondiging_router,
)
from bouwmeester.api.routes.debatten import router as debatten_router
from bouwmeester.api.routes.edge_schema import router as edge_schema_router
from bouwmeester.api.routes.edge_types import router as edge_types_router
from bouwmeester.api.routes.edges import router as edges_router
from bouwmeester.api.routes.eenheid_modules import router as eenheid_modules_router
from bouwmeester.api.routes.fcc import router as fcc_router
from bouwmeester.api.routes.graph import router as graph_router
from bouwmeester.api.routes.import_export import router as import_export_router
from bouwmeester.api.routes.initiatief import router as initiatieven_router
from bouwmeester.api.routes.initiatief_update import (
    router as initiatief_updates_router,
)
from bouwmeester.api.routes.issues import router as issues_router
from bouwmeester.api.routes.lead_columns import router as lead_columns_router
from bouwmeester.api.routes.lead_update import router as lead_updates_router
from bouwmeester.api.routes.leads import router as leads_router
from bouwmeester.api.routes.llm import router as llm_router
from bouwmeester.api.routes.mattermost import router as mattermost_router
from bouwmeester.api.routes.mattermost_channels import (
    router as mattermost_channels_router,
)
from bouwmeester.api.routes.mentions import router as mentions_router
from bouwmeester.api.routes.nodes import router as nodes_router
from bouwmeester.api.routes.notifications import router as notifications_router
from bouwmeester.api.routes.opdrachten import router as opdrachten_router
from bouwmeester.api.routes.org_placements import router as org_placements_router
from bouwmeester.api.routes.organisatie import router as organisatie_router
from bouwmeester.api.routes.parlementair import router as parlementair_router
from bouwmeester.api.routes.parlementair_abonnement import (
    router as parlementair_abonnement_router,
)
from bouwmeester.api.routes.people import router as people_router
from bouwmeester.api.routes.public_initiatief import (
    router as public_initiatief_router,
)
from bouwmeester.api.routes.reconciliation import router as reconciliation_router
from bouwmeester.api.routes.resource_permissions import (
    router as resource_permissions_router,
)
from bouwmeester.api.routes.roles import router as roles_router
from bouwmeester.api.routes.samenwerkingsverband import (
    router as samenwerkingsverband_router,
)
from bouwmeester.api.routes.search import router as search_router
from bouwmeester.api.routes.sharing import router as sharing_router
from bouwmeester.api.routes.skill import router as skill_router
from bouwmeester.api.routes.stakeholder_assessments import (
    router as stakeholder_assessments_router,
)
from bouwmeester.api.routes.tags import router as tags_router
from bouwmeester.api.routes.task_comments import router as task_comments_router
from bouwmeester.api.routes.tasks import router as tasks_router
from bouwmeester.api.routes.webauthn import router as webauthn_router

api_router = APIRouter()

api_router.include_router(activity_router)
api_router.include_router(admin_router)
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(bijlage_router)
api_router.include_router(edge_schema_router)
api_router.include_router(edge_types_router)
api_router.include_router(eenheid_modules_router)
api_router.include_router(edges_router)
api_router.include_router(admin_sync_router)
api_router.include_router(reconciliation_router)
api_router.include_router(fcc_router)
api_router.include_router(graph_router)
api_router.include_router(initiatieven_router)
api_router.include_router(initiatief_updates_router)
api_router.include_router(import_export_router)
api_router.include_router(lead_columns_router)
api_router.include_router(leads_router)
api_router.include_router(lead_updates_router)
api_router.include_router(casussen_router)
api_router.include_router(casus_soorten_router)
api_router.include_router(issues_router)
api_router.include_router(task_comments_router)
api_router.include_router(llm_router)
api_router.include_router(mattermost_router)
api_router.include_router(mattermost_channels_router)
api_router.include_router(mentions_router)
api_router.include_router(nodes_router)
api_router.include_router(notifications_router)
api_router.include_router(opdrachten_router)
api_router.include_router(org_placements_router)
api_router.include_router(organisatie_router)
api_router.include_router(parlementair_router)
api_router.include_router(debatten_router)
api_router.include_router(debat_aankondiging_router)
api_router.include_router(parlementair_abonnement_router)
api_router.include_router(people_router)
api_router.include_router(public_initiatief_router)
api_router.include_router(resource_permissions_router)
api_router.include_router(roles_router)
api_router.include_router(samenwerkingsverband_router)
api_router.include_router(search_router)
api_router.include_router(sharing_router)
api_router.include_router(skill_router)
api_router.include_router(stakeholder_assessments_router)
api_router.include_router(tags_router)
api_router.include_router(tasks_router)
api_router.include_router(webauthn_router)
