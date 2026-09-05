PLUGINS = {}


def register(name, callback):
    PLUGINS[name] = callback


def invoke(name, payload):
    handler = PLUGINS.get(name)
    return handler(payload) if handler else None


def invoke_attribute(target, method_name, payload):
    return getattr(target, method_name)(payload)
