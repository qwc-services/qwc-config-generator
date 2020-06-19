from collections import OrderedDict

from .service_config import ServiceConfig


class FeatureInfoServiceConfig(ServiceConfig):
    """FeatureInfoServiceConfig class

    Generate FeatureInfo service config and permissions.
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
            'featureInfo',
            'https://github.com/qwc-services/qwc-feature-info-service/raw/master/schemas/qwc-feature-info-service.json',
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

        config['service'] = 'feature-info'

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
        # get additional resources
        resources['wms_services'] += self.additional_wms_services()

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # NOTE: basic WMS service permissions collected by OGC service config
        # get additional permissions
        permissions['wms_services'] = self.additional_wms_permissions(role)

        return permissions

    # service config

    def wms_services(self):
        """Collect WMS service resources from capabilities."""
        wms_services = []

        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_wms_services = cfg_generator_config.get('wms_services', [])

        for service_name in self.capabilities_reader.wms_service_names():
            cap = self.capabilities_reader.wms_capabilities.get(service_name)

            # NOTE: use ordered keys
            wms_service = OrderedDict()
            wms_service['name'] = cap['name']

            # collect WMS layers
            wms_service['root_layer'] = self.collect_wms_layers(
                cap['root_layer']
            )

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
                # recursively collect queryable sub layer
                sub_wms_layer = self.collect_wms_layers(sublayer)
                if sub_wms_layer is not None:
                    sublayers.append(sub_wms_layer)

            wms_layer['layers'] = sublayers
        else:
            # layer
            if not layer.get('queryable', False):
                # layer not queryable
                return None

            # collect attributes
            if 'attributes' in layer:
                attributes = []
                for attr in layer['attributes']:
                    # NOTE: use ordered keys
                    attribute = OrderedDict()
                    attribute['name'] = attr

                    attributes.append(attribute)

                wms_layer['attributes'] = attributes

            # display field
            if 'display_field' in layer:
                wms_layer['display_field'] = layer['display_field']

        return wms_layer

    def additional_wms_services(self):
        """Collect additional WMS service resources from service config.

        These are resources e.g. for external info layers, which cannot be
        collected from capabilities.
        """
        # additional service config
        cfg_resources = self.service_config.get('resources', {})

        # get WMS service resources directly from service config
        return cfg_resources.get('wms_services', [])

    # permissions

    def additional_wms_permissions(self, role):
        """Collect additional WMS Service permissions from service config.

        These are permissions e.g. for external info layers, which cannot be
        collected from capabilities or ConfigDB.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # additional service config
        cfg_permissions = self.service_config.get('permissions', [])

        for role_permissions in cfg_permissions:
            # find role in permissions
            if role_permissions.get('role') == role:
                # get WMS service permissions for role directly
                #   from service config
                permissions = role_permissions.get('permissions', {}). \
                    get('wms_services', [])
                break

        return permissions
