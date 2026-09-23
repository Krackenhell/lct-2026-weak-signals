from dataclasses import dataclass, field


@dataclass
class RawDoc:
    """Документ в едином формате, независимо от источника."""

    url: str
    title: str
    snippet: str = ""
    published: str | None = None  # YYYY-MM-DD
    source_name: str = ""
    source_type: str = "news"  # science|preprint|news|repository|community|reference|patent
    language: str = "en"
    collector: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return f"{self.title}. {self.snippet}"


def clean(text: str | None, limit: int = 1200) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text[:limit]
