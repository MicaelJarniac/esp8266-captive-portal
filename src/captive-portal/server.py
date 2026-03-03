"""Base TCP/UDP server for the captive portal.

Provides a reusable :class:`Server` base class that handles socket creation,
binding, and poll registration for both TCP (stream) and UDP (datagram)
protocols.
"""

__all__: tuple[str, ...] = ("Server",)

import uselect as select
import usocket as socket


class Server:
    """Base server that manages a bound socket registered with a poller.

    Subclasses should override or extend this to implement protocol-specific
    request handling (e.g. DNS or HTTP).
    """

    def __init__(
        self, poller: select.poll, port: int, sock_type: int, name: str
    ) -> None:
        """Initialise the server, bind to *port*, and register with *poller*.

        Args:
            poller: The shared poll object used to monitor socket events.
            port: The port number to bind to.
            sock_type: Socket type constant (``socket.SOCK_STREAM`` for TCP,
                ``socket.SOCK_DGRAM`` for UDP).
            name: A human-readable name for log messages.
        """
        self.name: str = name
        # create socket with correct type: stream (TCP) or datagram (UDP)
        self.sock: socket.socket = socket.socket(socket.AF_INET, sock_type)

        # register to get event updates for this socket
        self.poller: select.poll = poller
        self.poller.register(self.sock, select.POLLIN)

        addr = socket.getaddrinfo("0.0.0.0", port)[0][-1]
        # allow new requests while still sending last response
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(addr)

        print(self.name, "listening on", addr)

    def stop(self, poller: select.poll) -> None:
        """Unregister the socket from *poller* and close it.

        Args:
            poller: The poll object the socket was registered with.
        """
        poller.unregister(self.sock)
        self.sock.close()
        print(self.name, "stopped")
