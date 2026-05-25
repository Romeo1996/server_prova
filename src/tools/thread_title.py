from google.adk.tools import ToolContext


def set_thread_title(title: str, tool_context: ToolContext) -> str:
    """Imposta un titolo breve per la conversazione corrente.

    Chiama questo strumento DOPO aver risposto alla prima domanda dell'utente,
    scegliendo 3-6 parole che riassumano l'argomento principale della conversazione.

    Args:
        title: Titolo breve (3-6 parole) per la conversazione.
    """
    tool_context.state["thread_title"] = title
    return f"Titolo '{title}' salvato."
