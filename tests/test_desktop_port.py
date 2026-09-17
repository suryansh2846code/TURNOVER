"""The webview origin must survive a quit.

localStorage is keyed to the origin, so a launch that lands on a different port
loses the onboarding flag, the chosen model and the lead agent — the app opens
looking empty. That happened on the first launch after every quit: the port
probe bound without SO_REUSEADDR, so a port left in TIME_WAIT by the server
that had just exited read as taken, even though uvicorn would have bound it.
"""
import socket

from chitragupta.desktop import _reserve_port

HOST = "127.0.0.1"


def _leave_in_time_wait(port: int) -> None:
    """Quit the app the way a real quit leaves the port behind."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(1)
    client = socket.create_connection((HOST, port))
    accepted, _ = srv.accept()
    srv.close()
    client.close()
    accepted.close()          # connection now sits in TIME_WAIT


def test_the_port_survives_a_quit():
    port, sock = _reserve_port(HOST)
    sock.close()
    _leave_in_time_wait(port)

    again, sock2 = _reserve_port(HOST)
    try:
        assert again == port, (
            f"relaunch moved to port {again} (was {port}) — the webview origin "
            "changed, so the user's localStorage is gone and the app looks empty")
    finally:
        sock2.close()


def test_the_reserved_socket_is_ready_to_serve():
    """We hand this socket to uvicorn, so it must already be listening."""
    port, sock = _reserve_port(HOST)
    try:
        with socket.create_connection((HOST, port), timeout=2):
            pass
    finally:
        sock.close()


def test_a_port_held_by_a_live_server_is_not_stolen():
    """A genuinely occupied port must fall back, not collide."""
    port, sock = _reserve_port(HOST)
    try:
        other, sock2 = _reserve_port(HOST)
        try:
            assert other != port, "handed out a port another server is listening on"
        finally:
            sock2.close()
    finally:
        sock.close()
