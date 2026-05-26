"""
Modelli LLM personalizzati per ADK.
Contiene wrapper che aggiungono funzionalità come lo strip del thinking/reasoning.
"""

import logging
from typing import AsyncGenerator
from google.adk.models import BaseLlm, LlmResponse
from google.adk.models.lite_llm import LiteLlm
from google.genai import types
from sloppy_xml import stream_parse, StartElement, EndElement, Text

logger = logging.getLogger(__name__)


class _ThinkStripper:
    """
    Black box streaming: accumula chunk, parsare con sloppy-xml,
    restituisce solo il delta di testo fuori dai tag think.
    """

    def __init__(self):
        self._buffer = ""
        self._last_clean_len = 0

    def feed(self, chunk: str):
        self._buffer += chunk

    def flush(self) -> str:
        if not self._buffer:
            return ""
        clean = ""
        depth = 0
        try:
            for event in stream_parse(
                self._buffer,
                recover=True,
                allow_fragments=True,
                auto_close_tags=True,
            ):
                if isinstance(event, StartElement):
                    if event.name.lower() in ("think", "thinking", "antthinking"):
                        depth += 1
                elif isinstance(event, EndElement):
                    if event.name.lower() in ("think", "thinking", "antthinking"):
                        if depth > 0:
                            depth -= 1
                elif isinstance(event, Text):
                    if depth == 0:
                        clean += event.content
        except Exception as e:
            logger.warning(f"Errore parsing XML: {e}")
            clean = self._buffer
        new_clean = clean[self._last_clean_len:]
        self._last_clean_len = len(clean)
        return new_clean

    def reset(self):
        self._buffer = ""
        self._last_clean_len = 0


class StripThinkingLiteLlm(BaseLlm):
    """
    Wrapper di LiteLlm che rimuove il thinking/reasoning dalla risposta,
    preservando tutti i campi dell'evento originale (partial, turn_complete,
    finish_reason, usage_metadata, ecc.).

    Due modalità in base a come il modello restituisce il thinking:
    - Part(thought=True) → scartato direttamente  (Nemotron, DeepSeek via LiteLLM)
    - Tag XML <think>...</think> nel testo → rimossi via sloppy-xml  (Qwen)
    """

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model)
        self._inner = LiteLlm(model=model, **kwargs)
        logger.info(f"StripThinkingLiteLlm inizializzato per modello: {model}")

    async def generate_content_async(
        self, *args, **kwargs
    ) -> AsyncGenerator[LlmResponse, None]:
        stripper = _ThinkStripper()

        async for event in self._inner.generate_content_async(*args, **kwargs):
            if not event or not event.content or not event.content.parts:
                yield event
                continue

            new_parts = []
            for part in event.content.parts:
                if not part.text:
                    new_parts.append(part)
                    continue

                # Caso 1: thinking strutturato → scarta
                if getattr(part, 'thought', False):
                    continue

                # Caso 2: thinking in tag XML → rimuovi tag
                stripper.feed(part.text)
                cleaned = stripper.flush()
                if cleaned:
                    new_parts.append(types.Part(text=cleaned))

            original_role = getattr(event.content, 'role', None) or "model"

            if new_parts:
                yield LlmResponse(
                    **event.model_dump(exclude={'content'}),
                    content=types.Content(role=original_role, parts=new_parts),
                )
            else:
                yield LlmResponse(
                    **event.model_dump(exclude={'content'}),
                    content=types.Content(role="model", parts=[types.Part(text="")]),
                )