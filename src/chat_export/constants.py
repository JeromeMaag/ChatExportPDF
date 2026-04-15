"""Define shared application constants.

This module centralizes stable values used by multiple entry points and runtime
components. It avoids repeating source keys, default values, and supported log
levels across CLI and GUI code.
"""

SOURCE_APP_THREEMA = "threema"
SOURCE_APP_WHATSAPP = "whatsapp"

SOURCE_APPS = (
    SOURCE_APP_THREEMA,
    SOURCE_APP_WHATSAPP,
)

DEFAULT_SOURCE_APP = SOURCE_APP_THREEMA
DEFAULT_TIMEZONE = "Europe/Zurich"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
