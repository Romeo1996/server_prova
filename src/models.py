"""
Modelli LLM personalizzati per ADK.
Contiene wrapper che aggiungono funzionalità come lo strip del thinking/reasoning.
"""

import logging
from typing import AsyncGenerator
from google.adk.models import BaseLlm, LlmResponse
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

logger = logging.getLogger(__name__)


class StripThinkingLiteLlm(BaseLlm):
    """
    Wrapper di LiteLlm che rimuove automaticamente i 'thought parts'
    dalla risposta del modello (DeepSeek R1, Qwen 3, Claude, ecc.).

    ADK converte il thinking/reasoning in Part(thought=True).
    Questo wrapper li filtra prima che arrivino all'agente.
    """

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model)
        self._inner = LiteLlm(model=model, **kwargs)
        logger.info(f"StripThinkingLiteLlm inizializzato per modello: {model}")

    @staticmethod
    def _filter_thought_parts(llm_response: LlmResponse) -> LlmResponse:
        """Filtra i thought parts da una risposta LLM."""
        if not llm_response or not llm_response.content or not llm_response.content.parts:
            return llm_response

        original_parts = llm_response.content.parts
        thought_count = sum(1 for p in original_parts if getattr(p, 'thought', False))

        if thought_count == 0:
            return llm_response

        filtered_parts = [p for p in original_parts if not getattr(p, 'thought', False)]

        if not filtered_parts:
            logger.warning("Tutti i parti erano thought, nessun contenuto rimasto.")
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="")],
                )
            )

        logger.info(
            f"Rimossi {thought_count} thought part(s) "
            f"su {len(original_parts)} totali. Mantenuti {len(filtered_parts)} part(s)."
        )

        original_role = getattr(llm_response.content, 'role', None) or "model"

        return LlmResponse(
            content=types.Content(
                role=original_role,
                parts=filtered_parts,
            ),
            grounding_metadata=getattr(llm_response, 'grounding_metadata', None),
        )

    async def generate_content_async(
        self, *args, **kwargs
    ) -> AsyncGenerator[LlmResponse, None]:
        """
        Genera contenuto e filtra i thought parts da ogni evento dello stream.
        """
        async for event in self._inner.generate_content_async(*args, **kwargs):
            yield self._filter_thought_parts(event)