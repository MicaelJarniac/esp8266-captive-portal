"""HTTP server for the captive portal.

Serves the WiFi configuration page and handles credential submission via an
HTTP-based request/response flow over TCP.
"""

__all__: tuple[str, ...] = ("HTTPServer",)

import gc
from collections import namedtuple

import micropython
import uerrno
import uio
import uselect as select
import usocket as socket
from credentials import Creds
from server import Server

# body: file-like readable stream (supports ``readinto``)
# buff: mutable byte buffer for outgoing TCP data
# buffmv: memoryview over *buff* for zero-copy slicing
# write_range: two-element list ``[start, end]`` tracking the next slice to send
WriteConn = namedtuple("WriteConn", ["body", "buff", "buffmv", "write_range"])

# type: HTTP method (e.g. ``b"GET"``)
# path: request path (e.g. ``b"/login"``)
# params: dict of query-string key/value pairs
# host: value of the ``Host`` header
ReqInfo = namedtuple("ReqInfo", ["type", "path", "params", "host"])


def unquote(string: str | bytes | None) -> bytes:
    """Decode a percent-encoded URL component into raw bytes.

    A stripped-down implementation of :func:`urllib.parse.unquote_to_bytes`
    suitable for MicroPython.  Plus signs are decoded as spaces.

    Args:
        string: The URL-encoded value to decode.  May be ``str``, ``bytes``,
            or ``None``.

    Returns:
        The decoded byte string, or an empty ``bytes`` object when *string*
        is falsy.
    """

    if not string:
        return b""

    if isinstance(string, str):
        string = string.encode("utf-8")
    string = string.replace(b"+", b" ")

    # split into substrings on each escape character
    bits = string.split(b"%")
    if len(bits) == 1:
        return string  # there was no escape character

    res: list[bytes] = [bits[0]]  # everything before the first escape character

    # for each escape character, get the next two digits and convert to byte
    for item in bits[1:]:
        code = item[:2]
        char = bytes([int(code, 16)])  # convert to utf-8-encoded byte
        res.append(char)  # append the converted character
        res.append(
            item[2:]
        )  # append anything else that occurred before the next escape character

    return b"".join(res)


