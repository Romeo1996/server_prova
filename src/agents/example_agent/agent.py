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

from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.genai import types
from config import get_model_instance
from ag_ui_adk import AGUIToolset

# Ottiene l'istanza del modello configurato
# Se STRIP_THINKING=True, model_instance è un StripThinkingLiteLlm
# che filtra automaticamente i thought parts
model_instance, llm_config = get_model_instance()

async def _after_agent_callback(callback_context: Context) -> Optional[types.Content]:
    """Genera un titolo breve per la conversazione dopo ogni risposta."""
    if callback_context.state.get("thread_title"):
        return None

    events = getattr(callback_context.session, "events", None)
    if not events or len(events) < 2:
        return None

    lines = []
    for e in events:
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.text:
                    author = getattr(e, "author", "user")
                    lines.append(f"{author}: {p.text}")

    if len(lines) < 2:
        return None

    conversation_text = "\n".join(lines)
    prompt = (
        conversation_text
        + "\n\nGenera un titolo breve (3-6 parole) per questa conversazione. "
        "Rispondi SOLO con il titolo, nient'altro."
    )

    from google.adk.models.llm_request import LlmRequest

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
        titolo = None
        async for resp in model_instance.generate_content_async(request):
            if resp.content and resp.content.parts:
                for part in resp.content.parts:
                    if part.text and not getattr(part, "thought", False):
                        titolo = part.text.strip(" '\"").strip()
                        break

    if titolo:
        callback_context.state["thread_title"] = titolo

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