"""
Example ADK Agent with LiteLLM - Multi-Provider Support
Supporta: Google Gemini, Groq, OpenRouter

Include after_model_callback opzionale per rimuovere il thinking/reasoning
dalla risposta dei modelli che lo supportano (DeepSeek R1, Qwen 3, Claude, ecc.).
Il flag STRIP_THINKING (env var, default: true) controlla se attivare lo strip.
"""

from google.adk.agents import LlmAgent
from config import get_model_instance, STRIP_THINKING

# Ottiene l'istanza del modello configurato
model_instance, llm_config = get_model_instance()

# Costruisce i parametri dell'agente
agent_kwargs = dict(
    model=model_instance,
    name='example_litellm_agent',
    description=f'Agente configurabile con {llm_config.display_name}',
    instruction=f'Sei un assistente utile alimentato da {llm_config.display_name}. Rispondi alle domande dell\'utente in modo chiaro e conciso.',
)

# Attiva il callback strip_thinking solo se il flag è true
if STRIP_THINKING:
    from callbacks import strip_thinking_callback
    agent_kwargs['after_model_callback'] = strip_thinking_callback

# Crea l'agente con la configurazione selezionata
root_agent = LlmAgent(**agent_kwargs)

