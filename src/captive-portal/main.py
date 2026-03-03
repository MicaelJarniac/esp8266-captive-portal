"""ESP8266 captive portal entry point.

This module serves as the main entry point for the ESP8266 captive portal
application.  It creates a :class:`~captive_portal.CaptivePortal` instance
and starts the portal service.
"""

__all__: tuple[str, ...] = ("portal",)

from captive_portal import CaptivePortal

portal = CaptivePortal()

portal.start()
