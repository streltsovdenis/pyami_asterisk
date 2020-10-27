import asyncio

from .utils import IdGenerator, _convert_bytes_to_dict


class Action:
    def __init__(self, actions, tasks):
        self.actions = actions
        self._actions_task = tasks

    async def __call__(self, send_action):
        for action in self.actions:
            if action['repeat'] is not None:
                asyncio.create_task(self._actions_task(action['action'][0], action['repeat']))
            await send_action(self.add_actionid(action)['action'][0])

    @staticmethod
    def add_actionid(action):
        if "ActionID" not in action['action'][0]:
            action_id_generator = IdGenerator('action')
            action['action'][0]['ActionID'] = action_id_generator()
        return action

    @staticmethod
    def action_callbacks(actions, data):
        for action in actions:
            if type(data) is bytes:
                data = _convert_bytes_to_dict(data)
            try:
                if action['action'][0]['ActionID'] in data.values():
                    action['action'][-1](data)
                    if 'Originate successfully queued' in data.values():
                        # del actions[actions.index(action)]
                        continue
                    try:
                        if action['repeat'] is None or action['repeat'] is True:
                            if data['EventList'] == 'start':
                                action['repeat'] = True
                                continue
                            if data['EventList'] == 'Complete':
                                action['repeat'] = None
                                raise KeyError
                    except KeyError:
                        if action['repeat'] is None:
                            del actions[actions.index(action)]
            except KeyError:
                continue
        return actions
