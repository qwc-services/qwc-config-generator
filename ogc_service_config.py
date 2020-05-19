from collections import OrderedDict

from service_config import ServiceConfig


class OGCServiceConfig(ServiceConfig):
    """OGCServiceConfig class

    Generate OGC service config and permissions.
    """

    def __init__(self, generator_config, capabilities_reader, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader capabilities_reader: CapabilitiesReader
        :param Logger logger: Logger
        """
        super().__init__(
            'ogc',
            'https://raw.githubusercontent.com/qwc-services/qwc-ogc-service/v2/schemas/qwc-ogc-service.json',
            logger
        )

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        self.capabilities_reader = capabilities_reader

    def config(self, service_config):
        """Return service config.

        :param obj service_config: Additional service config
        """
        # get base config
        config = super().config(service_config)

        # additional service config
        cfg_config = service_config.get('config', {})
        if 'default_qgis_server_url' not in cfg_config:
            # use default QGIS server URL from ConfigGenerator config
            # if not set in service config
            cfg_config['default_qgis_server_url'] = \
                self.default_qgis_server_url

        config['config'] = cfg_config

        resources = OrderedDict()
        config['resources'] = resources

        # collect resources from capabilities
        resources['wms_services'] = self.wms_services(service_config)
        # TODO: WFS service resources
        resources['wfs_services'] = []

        return config

    def wms_services(self, service_config):
        """Collect WMS service resources from capabilities.

        :param obj service_config: Additional service config
        """
        wms_services = []

        # additional service config
        cfg_resources = service_config.get('resources', {})
        cfg_wms_services = cfg_resources.get('wms_services', [])

        for service_name in self.capabilities_reader.wms_service_names():
            cap = self.capabilities_reader.wms_capabilities.get(service_name)

            # NOTE: use ordered keys
            wms_service = OrderedDict()
            wms_service['name'] = cap['name']

            # set any online resources
            if 'online_resources' in cfg_wms_services:
                # NOTE: use ordered keys
                online_resources = OrderedDict()
                for key, url in cfg_wms_services['online_resources'].items():
                    url = url.rstrip('/') + '/'
                    online_resources[key] = "%s%s" % (url, service_name)
                wms_service['online_resources'] = online_resources

            # collect WMS layers
            wms_service['root_layer'] = self.collect_wms_layers(
                cap['root_layer']
            )

            if 'print_templates' in cap:
                wms_service['print_templates'] = cap['print_templates']
            if 'internal_print_layers' in cap:
                wms_service['internal_print_layers'] = \
                    cap['internal_print_layers']

            wms_services.append(wms_service)

        return wms_services

    def collect_wms_layers(self, layer):
        """Recursively collect WMS layer info for layer subtree from
        capabilities and return nested WMS layers.

        :param obj layer: Layer or group layer
        """
        # NOTE: use ordered keys
        wms_layer = OrderedDict()

        wms_layer['name'] = layer['name']
        if 'title' in layer:
            wms_layer['title'] = layer['title']

        if 'layers' in layer:
            # group layer
            sublayers = []
            for sublayer in layer['layers']:
                # recursively collect sub layer
                sublayers.append(self.collect_wms_layers(sublayer))

            wms_layer['layers'] = sublayers
        else:
            # layer
            if 'attributes' in layer:
                wms_layer['attributes'] = layer['attributes']

            if layer.get('queryable', False):
                wms_layer['queryable'] = True

        return wms_layer
