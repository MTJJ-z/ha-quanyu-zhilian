"""Serve the bundled offline panel using HA's authenticated frontend connection."""

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant


async def async_setup_panel(hass: HomeAssistant) -> None:
    await hass.http.async_register_static_paths([
        StaticPathConfig("/quanyu_zhilian/panel.js", str(Path(__file__).parent / "frontend" / "panel.js"), False)
    ])
    await panel_custom.async_register_panel(
        hass, frontend_url_path="quanyu-zhilian", webcomponent_name="quanyu-zhilian-panel",
        sidebar_title="全域智联", sidebar_icon="mdi:remote", require_admin=True,
        module_url="/quanyu_zhilian/panel.js?v=0.3.1", config_panel_domain="quanyu_zhilian",
    )
