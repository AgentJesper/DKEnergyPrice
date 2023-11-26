from connectors import Connectors
from importlib import import_module
connectors=Connectors()
cnts = connectors.get_connectors('DK1')
today = None
tomorrow = None
today_calculated = False
tomorrow_calculated = False

for endpoint in cnts:
    module = import_module(
        endpoint.namespace, __name__.removesuffix(".api")
    )
    api = module.Connector(
        self._region, self._client, self._tz, self._config
    )