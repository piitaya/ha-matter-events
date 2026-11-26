"""Standard button and rotary event entities for Matter switches."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

MATTER_DOMAIN = "matter"
PLATFORMS = [Platform.EVENT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the rotary entities once Matter is loaded."""
    if not hass.config_entries.async_loaded_entries(MATTER_DOMAIN):
        raise ConfigEntryNotReady("Matter is not loaded yet")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the rotary entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
