"""
Callback per filtrare il thinking/reasoning content dai modelli LLM.
Rimuove i parti con thought=True dalla risposta del modello.
"""

import logging
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)


def strip_thinking_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """
    Callback after_model che rimuove i 'thought parts' dalla risposta del modello.
    I modelli come DeepSeek R1, Qwen 3, Claude (con thinking_blocks) restituiscono
    parti di 'thinking' che ADK converte in Part(thought=True).
    Questo callback li filtra in modo che non appaiano nell'output finale.
    """
    agent_name = callback_context.agent_name

    if not llm_response or not llm_response.content or not llm_response.content.parts:
        return None  # Nessuna modifica

    original_parts = llm_response.content.parts
    thought_count = sum(1 for p in original_parts if getattr(p, 'thought', False))

    if thought_count == 0:
        return None  # Nessun thinking da rimuovere

    # Filtra solo i parti NON thought
    filtered_parts = [p for p in original_parts if not getattr(p, 'thought', False)]

    if not filtered_parts:
        # Se dopo il filtraggio non rimane nulla, restituisci un messaggio vuoto
        logger.warning(f"[{agent_name}] Tutti i parti erano thought, nessun contenuto rimasto.")
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="")],
            )
        )

    logger.info(
        f"[{agent_name}] Rimossi {thought_count} thought part(s) "
        f"su {len(original_parts)} totali. Mantenuti {len(filtered_parts)} part(s)."
    )

    # Costruisce il nuovo Content preservando SEMPRE il role originale
    # Se il role originale è None o vuoto, usa "model" come fallback
    original_role = getattr(llm_response.content, 'role', None) or "model"

    return LlmResponse(
        content=types.Content(
            role=original_role,
            parts=filtered_parts,
        ),
        grounding_metadata=getattr(llm_response, 'grounding_metadata', None),
    )