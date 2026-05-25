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

from google.adk.agents import LlmAgent
from config import get_model_instance
from ag_ui_adk import AGUIToolset
from src.tools.thread_title import set_thread_title

# Ottiene l'istanza del modello configurato
# Se STRIP_THINKING=True, model_instance è un StripThinkingLiteLlm
# che filtra automaticamente i thought parts
model_instance, llm_config = get_model_instance()

# Crea l'agente con il modello configurato
# NOTA: after_model_callback NON viene usato.
# Lo strip del thinking è gestito internamente dal modello (StripThinkingLiteLlm).
root_agent = LlmAgent(
    model=model_instance,
    name='example_litellm_agent',
    description=f'Agente configurabile con {llm_config.display_name}',
    instruction=(
        f'Sei un assistente utile alimentato da {llm_config.display_name}. '
        "Rispondi alle domande dell'utente in modo chiaro e conciso.\n\n"
        "Dopo aver risposto alla prima domanda dell'utente, usa lo strumento "
        "'set_thread_title' per impostare un titolo breve (3-6 parole) che "
        "riassuma l'argomento principale della conversazione."
    ),
    tools=[AGUIToolset(), set_thread_title],
)