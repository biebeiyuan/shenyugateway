from __future__ import annotations

from ._helpers import (
    ADMIN_SCORERS,
    EXPLICIT_MENTION_STOPWORDS,
    FEEDBACK_ALIASES,
    FEEDBACK_VALUES,
    NEGATIVE_FEEDBACK,
    POSITIVE_FEEDBACK,
    STAR_ACTIVATION_TABLE,
    STAR_CANDIDATE_TABLE,
    STAR_FEEDBACK_TABLE,
    STAR_FEATURE_SCHEMA_VERSION,
    STAR_LINK_TABLE,
    STAR_RANKER_VERSION,
    STAR_RUN_TABLE,
    STAR_SELECT,
    STAR_TABLE,
    STAR_WEIGHTS_VERSION,
    parse_star_payload,
)
from ._weights import StarWeights
from ._render import render_star_context, RenderMixin
from ._embedding import EmbeddingMixin
from ._crud import CrudMixin
from ._recall import RecallMixin
from ._activity import ActivityMixin
from ._review import ReviewMixin
from ._feedback import FeedbackMixin
from ._logging import LoggingMixin


class StarService(
    RecallMixin,
    ActivityMixin,
    ReviewMixin,
    FeedbackMixin,
    LoggingMixin,
    EmbeddingMixin,
    RenderMixin,
    CrudMixin,
):
    pass


__all__ = [
    "StarService",
    "StarWeights",
    "parse_star_payload",
    "render_star_context",
    "STAR_ACTIVATION_TABLE",
    "STAR_CANDIDATE_TABLE",
    "STAR_FEEDBACK_TABLE",
    "STAR_LINK_TABLE",
    "STAR_RUN_TABLE",
    "STAR_TABLE",
    "STAR_SELECT",
]
