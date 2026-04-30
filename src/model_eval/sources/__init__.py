from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from model_eval.models import ResolutionReport, SourceData


@runtime_checkable
class DataSource(Protocol):
    """Protocol for model comparison data sources."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def fetch_and_compare(
        self,
        model_names: list[str],
        *,
        families: bool = False,
        fuzzy: bool = False,
        **kwargs: Any,
    ) -> SourceData: ...

    def resolve_names(
        self,
        model_names: list[str],
    ) -> ResolutionReport: ...


_REGISTRY: dict[str, type[DataSource]] = {}


def register_source(name: str, source_cls: type[DataSource]) -> None:
    _REGISTRY[name] = source_cls


def get_source(name: str, **kwargs: Any) -> DataSource:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unknown source '{name}'. Available: {available}")
    return _REGISTRY[name](**kwargs)  # type: ignore[call-arg]


def get_available_sources() -> list[str]:
    return sorted(_REGISTRY.keys())
