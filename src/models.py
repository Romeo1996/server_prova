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

# Tag di thinking supportati: (tag_apertura, tag_chiusura)
_THINK_TAGS = [
    ("<think>", "</think>"),           # Qwen 3, DeepSeek R1
    ("<thinking>", "</thinking>"),       # Altri modelli
    ("<antThinking>", "</antThinking>"), # Anthropic Claude
]

# Tutti i possibili prefissi di un tag di apertura (es. per <think>: <, <t, <th, ...)
_OPEN_PREFIXES = set()
for open_tag, _ in _THINK_TAGS:
    for i in range(1, len(open_tag)):
        _OPEN_PREFIXES.add(open_tag[:i])


class StripThinkingLiteLlm(BaseLlm):
    """
    Wrapper di LiteLlm che rimuove automaticamente i 'thought parts'
    e i tag <think>...</think> dalla risposta del modello.

    Gestisce due formati:
    1. Part(thought=True) — usato da ADK per Claude, DeepSeek, Qwen via LiteLLM
    2. Tag testuali <think>, <thinking>, <antThinking> — usato da vari modelli

    Durante lo streaming mantiene uno stato per gestire tag che arrivano spezzati.
    """

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model)
        self._inner = LiteLlm(model=model, **kwargs)
        self._in_think = False
        self._close_tag = ""
        self._head_buffer = ""  # buffer per inizio tag open in streaming
        logger.info(f"StripThinkingLiteLlm inizializzato per modello: {model}")

    def _find_first_tag(self, text: str):
        """
        Cerca il primo tag di thinking nel testo.
        Usa self._in_think, self._close_tag, self._head_buffer come stato.

        Returns:
            output: testo da emettere (fuori dai tag)
        """
        # Unisci buffer + chunk corrente
        full = self._head_buffer + text
        self._head_buffer = ""

        if not self._in_think:
            # Trova il primo tag di apertura tra tutti quelli supportati
            best_pos = len(full)
            best_close = ""
            for open_tag, close_tag in _THINK_TAGS:
                pos = full.find(open_tag)
                if pos != -1 and pos < best_pos:
                    best_pos = pos
                    best_close = close_tag

            if best_close:
                # Trovato un tag di apertura
                self._in_think = True
                self._close_tag = best_close
                return full[:best_pos]
            else:
                # Nessun tag trovato: controlla se la coda potrebbe
                # essere l'inizio di un tag (es. "<", "<t", "<th"...)
                for prefix_len in range(len(full), 0, -1):
                    suffix = full[-prefix_len:]
                    if suffix in _OPEN_PREFIXES:
                        # Potenziale inizio tag: bufferizza
                        self._head_buffer = suffix
                        return full[:-prefix_len]
                return full
        else:
            # Siamo dentro un tag: cerca la chiusura
            idx = full.find(self._close_tag)
            if idx == -1:
                # Non trovata: tutto è thinking, scarta
                return ""
            else:
                # Trovata chiusura: dopo il tag è di nuovo output
                self._in_think = False
                self._close_tag = ""
                return full[idx + len(self._close_tag):]

    async def generate_content_async(
        self, *args, **kwargs
    ) -> AsyncGenerator[LlmResponse, None]:
        """
        Genera contenuto e filtra i thought parts da ogni evento dello stream.
        """
        self._in_think = False
        self._close_tag = ""
        self._head_buffer = ""

        async for event in self._inner.generate_content_async(*args, **kwargs):
            if not event or not event.content or not event.content.parts:
                yield event
                continue

            new_parts = []
            for part in event.content.parts:
                if getattr(part, 'thought', False):
                    continue
                if part.text:
                    output = self._find_first_tag(part.text)
                    if output:
                        new_parts.append(types.Part(text=output))
                else:
                    new_parts.append(part)

            if new_parts:
                original_role = getattr(event.content, 'role', None) or "model"
                yield LlmResponse(
                    content=types.Content(role=original_role, parts=new_parts),
                    grounding_metadata=getattr(event, 'grounding_metadata', None),
                )
            else:
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part(text="")]),
                )