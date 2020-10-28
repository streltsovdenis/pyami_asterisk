import asyncio
import logging
from collections import deque

from .action import Action
from .event import Event
from .utils import _convert_dict_to_bytes, EOL, IdGenerator, _convert_bytes_to_dict


class AMIClient:
    defaults = dict(host="127.0.0.1", port=5038, ping_delay=2)

    def __init__(self, **config):
        self.config = dict(self.defaults, **config)
        self.ping_delay = int(self.config["ping_delay"])
        self.log = config.get('log', logging.getLogger(__name__))
        self._dq = deque()
        self._reader = None
        self._writer = None
        self._connected = False
        self._authenticated = None
        self.ami_version = None
        self._patterns = list()
        self._actions = list()
        self._actionsdq = deque()
        self._asyncio_tasks = list()
        self._loop = config.get('loop', None)

    async def _open_connection(self):
        try:
            connection = asyncio.open_connection(self.config["host"], self.config["port"], loop=self._loop)
            self._reader, self._writer = await asyncio.wait_for(connection, timeout=3)
            return True
        except (asyncio.exceptions.TimeoutError, ConnectionRefusedError):
            self.log.error(f"Connection failed ({self.config['host']}, {self.config['port']})")
        return False

    async def _connect_ami(self):
        self._connected = await self._open_connection()
        if not self._connected:
            await self._connection_lost()
        self._authenticated = await self._login()
        if not self._authenticated:
            await self._connection_close()
        else:
            if len(self._actionsdq) != 0:
                await Action(self._actions, self._actions_task).__call__(self._send_action)
                self._actionsdq.pop()
            if self._asyncio_tasks != list():
                for task in self._asyncio_tasks:
                    asyncio.create_task(task)
            if self.ping_delay > 0:
                self._service_ping()
            await self._event_listener()

    async def _login(self):
        action_id_generator = IdGenerator('action')
        await self._send_action(
            {
                "Action": "Login",
                "ActionID": action_id_generator(),
                "Username": self.config["username"],
                "Secret": self.config["secret"],
            }
        )
        data = await self._reader.readuntil(separator=EOL * 2)
        if data.decode().split(EOL.decode())[1] == "Response: Success" and \
                data.decode().split(EOL.decode())[-3] == "Message: Authentication accepted":
            self.ami_version = data.decode().split(EOL.decode())[0]
            return True
        self.log.error("Authentication failed")
        return False

    async def _actions_task(self, action, repeat, _service=False):
        generator = IdGenerator('action')
        while self._connected:
            action['ActionID'] = generator()
            if _service:
                if len(self._dq) > 3:
                    await self._connection_lost()
                self._dq.appendleft(action['ActionID'])
            await self._send_action(action)
            await asyncio.sleep(repeat)

    async def _add_actionid_send(self):
        if len(self._actionsdq) != 0:
            await self._send_action(Action.add_actionid(self._actions[-1])['action'][0])
            await self._writer.drain()
            self._actionsdq.pop()

    async def _event_listener(self):
        while self._connected:
            await self._add_actionid_send()
            try:
                try:
                    data = await self._reader.readuntil(separator=EOL * 2)
                except asyncio.exceptions.LimitOverrunError as e:
                    data = await self._reader.read(e.consumed) + await self._reader.readline()
                if data == "".encode():
                    continue
                if "Event: Shutdown".encode() in data:
                    self.log.warning("Asterisk is shutdown or restarted")
                    await self._connection_lost()
                if "ActionID".encode() in data:
                    if _convert_bytes_to_dict(data)['ActionID'] in self._dq:
                        self._dq.pop()
                        continue
                if self._patterns != list():
                    Event(self._patterns, data).__call__()
                await self._add_actionid_send()
                self._actions = Action.action_callbacks(self._actions, data)
            except (asyncio.exceptions.IncompleteReadError, TimeoutError):
                await self._connection_lost()

            if self._patterns == list() and self._actions == list():
                await self._connection_close()

    async def _send_action(self, action: dict):
        self._writer.write(_convert_dict_to_bytes(action))
        await self._writer.drain()

    async def _connection_close(self):
        """Close the connection"""
        self._connected = False
        self._writer.close()
        await self._writer.wait_closed()

    def _service_ping(self):
        asyncio.create_task(self._actions_task({"Action": "Ping"}, self.ping_delay, _service=True))

    async def _connection_lost(self):
        self._connected = False
        await self._connect_ami()

    def register_event(self, patterns: list, callbacks: object):
        for pattern in patterns:
            self._patterns.append({pattern: callbacks})

    def create_action(self, action, callbacks: object, repeat=None):
        self._actions.append({'action': [action, callbacks], 'repeat': repeat})
        self._actionsdq.appendleft(self._actions[0])

    def create_asyncio_task(self, tasks: list):
        self._asyncio_tasks.append(*tasks)

    def connect(self):
        asyncio.run(self._connect_ami())
