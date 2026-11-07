"""Errors carrying a message written for the user."""


class UserError(Exception):
    """Error shown to the user as is (no traceback)."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message


class TakeExistsError(UserError):
    """A take already exists and overwriting was not requested."""

    def __init__(self, what: str):
        super().__init__(f"This project already has a {what} take.")
        self.what = what


def friendly_message(exc: BaseException) -> str:
    """Turn any exception into an understandable message."""
    if isinstance(exc, UserError):
        return exc.message
    if isinstance(exc, PermissionError):
        return "Permission denied while reading or writing the file. Close other programs using it or choose another folder."
    if isinstance(exc, FileNotFoundError):
        return "The file or folder no longer exists."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    if isinstance(exc, MemoryError):
        return "Not enough memory. Close other programs or use a lighter soundfont."
    name = type(exc).__name__
    if "PortAudio" in name or "PortAudio" in str(exc):
        return "The audio device is not responding. Check that it is connected and not used exclusively by another program."
    return "An unexpected error occurred. Details were saved to the log file."
