"""
Simple Example ADK Agent - No Tools
"""

from google.adk.agents import LlmAgent


# Create the simplest root agent - no tools
root_agent = LlmAgent(
    model='gemini-flash-latest',
    name='example_simple_agent',
    description='Un semplice agente di esempio senza tool.',
    instruction='Sei un assistente utile. Rispondi alle domande dell\'utente in modo chiaramente e conciso.',
)

