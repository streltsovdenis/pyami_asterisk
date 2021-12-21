import asyncio
import contextlib
import os
import socket
import sys
from pathlib import Path

import pytest

file = Path(__file__).resolve()
parent, root = file.parent, file.parents[1]
sys.path.append(str(root))
from pyami_asterisk import AMIClient
from pyami_asterisk.utils import EOL, _convert_dict_to_bytes, _convert_bytes_to_dict


def replace_EOL():
    for _ in os.listdir(os.path.abspath(str(parent) + "/fixtures/")):
        with open(str(parent) + "/fixtures/" + _, "rb") as f:
            data = f.read().replace(b"\r\n", b"\n")
            data = data.replace(b"\n", b"\r\n")
        with open(str(parent) + "/fixtures/" + _, "wb") as f:
            f.write(data)


replace_EOL()


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
            if (message["Username"] == "valid_username" and message["Secret"] == "valid_password"):
                with open("tests/fixtures/login_ok.txt", "rb") as login_file:
                    response += login_file.read()
            else:
                with open("tests/fixtures/login_failed.txt", "rb") as login_fail_file:
                    response += login_fail_file.read()
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
    server = await asyncio.start_server(lambda r, w: handle_echo(r, w, stream), HOST, PORT)
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
    server = _server(**config)
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
    server = _server(**config)
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
