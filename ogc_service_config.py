from collections import OrderedDict

from service_config import ServiceConfig


class OGCServiceConfig(ServiceConfig):
    """OGCServiceConfig class

    Generate OGC service config and permissions.
    """

    def __init__(self, generator_config, capabilities_reader, service_config,
                 logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader capabilities_reader: CapabilitiesReader
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__(
            'ogc',
            'https://raw.githubusercontent.com/qwc-services/qwc-ogc-service/v2/schemas/qwc-ogc-service.json',
            service_config,
            logger
        )

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        self.capabilities_reader = capabilities_reader

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        # additional service config
        cfg_config = self.service_config.get('config', {})
        if 'default_qgis_server_url' not in cfg_config:
            # use default QGIS server URL from ConfigGenerator config
            # if not set in service config
            cfg_config['default_qgis_server_url'] = \
                self.default_qgis_server_url

        config['config'] = cfg_config

        resources = OrderedDict()
        config['resources'] = resources

        # collect resources from capabilities
        resources['wms_services'] = self.wms_services()
        # TODO: WFS service resources
        resources['wfs_services'] = []

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # TODO: collect permissions from ConfigDB
        permissions['wms_services'] = self.wms_permissions(role)
        permissions['wfs_services'] = []

        return permissions

    def wms_services(self):
        """Collect WMS service resources from capabilities."""
        wms_services = []

        # additional service config
        cfg_resources = self.service_config.get('resources', {})
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
                wms_service['print_templates'] = [
                    template['name'] for template in cap['print_templates']
                ]
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

    def wms_permissions(self, role):
        """Collect WMS Service permissions from capabilities and ConfigDB.

        :param str role: Role name
        """
        permissions = []

        # TODO: get permissions and restrictions from ConfigDB
        #       everything permitted to public role for now
        if role != 'public':
            return []

        for service_name in self.capabilities_reader.wms_service_names():
            cap = self.capabilities_reader.wms_capabilities.get(service_name)

            # NOTE: use ordered keys
            wms_permissions = OrderedDict()
            wms_permissions['name'] = cap['name']

            # collect WMS layers
            layers = self.collect_wms_layer_permissions(cap['root_layer'])
            # add internal print layers
            layers += self.permitted_print_layers(cap)
            wms_permissions['layers'] = layers

            # print templates
            print_templates = cap.get('print_templates', [])
            if print_templates:
                wms_permissions['print_templates'] = [
                    template['name'] for template in print_templates
                ]

            if layers or print_templates:
                permissions.append(wms_permissions)

        return permissions

    def collect_wms_layer_permissions(self, layer):
        """Recursively collect WMS layer permissions for a role for layer
        subtree from capabilities and ConfigDB and return flat list of
        permitted WMS layers.

        :param obj layer: Layer or group layer
        """
        wms_layers = []

        # NOTE: use ordered keys
        wms_layer = OrderedDict()
        wms_layer['name'] = layer['name']

        if 'layers' in layer:
            # group layer
            sublayers = []
            for sublayer in layer['layers']:
                # recursively collect sub layer
                sublayers += self.collect_wms_layer_permissions(sublayer)

            if sublayers:
                # add group layer if any sub layers are permitted
                wms_layers.append(wms_layer)
                # add sub layers
                wms_layers += sublayers
        else:
            # layer
            if 'attributes' in layer:
                wms_layer['attributes'] = layer['attributes']

            # add layer
            wms_layers.append(wms_layer)

        return wms_layers

    def permitted_print_layers(self, cap):
        """Return permitted internal print layers for background layers from
        capabilities and ConfigDB.

        :param obj cap: Capabilities
        """
        internal_print_layers = []
        for name in cap.get('internal_print_layers', []):
            # NOTE: use ordered keys
            print_layer = OrderedDict()
            print_layer['name'] = name

            internal_print_layers.append(print_layer)

        return internal_print_layers
