import asyncio
import logging
from types import SimpleNamespace

import h11
from uvicorn.protocols.http.h11_impl import RequestResponseCycle


def test_uvicorn_asgi_error_does_not_log_exception_secret(security_app, caplog, monkeypatch):
    async def scenario():
        logger = logging.getLogger("uvicorn.error")
        monkeypatch.setattr(logger, "disabled", False)
        logger.addHandler(caplog.handler)
        wire = []
        connection = h11.Connection(h11.SERVER)
        connection.receive_data(
            b"GET /api/v1/auth/security-test/failure HTTP/1.1\r\nHost: audit.invalid\r\n\r\n"
        )
        assert isinstance(connection.next_event(), h11.Request)
        assert isinstance(connection.next_event(), h11.EndOfMessage)
        event = asyncio.Event()
        event.set()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/auth/security-test/failure",
            "raw_path": b"/api/v1/auth/security-test/failure",
            "query_string": b"",
            "headers": [(b"host", b"audit.invalid")],
            "client": ("192.0.2.1", 1000),
            "server": ("audit.invalid", 80),
        }
        cycle = RequestResponseCycle(
            scope=scope,
            conn=connection,
            transport=SimpleNamespace(
                write=wire.append, close=lambda: None, is_closing=lambda: False
            ),
            flow=SimpleNamespace(write_paused=False, resume_reading=lambda: None),
            logger=logger,
            access_logger=logging.getLogger("uvicorn.access"),
            access_log=False,
            default_headers=[],
            message_event=event,
            on_response=lambda: None,
        )
        cycle.more_body = False
        try:
            await cycle.run_asgi(security_app.app)
        finally:
            logger.removeHandler(caplog.handler)
        assert b"500 Internal Server Error" in b"".join(wire)

    asyncio.run(scenario())
    records = [r for r in caplog.records if r.name == "uvicorn.error"]
    assert records
    rendered = "\n".join(logging.Formatter().format(record) for record in caplog.records)
    assert "B14-SYNTHETIC-SECRET-SENTINEL" not in rendered
