from collections import OrderedDict

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class FeatureInfoServiceConfig(ServiceConfig):
    """FeatureInfoServiceConfig class

    Generate FeatureInfo service config and permissions.
    """

    def __init__(self, generator_config, themes_reader, config_models,
                 schema_url, service_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader themes_reader: ThemesReader
        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__('featureInfo', schema_url, service_config, logger)

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.qgis_server_url_tenant_suffix = generator_config.get(
            'qgis_server_url_tenant_suffix', ''
        ).strip('/')
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )
        self.inherit_info_permissions = generator_config.get(
            'inherit_info_permissions', False
        )

        self.themes_reader = themes_reader

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

        if 'qgis_server_url_tenant_suffix' not in cfg_config:
            # use qgis_server_url_tenant_suffix from ConfigGenerator config
            # if not set in service config
            cfg_config['qgis_server_url_tenant_suffix'] = self.qgis_server_url_tenant_suffix

        config['config'] = cfg_config

        resources = OrderedDict()
        config['resources'] = resources

        # collect resources from capabilities
        resources['wms_services'] = self.wms_services()

        # merge additional resources
        for add_entry in self.additional_wms_services():
            result = list(filter(lambda e: e['name'] == add_entry['name'], resources['wms_services']))
            if result:
                self.__merge_resources(result[0]["root_layer"], add_entry.get("root_layer", {}))

        return config

    def __merge_resources(self, base_entry, add_entry):
        """Recursively merge resources collected from capabilitites with additional resources.
        """
        add_layers = {}
        for add_layer in add_entry.get("layers", []):
            add_layers[add_layer["name"]] = add_layer
        if "layers" in base_entry:
            base_entry["layers"] = list(map(
                lambda layer: OrderedDict(
                    list(layer.items()) + list(filter(lambda item: item[0] != "layers", add_layers.get(layer["name"], {}).items()))
                ), base_entry["layers"]
            ))
        for layer in base_entry.get("layers", {}):
            self.__merge_resources(layer, add_layers.get(layer["name"], {}))

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # NOTE: No feature-info-service specific permissions

        return permissions

    # service config

    def wms_services(self):
        """Collect WMS service resources from capabilities."""
        wms_services = []

        for service_name in self.themes_reader.wms_service_names():
            cap = self.themes_reader.wms_capabilities(service_name)
            if not cap or not 'name' in cap:
                continue

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
                for attr, alias in layer['attributes'].items():
                    # NOTE: use ordered keys
                    attribute = OrderedDict()
                    attribute['name'] = attr
                    attribute['alias'] = alias

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