class HTTPServer(Server):
    """HTTP server that serves the captive portal configuration page.

    On first boot the server presents an ``index.html`` form for entering
    WiFi credentials.  After a successful connection the route table is
    swapped to show a "connected" confirmation page instead.
    """

    def __init__(self, poller: select.poll, local_ip: str | bytes) -> None:
        """Create the HTTP server bound to TCP port 80.

        Args:
            poller: The shared poll object used to monitor socket events.
            local_ip: The IP address of the captive portal, as a string or
                bytes object.
        """
        super().__init__(poller, 80, socket.SOCK_STREAM, "HTTP Server")
        if isinstance(local_ip, bytes):
            self.local_ip: bytes = local_ip
        else:
            self.local_ip = local_ip.encode()
        self.request: dict[int, bytes] = dict()
        self.conns: dict[int, WriteConn] = dict()
        self.routes = {b"/": b"./index.html", b"/login": self.login}

        self.ssid: bytes | None = None

        # queue up to 5 connection requests before refusing
        self.sock.listen(5)
        self.sock.setblocking(False)

    def set_ip(self, new_ip: str, new_ssid: bytes) -> None:
        """Update settings after connecting to the local WiFi network.

        Replaces the route table so that the root URL now shows the
        "connected" confirmation page.

        Args:
            new_ip: The new local IP address obtained via DHCP.
            new_ssid: The SSID of the network that was joined.
        """

        self.local_ip = new_ip.encode()
        self.ssid = new_ssid
        self.routes = {b"/": self.connected}

    @micropython.native
    def handle(self, sock: socket.socket, event: int, others: list[int]) -> None:
        """Dispatch an HTTP socket event.

        Depending on the event type this method will accept a new
        connection, read incoming data, or continue writing a response.

        Args:
            sock: The socket that triggered the event.
            event: The poll event flags.
            others: Additional event data from ``ipoll``.
        """
        if sock is self.sock:
            # client connecting on port 80, so spawn off a new
            # socket to handle this connection
            print("- Accepting new HTTP connection")
            self.accept(sock)
        elif event & select.POLLIN:
            # socket has data to read in
            print("- Reading incoming HTTP data")
            self.read(sock)
        elif event & select.POLLOUT:
            # existing connection has space to send more data
            print("- Sending outgoing HTTP data")
            self.write_to(sock)

    def accept(self, server_sock: socket.socket) -> None:
        """Accept a new client connection and register it for polling.

        Args:
            server_sock: The listening server socket.
        """

        try:
            client_sock, addr = server_sock.accept()
        except OSError as e:
            if e.args[0] == uerrno.EAGAIN:
                return

        client_sock.setblocking(False)
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.poller.register(client_sock, select.POLLIN)

    def parse_request(self, req: bytes) -> ReqInfo:
        """Parse a raw HTTP request into its constituent parts.

        Args:
            req: The full HTTP request as raw bytes.

        Returns:
            A :class:`ReqInfo` named tuple containing the HTTP method,
            path, query parameters, and ``Host`` header value.
        """

        req_lines = req.split(b"\r\n")
        req_type, full_path, http_ver = req_lines[0].split(b" ")
        path = full_path.split(b"?")
        base_path = path[0]
        query = path[1] if len(path) > 1 else None
        query_params: dict[bytes, bytes] = (
            {
                key: val
                for key, val in [param.split(b"=") for param in query.split(b"&")]
            }
            if query
            else {}
        )
        host = [line.split(b": ")[1] for line in req_lines if b"Host:" in line][0]

        return ReqInfo(req_type, base_path, query_params, host)

    def login(self, params: dict[bytes, bytes]) -> tuple[bytes, bytes]:
        """Handle a login form submission.

        Extracts the SSID and password from the query parameters, saves
        them to disk, and responds with a redirect back to the portal root.

        Args:
            params: Query-string parameters from the login request.

        Returns:
            A ``(body, headers)`` tuple for the HTTP response.
        """
        ssid = unquote(params.get(b"ssid", None))
        password = unquote(params.get(b"password", None))

        # Write out credentials
        Creds(ssid=ssid, password=password).write()

        headers = (
            b"HTTP/1.1 307 Temporary Redirect\r\nLocation: http://{:s}\r\n".format(
                self.local_ip
            )
        )

        return b"", headers

    def connected(self, params: dict[bytes, bytes]) -> tuple[bytes, bytes]:
        """Serve the "connected" confirmation page.

        Args:
            params: Query-string parameters (unused).

        Returns:
            A ``(body, headers)`` tuple containing the rendered HTML and
            a ``200 OK`` status line.
        """
        headers = b"HTTP/1.1 200 OK\r\n"
        body = open("./connected.html", "rb").read() % (self.ssid, self.local_ip)
        return body, headers

    def get_response(self, req: ReqInfo) -> tuple[uio.BufferedIOBase, bytes]:
        """Generate an HTTP response body and headers for the given request.

        Routes mapped to ``bytes`` values are treated as file paths whose
        contents are streamed back.  Routes mapped to callables are invoked
        with the request parameters.  Unrecognized routes receive a 404.

        Args:
            req: The parsed request information.

        Returns:
            A ``(body_stream, headers)`` tuple where *body_stream* is a
            file-like object supporting ``readinto``.
        """

        headers = b"HTTP/1.1 200 OK\r\n"
        route = self.routes.get(req.path, None)

        if isinstance(route, bytes):
            # expect a filename, so return contents of file
            return open(route, "rb"), headers

        if callable(route):
            # call a function, which may or may not return a response
            response = route(req.params)
            body = response[0] or b""
            headers = response[1] or headers
            return uio.BytesIO(body), headers

        headers = b"HTTP/1.1 404 Not Found\r\n"
        return uio.BytesIO(b""), headers

    def is_valid_req(self, req: ReqInfo) -> bool:
        """Check whether the request targets a known route on this server.

        Requests whose ``Host`` header does not match :attr:`local_ip` are
        considered invalid so that a redirect can be issued.

        Args:
            req: The parsed request information.

        Returns:
            ``True`` if the request is for a valid route on this host.
        """
        if req.host != self.local_ip:
            # force a redirect to the MCU's IP address
            return False
        # redirect if we don't have a route for the requested path
        return req.path in self.routes

    def read(self, s: socket.socket) -> None:
        """Read incoming data from a client socket and dispatch the request.

        Data is buffered until a complete HTTP request (terminated by a
        blank line) is received.  Once complete the request is parsed and
        either served or redirected.

        Args:
            s: The client socket to read from.
        """

        data = s.read()
        if not data:
            # no data in the TCP stream, so close the socket
            self.close(s)
            return

        # add new data to the full request
        sid = id(s)
        self.request[sid] = self.request.get(sid, b"") + data

        # check if additional data expected
        if data[-4:] != b"\r\n\r\n":
            # HTTP request is not finished if no blank line at the end
            # wait for next read event on this socket instead
            return

        # get the completed request
        req = self.parse_request(self.request.pop(sid))

        if not self.is_valid_req(req):
            headers = (
                b"HTTP/1.1 307 Temporary Redirect\r\nLocation: http://{:s}/\r\n".format(
                    self.local_ip
                )
            )
            body = uio.BytesIO(b"")
            self.prepare_write(s, body, headers)
            return

        # by this point, we know the request has the correct
        # host and a valid route
        body, headers = self.get_response(req)
        self.prepare_write(s, body, headers)

    def prepare_write(
        self, s: socket.socket, body: uio.BufferedIOBase, headers: bytes
    ) -> None:
        """Buffer the response headers and first chunk of body for sending.

        Creates a :class:`WriteConn` that tracks write progress and switches
        the socket's poll registration to ``POLLOUT``.

        Args:
            s: The client socket to write to.
            body: A file-like stream containing the response body.
            headers: The raw HTTP response headers.
        """
        # add newline to headers to signify transition to body
        headers += "\r\n"
        # TCP/IP MSS is 536 bytes, so create buffer of this size and
        # initially populate with header data
        buff = bytearray(headers + "\x00" * (536 - len(headers)))
        # use memoryview to read directly into the buffer without copying
        buffmv = memoryview(buff)
        # start reading body data into the memoryview starting after
        # the headers, and writing at most the remaining space of the buffer
        # return the number of bytes written into the memoryview from the body
        bw = body.readinto(buffmv[len(headers) :], 536 - len(headers))
        # save place for next write event
        c = WriteConn(body, buff, buffmv, [0, len(headers) + bw])
        self.conns[id(s)] = c
        # let the poller know we want to know when it's OK to write
        self.poller.modify(s, select.POLLOUT)

    def write_to(self, sock: socket.socket) -> None:
        """Write the next chunk of response data to an open socket.

        If all data has been sent (or the write produced fewer bytes than
        the TCP MSS) the connection is closed.  Otherwise the buffer is
        advanced for the next ``POLLOUT`` event.

        Args:
            sock: The client socket to write to.
        """

        # get the data that needs to be written to this socket
        c = self.conns[id(sock)]
        if c:
            # write next 536 bytes (max) into the socket
            try:
                bytes_written = sock.write(
                    c.buffmv[c.write_range[0] : c.write_range[1]]
                )
            except OSError:
                print("cannot write to a closed socket")
                return
            if not bytes_written or c.write_range[1] < 536:
                # either we wrote no bytes, or we wrote < TCP MSS of bytes
                # so we're done with this connection
                self.close(sock)
            else:
                # more to write, so read the next portion of the data into
                # the memoryview for the next send event
                self.buff_advance(c, bytes_written)

    def buff_advance(self, c: WriteConn, bytes_written: int) -> None:
        """Advance the write buffer to the next outgoing chunk.

        If all buffered bytes were sent, reads the next portion of the body
        into the buffer from the beginning.  Otherwise adjusts the start
        offset to resume where the last write left off.

        Args:
            c: The active write-connection state.
            bytes_written: Number of bytes successfully sent in the last
                write.
        """

        if bytes_written == c.write_range[1] - c.write_range[0]:
            # wrote all the bytes we had buffered into the memoryview
            # set next write start on the memoryview to the beginning
            c.write_range[0] = 0
            # set next write end on the memoryview to length of bytes
            # read in from remainder of the body, up to TCP MSS
            c.write_range[1] = c.body.readinto(c.buff, 536)
        else:
            # didn't read in all the bytes that were in the memoryview
            # so just set next write start to where we ended the write
            c.write_range[0] += bytes_written

    def close(self, s: socket.socket) -> None:
        """Close a client socket, unregister it, and free associated resources.

        Args:
            s: The client socket to close.
        """
        s.close()
        self.poller.unregister(s)
        sid = id(s)
        if sid in self.request:
            del self.request[sid]
        if sid in self.conns:
            del self.conns[sid]
        gc.collect()
