"""Public MediaSensei Python SDK."""

from mediasensei.infrastructure.acquisition import AcquisitionService
from mediasensei.infrastructure.acquisition_discovery import (
    DirectUrlDiscoveryProvider,
    OpenverseDiscoveryProvider,
    SafeHttpDownloader,
    WikimediaCommonsDiscoveryProvider,
)
from mediasensei.infrastructure.acquisition_planning import (
    CapabilityResolver,
    DiscoveryRegistry,
    MetadataRelevanceEvaluator,
    RuleBasedPromptPlanner,
    TargetYieldController,
)
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.documents import (
    DocumentPipeline,
    LocalHashEmbeddingProvider,
    SQLiteVectorIndex,
)
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.media import FFmpegToolchain, MediaPipeline
from mediasensei.infrastructure.providers import (
    DatasetProviderRegistry,
    HuggingFaceDatasetProvider,
    KaggleDatasetProvider,
    ProviderImportService,
)
from mediasensei.infrastructure.storage import ContentAddressedStore, StoredObject
from mediasensei.infrastructure.worker import LocalWorker, ProcessorRegistry

__all__ = [
    "AcquisitionService",
    "CapabilityResolver",
    "Catalog",
    "ContentAddressedStore",
    "DatasetProviderRegistry",
    "DirectUrlDiscoveryProvider",
    "DiscoveryRegistry",
    "DocumentPipeline",
    "FFmpegToolchain",
    "HuggingFaceDatasetProvider",
    "JobQueue",
    "KaggleDatasetProvider",
    "LocalHashEmbeddingProvider",
    "LocalWorker",
    "MediaPipeline",
    "MetadataRelevanceEvaluator",
    "OpenverseDiscoveryProvider",
    "ProcessorRegistry",
    "ProviderImportService",
    "RuleBasedPromptPlanner",
    "SQLiteVectorIndex",
    "SafeHttpDownloader",
    "StoredObject",
    "TargetYieldController",
    "WikimediaCommonsDiscoveryProvider",
]
__version__ = "2.0.0-rc.1"
