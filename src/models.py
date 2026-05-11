"""
Modelli LLM personalizzati per ADK.
Contiene wrapper che aggiungono funzionalità come lo strip del thinking/reasoning.
"""

import re
import logging
from typing import AsyncGenerator
from google.adk.models import BaseLlm, LlmResponse
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

logger = logging.getLogger(__name__)

# Pattern per rimuovere blocchi di thinking nei formati più comuni:
# - <think>...</think> (Qwen 3, DeepSeek)
# -  ... 
# -  ...  (Anthropic Claude)
_THINK_PATTERNS = [
    re.compile(r'<think>.*?</think>', re.DOTALL),
    re.compile(r'<thinking>.*?</thinking>', re.DOTALL),
    re.compile(r'<antThinking>.*?</antThinking>', re.DOTALL),
]


class StripThinkingLiteLlm(BaseLlm):
    """
    Wrapper di LiteLlm che rimuove automaticamente i 'thought parts'
    dalla risposta del modello (DeepSeek R1, Qwen 3, Claude, ecc.).

    Gestisce due formati:
    1. Part(thought=True) — usato da ADK per modelli come Claude con thinking_blocks
    2. Tag testuali <think>...</think> — usato da Qwen 3, DeepSeek R1
    """

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model)
        self._inner = LiteLlm(model=model, **kwargs)
        logger.info(f"StripThinkingLiteLlm inizializzato per modello: {model}")

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Rimuove i blocchi di thinking dai tag XML nel testo."""
        for pattern in _THINK_PATTERNS:
            text = pattern.sub('', text)
        return text.strip()

    @staticmethod
    def _filter_thought_parts(llm_response: LlmResponse) -> LlmResponse:
        """Filtra i thought parts da una risposta LLM."""
        if not llm_response or not llm_response.content or not llm_response.content.parts:
            return llm_response

        original_parts = llm_response.content.parts
        filtered_parts = []
        thought_count = 0

        for part in original_parts:
            if getattr(part, 'thought', False):
                thought_count += 1
                continue  # Rimuove i thought parts strutturati

            if part.text:
                # Rimuove i tag <think> dal testo
                stripped_text = StripThinkingLiteLlm._strip_think_tags(part.text)
                if stripped_text:
                    # Se dopo lo strip rimane testo, aggiorna il part
                    if stripped_text != part.text:
                        filtered_parts.append(types.Part(text=stripped_text))
                    else:
                        filtered_parts.append(part)
                else:
                    # Se dopo lo strip non rimane nulla, conta come thought
                    thought_count += 1
            else:
                filtered_parts.append(part)

        if not filtered_parts:
            logger.warning("Tutti i parti erano thought, nessun contenuto rimasto.")
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="")],
                )
            )

        if thought_count > 0:
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