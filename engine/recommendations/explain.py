"""
Phase 3B - Provider-agnostic explanation generation.

At MVP stage the fallback explainer is always available. Provider-specific
classes can be enabled by environment configuration without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import settings


@dataclass(slots=True)
class ExplanationContext:
    product_title: str
    recommended_discount_pct: float
    confidence_score: float
    rationale: str


class BaseExplainer:
    def generate(self, ctx: ExplanationContext) -> str:
        raise NotImplementedError


class TemplateExplainer(BaseExplainer):
    def generate(self, ctx: ExplanationContext) -> str:
        return (
            f"Recommend a {ctx.recommended_discount_pct:.1f}% discount for {ctx.product_title}. "
            f"Confidence is {ctx.confidence_score:.0%}. {ctx.rationale}"
        )


class OpenAIExplainer(TemplateExplainer):
    """
    MVP-safe provider wrapper.

    We intentionally fall back to the deterministic template until API keys and
    prompting policy are finalized. The abstraction point exists now so the app
    can swap providers later without touching business logic.
    """


class AnthropicExplainer(TemplateExplainer):
    """MVP-safe provider wrapper mirroring the OpenAI explainer contract."""


def get_explainer() -> BaseExplainer:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAIExplainer()
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicExplainer()
    return TemplateExplainer()
