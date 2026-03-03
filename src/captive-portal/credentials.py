"""WiFi credential persistence for the captive portal.

Reads and writes WiFi SSID/password pairs to a simple comma-separated file
on the MicroPython filesystem so they survive reboots.
"""

__all__: tuple[str, ...] = ("Creds",)

import uos


class Creds:
    """Container for WiFi credentials backed by a file on disk.

    Credentials are stored as comma-separated bytes in :attr:`CRED_FILE`.
    """

    CRED_FILE: str = "./wifi.creds"

    def __init__(
        self, ssid: bytes | None = None, password: bytes | None = None
    ) -> None:
        """Create a new credentials instance.

        Args:
            ssid: WiFi network name as bytes, or ``None`` if unknown.
            password: WiFi password as bytes, or ``None`` if unknown.
        """
        self.ssid: bytes | None = ssid
        self.password: bytes | None = password

    def write(self) -> None:
        """Write credentials to :attr:`CRED_FILE` if valid input found."""
        if self.is_valid():
            with open(self.CRED_FILE, "wb") as f:
                f.write(b",".join([self.ssid, self.password]))
            print("Wrote credentials to {:s}".format(self.CRED_FILE))

    def load(self) -> Creds:
        """Load credentials from :attr:`CRED_FILE`.

        If the file does not exist or contains invalid data the credentials
        are cleared and the file is removed.

        Returns:
            This instance, to allow method chaining.
        """
        try:
            with open(self.CRED_FILE, "rb") as f:
                contents = f.read().split(b",")
            print("Loaded WiFi credentials from {:s}".format(self.CRED_FILE))
            if len(contents) == 2:
                self.ssid, self.password = contents

            if not self.is_valid():
                self.remove()
        except OSError:
            pass

        return self

    def remove(self) -> None:
        """Delete the credentials file from disk and reset fields to ``None``."""
        try:
            uos.remove(self.CRED_FILE)
        except OSError:
            pass

        self.ssid = self.password = None

    def is_valid(self) -> bool:
        """Return whether both *ssid* and *password* are non-empty byte strings."""
        # Ensure the credentials are entered as bytes
        if not isinstance(self.ssid, bytes):
            return False
        if not isinstance(self.password, bytes):
            return False

        # Ensure credentials are not None or empty
        return all((self.ssid, self.password))
