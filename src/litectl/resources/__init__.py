"""Bundled configuration and native service templates."""

SERVICE_TEMPLATES = {
    "darwin": "services/dev.litectl.proxy.plist.in",
    "linux": "services/litectl.service.in",
}
