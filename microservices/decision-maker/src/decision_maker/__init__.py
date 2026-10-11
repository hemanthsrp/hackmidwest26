"""decision-maker: the combination layer.

Evidence from the store, an optional user question and the quant math go in; a
buy / hold / sell / insufficient_data research assessment with a cited
explanation comes out. See README.md.
"""

from .combiner import COMBINER_VERSION
from .explain import bedrock_agent_factory, openai_compatible_agent_factory
from .models import (
    DecisionError,
    DecisionRequest,
    DecisionResponse,
    InvalidSymbolError,
    Preferences,
    ProviderUnavailableError,
    QuantInput,
    SignalRecord,
    StaleDataError,
    VolSurfaceSnapshot,
)
from .retrieval import FixtureEvidenceSource, PgEvidenceSource
from .service import DecisionMaker

__all__ = [
    "COMBINER_VERSION",
    "DecisionError",
    "DecisionMaker",
    "DecisionRequest",
    "DecisionResponse",
    "FixtureEvidenceSource",
    "InvalidSymbolError",
    "PgEvidenceSource",
    "Preferences",
    "ProviderUnavailableError",
    "QuantInput",
    "SignalRecord",
    "StaleDataError",
    "VolSurfaceSnapshot",
    "bedrock_agent_factory",
    "openai_compatible_agent_factory",
]
