from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import NeptunSmartCoordinator
from .device import NeptunSmart

PLATFORMS = [
    "binary_sensor",
    "select",
    "sensor",
    "switch",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    name = entry.data["name"]
    host_port = entry.data["host_port"]
    host_ip = entry.data["host_ip"]
    device = NeptunSmart(hass, name, host_ip, host_port)
    try:
        await device.init_sensors()
    except ValueError as ex:
        raise ConfigEntryNotReady(f"Timeout while connecting {host_ip}") from ex

    # интервал опроса — из опций интеграции (по умолчанию 10 с, как раньше)
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = NeptunSmartCoordinator(
        hass, device, update_interval=timedelta(seconds=scan_interval)
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # при смене опций (интервала опроса) перезагружаем entry
    entry.async_on_unload(entry.add_update_listener(options_update_listener))
    return True


async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезагрузка entry при изменении опций."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: NeptunSmartCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.device.async_close()

    return unload_ok
