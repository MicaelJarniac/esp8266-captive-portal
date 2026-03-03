"""ESP8266 captive portal boot."""
# This file is executed on every boot (including wake-boot from deep sleep)

__all__: tuple[str, ...] = ()

import gc

gc.collect()
