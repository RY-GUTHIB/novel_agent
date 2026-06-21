# novel_agent package - re-exports
from .core import MemoryManager, ContinuityGuard, ForeshadowTracker, RAGStore, EmbeddingService, get_embedding_service
from .agents import PlannerAgent, WriterAgent, ReviewerAgent
from .llm import generate
