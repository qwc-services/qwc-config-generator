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
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
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

        # NOTE: basic WMS service permissions collected by OGC service config
        # get additional permissions
        permissions['wms_services'] = self.additional_wms_permissions(role)

        return permissions

    # service config

    def wms_services(self):
        """Collect WMS service resources from capabilities."""
        wms_services = []

        for service_name in self.themes_reader.wms_service_names():
            cap = self.themes_reader.wms_capabilities(service_name)
            if not cap:
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

    def available_info_layers(self, session):
        """Collect all available info layers from ConfigDB, grouped by
        info service name.

        :param Session session: DB session
        """
        # NOTE: use ordered keys
        available_info_layers = OrderedDict()

        Resource = self.config_models.model('resources')

        query = session.query(Resource) \
            .filter(Resource.type == 'feature_info_service') \
            .order_by(Resource.name)
        for info_service in query.all():
            # collect unique info layers for each info service resource
            info_layers_query = session.query(Resource) \
                .filter(Resource.parent_id == info_service.id) \
                .filter(Resource.type == 'feature_info_layer') \
                .distinct(Resource.name) \
                .order_by(Resource.name)
            available_info_layers[info_service.name] = [
                resource.name for resource in info_layers_query.all()
            ]

        return available_info_layers

    def additional_wms_permissions(self, role):
        """Collect additional WMS Service permissions from ConfigDB
        or service config.

        These are permissions, e.g. for external info layers, which cannot be
        collected from capabilities.

        :param str role: Role name
        """
        wms_services = []

        if 'permissions' not in self.service_config:
            # collect permissions from ConfigDB
            session = self.config_models.session()

            # helper method alias
            non_public_resources = self.permissions_query.non_public_resources
            permitted_resources = self.permissions_query.permitted_resources

            # collect role permissions from ConfigDB
            role_permissions = {
                'info_services': permitted_resources(
                    'feature_info_service', role, session
                ),
                'info_layers': permitted_resources(
                    'feature_info_layer', role, session
                ),
                'attributes': permitted_resources(
                    'info_attribute', role, session
                )
            }

            # collect public permissions from ConfigDB
            public_role = self.permissions_query.public_role()
            public_permissions = {
                'info_services': permitted_resources(
                    'feature_info_service', public_role, session
                ),
                'info_layers': permitted_resources(
                    'feature_info_layer', public_role, session
                ),
                'attributes': permitted_resources(
                    'info_attribute', public_role, session
                )
            }

            # collect public restrictions from ConfigDB
            public_restrictions = {
                'info_services': non_public_resources('feature_info_service', session),
                'info_layers': non_public_resources('feature_info_layer', session),
                'attributes': non_public_resources('info_attribute', session)
            }

            is_public_role = (role == self.permissions_query.public_role())

            # collect info layer permissions for each info service
            available_info_layers = self.available_info_layers(session)
            for info_service, info_layers in available_info_layers.items():
                # lookup permissions
                if self.permissions_default_allow:
                    info_service_restricted_for_public = info_service in \
                        public_restrictions['info_services']
                else:
                    info_service_restricted_for_public = info_service not in \
                        public_permissions['info_services']
                info_service_permitted_for_role = info_service in \
                    role_permissions['info_services']
                if (
                    info_service_restricted_for_public
                    and not info_service_permitted_for_role
                ):
                    # info service not permitted
                    continue

                # NOTE: use ordered keys
                wms_service = OrderedDict()
                wms_service['name'] = info_service

                # collect info layers
                layers = []
                for info_layer in info_layers:
                    # lookup permissions
                    if self.permissions_default_allow:
                        info_layer_restricted_for_public = info_layer in \
                            public_restrictions['info_layers'].get(info_service, {})
                    else:
                        info_layer_restricted_for_public = info_layer not in \
                            public_permissions['info_layers'].get(info_service, {})
                    info_layer_permitted_for_role = info_layer in \
                        role_permissions['info_layers'].get(info_service, {})
                    if (
                        info_layer_restricted_for_public
                        and not info_layer_permitted_for_role
                    ):
                        # info layer not permitted
                        continue

                    # NOTE: use ordered keys
                    wms_layer = OrderedDict()
                    wms_layer['name'] = info_layer

                    # collect info attribute names (restricted by default)
                    attributes = role_permissions['attributes'] \
                        .get(info_service, {}).get(info_layer, {}).keys()
                    if attributes:
                        wms_layer['attributes'] = sorted(list(attributes))

                    # info template always permitted
                    wms_layer['info_template'] = True

                    if is_public_role:
                        # add public dataset
                        layers.append(wms_layer)
                    elif info_layer_restricted_for_public:
                        # add dataset permitted for role
                        layers.append(wms_layer)
                    elif attributes:
                        # only add additional permissions
                        layers.append(wms_layer)

                wms_service['layers'] = layers

                if layers:
                    wms_services.append(wms_service)

            session.close()
        else:
            # use permissions from additional service config if present
            self.logger.debug("Reading permissions from tenantConfig")

            # additional service config
            cfg_permissions = self.service_config.get('permissions', [])

            for role_permissions in cfg_permissions:
                # find role in permissions
                if role_permissions.get('role') == role:
                    # get WMS service permissions for role directly
                    #   from service config
                    wms_services = role_permissions.get('permissions', {}). \
                        get('wms_services', [])
                    break

        return wms_services
