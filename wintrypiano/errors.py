"""Errori con un messaggio in italiano pensato per l'utente."""


class UserError(Exception):
    """Errore da mostrare all'utente così com'è (niente traceback)."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message


class TakeExistsError(UserError):
    """Una take esiste già e non è stata chiesta la sovrascrittura."""

    def __init__(self, what: str):
        super().__init__(f"Esiste già una take di {what} in questo progetto.")
        self.what = what


def friendly_message(exc: BaseException) -> str:
    """Traduce un'eccezione qualsiasi in un messaggio comprensibile."""
    if isinstance(exc, UserError):
        return exc.message
    if isinstance(exc, PermissionError):
        return "Non ho i permessi per scrivere o leggere il file. Chiudi altri programmi che lo usano o scegli un'altra cartella."
    if isinstance(exc, FileNotFoundError):
        return "Il file o la cartella non esiste più."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "Il disco è pieno. Libera spazio e riprova."
    if isinstance(exc, MemoryError):
        return "Memoria insufficiente. Chiudi altri programmi o usa un soundfont più leggero."
    name = type(exc).__name__
    if "PortAudio" in name or "PortAudio" in str(exc):
        return "Il dispositivo audio non risponde. Controlla che sia collegato e non usato in esclusiva da un altro programma."
    return "Si è verificato un errore imprevisto. Dettagli salvati nel file di log."
