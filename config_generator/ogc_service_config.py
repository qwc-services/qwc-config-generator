from collections import OrderedDict

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class OGCServiceConfig(ServiceConfig):
    """OGCServiceConfig class

    Generate OGC service config and permissions.
    """

    def __init__(self, generator_config, capabilities_reader, config_models,
                 service_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader capabilities_reader: CapabilitiesReader
        :param ConfigModels config_models: Helper for ORM models
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__(
            'ogc',
            'https://raw.githubusercontent.com/qwc-services/qwc-ogc-service/master/schemas/qwc-ogc-service.json',
            service_config,
            logger
        )

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        self.capabilities_reader = capabilities_reader

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )

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

        # collect permissions from ConfigDB
        session = self.config_models.session()

        permissions['wms_services'] = self.wms_permissions(role, session)
        permissions['wfs_services'] = []

        session.close()

        return permissions

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

    def wms_permissions(self, role, session):
        """Collect WMS Service permissions from capabilities and ConfigDB.

        :param str role: Role name
        :param Session session: DB session
        """
        permissions = []

        # TODO: permissions for permissions_default_allow == false

        # helper method aliases
        non_public_resources = self.permissions_query.non_public_resources
        permitted_resources = self.permissions_query.permitted_resources

        # collect public restrictions from ConfigDB
        public_restrictions = {
            'maps': non_public_resources('map', session),
            'layers': non_public_resources('layer', session),
            'attributes': non_public_resources('attribute', session),
            'print_templates': non_public_resources('print_template', session)
        }

        # collect role permissions from ConfigDB
        role_permissions = {
            'maps': permitted_resources('map', role, session),
            'layers': permitted_resources('layer', role, session),
            'attributes': permitted_resources('attribute', role, session),
            'print_templates':
                permitted_resources('print_template', role, session)
        }

        is_public_role = (role == self.permissions_query.public_role())

        for service_name in self.capabilities_reader.wms_service_names():
            # lookup permissions
            restricted_for_public = service_name in public_restrictions['maps']
            permitted_for_role = service_name in role_permissions['maps']
            if restricted_for_public and not permitted_for_role:
                # WMS not permitted
                continue

            cap = self.capabilities_reader.wms_capabilities.get(service_name)

            # NOTE: use ordered keys
            wms_permissions = OrderedDict()
            wms_permissions['name'] = cap['name']

            # collect WMS layers
            layers = self.collect_wms_layer_permissions(
                service_name, cap['root_layer'], is_public_role,
                role_permissions, public_restrictions, restricted_for_public
            )
            # add internal print layers
            layers += self.permitted_print_layers(
                service_name, cap, is_public_role, role_permissions,
                public_restrictions
            )
            wms_permissions['layers'] = layers

            # print templates
            print_templates = self.permitted_print_templates(
                service_name, cap, role_permissions, public_restrictions
            )
            if print_templates:
                wms_permissions['print_templates'] = [
                    template['name'] for template in print_templates
                ]

            if layers or print_templates:
                permissions.append(wms_permissions)

        return permissions

    def collect_wms_layer_permissions(self, service_name, layer,
                                      is_public_role, role_permissions,
                                      public_restrictions, parent_restricted):
        """Recursively collect WMS layer permissions for a role for layer
        subtree from capabilities and permissions and return flat list of
        permitted WMS layers.

        :param str service_name: Name of parent WMS service
        :param obj layer: Layer or group layer
        :param bool is_public_role: Whether current role is public
        :param obj role_permissions: Lookup for role permissions
        :param obj public_restrictions: Lookup for public restrictions
        :param bool parent_restricted: Whether parent resource is restricted
                                       for public
        """
        wms_layers = []

        # lookup permissions
        restricted_for_public = layer['name'] in \
            public_restrictions['layers'].get(service_name, {})
        permitted_for_role = layer['name'] in \
            role_permissions['layers'].get(service_name, {})
        layer_or_parent_restricted = restricted_for_public or parent_restricted

        if restricted_for_public and not permitted_for_role:
            # WMS layer not permitted
            return wms_layers

        # NOTE: use ordered keys
        wms_layer = OrderedDict()
        wms_layer['name'] = layer['name']

        if 'layers' in layer:
            # group layer
            sublayers = []
            for sublayer in layer['layers']:
                # recursively collect sub layer
                sublayers += self.collect_wms_layer_permissions(
                    service_name, sublayer, is_public_role, role_permissions,
                    public_restrictions, layer_or_parent_restricted
                )

            if sublayers:
                if is_public_role:
                    # add group layer if any sub layers are permitted
                    wms_layers.append(wms_layer)
                elif layer_or_parent_restricted:
                    # add group layer if any sub layers are permitted
                    # and group is not public
                    wms_layers.append(wms_layer)

                # add sub layers
                wms_layers += sublayers
        else:
            # layer
            if 'attributes' in layer:
                if is_public_role:
                    # collect all permitted attributes
                    restricted_attributes = (
                        public_restrictions['attributes'].
                        get(service_name, {}).get(layer['name'], {})
                    )
                    wms_layer['attributes'] = [
                        attr for attr in layer['attributes']
                        if attr not in restricted_attributes
                    ]
                else:
                    attributes = None

                    if layer_or_parent_restricted:
                        # collect restricted attributes not permitted for role
                        restricted_attributes = set(
                            public_restrictions['attributes'].
                            get(service_name, {}).get(layer['name'], {}).keys()
                        )
                        permitted_attributes = set(
                            role_permissions['attributes'].
                            get(service_name, {}).get(layer['name'], {}).keys()
                        )
                        restricted_attributes -= permitted_attributes

                        # collect all permitted attributes
                        wms_layer['attributes'] = [
                            attr for attr in layer['attributes']
                            if attr not in restricted_attributes
                        ]
                    else:
                        # collect additional attributes
                        permitted_attributes = (
                            role_permissions['attributes'].
                            get(service_name, {}).get(layer['name'], {}).keys()
                        )
                        attributes = [
                            attr for attr in layer['attributes']
                            if attr in permitted_attributes
                        ]

                    if attributes:
                        wms_layer['attributes'] = attributes

            if is_public_role:
                # add public layer
                wms_layers.append(wms_layer)
            elif layer_or_parent_restricted:
                # add layer permitted for role
                wms_layers.append(wms_layer)
            elif wms_layer.get('attributes', []):
                # add layer with additional attributes
                wms_layers.append(wms_layer)

        return wms_layers

    def permitted_print_layers(self, service_name, cap, is_public_role,
                               role_permissions, public_restrictions):
        """Return permitted internal print layers for background layers from
        capabilities and permissions.

        :param str service_name: Name of parent WMS service
        :param obj cap: Capabilities
        :param bool is_public_role: Whether current role is public
        :param obj role_permissions: Lookup for role permissions
        :param obj public_restrictions: Lookup for public restrictions
        """
        print_layers = []

        internal_print_layers = cap.get('internal_print_layers', [])

        if is_public_role:
            # collect all permitted print layers
            restricted_layers = (
                public_restrictions['layers'].get(service_name, {}).keys()
            )
            internal_print_layers = [
                layer for layer in internal_print_layers
                if layer not in restricted_layers
            ]
        else:
            # collect print layers permitted for role and restricted for public
            permitted_layers = set(
                role_permissions['layers'].get(service_name, {}).keys()
            )
            restricted_layers = set(
                public_restrictions['layers'].get(service_name, {}).keys()
            )
            permitted_layers = permitted_layers or restricted_layers

            # collect additional print layers
            internal_print_layers = [
                layer for layer in internal_print_layers
                if layer in permitted_layers
            ]

        for name in internal_print_layers:
            # NOTE: use ordered keys
            print_layer = OrderedDict()
            print_layer['name'] = name

            print_layers.append(print_layer)

        return print_layers

    def permitted_print_templates(self, service_name, cap, role_permissions,
                                  public_restrictions):
        """Return permitted print templates from
        capabilities and permissions.

        :param str service_name: Name of parent WMS service
        :param obj cap: Capabilities
        :param obj role_permissions: Lookup for role permissions
        :param obj public_restrictions: Lookup for public restrictions
        """
        print_templates = []

        # collect restricted print templates not permitted for role
        restricted_templates = set(
            public_restrictions['print_templates'].get(service_name, {}).keys()
        )
        permitted_templates = set(
            role_permissions['print_templates'].get(service_name, {}).keys()
        )
        restricted_templates -= permitted_templates

        return [
            template for template in cap.get('print_templates', [])
            if template['name'] not in restricted_templates
        ]
