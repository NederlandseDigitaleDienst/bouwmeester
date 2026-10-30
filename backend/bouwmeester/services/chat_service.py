"""Chat orchestration service — manages tool-calling conversations with VLAM."""

import asyncio
import base64
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from openai import APIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from bouwmeester.models.chat_attachment import ChatAttachment
from bouwmeester.models.chat_conversation import ChatConversation
from bouwmeester.schema.chat import (
    ChatAction,
    ChatAttachmentResponse,
    ChatMessage,
    PendingAction,
)
from bouwmeester.services.document_extract import (
    IMAGE_CONTENT_TYPES,
    extract_text_from_bytes,
)
from bouwmeester.services.llm.base import BaseLLMService
from bouwmeester.services.llm.prompts import (
    CHAT_SYSTEM_PROMPT,
    build_chat_context_message,
)

if TYPE_CHECKING:
    from bouwmeester.core.initiatief_context import InitiatiefContext
    from bouwmeester.core.org_context import OrgContext
    from bouwmeester.core.permissions import PermissionContext
    from bouwmeester.models.person import Person

logger = logging.getLogger(__name__)


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID, date/datetime, and Decimal objects."""

    def default(self, o: object) -> object:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def _safe_dumps(obj: object, **kwargs: object) -> str:
    """json.dumps with safe UUID/date/Decimal serialization."""
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(obj, cls=_SafeEncoder, **kwargs)


# Maximum tool-calling loop iterations to prevent runaway loops.
_MAX_TOOL_ROUNDS = 5

# Maximum number of messages to send to the LLM to stay within token limits.
# The system prompt is always included; we keep the most recent messages.
_MAX_MESSAGES_FOR_LLM = 40


# Regex to strip raw tool-call artefacts from LLM output
_TOOL_CALL_RE = re.compile(r"\[TOOL_CALLS?\].*", re.DOTALL)


def _clean_content(text: str) -> str:
    """Strip raw tool-call artefacts and internal noise from LLM output."""
    # Remove [TOOL_CALLS] blocks that some models emit
    text = _TOOL_CALL_RE.sub("", text)
    return text.strip()


async def _build_attachment_refs(
    attachments: list[ChatAttachment],
) -> list[dict]:
    """Build lightweight refs for storing in conversation history (no base64).

    Documents are read from the bijlagen store once, here, and their text is
    kept in the ref, so later turns do not have to extract it again.
    """
    from bouwmeester.core.storage import chat_key, read_blob

    refs = []
    for att in attachments:
        if att.content_type in IMAGE_CONTENT_TYPES:
            refs.append(
                {
                    "type": "image_ref",
                    "attachment_id": str(att.id),
                    "content_type": att.content_type,
                    "pad": att.pad,
                    "bestandsnaam": att.bestandsnaam,
                }
            )
        else:
            # Store extracted text inline so we don't need to re-extract
            data = await read_blob(chat_key(att.pad))
            extracted = (
                await asyncio.to_thread(extract_text_from_bytes, data, att.content_type)
                if data is not None
                else None
            )
            refs.append(
                {
                    "type": "document_ref",
                    "attachment_id": str(att.id),
                    "bestandsnaam": att.bestandsnaam,
                    "extracted_text": extracted or "",
                }
            )
    return refs


async def _reconstruct_content_from_refs(
    text: str | None,
    refs: list[dict],
) -> str | list[dict]:
    """Reconstruct LLM content array from stored refs.

    Uses the ``pad`` field stored in image refs to fetch the image from the
    bijlagen store.
    """
    from bouwmeester.core.storage import chat_key, read_blob

    if not refs:
        return text or ""

    parts: list[dict] = [{"type": "text", "text": text or ""}]
    has_image = False

    for ref in refs:
        if ref.get("type") == "image_ref":
            content_type = ref.get("content_type", "image/png")
            pad = ref.get("pad")
            if pad:
                data = await read_blob(chat_key(pad))
                if data is None:
                    logger.warning("Could not read image file: %s", pad)
                    continue
                b64 = base64.b64encode(data).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{b64}",
                        },
                    }
                )
                has_image = True
        elif ref.get("type") == "document_ref":
            extracted = ref.get("extracted_text", "")
            if extracted:
                name = ref.get("bestandsnaam", "document")
                parts.append(
                    {
                        "type": "text",
                        "text": f"\n\n--- Inhoud van {name} ---\n{extracted}",
                    }
                )

    if not has_image:
        return "".join(p["text"] for p in parts if p["type"] == "text")

    return parts


async def _prepare_llm_messages(messages: list[dict]) -> list[dict]:
    """Prepare messages for the LLM by reconstructing attachment refs.

    Replaces ``attachment_refs`` in *all* user messages with actual content
    (base64 images / extracted text).  Strips the ``attachment_refs`` key so
    the LLM never sees it.
    """
    out: list[dict] = []
    for msg in messages:
        refs = msg.get("attachment_refs")
        if refs:
            copy = {k: v for k, v in msg.items() if k != "attachment_refs"}
            copy["content"] = await _reconstruct_content_from_refs(
                msg.get("content"), refs
            )
            out.append(copy)
        else:
            out.append(msg)
    return out


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

_READ_TOOLS: dict[str, dict] = {
    "search_nodes": {
        "type": "function",
        "function": {
            "name": "search_nodes",
            "description": (
                "Zoek in het beleidscorpus op"
                " trefwoorden. Geeft nodes terug"
                " met titel, type en ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zoekterm(en)"},
                    "node_type": {
                        "type": "string",
                        "description": (
                            "Optioneel filter op node-type"
                            " (bijv. dossier, doel,"
                            " instrument)"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    "get_node": {
        "type": "function",
        "function": {
            "name": "get_node",
            "description": (
                "Haal details op van een specifieke"
                " node (titel, beschrijving,"
                " type, status)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "UUID van de node"},
                },
                "required": ["node_id"],
            },
        },
    },
    "get_node_neighbors": {
        "type": "function",
        "function": {
            "name": "get_node_neighbors",
            "description": (
                "Haal de directe buren (verbonden nodes via relaties) op van een node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "UUID van de node"},
                },
                "required": ["node_id"],
            },
        },
    },
    "get_tasks_for_node": {
        "type": "function",
        "function": {
            "name": "get_tasks_for_node",
            "description": "Haal alle taken op die gekoppeld zijn aan een node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "UUID van de node"},
                },
                "required": ["node_id"],
            },
        },
    },
    "get_tasks_for_person": {
        "type": "function",
        "function": {
            "name": "get_tasks_for_person",
            "description": ("Haal alle taken op die toegewezen zijn aan een persoon."),
            "parameters": {
                "type": "object",
                "properties": {
                    "person_id": {
                        "type": "string",
                        "description": "UUID van de persoon",
                    },
                },
                "required": ["person_id"],
            },
        },
    },
    "get_overdue_tasks": {
        "type": "function",
        "function": {
            "name": "get_overdue_tasks",
            "description": (
                "Haal alle verlopen taken op"
                " (deadline verstreken, nog niet afgerond)."
                " Optioneel gefilterd op persoon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "assignee_id": {
                        "type": "string",
                        "description": (
                            "UUID van de persoon (optioneel,"
                            " laat leeg voor alle verlopen taken)"
                        ),
                    },
                },
            },
        },
    },
    "list_tags": {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "Toon alle beschikbare tags in het systeem.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "list_edge_types": {
        "type": "function",
        "function": {
            "name": "list_edge_types",
            "description": "Toon alle beschikbare relatie-types.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "search_people": {
        "type": "function",
        "function": {
            "name": "search_people",
            "description": "Zoek personen op naam.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Naam of deel van naam"},
                },
                "required": ["query"],
            },
        },
    },
    "search_organisatie": {
        "type": "function",
        "function": {
            "name": "search_organisatie",
            "description": (
                "Zoek organisatie-eenheden op naam"
                " (ministerie, DG, directie, afdeling, team)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Naam of deel van naam",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "get_organisatie": {
        "type": "function",
        "function": {
            "name": "get_organisatie",
            "description": (
                "Haal details op van een organisatie-eenheid"
                " (naam, type, manager, medewerkers)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "organisatie_id": {
                        "type": "string",
                        "description": "UUID van de organisatie-eenheid",
                    },
                },
                "required": ["organisatie_id"],
            },
        },
    },
    "get_person_summary": {
        "type": "function",
        "function": {
            "name": "get_person_summary",
            "description": (
                "Haal een samenvatting op van een persoon:"
                " naam, organisatie, taken, en betrokken nodes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "person_id": {
                        "type": "string",
                        "description": "UUID van de persoon",
                    },
                },
                "required": ["person_id"],
            },
        },
    },
    "find_path": {
        "type": "function",
        "function": {
            "name": "find_path",
            "description": (
                "Vind het kortste pad via relaties tussen twee nodes"
                " in het beleidsgrafiek."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_node_id": {
                        "type": "string",
                        "description": "UUID van de start-node",
                    },
                    "to_node_id": {
                        "type": "string",
                        "description": "UUID van de eind-node",
                    },
                },
                "required": ["from_node_id", "to_node_id"],
            },
        },
    },
    "find_similar_nodes": {
        "type": "function",
        "function": {
            "name": "find_similar_nodes",
            "description": (
                "Vind nodes met vergelijkbare titels"
                " (handig om duplicaten te ontdekken)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel om op te zoeken",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optionele beschrijving voor betere matching",
                    },
                },
                "required": ["title"],
            },
        },
    },
    "list_opdrachten": {
        "type": "function",
        "function": {
            "name": "list_opdrachten",
            "description": (
                "Zoek opdrachten/subsidies. Optioneel"
                " gefilterd op begrotingsjaar, status, of type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "begrotingsjaar": {
                        "type": "integer",
                        "description": "Begrotingsjaar (bijv. 2025)",
                    },
                    "status": {
                        "type": "string",
                        "description": (
                            "Status: concept, actief,"
                            " afgerond, verantwoord,"
                            " geannuleerd"
                        ),
                    },
                    "type": {
                        "type": "string",
                        "description": "Type: opdracht of subsidie",
                    },
                },
            },
        },
    },
    "get_opdracht": {
        "type": "function",
        "function": {
            "name": "get_opdracht",
            "description": (
                "Haal details op van een opdracht/subsidie"
                " (titel, budget, status, verantwoordelijke)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "opdracht_id": {
                        "type": "string",
                        "description": "UUID van de opdracht",
                    },
                },
                "required": ["opdracht_id"],
            },
        },
    },
    "get_recent_activity": {
        "type": "function",
        "function": {
            "name": "get_recent_activity",
            "description": (
                "Bekijk recente activiteiten/wijzigingen in het systeem (audit log)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Aantal resultaten (standaard 10, max 20)",
                    },
                },
            },
        },
    },
    "list_parlementair": {
        "type": "function",
        "function": {
            "name": "list_parlementair",
            "description": (
                "Zoek parlementaire items: moties,"
                " kamervragen, toezeggingen, amendementen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Zoekterm in titel/onderwerp",
                    },
                    "item_type": {
                        "type": "string",
                        "description": (
                            "Type: motie, kamervraag,"
                            " toezegging, amendement,"
                            " commissiedebat"
                        ),
                    },
                    "status": {
                        "type": "string",
                        "description": "Status: pending, imported, rejected",
                    },
                },
            },
        },
    },
    "search_leads": {
        "type": "function",
        "function": {
            "name": "search_leads",
            "description": (
                "Zoek leads in de sales funnel."
                " Gebruik 'query' om op naam/organisatie te zoeken,"
                " of filter op stage, toegewezen persoon,"
                " of volgende-actie status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Zoekterm op titel of organisatienaam"
                            " (optioneel, gebruikt fuzzy matching)"
                        ),
                    },
                    "stage": {
                        "type": "string",
                        "description": (
                            "Filter op stage: inbox, verkennen,"
                            " eerste_gesprek, interne_check,"
                            " follow_up, in_the_pocket, koelkast"
                        ),
                    },
                    "assignee_id": {
                        "type": "string",
                        "description": ("UUID van de toegewezen persoon (optioneel)"),
                    },
                    "next_action_filter": {
                        "type": "string",
                        "description": (
                            "Filter op volgende actie: overdue, today, this_week"
                        ),
                    },
                },
            },
        },
    },
    "get_lead": {
        "type": "function",
        "function": {
            "name": "get_lead",
            "description": (
                "Haal details op van een specifieke lead"
                " (titel, organisatie, stage, contacten,"
                " activiteiten, volgende actie)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {
                        "type": "string",
                        "description": "UUID van de lead",
                    },
                },
                "required": ["lead_id"],
            },
        },
    },
    "get_lead_metrics": {
        "type": "function",
        "function": {
            "name": "get_lead_metrics",
            "description": (
                "Haal funnel-metrics op: totaal aantal leads,"
                " aantal per stage, en aantal vervallen leads."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
}

_WRITE_TOOLS: dict[str, dict] = {
    "create_node": {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "Maak een nieuwe node aan in het beleidscorpus.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titel van de node"},
                    "node_type": {
                        "type": "string",
                        "description": (
                            "Type: dossier, doel,"
                            " instrument, beleidskader,"
                            " maatregel, politieke_input,"
                            " probleem, effect,"
                            " beleidsoptie, bron"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschrijving (optioneel)",
                    },
                },
                "required": ["title", "node_type"],
            },
        },
    },
    "update_node": {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "Wijzig de titel of beschrijving van een bestaande node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "UUID van de node"},
                    "title": {
                        "type": "string",
                        "description": "Nieuwe titel (optioneel)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Nieuwe beschrijving (optioneel)",
                    },
                },
                "required": ["node_id"],
            },
        },
    },
    "create_edge": {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": "Maak een relatie aan tussen twee nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_node_id": {
                        "type": "string",
                        "description": "UUID van de bron-node",
                    },
                    "to_node_id": {
                        "type": "string",
                        "description": "UUID van de doel-node",
                    },
                    "edge_type_id": {
                        "type": "string",
                        "description": (
                            "Relatie-type (bijv."
                            " draagt_bij_aan,"
                            " onderdeel_van,"
                            " verwijst_naar)"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschrijving van de relatie (optioneel)",
                    },
                },
                "required": ["from_node_id", "to_node_id", "edge_type_id"],
            },
        },
    },
    "create_task": {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "Maak een nieuwe taak aan, gekoppeld aan een node."
                " Gebruik parent_task_id om een subtaak te maken."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Taaktitel"},
                    "node_id": {
                        "type": "string",
                        "description": "UUID van de gekoppelde node",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschrijving (optioneel)",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Prioriteit: laag, normaal, hoog, kritiek",
                    },
                    "assignee_id": {
                        "type": "string",
                        "description": ("UUID van de toegewezen persoon (optioneel)"),
                    },
                    "parent_task_id": {
                        "type": "string",
                        "description": (
                            "UUID van de bovenliggende taak"
                            " om een subtaak te maken (optioneel)"
                        ),
                    },
                },
                "required": ["title", "node_id"],
            },
        },
    },
    "update_task": {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": (
                "Wijzig een bestaande taak (status, prioriteit, titel, beschrijving)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "UUID van de taak"},
                    "title": {
                        "type": "string",
                        "description": "Nieuwe titel (optioneel)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Nieuwe beschrijving (optioneel)",
                    },
                    "status": {
                        "type": "string",
                        "description": "Status: open, in_progress, done, cancelled",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Prioriteit: laag, normaal, hoog, kritiek",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    "add_tag_to_node": {
        "type": "function",
        "function": {
            "name": "add_tag_to_node",
            "description": "Koppel een bestaande tag aan een node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "UUID van de node"},
                    "tag_name": {"type": "string", "description": "Naam van de tag"},
                },
                "required": ["node_id", "tag_name"],
            },
        },
    },
    "add_stakeholder": {
        "type": "function",
        "function": {
            "name": "add_stakeholder",
            "description": "Koppel een persoon als stakeholder aan een node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "UUID van de node"},
                    "person_id": {
                        "type": "string",
                        "description": "UUID van de persoon",
                    },
                    "rol": {
                        "type": "string",
                        "description": "Rol: eigenaar, betrokken, adviseur",
                    },
                },
                "required": ["node_id", "person_id", "rol"],
            },
        },
    },
    "attach_to_bron": {
        "type": "function",
        "function": {
            "name": "attach_to_bron",
            "description": (
                "Koppel een geüpload chatbestand als bijlage aan een bron-node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "UUID van de chat-bijlage",
                    },
                    "node_id": {
                        "type": "string",
                        "description": "UUID van de bron-node",
                    },
                },
                "required": ["attachment_id", "node_id"],
            },
        },
    },
    "create_lead": {
        "type": "function",
        "function": {
            "name": "create_lead",
            "description": (
                "Maak een nieuwe lead aan in de sales funnel."
                " De organisatie_eenheid_id wordt automatisch"
                " ingevuld op basis van de ingelogde gebruiker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": (
                            "Titel van de lead (naam organisatie/afdeling)"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschrijving van de vraag/behoefte",
                    },
                    "organization": {
                        "type": "string",
                        "description": "Naam van de externe organisatie",
                    },
                    "stage": {
                        "type": "string",
                        "description": (
                            "Stage: inbox, verkennen, eerste_gesprek,"
                            " interne_check, follow_up,"
                            " in_the_pocket, koelkast"
                            " (standaard: inbox)"
                        ),
                    },
                    "assignee_id": {
                        "type": "string",
                        "description": ("UUID van de toegewezen persoon (optioneel)"),
                    },
                    "next_action": {
                        "type": "string",
                        "description": (
                            "Beschrijving van de volgende actie (optioneel)"
                        ),
                    },
                    "next_action_date": {
                        "type": "string",
                        "description": (
                            "Datum van de volgende actie"
                            " in YYYY-MM-DD formaat (optioneel)"
                        ),
                    },
                },
                "required": ["title"],
            },
        },
    },
    "update_lead": {
        "type": "function",
        "function": {
            "name": "update_lead",
            "description": (
                "Wijzig een bestaande lead"
                " (titel, beschrijving, organisatie,"
                " toewijzing, volgende actie)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {
                        "type": "string",
                        "description": "UUID van de lead",
                    },
                    "title": {
                        "type": "string",
                        "description": "Nieuwe titel (optioneel)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Nieuwe beschrijving (optioneel)",
                    },
                    "organization": {
                        "type": "string",
                        "description": "Nieuwe organisatienaam (optioneel)",
                    },
                    "assignee_id": {
                        "type": "string",
                        "description": (
                            "UUID van de nieuwe toegewezen persoon (optioneel)"
                        ),
                    },
                    "next_action": {
                        "type": "string",
                        "description": ("Nieuwe volgende actie (optioneel)"),
                    },
                    "next_action_date": {
                        "type": "string",
                        "description": (
                            "Nieuwe datum volgende actie"
                            " in YYYY-MM-DD formaat (optioneel)"
                        ),
                    },
                },
                "required": ["lead_id"],
            },
        },
    },
    "move_lead": {
        "type": "function",
        "function": {
            "name": "move_lead",
            "description": ("Verplaats een lead naar een andere stage in de funnel."),
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {
                        "type": "string",
                        "description": "UUID van de lead",
                    },
                    "stage": {
                        "type": "string",
                        "description": (
                            "Nieuwe stage: inbox, verkennen,"
                            " eerste_gesprek, interne_check,"
                            " follow_up, in_the_pocket, koelkast"
                        ),
                    },
                },
                "required": ["lead_id", "stage"],
            },
        },
    },
    "add_lead_activity": {
        "type": "function",
        "function": {
            "name": "add_lead_activity",
            "description": (
                "Voeg een activiteit (notitie, meeting,"
                " telefoongesprek, e-mail) toe aan een lead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {
                        "type": "string",
                        "description": "UUID van de lead",
                    },
                    "content": {
                        "type": "string",
                        "description": "Inhoud van de activiteit",
                    },
                    "activity_type": {
                        "type": "string",
                        "description": (
                            "Type: note, meeting, call, email (standaard: note)"
                        ),
                    },
                },
                "required": ["lead_id", "content"],
            },
        },
    },
}

ALL_TOOLS = list(_READ_TOOLS.values()) + list(_WRITE_TOOLS.values())
_WRITE_TOOL_NAMES = set(_WRITE_TOOLS.keys())


def _describe_action(tool_name: str, args: dict) -> str:
    """Generate a human-readable Dutch description of a tool call."""
    descriptions = {
        "create_node": lambda a: (
            f'Node "{a.get("title", "")}" ({a.get("node_type", "")}) aanmaken'
        ),
        "update_node": lambda a: f"Node {a.get('node_id', '')[:8]}... bijwerken",
        "create_edge": lambda a: f"Relatie '{a.get('edge_type_id', '')}' aanmaken",
        "create_task": lambda a: (
            f"{'Subtaak' if a.get('parent_task_id') else 'Taak'}"
            f' "{a.get("title", "")}" aanmaken'
        ),
        "update_task": lambda a: f"Taak {a.get('task_id', '')[:8]}... bijwerken",
        "add_tag_to_node": lambda a: f"Tag '{a.get('tag_name', '')}' koppelen aan node",
        "add_stakeholder": lambda a: (
            f"Stakeholder ({a.get('rol', '')}) koppelen aan node"
        ),
        "attach_to_bron": lambda a: (
            f"Chatbijlage koppelen aan bron {a.get('node_id', '')[:8]}..."
        ),
        "create_lead": lambda a: f'Lead "{a.get("title", "")}" aanmaken',
        "update_lead": lambda a: f"Lead {a.get('lead_id', '')[:8]}... bijwerken",
        "move_lead": lambda a: f"Lead verplaatsen naar {a.get('stage', '')}",
        "add_lead_activity": lambda a: (
            f"Activiteit ({a.get('activity_type', 'note')}) toevoegen aan lead"
        ),
    }
    fn = descriptions.get(tool_name)
    return fn(args) if fn else f"{tool_name} uitvoeren"


# ---------------------------------------------------------------------------
# Tool execution helpers
# ---------------------------------------------------------------------------


def _task_to_dict(task: object) -> dict:
    """Convert a Task ORM object to a serializable dict."""
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": getattr(task, "priority", None),
        "deadline": str(task.deadline) if task.deadline else None,
        "assignee": task.assignee.naam if getattr(task, "assignee", None) else None,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "node_id": str(task.node_id) if task.node_id else None,
    }


async def _execute_read_tool(
    tool_name: str,
    args: dict,
    db: AsyncSession,
    *,
    person_id: UUID | None = None,
) -> str:
    """Execute a read-only tool and return a JSON string result."""
    try:
        if tool_name == "search_nodes":
            from bouwmeester.repositories.search import SearchRepository

            repo = SearchRepository(db)
            query = args.get("query", "")
            node_type = args.get("node_type")
            results = await repo.full_text_search(
                query, result_types=["corpus_node"], limit=10
            )
            if node_type:
                results = [r for r in results if r.get("subtitle") == node_type]
            items = [
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "type": r.get("subtitle"),
                    "score": round(r.get("score", 0), 2),
                }
                for r in results[:10]
            ]
            return _safe_dumps({"results": items, "count": len(items)})

        elif tool_name == "get_node":
            from bouwmeester.repositories.corpus_node import CorpusNodeRepository

            repo = CorpusNodeRepository(db)
            node = await repo.get(UUID(args["node_id"]))
            if not node:
                return _safe_dumps({"error": "Node niet gevonden"})
            return _safe_dumps(
                {
                    "id": str(node.id),
                    "title": node.title,
                    "node_type": node.node_type,
                    "description": (node.description or "")[:500],
                    "status": node.status,
                },
            )

        elif tool_name == "get_node_neighbors":
            from bouwmeester.repositories.corpus_node import CorpusNodeRepository

            repo = CorpusNodeRepository(db)
            data = await repo.get_neighbors(UUID(args["node_id"]))
            if not data.get("node"):
                return _safe_dumps({"error": "Node niet gevonden"})
            neighbors = [
                {
                    "node_id": str(n["node"].id),
                    "title": n["node"].title,
                    "node_type": n["node"].node_type,
                    "edge_type": n["edge"].edge_type_id,
                }
                for n in data.get("neighbors", [])
            ]
            return _safe_dumps({"neighbors": neighbors, "count": len(neighbors)})

        elif tool_name == "get_tasks_for_node":
            from bouwmeester.repositories.task import TaskRepository

            repo = TaskRepository(db)
            org_ctx = await _build_chat_org_context(db, person_id)
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            tasks = await repo.get_by_node(
                UUID(args["node_id"]), limit=20, org_ctx=org_ctx, init_ctx=init_ctx
            )
            items = [_task_to_dict(t) for t in tasks]
            return _safe_dumps({"tasks": items, "count": len(items)})

        elif tool_name == "get_tasks_for_person":
            from bouwmeester.repositories.task import TaskRepository

            repo = TaskRepository(db)
            org_ctx = await _build_chat_org_context(db, person_id)
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            tasks = await repo.get_by_assignee(
                UUID(args["person_id"]), limit=20, org_ctx=org_ctx, init_ctx=init_ctx
            )
            items = [_task_to_dict(t) for t in tasks]
            return _safe_dumps({"tasks": items, "count": len(items)})

        elif tool_name == "get_overdue_tasks":
            from bouwmeester.repositories.task import TaskRepository

            repo = TaskRepository(db)
            org_ctx = await _build_chat_org_context(db, person_id)
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            assignee_id = UUID(args["assignee_id"]) if args.get("assignee_id") else None
            tasks = await repo.get_overdue(
                assignee_id=assignee_id, org_ctx=org_ctx, init_ctx=init_ctx
            )
            items = [_task_to_dict(t) for t in tasks[:20]]
            return _safe_dumps({"tasks": items, "count": len(items)})

        elif tool_name == "list_tags":
            from bouwmeester.repositories.tag import TagRepository

            repo = TagRepository(db)
            tags = await repo.get_all()
            tag_names = [t.name for t in tags[:100]]
            return _safe_dumps({"tags": tag_names, "count": len(tag_names)})

        elif tool_name == "list_edge_types":
            from bouwmeester.repositories.edge_type import EdgeTypeRepository

            repo = EdgeTypeRepository(db)
            types = await repo.get_all()
            type_ids = [t.id for t in types]
            return _safe_dumps({"edge_types": type_ids})

        elif tool_name == "search_people":
            from bouwmeester.repositories.person import PersonRepository

            repo = PersonRepository(db)
            people = await repo.search(args.get("query", ""), limit=10)
            items = [{"id": str(p.id), "naam": p.naam} for p in people]
            return _safe_dumps({"results": items, "count": len(items)})

        elif tool_name == "search_organisatie":
            from bouwmeester.repositories.organisatie_eenheid import (
                OrganisatieEenheidRepository,
            )

            repo = OrganisatieEenheidRepository(db)
            units = await repo.search(args.get("query", ""), limit=10)
            items = [
                {
                    "id": str(u.id),
                    "naam": u.naam,
                    "type": u.type,
                }
                for u in units
            ]
            return _safe_dumps({"results": items, "count": len(items)})

        elif tool_name == "get_organisatie":
            from bouwmeester.repositories.organisatie_eenheid import (
                OrganisatieEenheidRepository,
            )

            repo = OrganisatieEenheidRepository(db)
            unit = await repo.get(UUID(args["organisatie_id"]))
            if not unit:
                return _safe_dumps({"error": "Organisatie-eenheid niet gevonden"})
            personen = await repo.get_personen(unit.id)
            manager = await repo.get_unit_manager(unit.id)
            return _safe_dumps(
                {
                    "id": str(unit.id),
                    "naam": unit.naam,
                    "type": unit.type,
                    "manager": manager.naam if manager else None,
                    "manager_id": str(manager.id) if manager else None,
                    "parent_id": str(unit.parent_id) if unit.parent_id else None,
                    "medewerkers": [
                        {"id": str(p.id), "naam": p.naam} for p in personen[:20]
                    ],
                    "aantal_medewerkers": len(personen),
                },
            )

        elif tool_name == "get_person_summary":
            from sqlalchemy import select as sa_select

            from bouwmeester.models.organisatie_eenheid import (
                OrganisatieEenheid,
            )
            from bouwmeester.models.person_organisatie import (
                PersonOrganisatieEenheid,
            )
            from bouwmeester.repositories.person import PersonRepository
            from bouwmeester.repositories.task import TaskRepository

            person_repo = PersonRepository(db)
            person = await person_repo.get(UUID(args["person_id"]))
            if not person:
                return _safe_dumps({"error": "Persoon niet gevonden"})

            task_repo = TaskRepository(db)
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            tasks = await task_repo.get_by_assignee(
                person.id, limit=10, init_ctx=init_ctx
            )
            open_tasks = [t for t in tasks if t.status not in ("done", "cancelled")]

            # Find current org unit via active placement
            org_name = None
            org_id = None
            stmt = (
                sa_select(OrganisatieEenheid)
                .join(PersonOrganisatieEenheid)
                .where(
                    PersonOrganisatieEenheid.person_id == person.id,
                    PersonOrganisatieEenheid.eind_datum.is_(None),
                )
                .limit(1)
            )
            org_result = await db.execute(stmt)
            org_unit = org_result.scalar_one_or_none()
            if org_unit:
                org_name = org_unit.naam
                org_id = str(org_unit.id)

            result = {
                "id": str(person.id),
                "naam": person.naam,
                "organisatie_eenheid": org_name,
                "organisatie_eenheid_id": org_id,
                "open_taken": [_task_to_dict(t) for t in open_tasks[:5]],
                "aantal_open_taken": len(open_tasks),
            }
            return _safe_dumps(result)

        elif tool_name == "find_path":
            from bouwmeester.repositories.graph import GraphRepository

            repo = GraphRepository(db)
            path = await repo.find_path(
                UUID(args["from_node_id"]), UUID(args["to_node_id"])
            )
            if not path:
                return _safe_dumps(
                    {"path": [], "message": "Geen pad gevonden tussen deze nodes"}
                )
            steps = [
                {
                    "node_id": str(step.get("node_id", "")),
                    "title": step.get("node_title", ""),
                    "node_type": step.get("node_type", ""),
                    "edge_type": step.get("edge_type_id"),
                }
                for step in path
            ]
            return _safe_dumps({"path": steps, "length": len(steps)})

        elif tool_name == "find_similar_nodes":
            from bouwmeester.repositories.search import SearchRepository

            repo = SearchRepository(db)
            results = await repo.find_similar_nodes(
                title=args["title"],
                description=args.get("description"),
                limit=5,
            )
            items = [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "node_type": r["node_type"],
                    "similarity": r.get("similarity", 0),
                }
                for r in results
            ]
            return _safe_dumps({"results": items, "count": len(items)})

        elif tool_name == "list_opdrachten":
            from bouwmeester.repositories.opdracht import OpdrachtRepository

            repo = OpdrachtRepository(db)
            org_ctx = await _build_chat_org_context(db, person_id)
            opdrachten = await repo.get_all(
                limit=15,
                begrotingsjaar=args.get("begrotingsjaar"),
                status=args.get("status"),
                type=args.get("type"),
                org_ctx=org_ctx,
            )
            items = [
                {
                    "id": str(o.id),
                    "titel": o.titel,
                    "type": o.type,
                    "status": o.status,
                    "begrotingsjaar": o.begrotingsjaar,
                    "budget": str(o.budget) if o.budget else None,
                    "gerealiseerd": str(o.gerealiseerd) if o.gerealiseerd else None,
                }
                for o in opdrachten
            ]
            return _safe_dumps({"opdrachten": items, "count": len(items)})

        elif tool_name == "get_opdracht":
            from bouwmeester.repositories.opdracht import OpdrachtRepository

            repo = OpdrachtRepository(db)
            org_ctx = await _build_chat_org_context(db, person_id)
            opdracht_id = UUID(args["opdracht_id"])
            o = await repo.get(opdracht_id)
            if not o:
                return _safe_dumps({"error": "Opdracht niet gevonden"})
            # Respect org-context: hide opdrachten from invisible eenheden.
            if not org_ctx.is_admin and o.opdrachtgever_id is not None:
                visible = set(org_ctx.visible_eenheid_ids) | set(
                    org_ctx.shared_eenheid_ids
                )
                if o.opdrachtgever_id not in visible:
                    return _safe_dumps({"error": "Geen toegang tot deze opdracht"})
            return _safe_dumps(
                {
                    "id": str(o.id),
                    "titel": o.titel,
                    "type": o.type,
                    "status": o.status,
                    "begrotingsjaar": o.begrotingsjaar,
                    "budget": str(o.budget) if o.budget else None,
                    "gerealiseerd": str(o.gerealiseerd) if o.gerealiseerd else None,
                    "beschrijving": (o.beschrijving or "")[:300],
                    "verantwoordelijke": (
                        o.verantwoordelijke.naam
                        if getattr(o, "verantwoordelijke", None)
                        else None
                    ),
                    "verantwoordelijke_id": (
                        str(o.verantwoordelijke_id) if o.verantwoordelijke_id else None
                    ),
                    "instrument_id": str(o.instrument_id) if o.instrument_id else None,
                },
            )

        elif tool_name == "get_recent_activity":
            from bouwmeester.repositories.activity import ActivityRepository

            repo = ActivityRepository(db)
            limit = min(int(args.get("limit", 10)), 20)
            activities = await repo.get_recent(limit=limit)
            items = [
                {
                    "event_type": a.event_type,
                    "actor": a.actor.naam if getattr(a, "actor", None) else None,
                    "node_id": str(a.node_id) if a.node_id else None,
                    "task_id": str(a.task_id) if a.task_id else None,
                    "details": a.details if a.details else None,
                    "timestamp": a.created_at.isoformat() if a.created_at else None,
                }
                for a in activities
            ]
            return _safe_dumps({"activities": items, "count": len(items)})

        elif tool_name == "list_parlementair":
            from bouwmeester.repositories.parlementair_item import (
                ParlementairItemRepository,
            )

            repo = ParlementairItemRepository(db)
            items_raw = await repo.get_all(
                search=args.get("search"),
                item_type=args.get("item_type"),
                status=args.get("status"),
                limit=10,
            )
            items = [
                {
                    "id": str(pi.id),
                    "titel": pi.titel,
                    "type": pi.type,
                    "status": pi.status,
                    "onderwerp": (pi.onderwerp or "")[:200],
                }
                for pi in items_raw
            ]
            return _safe_dumps({"items": items, "count": len(items)})

        elif tool_name == "search_leads":
            from bouwmeester.repositories.lead import LeadRepository
            from bouwmeester.schema.lead import LeadStage

            init_ctx = await _build_chat_initiatief_context(db, person_id)
            repo = LeadRepository(db)

            # Text search via find_similar if query provided
            query = args.get("query")
            if query:
                leads = await repo.find_similar(
                    title=query,
                    organization=query,
                    init_ctx=init_ctx,
                )
            else:
                stage = None
                if args.get("stage"):
                    try:
                        stage = LeadStage(args["stage"])
                    except ValueError:
                        pass
                assignee_id_val = (
                    UUID(args["assignee_id"]) if args.get("assignee_id") else None
                )
                leads = await repo.get_all(
                    limit=15,
                    stage=stage,
                    assignee_id=assignee_id_val,
                    next_action_filter=args.get("next_action_filter"),
                    init_ctx=init_ctx,
                )
            items = [
                {
                    "id": str(lead.id),
                    "title": lead.title,
                    "organization": lead.organization,
                    "stage": lead.stage,
                    "assignee": (lead.assignee.naam if lead.assignee else None),
                    "assignee_id": (
                        str(lead.assignee_id) if lead.assignee_id else None
                    ),
                    "next_action": lead.next_action,
                    "next_action_date": (
                        str(lead.next_action_date) if lead.next_action_date else None
                    ),
                    "tags": (
                        [lt.tag.name for lt in lead.lead_tags if lt.tag]
                        if lead.lead_tags
                        else []
                    ),
                    "created_at": lead.created_at.isoformat(),
                }
                for lead in leads
            ]
            return _safe_dumps({"leads": items, "count": len(items)})

        elif tool_name == "get_lead":
            from bouwmeester.repositories.lead import LeadRepository

            init_ctx = await _build_chat_initiatief_context(db, person_id)
            repo = LeadRepository(db)
            lead = await repo.get_detail(UUID(args["lead_id"]), init_ctx=init_ctx)
            if not lead:
                return _safe_dumps({"error": "Lead niet gevonden"})
            activities = [
                {
                    "id": str(a.id),
                    "content": a.content[:300],
                    "activity_type": a.activity_type,
                    "author": (a.author.naam if a.author else None),
                    "created_at": a.created_at.isoformat(),
                }
                for a in (lead.activities or [])[:10]
            ]
            contacts = [
                {
                    "person_naam": (c.person.naam if c.person else ""),
                    "person_id": str(c.person_id),
                    "rol": c.rol,
                }
                for c in (lead.contacts or [])
            ]
            return _safe_dumps(
                {
                    "id": str(lead.id),
                    "title": lead.title,
                    "description": (lead.description or "")[:500],
                    "organization": lead.organization,
                    "stage": lead.stage,
                    "assignee": (lead.assignee.naam if lead.assignee else None),
                    "assignee_id": (
                        str(lead.assignee_id) if lead.assignee_id else None
                    ),
                    "next_action": lead.next_action,
                    "next_action_date": (
                        str(lead.next_action_date) if lead.next_action_date else None
                    ),
                    "tags": (
                        [lt.tag.name for lt in lead.lead_tags if lt.tag]
                        if lead.lead_tags
                        else []
                    ),
                    "contacts": contacts,
                    "activities": activities,
                    "created_at": lead.created_at.isoformat(),
                },
            )

        elif tool_name == "get_lead_metrics":
            from bouwmeester.repositories.lead import LeadRepository

            init_ctx = await _build_chat_initiatief_context(db, person_id)
            repo = LeadRepository(db)
            metrics = await repo.get_metrics(init_ctx=init_ctx)
            return _safe_dumps(metrics)

        return _safe_dumps({"error": f"Onbekende tool: {tool_name}"})
    except ValueError:
        return _safe_dumps({"error": "Ongeldig ID-formaat. Gebruik een geldig UUID."})
    except Exception:
        logger.exception("Error executing read tool %s", tool_name)
        return _safe_dumps(
            {"error": "Er is een fout opgetreden bij het ophalen van data."}
        )


async def _resolve_person_org_eenheid(
    db: AsyncSession, person_id: UUID | None
) -> UUID | None:
    """Find the active organisatie_eenheid_id for a person."""
    if not person_id:
        return None
    from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
    from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid

    stmt = (
        select(OrganisatieEenheid.id)
        .join(PersonOrganisatieEenheid)
        .where(
            PersonOrganisatieEenheid.person_id == person_id,
            PersonOrganisatieEenheid.eind_datum.is_(None),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row if row else None


@dataclass
class _ChatAccess:
    """Who the chat acts for, with contexts built at most once per session."""

    person: "Person | None"
    perm_ctx: "PermissionContext"
    org_ctx: "OrgContext | None" = None
    init_ctx: "InitiatiefContext | None" = None


async def _chat_access(db: AsyncSession, person_id: UUID | None) -> _ChatAccess:
    """Resolve the chat user once per database session (one per request)."""
    from bouwmeester.core.permissions import (
        anonymous_permission_context,
        build_permission_context,
    )
    from bouwmeester.models.person import Person

    key = ("chat_access", person_id)
    access = db.info.get(key)
    if access is None:
        person = await db.get(Person, person_id) if person_id else None
        perm_ctx = (
            await build_permission_context(db, person)
            if person is not None
            else anonymous_permission_context()
        )
        access = db.info[key] = _ChatAccess(person=person, perm_ctx=perm_ctx)
    return access


async def _build_chat_org_context(
    db: AsyncSession, person_id: UUID | None
) -> "OrgContext":
    """OrgContext for the chat user (dev mode: everything, anonymous: nothing)."""
    from bouwmeester.core.org_context import build_org_context

    access = await _chat_access(db, person_id)
    if access.org_ctx is None:
        access.org_ctx = await build_org_context(
            db, access.person, perm_ctx=access.perm_ctx
        )
    return access.org_ctx


async def _build_chat_initiatief_context(
    db: AsyncSession, person_id: UUID | None
) -> "InitiatiefContext":
    """InitiatiefContext for the chat user (lead access), same rules."""
    from bouwmeester.core.initiatief_context import build_initiatief_context

    access = await _chat_access(db, person_id)
    if access.init_ctx is None:
        access.init_ctx = await build_initiatief_context(
            db, access.person, perm_ctx=access.perm_ctx
        )
    return access.init_ctx


# Each write tool stands in for a REST route and must pass that route's
# checks: its permission, plus org scope on every resource the tool touches
# (``(resource_type, argument name)``; an absent optional argument is
# skipped).  Lead tools are scoped through the initiatief context inside the
# tool itself, as the lead routes are.  Granting a stakeholder role goes
# through the same authority check as the REST routes.
_WRITE_TOOL_POLICY: dict[str, tuple[str | None, tuple[tuple[str, str], ...]]] = {
    "create_node": ("node:create", ()),
    "update_node": ("node:update", (("corpus_node", "node_id"),)),
    "create_edge": (
        "edge:create",
        (("corpus_node", "from_node_id"), ("corpus_node", "to_node_id")),
    ),
    "create_task": (
        "task:create",
        (("corpus_node", "node_id"), ("task", "parent_task_id")),
    ),
    "update_task": ("task:update", (("task", "task_id"),)),
    "add_tag_to_node": ("tag:create", (("corpus_node", "node_id"),)),
    "add_stakeholder": (None, ()),
    "attach_to_bron": ("node:update", (("corpus_node", "node_id"),)),
    "create_lead": (None, ()),
    "update_lead": (None, ()),
    "move_lead": (None, ()),
    "add_lead_activity": (None, ()),
}


async def _authorize_write_tool(
    tool_name: str,
    args: dict,
    db: AsyncSession,
    person_id: UUID | None,
) -> str | None:
    """Return a refusal message, or ``None`` when the user may run the tool."""
    from fastapi import HTTPException

    from bouwmeester.core.authority import require_can_grant_resource_role
    from bouwmeester.core.org_context import check_resource_org_scope

    policy = _WRITE_TOOL_POLICY.get(tool_name)
    if policy is None:
        return f"Onbekende tool: {tool_name}"
    perm, targets = policy

    access = await _chat_access(db, person_id)
    perm_ctx = access.perm_ctx
    if not perm_ctx.is_authenticated:
        return "Niet ingelogd"
    if perm is not None and not perm_ctx.has_permission(perm):
        return "Je hebt geen rechten voor deze actie."
    try:
        if targets:
            org_ctx = await _build_chat_org_context(db, person_id)
            for resource_type, arg in targets:
                if args.get(arg):
                    await check_resource_org_scope(
                        db, resource_type, UUID(args[arg]), org_ctx
                    )
        if tool_name == "add_stakeholder":
            await require_can_grant_resource_role(
                db,
                perm_ctx,
                resource_type="corpus_node",
                resource_id=UUID(args["node_id"]),
                rol=args.get("rol", ""),
                target_person_id=UUID(args["person_id"]),
            )
    except HTTPException as exc:
        return str(exc.detail)
    return None


async def _execute_write_tool(
    tool_name: str,
    args: dict,
    db: AsyncSession,
    *,
    person_id: UUID | None = None,
) -> dict:
    """Execute a write tool. Returns { success, summary, entity_id, entity_type }."""
    try:
        refusal = await _authorize_write_tool(tool_name, args, db, person_id)
        if refusal is not None:
            return {"success": False, "summary": refusal}

        if tool_name == "create_node":
            from bouwmeester.repositories.corpus_node import CorpusNodeRepository
            from bouwmeester.schema.corpus_node import CorpusNodeCreate

            repo = CorpusNodeRepository(db)
            data = CorpusNodeCreate(
                title=args["title"],
                node_type=args["node_type"],
                description=args.get("description"),
            )
            node = await repo.create(data)
            await db.commit()
            return {
                "success": True,
                "summary": f'Node "{node.title}" ({node.node_type}) aangemaakt',
                "entity_id": str(node.id),
                "entity_type": "node",
            }

        elif tool_name == "update_node":
            from bouwmeester.repositories.corpus_node import CorpusNodeRepository
            from bouwmeester.schema.corpus_node import CorpusNodeUpdate

            repo = CorpusNodeRepository(db)
            update_data: dict = {}
            if "title" in args:
                update_data["title"] = args["title"]
            if "description" in args:
                update_data["description"] = args["description"]
            data = CorpusNodeUpdate(**update_data)
            node = await repo.update(UUID(args["node_id"]), data)
            if not node:
                return {"success": False, "summary": "Node niet gevonden"}
            await db.commit()
            return {
                "success": True,
                "summary": f'Node "{node.title}" bijgewerkt',
                "entity_id": str(node.id),
                "entity_type": "node",
            }

        elif tool_name == "create_edge":
            from bouwmeester.models.edge import Edge
            from bouwmeester.repositories.corpus_node import (
                CorpusNodeRepository,
            )

            node_repo = CorpusNodeRepository(db)

            from_node = await node_repo.get(UUID(args["from_node_id"]))
            if not from_node:
                return {
                    "success": False,
                    "summary": "Bron-node niet gevonden.",
                }

            to_node = await node_repo.get(UUID(args["to_node_id"]))
            if not to_node:
                return {
                    "success": False,
                    "summary": "Doel-node niet gevonden.",
                }

            edge = Edge(
                from_node_id=from_node.id,
                to_node_id=to_node.id,
                edge_type_id=args["edge_type_id"],
                description=args.get("description"),
            )
            db.add(edge)
            await db.flush()
            await db.commit()
            return {
                "success": True,
                "summary": f"Relatie '{edge.edge_type_id}' aangemaakt",
                "entity_id": str(edge.id),
                "entity_type": "edge",
            }

        elif tool_name == "create_task":
            from bouwmeester.repositories.corpus_node import CorpusNodeRepository
            from bouwmeester.repositories.person import PersonRepository
            from bouwmeester.repositories.task import TaskRepository
            from bouwmeester.schema.task import TaskCreate

            # Validate node exists
            node_repo = CorpusNodeRepository(db)
            node = await node_repo.get(UUID(args["node_id"]))
            if not node:
                return {
                    "success": False,
                    "summary": "Node niet gevonden",
                }

            # Validate assignee exists if provided
            if args.get("assignee_id"):
                person_repo = PersonRepository(db)
                person = await person_repo.get(UUID(args["assignee_id"]))
                if not person:
                    return {
                        "success": False,
                        "summary": (
                            "Persoon niet gevonden."
                            " Gebruik search_people om"
                            " de juiste persoon te vinden."
                        ),
                    }

            # Validate parent task exists if provided
            if args.get("parent_task_id"):
                parent_repo = TaskRepository(db)
                parent_task = await parent_repo.get(UUID(args["parent_task_id"]))
                if not parent_task:
                    return {
                        "success": False,
                        "summary": (
                            "Bovenliggende taak niet"
                            " gevonden. Gebruik"
                            " get_tasks_for_node om de"
                            " juiste taak te vinden."
                        ),
                    }

            repo = TaskRepository(db)
            task_data: dict = {
                "title": args["title"],
                "node_id": UUID(args["node_id"]),
                "description": args.get("description"),
                "priority": args.get("priority", "normaal"),
                "status": "open",
            }
            if args.get("assignee_id"):
                task_data["assignee_id"] = UUID(args["assignee_id"])
            if args.get("parent_task_id"):
                task_data["parent_id"] = UUID(args["parent_task_id"])
            data = TaskCreate(**task_data)
            task = await repo.create(data)
            await db.commit()
            is_subtask = bool(args.get("parent_task_id"))
            label = "Subtaak" if is_subtask else "Taak"
            return {
                "success": True,
                "summary": f'{label} "{task.title}" aangemaakt',
                "entity_id": str(task.id),
                "entity_type": "task",
            }

        elif tool_name == "update_task":
            from bouwmeester.repositories.task import TaskRepository
            from bouwmeester.schema.task import TaskUpdate

            repo = TaskRepository(db)
            update_data = {}
            for field in ("title", "description", "status", "priority"):
                if field in args and args[field] is not None:
                    update_data[field] = args[field]
            data = TaskUpdate(**update_data)
            task = await repo.update(UUID(args["task_id"]), data)
            if not task:
                return {"success": False, "summary": "Taak niet gevonden"}
            await db.commit()
            return {
                "success": True,
                "summary": f'Taak "{task.title}" bijgewerkt',
                "entity_id": str(task.id),
                "entity_type": "task",
            }

        elif tool_name == "add_tag_to_node":
            from bouwmeester.models.tag import NodeTag
            from bouwmeester.repositories.corpus_node import (
                CorpusNodeRepository,
            )
            from bouwmeester.repositories.tag import TagRepository

            node_repo = CorpusNodeRepository(db)
            node = await node_repo.get(UUID(args["node_id"]))
            if not node:
                return {
                    "success": False,
                    "summary": "Node niet gevonden.",
                }

            tag_repo = TagRepository(db)
            tag = await tag_repo.get_by_name(args["tag_name"])
            if not tag:
                return {
                    "success": False,
                    "summary": (
                        f"Tag '{args['tag_name']}'"
                        " niet gevonden."
                        " Gebruik list_tags om"
                        " beschikbare tags te zien."
                    ),
                }
            node_tag = NodeTag(node_id=node.id, tag_id=tag.id)
            db.add(node_tag)
            await db.flush()
            await db.commit()
            return {
                "success": True,
                "summary": f"Tag '{tag.name}' gekoppeld aan node",
                "entity_id": args["node_id"],
                "entity_type": "tag",
            }

        elif tool_name == "add_stakeholder":
            from bouwmeester.repositories.corpus_node import (
                CorpusNodeRepository,
            )
            from bouwmeester.repositories.person import PersonRepository
            from bouwmeester.repositories.resource_permission import (
                ResourcePermissionRepository,
            )

            node_repo = CorpusNodeRepository(db)
            node = await node_repo.get(UUID(args["node_id"]))
            if not node:
                return {
                    "success": False,
                    "summary": "Node niet gevonden.",
                }

            person_repo = PersonRepository(db)
            person = await person_repo.get(UUID(args["person_id"]))
            if not person:
                return {
                    "success": False,
                    "summary": (
                        "Persoon niet gevonden."
                        " Gebruik search_people om"
                        " de juiste persoon te vinden."
                    ),
                }

            repo = ResourcePermissionRepository(db)
            await repo.create_permission(
                person_id=person.id,
                resource_type="corpus_node",
                resource_id=node.id,
                rol=args["rol"],
            )
            await db.commit()
            return {
                "success": True,
                "summary": f"Stakeholder ({args['rol']}) gekoppeld aan node",
                "entity_id": args["node_id"],
                "entity_type": "node",
            }

        elif tool_name == "attach_to_bron":
            from bouwmeester.core.storage import (
                BRON_ALLOWED_CONTENT_TYPES,
                chat_key,
                read_blob,
                store_upload,
            )
            from bouwmeester.models.bron import Bron
            from bouwmeester.models.bron_bijlage import BronBijlage

            # Load chat attachment (scoped to current user)
            att_id = UUID(args["attachment_id"])
            stmt = select(ChatAttachment).where(ChatAttachment.id == att_id)
            if person_id:
                stmt = stmt.where(
                    ChatAttachment.person_id.in_([person_id])
                    | ChatAttachment.person_id.is_(None)
                )
            else:
                stmt = stmt.where(ChatAttachment.person_id.is_(None))
            result = await db.execute(stmt)
            att = result.scalar_one_or_none()
            if not att:
                return {
                    "success": False,
                    "summary": "Chat-bijlage niet gevonden.",
                }

            # Validate content type against bron allowlist
            if att.content_type not in BRON_ALLOWED_CONTENT_TYPES:
                return {
                    "success": False,
                    "summary": (
                        f"Bestandstype '{att.content_type}' is niet"
                        " toegestaan als bron-bijlage."
                        " Toegestaan: PDF, Word, ODT, TXT, PNG, JPEG."
                    ),
                }

            # Load bron node
            node_id = UUID(args["node_id"])
            bron_stmt = select(Bron).where(Bron.id == node_id)
            bron_result = await db.execute(bron_stmt)
            bron = bron_result.scalar_one_or_none()
            if not bron:
                return {
                    "success": False,
                    "summary": (
                        "Bron-node niet gevonden."
                        " Controleer of de node van type 'bron' is."
                    ),
                }

            # Check if bron already has an attachment
            existing_stmt = select(BronBijlage).where(BronBijlage.bron_id == node_id)
            existing_result = await db.execute(existing_stmt)
            if existing_result.scalar_one_or_none():
                return {
                    "success": False,
                    "summary": (
                        "Deze bron heeft al een bijlage."
                        " Verwijder eerst de bestaande bijlage."
                    ),
                }

            data = await read_blob(chat_key(att.pad))
            if data is None:
                return {
                    "success": False,
                    "summary": "Bronbestand niet gevonden.",
                }

            _, relative_path = await store_upload(
                data,
                att.bestandsnaam,
                item_id=node_id,
                content_type=att.content_type,
            )
            bijlage = BronBijlage(
                bron_id=node_id,
                bestandsnaam=att.bestandsnaam,
                content_type=att.content_type,
                bestandsgrootte=att.bestandsgrootte,
                pad=relative_path,
            )
            db.add(bijlage)
            await db.commit()
            return {
                "success": True,
                "summary": (
                    f'Bestand "{att.bestandsnaam}" gekoppeld als bijlage aan bron'
                ),
                "entity_id": str(node_id),
                "entity_type": "node",
            }

        elif tool_name == "create_lead":
            from bouwmeester.repositories.lead import LeadRepository
            from bouwmeester.schema.lead import LeadCreate, LeadStage

            # Resolve user's org unit for the lead
            org_eenheid_id = await _resolve_person_org_eenheid(db, person_id)
            if not org_eenheid_id:
                return {
                    "success": False,
                    "summary": (
                        "Kan geen lead aanmaken:"
                        " geen organisatie-eenheid gevonden"
                        " voor de ingelogde gebruiker."
                    ),
                }

            lead_data: dict = {
                "title": args["title"],
                "organisatie_eenheid_id": org_eenheid_id,
            }
            if args.get("description"):
                lead_data["description"] = args["description"]
            if args.get("organization"):
                lead_data["organization"] = args["organization"]
            if args.get("stage"):
                try:
                    lead_data["stage"] = LeadStage(args["stage"])
                except ValueError:
                    pass
            if args.get("assignee_id"):
                lead_data["assignee_id"] = UUID(args["assignee_id"])
            if args.get("next_action"):
                lead_data["next_action"] = args["next_action"]
            if args.get("next_action_date"):
                try:
                    lead_data["next_action_date"] = date.fromisoformat(
                        args["next_action_date"]
                    )
                except ValueError:
                    return {
                        "success": False,
                        "summary": (
                            "Ongeldig datumformaat voor next_action_date."
                            " Gebruik YYYY-MM-DD."
                        ),
                    }

            repo = LeadRepository(db)
            data = LeadCreate(**lead_data)
            lead = await repo.create(data, author_id=person_id)
            await db.commit()
            return {
                "success": True,
                "summary": f'Lead "{lead.title}" aangemaakt',
                "entity_id": str(lead.id),
                "entity_type": "lead",
            }

        elif tool_name == "update_lead":
            from bouwmeester.repositories.lead import LeadRepository
            from bouwmeester.schema.lead import LeadUpdate

            # Verify access via org context
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            repo = LeadRepository(db)
            existing = await repo.get(UUID(args["lead_id"]), init_ctx=init_ctx)
            if not existing:
                return {"success": False, "summary": "Lead niet gevonden"}

            update_data: dict = {}
            # Allow clearing text fields by passing empty string or null
            for field in (
                "title",
                "description",
                "organization",
                "next_action",
            ):
                if field in args:
                    val = args[field]
                    # Allow explicit null/empty to clear a field,
                    # but title cannot be empty
                    if field == "title" and not val:
                        continue
                    update_data[field] = val if val else None
            if "assignee_id" in args:
                val = args["assignee_id"]
                update_data["assignee_id"] = UUID(val) if val else None
            if "next_action_date" in args:
                val = args["next_action_date"]
                if val:
                    try:
                        update_data["next_action_date"] = date.fromisoformat(val)
                    except ValueError:
                        return {
                            "success": False,
                            "summary": (
                                "Ongeldig datumformaat voor next_action_date."
                                " Gebruik YYYY-MM-DD."
                            ),
                        }
                else:
                    update_data["next_action_date"] = None
            data = LeadUpdate(**update_data)
            lead = await repo.update(UUID(args["lead_id"]), data)
            if not lead:
                return {"success": False, "summary": "Lead niet gevonden"}
            await db.commit()
            return {
                "success": True,
                "summary": f'Lead "{lead.title}" bijgewerkt',
                "entity_id": str(lead.id),
                "entity_type": "lead",
            }

        elif tool_name == "move_lead":
            from bouwmeester.repositories.lead import LeadRepository
            from bouwmeester.schema.lead import LeadStage

            # Verify access via org context
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            repo = LeadRepository(db)
            existing = await repo.get(UUID(args["lead_id"]), init_ctx=init_ctx)
            if not existing:
                return {"success": False, "summary": "Lead niet gevonden"}

            try:
                stage = LeadStage(args["stage"])
            except ValueError:
                return {
                    "success": False,
                    "summary": f"Onbekende stage: {args['stage']}",
                }
            lead = await repo.move(
                UUID(args["lead_id"]),
                stage,
                author_id=person_id,
            )
            if not lead:
                return {"success": False, "summary": "Lead niet gevonden"}
            await db.commit()
            return {
                "success": True,
                "summary": (f'Lead "{lead.title}" verplaatst naar {stage}'),
                "entity_id": str(lead.id),
                "entity_type": "lead",
            }

        elif tool_name == "add_lead_activity":
            from bouwmeester.repositories.lead import LeadRepository
            from bouwmeester.repositories.lead_activity import (
                LeadActivityRepository,
            )
            from bouwmeester.schema.lead import LeadActivityCreate

            # Verify lead exists and user has access
            init_ctx = await _build_chat_initiatief_context(db, person_id)
            lead_repo = LeadRepository(db)
            lead = await lead_repo.get(UUID(args["lead_id"]), init_ctx=init_ctx)
            if not lead:
                return {"success": False, "summary": "Lead niet gevonden"}

            act_repo = LeadActivityRepository(db)
            act_data = LeadActivityCreate(
                content=args["content"],
                activity_type=args.get("activity_type", "note"),
            )
            activity = await act_repo.create(
                lead_id=UUID(args["lead_id"]),
                data=act_data,
                author_id=person_id,
            )
            await db.commit()
            return {
                "success": True,
                "summary": (
                    f"Activiteit ({activity.activity_type}) toegevoegd aan lead"
                ),
                "entity_id": str(lead.id),
                "entity_type": "lead",
            }

        return {"success": False, "summary": f"Onbekende tool: {tool_name}"}
    except ValueError:
        return {
            "success": False,
            "summary": "Ongeldig ID-formaat. Gebruik een geldig UUID.",
        }
    except Exception:
        logger.exception("Error executing write tool %s", tool_name)
        await db.rollback()
        return {
            "success": False,
            "summary": (
                "Er is een fout opgetreden bij het"
                " uitvoeren van deze actie."
                " Probeer het opnieuw."
            ),
        }


# ---------------------------------------------------------------------------
# Main chat orchestration
# ---------------------------------------------------------------------------


def _truncate_messages(messages: list[dict], max_messages: int) -> list[dict]:
    """Keep the system message + the most recent messages within the limit.

    This prevents the LLM context window from being exceeded in long
    conversations.  The system prompt (index 0) is always preserved.
    """
    if len(messages) <= max_messages:
        return messages
    # Always keep the system message, then take the tail
    return [messages[0]] + messages[-(max_messages - 1) :]


class ChatService:
    """Orchestrates multi-turn chat with tool calling.

    Conversations are persisted in the ``chat_conversation`` table and
    scoped to the authenticated user (``person_id``).
    """

    def __init__(
        self,
        llm: BaseLLMService,
        db: AsyncSession,
        person_id: UUID | None = None,
    ) -> None:
        self._llm = llm
        self._db = db
        self._person_id = person_id

    # -- DB helpers ----------------------------------------------------------

    async def _load_conversation(self, conversation_id: str) -> ChatConversation | None:
        """Load a conversation owned by the current user."""
        stmt = select(ChatConversation).where(
            ChatConversation.id == UUID(conversation_id),
            ChatConversation.person_id == self._person_id,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_conversation(self) -> ChatConversation:
        """Create a new conversation for the current user."""
        conv = ChatConversation(
            messages=[{"role": "system", "content": CHAT_SYSTEM_PROMPT}],
            pending_actions={},
            person_id=self._person_id,
        )
        self._db.add(conv)
        await self._db.flush()
        return conv

    async def _save_conversation(self, conv: ChatConversation) -> None:
        """Persist conversation state to DB."""
        # Mark JSONB columns as modified so SQLAlchemy picks up in-place changes
        flag_modified(conv, "messages")
        flag_modified(conv, "pending_actions")
        await self._db.commit()

    async def _get_user_context(self) -> str | None:
        """Build context string about the current user (name, org, function)."""
        if not self._person_id:
            return None
        from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
        from bouwmeester.models.person import Person
        from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid

        result = await self._db.execute(
            select(Person).where(Person.id == self._person_id)
        )
        person = result.scalar_one_or_none()
        if not person:
            return None

        parts = [f"Ingelogde gebruiker: {person.naam} (ID: {self._person_id})"]
        if person.functie:
            parts.append(f"Functie: {person.functie}")

        # Current org unit + full hierarchy (walk up the tree)
        org_stmt = (
            select(OrganisatieEenheid)
            .join(PersonOrganisatieEenheid)
            .where(
                PersonOrganisatieEenheid.person_id == self._person_id,
                PersonOrganisatieEenheid.eind_datum.is_(None),
            )
            .limit(1)
        )
        org_result = await self._db.execute(org_stmt)
        org_unit = org_result.scalar_one_or_none()
        if org_unit:
            # Walk up to build full hierarchy
            chain: list[tuple[str, str, str]] = []  # (naam, type, id)
            current = org_unit
            seen: set[str] = set()
            while current and str(current.id) not in seen:
                seen.add(str(current.id))
                chain.append((current.naam, current.type, str(current.id)))
                if current.parent_id:
                    parent_result = await self._db.execute(
                        select(OrganisatieEenheid).where(
                            OrganisatieEenheid.id == current.parent_id
                        )
                    )
                    current = parent_result.scalar_one_or_none()
                else:
                    break
            chain.reverse()  # top-down: ministerie → DG → directie → ...
            hierarchy = " > ".join(
                f"{naam} ({typ}, ID: {oid})" for naam, typ, oid in chain
            )
            parts.append(f"Organisatie: {hierarchy}")

        # Current date/time (Dutch day/month names)
        now = datetime.now()
        dagen = [
            "maandag",
            "dinsdag",
            "woensdag",
            "donderdag",
            "vrijdag",
            "zaterdag",
            "zondag",
        ]
        maanden = [
            "",
            "januari",
            "februari",
            "maart",
            "april",
            "mei",
            "juni",
            "juli",
            "augustus",
            "september",
            "oktober",
            "november",
            "december",
        ]
        dag = dagen[now.weekday()]
        maand = maanden[now.month]
        parts.append(
            f"Huidige datum en tijd: {dag} {now.day} {maand} {now.year},"
            f" {now.strftime('%H:%M')}"
        )

        return "\n".join(parts)

    # -- Public API ----------------------------------------------------------

    async def get_history(self, conversation_id: str) -> tuple[str, list[ChatMessage]]:
        """Load conversation history and return frontend-friendly messages.

        Filters out ``system`` and ``tool`` role messages and resolves
        attachment refs on user messages.  Returns ``(conversation_id, messages)``.
        Raises ``ValueError`` if the conversation is not found.
        """
        try:
            conv = await self._load_conversation(conversation_id)
        except ValueError:
            conv = None

        if conv is None:
            raise ValueError("Conversation not found")

        raw_messages: list[dict] = conv.messages
        pending_map: dict = conv.pending_actions or {}

        # Collect all attachment_ids referenced in user messages so we can
        # batch-query ChatAttachment metadata.
        all_att_ids: set[str] = set()
        for msg in raw_messages:
            if msg.get("role") != "user":
                continue
            for ref in msg.get("attachment_refs", []):
                att_id = ref.get("attachment_id")
                if att_id:
                    all_att_ids.add(att_id)

        # Batch load attachment metadata
        att_map: dict[str, ChatAttachmentResponse] = {}
        if all_att_ids:
            att_uuids = []
            for aid in all_att_ids:
                try:
                    att_uuids.append(UUID(aid))
                except ValueError:
                    continue
            if att_uuids:
                stmt = select(ChatAttachment).where(ChatAttachment.id.in_(att_uuids))
                result = await self._db.execute(stmt)
                for att in result.scalars():
                    att_map[str(att.id)] = ChatAttachmentResponse(
                        id=str(att.id),
                        bestandsnaam=att.bestandsnaam,
                        content_type=att.content_type,
                        bestandsgrootte=att.bestandsgrootte,
                    )

        out: list[ChatMessage] = []
        last_assistant_idx: int | None = None

        for msg in raw_messages:
            role = msg.get("role")
            if role == "user":
                # Resolve attachment refs to ChatAttachmentResponse objects
                attachments: list[ChatAttachmentResponse] = []
                for ref in msg.get("attachment_refs", []):
                    att_id = ref.get("attachment_id")
                    if att_id and att_id in att_map:
                        attachments.append(att_map[att_id])
                out.append(
                    ChatMessage(
                        role="user",
                        content=msg.get("content", ""),
                        attachments=attachments if attachments else [],
                    )
                )
            elif role == "assistant":
                content = msg.get("content", "")
                # Skip assistant messages that are just empty tool-call holders
                if not content and msg.get("tool_calls"):
                    continue
                out.append(
                    ChatMessage(
                        role="assistant",
                        content=content,
                    )
                )
                last_assistant_idx = len(out) - 1
            # Skip system, tool messages

        # Attach pending actions to the last assistant message
        if pending_map and last_assistant_idx is not None:
            pending_list: list[PendingAction] = []
            for action_id, info in pending_map.items():
                pending_list.append(
                    PendingAction(
                        action_id=action_id,
                        tool_name=info["tool_name"],
                        arguments=info.get("arguments", {}),
                        description=_describe_action(
                            info["tool_name"], info.get("arguments", {})
                        ),
                    )
                )
            if pending_list:
                last_msg = out[last_assistant_idx]
                out[last_assistant_idx] = ChatMessage(
                    role=last_msg.role,
                    content=last_msg.content,
                    actions=last_msg.actions,
                    pending_actions=pending_list,
                    attachments=last_msg.attachments,
                )

        return str(conv.id), out

    async def send_message(
        self,
        message: str,
        conversation_id: str | None = None,
        context: dict | None = None,
        attachment_ids: list[str] | None = None,
    ) -> tuple[str, ChatMessage]:
        """Process a user message and return (conversation_id, response_message)."""

        # Load or create conversation
        conv: ChatConversation | None = None
        if conversation_id:
            try:
                conv = await self._load_conversation(conversation_id)
            except ValueError:
                conv = None

        if conv is None:
            conv = await self._create_conversation()

        messages: list[dict] = conv.messages
        pending_map: dict = conv.pending_actions

        # Add context awareness
        context_msg = build_chat_context_message(context)
        user_ctx = await self._get_user_context()
        if user_ctx:
            context_msg = user_ctx + ("\n" + context_msg if context_msg else "")
        if context_msg:
            system_content = CHAT_SYSTEM_PROMPT + "\n\nHUIDIGE CONTEXT:\n" + context_msg
            messages[0] = {"role": "system", "content": system_content}

        # Load attachments if provided (scoped to current user)
        attachments: list[ChatAttachment] = []
        attachment_responses: list[ChatAttachmentResponse] = []
        if attachment_ids:
            for aid in attachment_ids:
                try:
                    att_uuid = UUID(aid)
                except ValueError:
                    logger.warning("Invalid attachment UUID: %s", aid)
                    continue
                stmt = select(ChatAttachment).where(ChatAttachment.id == att_uuid)
                if self._person_id:
                    stmt = stmt.where(
                        ChatAttachment.person_id.in_([self._person_id])
                        | ChatAttachment.person_id.is_(None)
                    )
                else:
                    stmt = stmt.where(ChatAttachment.person_id.is_(None))
                result = await self._db.execute(stmt)
                att = result.scalar_one_or_none()
                if att:
                    # Associate with conversation
                    if att.conversation_id is None:
                        att.conversation_id = conv.id
                    attachments.append(att)
                    attachment_responses.append(
                        ChatAttachmentResponse(
                            id=str(att.id),
                            bestandsnaam=att.bestandsnaam,
                            content_type=att.content_type,
                            bestandsgrootte=att.bestandsgrootte,
                        )
                    )

        # Store in history with lightweight refs (no base64)
        # Use asyncio.to_thread for blocking text extraction (#8)
        attachment_refs = (
            await _build_attachment_refs(attachments) if attachments else []
        )
        history_entry: dict = {"role": "user", "content": message}
        if attachment_refs:
            history_entry["attachment_refs"] = attachment_refs
        messages.append(history_entry)

        # Tool-calling loop
        actions: list[ChatAction] = []
        pending_actions: list[PendingAction] = []

        # Track whether any message in history has attachment refs so we
        # know whether to attempt the vision fallback on failure.
        has_any_attachments = attachments or any(
            m.get("attachment_refs") for m in messages if isinstance(m, dict)
        )

        for _ in range(_MAX_TOOL_ROUNDS):
            # Truncate to stay within LLM token window
            llm_messages = _truncate_messages(messages, _MAX_MESSAGES_FOR_LLM)

            # Reconstruct ALL user messages that have attachment_refs (#1, #2)
            # Done once before the LLM call, outside per-message iteration.
            llm_messages = await _prepare_llm_messages(llm_messages)

            try:
                response = await self._llm.chat_with_tools(
                    messages=llm_messages,
                    tools=ALL_TOOLS,
                )
            except APIError:
                # Fallback: strip image content parts and retry with text only
                if has_any_attachments:
                    logger.warning(
                        "LLM call failed with attachments, retrying text-only"
                    )
                    for i, msg in enumerate(llm_messages):
                        if isinstance(msg.get("content"), list):
                            text_parts = [
                                p["text"]
                                for p in msg["content"]
                                if p.get("type") == "text"
                            ]
                            llm_messages[i] = {
                                **msg,
                                "content": "".join(text_parts),
                            }
                    response = await self._llm.chat_with_tools(
                        messages=llm_messages,
                        tools=ALL_TOOLS,
                    )
                else:
                    raise
            choice = response.choices[0]
            assistant_msg = choice.message

            # If no tool calls, we have the final text response
            if not assistant_msg.tool_calls:
                content = _clean_content(assistant_msg.content or "")
                messages.append({"role": "assistant", "content": content})
                break

            # Process tool calls
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_msg.tool_calls
                    ],
                }
            )

            has_pending = False
            for tc in assistant_msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse tool arguments for %s: %s",
                        tool_name,
                        tc.function.arguments[:200],
                    )
                    args = {}

                if tool_name in _WRITE_TOOL_NAMES:
                    # Queue for confirmation
                    action_id = str(uuid.uuid4())
                    pending = PendingAction(
                        action_id=action_id,
                        tool_name=tool_name,
                        arguments=args,
                        description=_describe_action(tool_name, args),
                    )
                    pending_actions.append(pending)
                    pending_map[action_id] = {
                        "tool_name": tool_name,
                        "arguments": args,
                        "tool_call_id": tc.id,
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": _safe_dumps(
                                {
                                    "status": "pending_confirmation",
                                    "message": (
                                        "Deze actie is NOG NIET"
                                        " uitgevoerd. De gebruiker"
                                        " moet eerst bevestigen via"
                                        " een knop in de interface."
                                    ),
                                }
                            ),
                        }
                    )
                    has_pending = True
                else:
                    # Execute read tool immediately
                    result = await _execute_read_tool(
                        tool_name, args, self._db, person_id=self._person_id
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )

            # If we have pending writes, stop the loop and return to user
            if has_pending:
                llm_messages = _truncate_messages(messages, _MAX_MESSAGES_FOR_LLM)
                llm_messages = await _prepare_llm_messages(llm_messages)
                try:
                    response2 = await self._llm.chat_with_tools(
                        messages=llm_messages,
                        tools=[],
                    )
                    content = _clean_content(response2.choices[0].message.content or "")
                except Exception:
                    logger.warning(
                        "LLM summary call failed after pending actions, using fallback"
                    )
                    descriptions = [pa.description for pa in pending_actions]
                    content = (
                        "Ik wil de volgende acties uitvoeren:\n\n"
                        + "\n".join(f"- {d}" for d in descriptions)
                        + "\n\nBevestig of annuleer de acties hierboven."
                    )
                messages.append({"role": "assistant", "content": content})
                break
        else:
            # If we exhausted the loop
            content = (
                "Ik kon het verzoek niet volledig"
                " verwerken. Probeer het opnieuw"
                " met een specifiekere vraag."
            )
            messages.append({"role": "assistant", "content": content})

        # Persist to DB
        conv.messages = messages
        conv.pending_actions = pending_map
        await self._save_conversation(conv)

        return str(conv.id), ChatMessage(
            role="assistant",
            content=content,
            actions=actions,
            pending_actions=pending_actions,
            attachments=attachment_responses,
        )

    async def confirm_action(
        self,
        conversation_id: str,
        action_id: str,
        approved: bool,
    ) -> ChatMessage:
        """Confirm or reject a pending write action."""
        try:
            conv = await self._load_conversation(conversation_id)
        except ValueError:
            conv = None

        if not conv:
            return ChatMessage(
                role="assistant",
                content="Conversatie niet gevonden of verlopen.",
            )

        pending_map: dict = conv.pending_actions
        pending = pending_map.pop(action_id, None)
        if not pending:
            return ChatMessage(
                role="assistant",
                content="Actie niet gevonden of al verwerkt.",
            )

        messages: list[dict] = conv.messages
        actions: list[ChatAction] = []

        if approved:
            result = await _execute_write_tool(
                pending["tool_name"],
                pending["arguments"],
                self._db,
                person_id=self._person_id,
            )
            actions.append(
                ChatAction(
                    tool_name=pending["tool_name"],
                    description=result.get("summary", ""),
                    result_summary=result.get("summary", ""),
                    entity_id=result.get("entity_id"),
                    entity_type=result.get("entity_type"),
                )
            )
            status_msg = (
                result["summary"]
                if result["success"]
                else f"Mislukt: {result['summary']}"
            )
        else:
            desc = _describe_action(pending["tool_name"], pending["arguments"])
            status_msg = f"{desc} — geannuleerd door gebruiker"

        messages.append(
            {
                "role": "user",
                "content": (
                    f"[Actie {'bevestigd' if approved else 'geannuleerd'}] {status_msg}"
                ),
            }
        )

        try:
            llm_messages = _truncate_messages(messages, _MAX_MESSAGES_FOR_LLM)
            llm_messages = await _prepare_llm_messages(llm_messages)
            response = await self._llm.chat_with_tools(
                messages=llm_messages,
                tools=[],
            )
            content = _clean_content(response.choices[0].message.content or status_msg)
        except Exception:
            logger.warning("LLM summary call failed after confirm, using fallback")
            content = status_msg

        messages.append({"role": "assistant", "content": content})

        # Persist to DB
        conv.messages = messages
        conv.pending_actions = pending_map
        await self._save_conversation(conv)

        return ChatMessage(
            role="assistant",
            content=content,
            actions=actions,
        )
