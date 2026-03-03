"""Captive portal orchestrator for the ESP8266.

Coordinates the WiFi access point, DNS server, and HTTP server to present a
captive configuration page where users can enter their home WiFi credentials.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ("CaptivePortal",)

import gc

import network
import ubinascii as binascii
import uselect as select
import usocket as socket
import utime as time
from captive_dns import DNSServer
from captive_http import HTTPServer
from credentials import Creds
from micropython import const


class CaptivePortal:
    """WiFi captive portal for first-time network configuration.

    When started, the portal checks for stored WiFi credentials and attempts
    to connect.  If no valid credentials exist it opens a soft access point
    and runs a DNS + HTTP server so that any connected device is redirected
    to a configuration page where the user can supply their home WiFi SSID
    and password.
    """

    AP_IP: str = "192.168.4.1"
    AP_OFF_DELAY: int = const(10 * 1000)
    MAX_CONN_ATTEMPTS: int = 10

    def __init__(self, essid: bytes | None = None) -> None:
        """Initialise the captive portal.

        Args:
            essid: Custom access-point name as bytes.  When ``None`` a name
                is derived from the last three bytes of the device MAC
                address (e.g. ``b"ESP8266-abcdef"``).
        """
        self.local_ip: str = self.AP_IP
        self.sta_if: network.WLAN = network.WLAN(network.STA_IF)
        self.ap_if: network.WLAN = network.WLAN(network.AP_IF)

        if essid is None:
            essid = b"ESP8266-%s" % binascii.hexlify(self.ap_if.config("mac")[-3:])
        self.essid: bytes = essid

        self.creds: Creds = Creds()

        self.dns_server: DNSServer | None = None
        self.http_server: HTTPServer | None = None
        self.poller: select.poll = select.poll()

        self.conn_time_start: int | None = None

    def start_access_point(self) -> None:
        """Activate the soft access point with an open auth mode.

        Configures the AP interface with :attr:`AP_IP` as the IP address,
        netmask, gateway, and DNS server so that all traffic is routed
        through the ESP8266 itself.
        """
        # sometimes need to turn off AP before it will come up properly
        self.ap_if.active(False)
        while not self.ap_if.active():
            print("Waiting for access point to turn on")
            self.ap_if.active(True)
            time.sleep(1)
        # IP address, netmask, gateway, DNS
        self.ap_if.ifconfig(
            (self.local_ip, "255.255.255.0", self.local_ip, self.local_ip)
        )
        self.ap_if.config(essid=self.essid, authmode=network.AUTH_OPEN)
        print("AP mode configured:", self.ap_if.ifconfig())

    def connect_to_wifi(self) -> bool:
        """Attempt to connect to a WiFi network using stored credentials.

        Tries up to :attr:`MAX_CONN_ATTEMPTS` times with a two-second delay
        between each attempt.  If connection fails the stored credentials
        are removed and station mode is deactivated.

        Returns:
            ``True`` if the connection succeeded, ``False`` otherwise.
        """
        print(
            "Trying to connect to SSID '{:s}' with password {:s}".format(
                self.creds.ssid, self.creds.password
            )
        )

        # initiate the connection
        self.sta_if.active(True)
        self.sta_if.connect(self.creds.ssid, self.creds.password)

        attempts: int = 1
        while attempts <= self.MAX_CONN_ATTEMPTS:
            if not self.sta_if.isconnected():
                print(
                    "Connection attempt {:d}/{:d} ...".format(
                        attempts, self.MAX_CONN_ATTEMPTS
                    )
                )
                time.sleep(2)
                attempts += 1
            else:
                print("Connected to {:s}".format(self.creds.ssid))
                self.local_ip = self.sta_if.ifconfig()[0]
                return True

        print(
            "Failed to connect to {:s} with {:s}. WLAN status={:d}".format(
                self.creds.ssid, self.creds.password, self.sta_if.status()
            )
        )
        # forget the credentials since they didn't work, and turn off station mode
        self.creds.remove()
        self.sta_if.active(False)
        return False

    def check_valid_wifi(self) -> bool:
        """Check the current WiFi state and manage the access-point lifecycle.

        Handles three scenarios:

        1. Not connected but valid credentials exist → attempt connection.
        2. Connected and AP still active → schedule AP shutdown after
           :attr:`AP_OFF_DELAY` milliseconds.
        3. Connected and AP already off → no-op.

        Returns:
            ``True`` if a new connection was established during this call,
            ``False`` otherwise.
        """
        if not self.sta_if.isconnected():
            if self.creds.load().is_valid():
                # have credentials to connect, but not yet connected
                # return value based on whether the connection was successful
                return self.connect_to_wifi()
            # not connected, and no credentials to connect yet
            return False

        if not self.ap_if.active():
            # access point is already off; do nothing
            return False

        # already connected to WiFi, so turn off Access Point after a delay
        if self.conn_time_start is None:
            self.conn_time_start = time.ticks_ms()
            remaining = self.AP_OFF_DELAY
        else:
            remaining = self.AP_OFF_DELAY - time.ticks_diff(
                time.ticks_ms(), self.conn_time_start
            )
            if remaining <= 0:
                self.ap_if.active(False)
                print("Turned off access point")
        return False

    def captive_portal(self) -> None:
        """Run the captive portal event loop.

        Starts the access point, brings up the DNS and HTTP servers, and
        enters a polling loop that dispatches socket events until the user
        submits valid WiFi credentials and a connection is established.
        """
        print("Starting captive portal")
        self.start_access_point()

        if self.http_server is None:
            self.http_server = HTTPServer(self.poller, self.local_ip)
            print("Configured HTTP server")
        if self.dns_server is None:
            self.dns_server = DNSServer(self.poller, self.local_ip)
            print("Configured DNS server")

        try:
            while True:
                gc.collect()
                # check for socket events and handle them
                for response in self.poller.ipoll(1000):
                    sock, event, *others = response
                    is_handled = self.handle_dns(sock, event, others)
                    if not is_handled:
                        self.handle_http(sock, event, others)

                if self.check_valid_wifi():
                    print("Connected to WiFi!")
                    self.http_server.set_ip(self.local_ip, self.creds.ssid)
                    self.dns_server.stop(self.poller)
                    break

        except KeyboardInterrupt:
            print("Captive portal stopped")
        self.cleanup()

    def handle_dns(self, sock: socket.socket, event: int, others: list[int]) -> bool:
        """Dispatch a poll event to the DNS server if applicable.

        Args:
            sock: The socket that triggered the event.
            event: The poll event flags.
            others: Additional event data from ``ipoll``.

        Returns:
            ``True`` if the event was handled by the DNS server,
            ``False`` if it should be passed to another handler.
        """
        if sock is self.dns_server.sock:
            # ignore UDP socket hangups
            if event == select.POLLHUP:
                return True
            self.dns_server.handle(sock, event, others)
            return True
        return False

    def handle_http(self, sock: socket.socket, event: int, others: list[int]) -> None:
        """Dispatch a poll event to the HTTP server.

        Args:
            sock: The socket that triggered the event.
            event: The poll event flags.
            others: Additional event data from ``ipoll``.
        """
        self.http_server.handle(sock, event, others)

    def cleanup(self) -> None:
        """Stop the DNS server (if running) and free memory."""
        print("Cleaning up")
        if self.dns_server:
            self.dns_server.stop(self.poller)
        gc.collect()

    def try_connect_from_file(self) -> bool:
        """Load stored credentials and attempt a WiFi connection.

        If the connection fails the credentials file is removed.

        Returns:
            ``True`` if connected successfully, ``False`` otherwise.
        """
        if self.creds.load().is_valid():
            if self.connect_to_wifi():
                return True

        # WiFi Connection failed - remove credentials from disk
        self.creds.remove()
        return False

    def start(self) -> None:
        """Entry point — try stored credentials first, fall back to captive portal."""
        # turn off station interface to force a reconnect
        self.sta_if.active(False)
        if not self.try_connect_from_file():
            self.captive_portal()
