"""Captive DNS server implementation.

A simple DNS server that responds to all queries with the same IP address,
which is useful for captive portals where you want to redirect all traffic
to a specific page.
"""

__all__: tuple[str, ...] = ("DNSServer",)

import gc

import uselect as select
import usocket as socket
from server import Server


class DNSQuery:
    """Minimal DNS query parser.

    Extracts the requested domain name from a raw DNS query packet so that
    a spoofed A-record answer can be constructed.
    """

    def __init__(self, data: bytes) -> None:
        """Parse *data* and extract the queried domain name.

        Args:
            data: The raw DNS query bytes received from a client.
        """
        self.data: bytes = data
        self.domain: str = ""
        # header is bytes 0-11, so question starts on byte 12
        head: int = 12
        # length of this label defined in first byte
        length: int = data[head]
        while length != 0:
            label: int = head + 1
            # add the label to the requested domain and insert a dot after
            self.domain += data[label : label + length].decode("utf-8") + "."
            # check if there is another label after this one
            head += length + 1
            length = data[head]

    def answer(self, ip_addr: str) -> bytes:
        """Build a DNS response packet that resolves to *ip_addr*.

        The response mirrors the original query and appends a single A-record
        answer pointing to the given IP address with a 60-second TTL.

        Args:
            ip_addr: The IPv4 address string (e.g. ``"192.168.4.1"``) to
                return in the answer.

        Returns:
            The complete DNS response packet as bytes.
        """
        # ** create the answer header **
        # copy the ID from incoming request
        packet: bytes = self.data[:2]
        # set response flags (assume RD=1 from request)
        packet += b"\x81\x80"
        # copy over QDCOUNT and set ANCOUNT equal
        packet += self.data[4:6] + self.data[4:6]
        # set NSCOUNT and ARCOUNT to 0
        packet += b"\x00\x00\x00\x00"

        # ** create the answer body **
        # respond with original domain name question
        packet += self.data[12:]
        # pointer back to domain name (at byte 12)
        packet += b"\xc0\x0c"
        # set TYPE and CLASS (A record and IN class)
        packet += b"\x00\x01\x00\x01"
        # set TTL to 60sec
        packet += b"\x00\x00\x00\x3c"
        # set response length to 4 bytes (to hold one IPv4 address)
        packet += b"\x00\x04"
        # now actually send the IP address as 4 bytes (without the "."s)
        packet += bytes(map(int, ip_addr.split(".")))

        gc.collect()

        return packet


class DNSServer(Server):
    """DNS server that resolves every query to a single IP address.

    Used by the captive portal to redirect all DNS look-ups to the
    ESP8266's own access-point IP so that clients land on the
    configuration page regardless of the domain they request.
    """

    def __init__(self, poller: select.poll, ip_addr: str) -> None:
        """Create the DNS server bound to UDP port 53.

        Args:
            poller: The shared poll object used to monitor socket events.
            ip_addr: The IPv4 address to return for every DNS query.
        """
        super().__init__(poller, 53, socket.SOCK_DGRAM, "DNS Server")
        self.ip_addr: str = ip_addr

    def handle(self, sock: socket.socket, event: int, others: list[int]) -> None:
        """Handle an incoming DNS request on *sock*.

        Reads the query, constructs a spoofed A-record answer pointing to
        :attr:`ip_addr`, and sends it back to the sender.

        Args:
            sock: The socket that received the event.
            event: The poll event flags (e.g. ``select.POLLIN``).
            others: Additional event data from ``ipoll`` (typically unused).
        """
        # server doesn't spawn other sockets, so only respond to its own socket
        if sock is not self.sock:
            return

        # check the DNS question, and respond with an answer
        try:
            data, sender = sock.recvfrom(1024)
            request = DNSQuery(data)

            print("Sending {:s} -> {:s}".format(request.domain, self.ip_addr))
            sock.sendto(request.answer(self.ip_addr), sender)

            # help MicroPython with memory management
            del request
            gc.collect()
        except Exception as e:
            print("DNS server exception:", e)
