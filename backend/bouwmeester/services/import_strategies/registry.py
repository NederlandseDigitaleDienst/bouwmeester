"""Registry of available import strategies."""

from bouwmeester.services.import_strategies.base import ImportStrategy
from bouwmeester.services.import_strategies.kamervraag import KamervraagStrategy
from bouwmeester.services.import_strategies.motie import MotieStrategy
from bouwmeester.services.import_strategies.nieuws import NieuwsStrategy
from bouwmeester.services.import_strategies.tkconv import TkconvSearchStrategy
from bouwmeester.services.import_strategies.toezegging import ToezeggingStrategy

STRATEGIES: dict[str, type[ImportStrategy]] = {
    "motie": MotieStrategy,
    "kamervraag": KamervraagStrategy,
    "toezegging": ToezeggingStrategy,
    "tkconv_document": TkconvSearchStrategy,
    "nieuwsartikel": NieuwsStrategy,
}


def get_strategy(item_type: str) -> ImportStrategy:
    """Get a strategy instance by item type."""
    cls = STRATEGIES.get(item_type)
    if cls is None:
        raise ValueError(f"Unknown item type: {item_type}")
    return cls()


def get_all_strategies() -> dict[str, ImportStrategy]:
    """Get instances of all registered strategies."""
    return {k: v() for k, v in STRATEGIES.items()}
