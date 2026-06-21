# core package - re-exports
from .models import (
    CharacterProfile, LocationProfile, WorldSetting,
    PlotRule, CharacterKnowledge, SectFaction, SceneEvent,
    RelationshipRecord, TimelineEvent, CharacterLocation,
    Foreshadow,
)
from .memory import MemoryManager
from .continuity import ContinuityGuard
from .foreshadow import ForeshadowTracker
from .rag import RAGStore
from .embedding_service import EmbeddingService, get_embedding_service
from .validator import ContractValidator, ContractViolation, format_violations_report
