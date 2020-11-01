import asyncio
import contextlib
import socket
import sys
from pathlib import Path

import pytest
import yaml

file = Path(__file__).resolve()
parent, root = file.parent, file.parents[1]
sys.path.append(str(root))
from pyami_asterisk import AMIClient
from pyami_asterisk.utils import EOL, _convert_dict_to_bytes, _convert_bytes_to_dict


class GenActions:
    instanses = list()

    def __init__(self):
        self.instanses.append(self)
        self.gen = self.get_gen()
        self.response = ""

    def get_gen(self):
        with open("tests/fixtures/actions.txt", "rb") as resp_file:
            response = b""
            for resp in resp_file.readlines():
                response += resp
                if response.endswith(EOL * 2):
                    self.response = response.decode()
                    yield self.response
                    response = b""

    def __call__(self):
        return next(self.gen)

    def __repr__(self):
        return self.response


class GenActionsResponse:
    instanses = list()

    def __init__(self):
        self.instanses.append(self)
        self.gen = self.get_gen()
        self.response = ""

    def get_gen(self):
        with open("tests/fixtures/actions_response.txt", "rb") as resp_file:
            response = b""
            for resp in resp_file.readlines():
                response += resp
                if response.endswith(EOL * 2):
                    self.response = response.decode()
                    yield self.response
                    response = b""

    def __call__(self):
        return next(self.gen)

    def __repr__(self):
        return self.response


def unused_tcp_port_factory():
    """Find an unused localhost TCP port from 1024-65535 and return it."""
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def handle_echo(reader, writer, stream=None):
    while True:
        data = await reader.readuntil(separator=EOL * 2)
        message = _convert_bytes_to_dict(data)
        if message['Action'] == 'Login':
            response = "Asterisk Call Manager/5.0.1\r\n".encode()
            if (
                    message["Username"] == "valid_username"
                    and message["Secret"] == "valid_password"
            ):
                with open("tests/fixtures/login_ok.yaml") as conf:
                    auth_login = yaml.full_load(conf)
                response += _convert_dict_to_bytes(auth_login)
            else:
                with open("tests/fixtures/login_failed.yaml") as conf:
                    auth_login = yaml.full_load(conf)
                response += _convert_dict_to_bytes(auth_login)
            writer.write(response)
            await writer.drain()
            continue

        try:
            response = str(stream).encode()
            if b"EventList: start" in response:
                while True:
                    stream()
                    response += str(stream).encode()
                    if b"EventList: Complete" in response:
                        break
            writer.write(response)
            await writer.drain()
        except FileNotFoundError:
            writer.write(_convert_dict_to_bytes({'Response': 'Error', 'ActionID': message['ActionID']}))
            await writer.drain()


async def _server(stream=None, **config):
    HOST = "127.0.0.1"
    PORT = unused_tcp_port_factory()
    defaults = dict(host=HOST, port=PORT, ping_delay=0)
    config = dict(defaults, **config)
    server = await asyncio.start_server(
        lambda r, w: handle_echo(r, w, stream), HOST, PORT
    )
    asyncio.create_task(server.serve_forever())
    ami = AMIClient(**config)
    yield ami
    await ami._connection_close()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_connection():
    server = _server()
    ami = await server.asend(None)
    connect = await ami._open_connection()
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass
    assert connect is True


@pytest.mark.asyncio
async def test_login_ok():
    config = dict(username="valid_username", secret="valid_password")
    server = _server(stream="login_ok.yaml", **config)
    ami = await server.asend(None)
    try:
        await ami._open_connection()
        login = await ami._login()
    except ConnectionResetError:
        login = False
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass
    assert login is True


@pytest.mark.asyncio
async def test_login_failed():
    config = dict(username="not_valid_username", secret="not_valid_password")
    server = _server(stream="login_ok.yaml", **config)
    ami = await server.asend(None)
    try:
        await ami._open_connection()
        login = await ami._login()
    except ConnectionResetError:
        login = False
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass
    assert login is False


@pytest.mark.asyncio
async def test_actions():
    def callbacks(events):
        assert events == _convert_bytes_to_dict(str(generator_resp).encode())
        try:
            generator()
            generator_resp()
            ami.create_action(_convert_bytes_to_dict(str(generator).encode()), callbacks=callbacks)
        except StopIteration:
            pass

    config = dict(username="valid_username", secret="valid_password", ping_delay=0)
    generator_resp = GenActionsResponse()
    generator_resp()
    server = _server(stream=generator_resp, **config)
    ami = await server.asend(None)
    generator = GenActions()
    generator()
    ami.create_action(_convert_bytes_to_dict(str(generator).encode()), callbacks=callbacks)
    try:
        await ami._connect_ami()
    except ConnectionResetError:
        assert False
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass
