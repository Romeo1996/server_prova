"""
Example ADK Agent with LiteLLM - Multi-Provider Support
Supporta: Google Gemini, Groq, OpenRouter

Include strip del thinking/reasoning opzionale dalla risposta dei modelli
(DeepSeek R1, Qwen 3, Claude, ecc.).
Il flag STRIP_THINKIN/api/adkG (env var, default: true) controlla se attivare lo strip.

Lo strip è centralizzato in src/models.py (StripThinkingLiteLlm) e src/callbacks.py.
Viene applicato a livello di modello, non di agente, per evitare problemi
di serializzazione Pydantic col Visual Builder di ADK.
"""

import logging
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.genai import types
from config import get_model_instance
from ag_ui_adk import AGUIToolset

logger = logging.getLogger(__name__)

# Ottiene l'istanza del modello configurato
# Se STRIP_THINKING=True, model_instance è un StripThinkingLiteLlm
# che filtra automaticamente i thought parts
model_instance, llm_config = get_model_instance()

async def _after_agent_callback(callback_context: Context) -> Optional[types.Content]:
    """Genera un titolo breve per la conversazione dopo ogni risposta."""
    existing_title = callback_context.state.get("thread_title")
    logger.info("[TitleDebug] after_agent_callback START existing_title=%s session_id=%s", existing_title, callback_context.session.id if callback_context.session else "NO_SESSION")

    if existing_title:
        logger.info("[TitleDebug] after_agent_callback SKIP already has title")
        return None

    events = getattr(callback_context.session, "events", None)
    events_count = len(events) if events else 0
    logger.info("[TitleDebug] after_agent_callback events_count=%s", events_count)

    if not events or events_count < 2:
        logger.info("[TitleDebug] after_agent_callback SKIP not enough events")
        return None

    lines = []
    for e in events:
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.text:
                    author = getattr(e, "author", "user")
                    lines.append(f"{author}: {p.text}")

    lines_count = len(lines)
    logger.info("[TitleDebug] after_agent_callback lines_count=%s", lines_count)

    if lines_count < 2:
        logger.info("[TitleDebug] after_agent_callback SKIP not enough text lines")
        return None

    conversation_text = "\n".join(lines)
    prompt = (
        conversation_text
        + "\n\nGenera un titolo breve (3-6 parole) per questa conversazione. "
        "Rispondi SOLO con il titolo, nient'altro."
    )

    from google.adk.models.llm_request import LlmRequest

    titolo = None
    try:
        if isinstance(model_instance, str):
            import google.genai as genai

            client = genai.Client()
            response = client.models.generate_content(
                model=model_instance,
                contents=prompt,
            )
            titolo = response.text.strip(" '\"").strip() if response.text else None
        else:
            request = LlmRequest(
                contents=[types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)],
                )],
            )
            async for resp in model_instance.generate_content_async(request):
                if resp.content and resp.content.parts:
                    for part in resp.content.parts:
                        if part.text and not getattr(part, "thought", False):
                            titolo = part.text.strip(" '\"").strip()
                            break
    except Exception as e:
        logger.error("[TitleDebug] after_agent_callback LLM ERROR: %s", e, exc_info=True)

    logger.info("[TitleDebug] after_agent_callback generated titolo=%s", titolo)

    if titolo:
        callback_context.state["thread_title"] = titolo
        logger.info("[TitleDebug] after_agent_callback SET thread_title=%s", titolo)
    else:
        # Fallback: primo messaggio utente come titolo
        for line in lines:
            if line.startswith("user:"):
                fallback = line[len("user:"):].strip()[:60]
                if fallback:
                    callback_context.state["thread_title"] = fallback
                    logger.info("[TitleDebug] after_agent_callback FALLBACK title=%s", fallback)
                break

    return None


# Crea l'agente con il modello configurato
root_agent = LlmAgent(
    model=model_instance,
    name='example_litellm_agent',
    description=f'Agente configurabile con {llm_config.display_name}',
    instruction=(
        f'Sei un assistente utile alimentato da {llm_config.display_name}. '
        "Rispondi alle domande dell'utente in modo chiaro e conciso."
    ),
    tools=[AGUIToolset()],
    after_agent_callback=_after_agent_callback,
)