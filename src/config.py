"""
Configurazione dei provider LLM
"""

import os
import sys
import logging
from enum import Enum
from google.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)

# Assicura che src/ sia nel PYTHONPATH per importare models.py
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)


class StripMode(str, Enum):
    """Modalità di strip del thinking/reasoning"""
    FORCE = "force"        # Applica sempre lo strip
    ADAPTIVE = "adaptive"  # Applica solo se il modello lo supporta
    NONE = "none"          # Non applica mai lo strip


# Provider disponibili
SUPPORTED_PROVIDERS = ["google", "groq", "openrouter", "openai", "anthropic"]

# Provider predefinito
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "google").lower()

# Modalità strip thinking (force/adaptive/none)
_raw_strip = os.environ.get("STRIP_THINKING", "adaptive").lower()
try:
    STRIP_MODE = StripMode(_raw_strip)
except ValueError:
    logger.warning(f"Valore STRIP_THINKING '{_raw_strip}' non valido. Uso 'adaptive'.")
    STRIP_MODE = StripMode.ADAPTIVE

# Modelli disponibili per provider
# Ogni modello può avere un flag strip_thinking per la modalità ADAPTIVE
MODELS = {
    "google": {
        "model": "gemini-flash-latest",
        "display": "Google Gemini Flash",
        "env_key": "GOOGLE_API_KEY",
        "strip_thinking": False,  # Gemini nativo non produce thinking
    },
    "groq": {
        "model": "groq/qwen/qwen3-32b",
        "display": "Groq Qwen 32B",
        "env_key": "GROQ_API_KEY",
        "strip_thinking": True,   # Qwen produce tag <think>
    },
    "openrouter": {
        #"model": "openrouter/google/gemma-4-31b-it:free",
        "model": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
        "display": "OpenRouter Nemotron 3 Super 120B",
        "env_key": "OPENROUTER_API_KEY",
        "strip_thinking": True,   # Nemotron produce Part(thought=True)
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
        self.needs_strip = config.get("strip_thinking", False)

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

    La scelta di usare StripThinkingLiteLlm o LiteLlm segue la modalità STRIP_MODE:
    - FORCE: usa sempre StripThinkingLiteLlm
    - ADAPTIVE: usa StripThinkingLiteLlm solo se il modello ha strip_thinking=True
    - NONE: usa sempre LiteLlm standard

    Returns:
        tuple: (model_instance, llm_config)
    """
    llm_config = get_llm_config()
    logger.info(f"Inizializzazione agente con: {llm_config}")
    logger.info(f"STRIP_MODE={STRIP_MODE.value}, needs_strip={llm_config.needs_strip}")

    # Provider Google: modello nativo (stringa), mai strip
    if llm_config.provider == "google":
        model_instance = llm_config.model
        logger.info(f"Usando modello Google nativo: {model_instance}")
        return model_instance, llm_config

    # Decide se applicare lo strip in base alla modalità
    should_strip = (
        STRIP_MODE == StripMode.FORCE
        or (STRIP_MODE == StripMode.ADAPTIVE and llm_config.needs_strip)
    )

    if should_strip:
        from models import StripThinkingLiteLlm
        model_instance = StripThinkingLiteLlm(model=llm_config.model)
        logger.info(f"Usando StripThinkingLiteLlm per provider: {llm_config.provider}")
    else:
        model_instance = LiteLlm(model=llm_config.model)
        logger.info(f"Usando LiteLLM standard per provider: {llm_config.provider}")

    return model_instance, llm_config