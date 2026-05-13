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


class ThinkStripper:
    """
    Black box streaming per rimuovere tag <think> e contenuto.

    Accumula tutti i chunk in un buffer unico. A ogni flush(),
    parsare l'intero buffer con sloppy-xml e restituisce
    SOLO il nuovo testo fuori dai tag think non ancora emesso.

    Questo garantisce che tag spezzati su più chunk vengano
    sempre riconosciuti correttamente.
    """

    def __init__(self):
        self._buffer = ""          # tutto il testo mai ricevuto
        self._last_clean_len = 0   # quanti caratteri "puliti" già emessi

    def feed(self, chunk: str):
        """Accumula un chunk."""
        self._buffer += chunk

    def flush(self) -> str:
        """
        Parsa l'intero buffer accumulato e restituisce
        solo il nuovo testo "pulito" (fuori dai tag think)
        non ancora emesso nelle flush precedenti.
        """
        if not self._buffer:
            return ""

        # Parsa l'intero buffer con sloppy-xml
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
                        depth -= 1
                        if depth < 0:
                            depth = 0
                elif isinstance(event, Text):
                    if depth == 0:
                        clean += event.content
        except Exception as e:
            logger.warning(f"Errore parsing XML sloppy: {e}")
            clean = self._buffer

        # Calcola il delta: solo la parte nuova
        new_clean = clean[self._last_clean_len:]
        self._last_clean_len = len(clean)
        return new_clean

    def close(self):
        """Reset."""
        self._buffer = ""
        self._last_clean_len = 0


class StripThinkingLiteLlm(BaseLlm):
    """
    Wrapper di LiteLlm che rimuove automaticamente i 'thought parts'
    e i tag XML di thinking (<think>, <thinking>, <antThinking>)
    dalla risposta del modello.

    Usa sloppy-xml come parser robusto per XML malformato
    prodotto dagli LLM.
    """

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model)
        self._inner = LiteLlm(model=model, **kwargs)
        self._stripper = ThinkStripper()
        logger.info(f"StripThinkingLiteLlm inizializzato per modello: {model}")

    async def generate_content_async(
        self, *args, **kwargs
    ) -> AsyncGenerator[LlmResponse, None]:
        """
        Genera contenuto e filtra i thought parts da ogni evento dello stream.
        """
        self._stripper = ThinkStripper()

        async for event in self._inner.generate_content_async(*args, **kwargs):
            if not event or not event.content or not event.content.parts:
                yield event
                continue

            new_parts = []
            for part in event.content.parts:
                if not part.text:
                    new_parts.append(part)
                    continue

                # Alimenta lo stripper e ottieni solo il delta pulito
                self._stripper.feed(part.text)
                cleaned = self._stripper.flush()

                if cleaned:
                    new_parts.append(types.Part(text=cleaned))

            if new_parts:
                original_role = getattr(event.content, 'role', None) or "model"
                yield LlmResponse(
                    content=types.Content(role=original_role, parts=new_parts),
                    grounding_metadata=getattr(event, 'grounding_metadata', None),
                )
            else:
                # Nessun output in questo chunk (tutto thinking)
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part(text="")]),
                )