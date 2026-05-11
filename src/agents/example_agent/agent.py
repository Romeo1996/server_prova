"""
Example ADK Agent with LiteLLM - Multi-Provider Support
Supporta: Google Gemini, Groq, OpenRouter
"""

from google.adk.agents import LlmAgent
from src.config import get_model_instance

# Ottiene l'istanza del modello configurato
model_instance, llm_config = get_model_instance()

# Crea l'agente con il modello configurato
root_agent = LlmAgent(
    model=model_instance,
    name='example_litellm_agent',
    description=f'Agente configurabile con {llm_config.display_name}',
    instruction=f'Sei un assistente utile alimentato da {llm_config.display_name}. Rispondi alle domande dell\'utente in modo chiaro e conciso.',
)

