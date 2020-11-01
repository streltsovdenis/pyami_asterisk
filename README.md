AsyncIO python library with Asterisk AMI
========================================

[![Build Status](https://travis-ci.com/streltsovdenis/pyami_asterisk.svg?branch=main)](https://travis-ci.com/streltsovdenis/pyami_asterisk)
![PyPI](https://img.shields.io/pypi/v/pyami_asterisk)
![PyPI - Downloads](https://img.shields.io/pypi/dm/pyami_asterisk?color=green)
![PyPI - License](https://img.shields.io/pypi/l/pyami-asterisk?color=green)

Pyami_asterisk is a library based on python’s AsyncIO with Asterisk AMI

Install
-------

Install pyami_asterisk

```
pip install pyami-asterisk
```

Usage
-----

Asterisk AMI Listen all Events

```python
from pyami_asterisk import AMIClient


def all_events(events):
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(["*"], all_events)
ami.connect()
```

Asterisk AMI Listen Events: Registry, ContactStatus, PeerStatus

```python
from pyami_asterisk import AMIClient


def register_multiple_events(events):
    print(events)


def callback_peer_status(events):
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(patterns=["Registry", "ContactStatus"], callbacks=register_multiple_events)
ami.register_event(["PeerStatus"], callback_peer_status)
ami.connect()
```

Asterisk AMI Actions: CoreSettings

```python
from pyami_asterisk import AMIClient


def core_settings(events):
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_action({"Action": "CoreSettings"}, core_settings)
ami.connect()
```

Asterisk AMI Actions: CoreSettings, CoreStatus (repeat 3 seconds)

```python
from pyami_asterisk import AMIClient


def core_settings(events):
    print(events)


def core_status(events):
    print(events)
    print(events['CoreCurrentCalls'])


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_action({"Action": "CoreSettings"}, core_settings)
ami.create_action({"Action": "CoreStatus"}, core_status, repeat=3)
ami.connect()
```

Asterisk AMI Action Originate

```python
from pyami_asterisk import AMIClient


def callback_originate(events):
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_action(
    {
        "Action": "Originate",
        "Channel": "pjsip/203",
        "Timeout": "20000",
        "CallerID": "+37529XXXXXXX <203>",
        "Exten": "+37529XXXXXXX",
        "Context": "from-internal",
        "Async": "true",
        "Variable": r"PJSIP_HEADER(add,Call-Info)=\;Answer-After=0",
        "Priority": "1",
    },
    callback_originate,
)
ami.connect()
```

Asterisk AMI Listen Events + Action

```python
from pyami_asterisk import AMIClient


def callback_peer_status(events):
    def callback_ping(response_ping):
        print("Response Ping", response_ping)

    print("PeerStatus", events)
    ami.create_action({"Action": "Ping"}, callback_ping)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(["PeerStatus"], callback_peer_status)
ami.connect()
```

Create asyncio task

```python
import asyncio
import random
from pyami_asterisk import AMIClient


async def refresh_tokens(timeout=4):
    """Example: Refresh tokens"""
    while True:
        print(random.randrange(0, 1000))
        await asyncio.sleep(timeout)
    


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_asyncio_task(tasks=[refresh_tokens(timeout=2)])
ami.connect()
```