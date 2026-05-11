"""
Configurazione dei provider LLM
"""

import os
import logging
from google.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)

# Provider disponibili
SUPPORTED_PROVIDERS = ["google", "groq", "openrouter", "openai", "anthropic"]

# Provider predefinito
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "google").lower()

# Modelli disponibili per provider
MODELS = {
    "google": {
        "model": "gemini-flash-latest",
        "display": "Google Gemini Flash",
        "env_key": "GOOGLE_API_KEY",
    },
    "groq": {
        "model": "qwen/qwen3-32b",
        "display": "Groq Qwen 32B",
        "env_key": "GROQ_API_KEY",
    },
    "openrouter": {
        "model": "google/gemma-4-31b-it:free",
        "display": "OpenRouter Google Gemma 4 31B",
        "env_key": "OPENROUTER_API_KEY",
    },
}


class LLMConfig:
    """Configurazione del modello LLM"""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or DEFAULT_PROVIDER).lower()

        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Provider '{self.provider}' non supportato. Scegli tra: {SUPPORTED_PROVIDERS}")

        config = MODELS.get(self.provider)
        if not config:
            raise ValueError(f"Configurazione non trovata per provider: {self.provider}")

        self.model = model or config["model"]
        self.display_name = config["display"]
        self.env_key = config["env_key"]

    def get_api_key(self) -> str:
        """Ottiene la chiave API dal provider configurato"""
        key = os.environ.get(self.env_key)
        if not key:
            raise ValueError(f"Variabile d'ambiente '{self.env_key}' non trovata per provider '{self.provider}'")
        return key

    def __str__(self) -> str:
        return f"Provider: {self.provider} ({self.display_name}), Model: {self.model}"


def get_llm_config(provider: str | None = None) -> LLMConfig:
    """Factory per ottenere configurazione LLM"""
    return LLMConfig(provider=provider)


def get_model_instance():
    """
    Ottiene l'istanza del modello in base al provider configurato.
    Restituisce il modello nativo per Google o LiteLLM per gli altri provider.

    Returns:
        tuple: (model_instance, llm_config)
    """
    llm_config = get_llm_config()
    logger.info(f"Inizializzazione agente con: {llm_config}")

    # Se il provider è Google, usa il modello predefinito (senza LiteLLM)
    if llm_config.provider == "google":
        model_instance = llm_config.model  # 'gemini-flash-latest'
        logger.info(f"Usando modello Google nativo: {model_instance}")
    else:
        # Per gli altri provider, usa LiteLLM
        model_instance = LiteLlm(model=llm_config.model)
        logger.info(f"Usando LiteLLM per provider: {llm_config.provider}")

    return model_instance, llm_config
