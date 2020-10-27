from .utils import _convert_bytes_to_dict


class Event:
    def __init__(self, patterns, data):
        self.patterns = patterns
        self.data = _convert_bytes_to_dict(data)

    def __call__(self):
        for pattern in self.patterns:
            if "*" in pattern.keys():
                pattern.get("*")(self.data)
            if "*" not in pattern.keys() and list(pattern.keys())[0] in self.data.values():
                list(pattern.values())[0](self.data)
