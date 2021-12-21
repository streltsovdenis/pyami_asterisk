import asyncio
import logging
from .utils import _convert_dict_to_bytes, EOL, IdGenerator, _convert_bytes_to_dict


class AMIClient:
    defaults = dict(host="127.0.0.1",
                    port=5038,
                    ping_delay=5,
                    reconnect_timeout=5,
                    reconnect_timeout_increase=0,
                    ami_version=False)

    def __init__(self, **config):
        """
        Config data connect to AMI
            Keyword Arguments:
                host (str): Asterisk AMI host
                port (int): Asterisk AMI port
                username (str): Asterisk AMI port
                secret (str): Asterisk AMI port
                ping_delay (int): Ping delay
                reconnect_timeout (int): Reconnect timeout
                reconnect_timeout_increase (int): Reconnect timeout increase
                ami_version (func): callback AMI version
        """
        self.config = dict(self.defaults, **config)
        self.ping_delay = int(self.config["ping_delay"])
        self.reconnect_timeout = int(self.config["reconnect_timeout"])
        self.reconnect_timeout_increase = int(self.config["reconnect_timeout_increase"])
        self.log = config.get('log', logging.getLogger(__name__))
        self._reader = None
        self._writer = None
        self._connected = False
        self._authenticated = None
        self.ami_version = self.config.get('ami_version')
        self._asyncio_tasks = list()
        self._patterns = list()
        self._data = asyncio.Queue()
        self._actions = list()
        self._actions_ids = dict()
        self._actions_queue = asyncio.Queue()
        self._actions_repeat = False
        self._actions_repeat_connections_lost = list()

    async def _open_connection(self):
        try:
            connection = asyncio.open_connection(self.config["host"], self.config["port"])
            self._reader, self._writer = await asyncio.wait_for(connection, timeout=5)
        except (asyncio.exceptions.TimeoutError, ConnectionRefusedError):
            if self.reconnect_timeout == 0:
                return False
            self.log.warning(f"Connection failed ({self.config['host']}, {self.config['port']}), next connection "
                             f"attempt in {self.reconnect_timeout} second(s)")
            await asyncio.sleep(self.reconnect_timeout)
            if self.reconnect_timeout_increase > 0:
                self.reconnect_timeout += self.reconnect_timeout_increase
            await self._open_connection()
        if self.reconnect_timeout_increase > 0:
            self.reconnect_timeout = int(self.config["reconnect_timeout"])
        return True

    async def _connect_ami(self):
        self._connected = await self._open_connection()
        if not self._connected:
            return
        self._authenticated = await self._login()
        if not self._authenticated:
            return
        await self._handler_tasks()

    async def _handler_tasks(self):
        if self._actions != list():
            for action in self._actions:
                if action['repeat'] > 0:
                    asyncio.create_task(self._actions_task_repeat(action))
                    self._actions_repeat = True
                    self._actions_repeat_connections_lost.append(action)
                else:
                    await self._send_action(action['action'], callback=action['callback'])
            self._actions.clear()
        if self._asyncio_tasks != list():
            for task in self._asyncio_tasks:
                asyncio.create_task(task)
        self._service_ping()
        await self._event_listener()

    async def _login(self):
        await self._send_action({
            "Action": "Login",
            "Username": self.config["username"],
            "Secret": self.config["secret"],
        })
        data = await self._reader.readuntil(separator=EOL * 2)
        if data.decode().split(EOL.decode())[1] == "Response: Success" and \
                data.decode().split(EOL.decode())[-3] == "Message: Authentication accepted":
            self.ami_version = data.decode().split(EOL.decode())[0]
            if self.config.get('ami_version'):
                self.config.get('ami_version')(dict(AMI_version=self.ami_version))
            self._actions_ids.clear()
            return True
        self.log.error("Authentication failed")
        return False

    async def _actions_task_repeat(self, action: dict):
        generator = IdGenerator('action')
        while self._connected:
            action.get('action')['ActionID'] = generator()
            await self._send_action(action.get('action'), action.get('callback'))
            await asyncio.sleep(action.get('repeat'))

    async def _event_listener(self):
        while self._connected:
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
                    response = _convert_bytes_to_dict(data)
                    if response['ActionID'] in self._actions_ids.keys():
                        if self._actions_ids.get(response['ActionID']).get('callback') is not None:
                            self._actions_queue.put_nowait((self._actions_ids.get(response['ActionID']), response))
                            asyncio.create_task(self._actions_callbacks())
                            if response.get('Message', '').endswith('successfully queued') \
                                    and self._actions_ids.get(response['ActionID'])[
                                        'action'].get('Async', "false") == 'true' \
                                    or response.get('EventList', '') == 'start':
                                self._actions_ids.get(response['ActionID'])['wait_next'] = True
                            elif response.get('Response') in ('Success', 'Error', 'Fail', 'Failure'):
                                self._actions_ids.get(response['ActionID'])['wait_next'] = False
                            elif response.get('Event').endswith('Complete'):
                                self._actions_ids.get(response['ActionID'])['wait_next'] = False
                        if not self._actions_ids.get(response['ActionID'])['wait_next']:
                            self._actions_ids.pop(response['ActionID'])
                        await self._check_empty()
                        continue

                if self._patterns != list():
                    self._data.put_nowait(_convert_bytes_to_dict(data))
                    asyncio.create_task(self._events_callbacks())

                await self._check_empty()
            except (asyncio.exceptions.IncompleteReadError, TimeoutError, RuntimeError, ConnectionResetError):
                await self._connection_lost()

    async def _check_empty(self):
        if self._patterns == list() and self._actions_ids == dict() and not self._actions_repeat:
            await self._connection_close()

    async def _actions_callbacks(self):
        action, response = await self._actions_queue.get()
        if asyncio.iscoroutinefunction(action.get('callback')):
            await action.get('callback')(response)
        else:
            action.get('callback')(response)
        self._actions_queue.task_done()

    async def _events_callbacks(self):
        data = await self._data.get()
        for pattern in self._patterns:
            if "*" == list(pattern.keys())[0]:
                if asyncio.iscoroutinefunction(pattern.get("*")):
                    await pattern.get("*")(data)
                else:
                    pattern.get("*")(data)
            if "*" != list(pattern.keys())[0] and list(pattern.keys())[0] == data.get('Event'):
                if asyncio.iscoroutinefunction(list(pattern.values())[0]):
                    await list(pattern.values())[0](data)
                else:
                    list(pattern.values())[0](data)
        if self._actions != list():
            for action in self._actions:
                await self._send_action(action.get('action'), callback=action.get('callback'))
            self._actions.clear()
        self._data.task_done()

    async def _send_action(self, action: dict, callback: object = None):
        if "ActionID" not in action.keys():
            action_id_generator = IdGenerator('action')
            action['ActionID'] = action_id_generator()
        # if callback is not None:
        self._actions_ids[action['ActionID']] = {'action': action, 'callback': callback, 'wait_next': False}
        self._writer.write(_convert_dict_to_bytes(action))
        try:
            await self._writer.drain()
        except ConnectionResetError:
            await self._connection_lost()

    async def _connection_close(self):
        """Close the connection"""
        self._connected = False
        self._writer.close()
        await self._writer.wait_closed()

    def _service_ping(self):
        if self.ping_delay > 0:
            asyncio.create_task(self._actions_task_repeat({'action': {"Action": "Ping"}, 'repeat': self.ping_delay}))

    async def _connection_lost(self):
        self._connected = False
        self._authenticated = False
        if self._actions_repeat:
            self._actions = self._actions_repeat_connections_lost.copy()
            self._actions_repeat = False
        await self._connect_ami()

    def register_event(self, patterns: list, callbacks: object):
        for pattern in patterns:
            self._patterns.append({pattern: callbacks})

    def create_action(self, action: dict, callback: object, repeat: int = False):
        self._actions.append({'action': action, 'callback': callback, 'repeat': repeat})

    def create_asyncio_task(self, tasks: list):
        for task in tasks:
            self._asyncio_tasks.append(task)

    def connect(self):
        asyncio.run(self._connect_ami())
