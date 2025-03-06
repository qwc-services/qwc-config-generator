from collections import OrderedDict

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class OGCServiceConfig(ServiceConfig):
    """OGCServiceConfig class

    Generate OGC service config and permissions.
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
        super().__init__('ogc', schema_url, service_config, logger)

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        self.themes_reader = themes_reader

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )
        self.inherit_info_permissions = generator_config.get(
            'inherit_info_permissions', False
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

        # collect WMS service resources from capabilities
        resources['wms_services'] = self.wms_services()
        # collect WFS service resources from capabilities
        resources['wfs_services'] = self.wfs_services()

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # collect permissions from ConfigDB
        with self.config_models.session() as session:
            permissions['wms_services'] = self.wms_permissions(role, session)
            permissions['wfs_services'] = self.wfs_permissions(role, session)

        return permissions

    # service config

    def wms_services(self):
        """Collect WMS service resources from capabilities."""
        wms_services = []

        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_wms_services = cfg_generator_config.get('wms_services', {})

        for service_name in self.themes_reader.wms_service_names():
            cap = self.themes_reader.wms_capabilities(service_name)
            if not cap or not 'name' in cap:
                continue

            # NOTE: use ordered keys
            wms_service = OrderedDict()
            wms_service['name'] = cap['name']

            if not cap['wms_url'].startswith(self.default_qgis_server_url):
                wms_service['wms_url'] = cap['wms_url']

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
                ] + [
                    template['legendLayout'] for template in cap['print_templates'] if 'legendLayout' in template
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

            wms_layer['queryable'] = layer.get('queryable', False)

        return wms_layer

    def wfs_services(self):
        """Collect WFS service resources from capabilities."""
        wfs_services = []

        for service_name in self.themes_reader.wfs_service_names():
            cap = self.themes_reader.wfs_capabilities(service_name)
            if not cap or not 'name' in cap:
                continue

            # NOTE: use ordered keys
            wfs_service = OrderedDict()
            wfs_service['name'] = cap['name']

            if not cap['wfs_url'].startswith(self.default_qgis_server_url):
                wfs_service['wfs_url'] = cap['wfs_url']

            # collect WFS layers
            wfs_layers = []
            for layer_cap in cap['wfs_layers']:
                # NOTE: use ordered keys
                wfs_layer = OrderedDict()

                wfs_layer['name'] = layer_cap['name']
                wfs_layer['attributes'] = layer_cap['attributes']

                wfs_layers.append(wfs_layer)

            wfs_service['layers'] = wfs_layers

            wfs_services.append(wfs_service)

        return wfs_services

    # permissions

    def wms_permissions(self, role, session):
        """Collect WMS Service permissions from capabilities and ConfigDB.

        :param str role: Role name
        :param Session session: DB session
        """
        permissions = []

        # helper method aliases
        non_public_resources = self.permissions_query.non_public_resources
        permitted_resources = self.permissions_query.permitted_resources

        # collect role permissions from ConfigDB
        role_permissions = {
            'maps': permitted_resources('map', role, session),
            'layers': permitted_resources('layer', role, session),
            'attributes': permitted_resources('attribute', role, session),
            'info_services': permitted_resources('feature_info_service', role, session),
            'info_layers': permitted_resources('feature_info_layer', role, session),
            'print_templates': permitted_resources('print_template', role, session)
        }

        # collect public permissions from ConfigDB
        public_role = self.permissions_query.public_role()
        public_permissions = {
            'maps': permitted_resources('map', public_role, session),
            'layers': permitted_resources('layer', public_role, session),
            'attributes': permitted_resources('attribute', public_role, session),
            'info_services': permitted_resources('feature_info_service', public_role, session),
            'info_layers': permitted_resources('feature_info_layer', public_role, session),
            'print_templates': permitted_resources('print_template', public_role, session)
        }

        # collect public restrictions from ConfigDB
        public_restrictions = {
            'maps': non_public_resources('map', session),
            'layers': non_public_resources('layer', session),
            'attributes': non_public_resources('attribute', session),
            'info_services': non_public_resources('feature_info_service', session),
            'info_layers': non_public_resources('feature_info_layer', session),
            'print_templates': non_public_resources('print_template', session)
        }

        is_public_role = (role == self.permissions_query.public_role())

        for service_name in self.themes_reader.wms_service_names():
            # lookup permissions
            if self.permissions_default_allow:
                map_restricted_for_public = service_name in \
                    public_restrictions['maps']
                info_service_restricted_for_public = map_restricted_for_public or \
                        service_name in public_restrictions['info_services']
            else:
                map_restricted_for_public = service_name not in \
                    public_permissions['maps']
                info_service_restricted_for_public = map_restricted_for_public or \
                        service_name not in public_permissions['info_services']

            map_permitted_for_role = service_name in role_permissions['maps']
            info_service_permitted_for_role = service_name in role_permissions['info_services']
            # If service is not restricted for public or permitted for role, allow info_service unless restricted if permissions_default_allow or inherit_info_permissions
            if (
                self.permissions_default_allow or self.inherit_info_permissions
            ) and (
                not map_restricted_for_public or map_permitted_for_role
            ) and service_name not in public_restrictions['info_services']:
                info_service_permitted_for_role = True

            if map_restricted_for_public and not map_permitted_for_role:
                # WMS not permitted
                continue

            cap = self.themes_reader.wms_capabilities(service_name)
            if not cap or not 'name' in cap:
                continue

            # NOTE: use ordered keys
            wms_permissions = OrderedDict()
            wms_permissions['name'] = cap['name']

            # collect WMS layers
            layers = self.collect_wms_layer_permissions(
                service_name, cap['root_layer'], is_public_role,
                role_permissions, public_permissions, public_restrictions,
                map_restricted_for_public, info_service_restricted_for_public,
                info_service_permitted_for_role
            )

            # add internal print layers
            layers += self.permitted_print_layers(
                service_name, cap, is_public_role, role_permissions,
                public_permissions, public_restrictions, map_restricted_for_public
            )
            wms_permissions['layers'] = layers

            # print templates
            print_templates = self.permitted_print_templates(
                service_name, cap, is_public_role, role_permissions,
                public_permissions, public_restrictions, map_restricted_for_public
            )
            if print_templates:
                wms_permissions['print_templates'] = [
                    template['name'] for template in print_templates
                ] + [
                    template['legendLayout'] for template in print_templates if 'legendLayout' in template
                ]

            if layers or print_templates:
                permissions.append(wms_permissions)

        return permissions

    def collect_wms_layer_permissions(self, service_name, layer,
                                      is_public_role, role_permissions,
                                      public_permissions, public_restrictions,
                                      parent_restricted,
                                      info_service_restricted_for_public,
                                      info_service_permitted_for_role):
        """Recursively collect WMS layer permissions for a role for layer
        subtree from capabilities and permissions and return flat list of
        permitted WMS layers.

        :param str service_name: Name of parent WMS service
        :param obj layer: Layer or group layer
        :param bool is_public_role: Whether current role is public
        :param obj role_permissions: Lookup for role permissions
        :param obj public_permissions: Lookup for public permissions
        :param obj public_restrictions: Lookup for public restrictions
        :param bool parent_restricted: Whether parent resource is restricted for public
        :param bool info_service_restricted_for_public: Whether the parent info service is restricted for public
        :param bool info_service_permitted_for_role: Whether the parent info service is permitted for role
        """
        wms_layers = []

        # lookup permissions
        if self.permissions_default_allow:
            layer_restricted_for_public = layer['name'] in \
                public_restrictions['layers'].get(service_name, {})
            info_layer_restricted_for_public = layer_restricted_for_public or \
                layer['name'] in public_restrictions['info_layers'].get(service_name, {})
        else:
            layer_restricted_for_public = layer['name'] not in \
                public_permissions['layers'].get(service_name, {})
            info_layer_restricted_for_public = layer_restricted_for_public or \
                layer['name'] not in public_permissions['info_layers'].get(service_name, {})

        layer_permissions = role_permissions[
            'layers'].get(service_name, {})
        all_layers_permitted = "*" in layer_permissions.keys()
        layer_permitted_for_role = all_layers_permitted or \
            layer['name'] in layer_permissions
        layer_or_parent_restricted = layer_restricted_for_public or parent_restricted
        info_layer_permitted_for_role = layer['name'] in role_permissions['info_layers'].get(service_name, {})
        # If layer is not restricted for public or permitted for role, allow info_layer unless restricted if permissions_default_allow or inherit_info_permissions
        if (
             self.permissions_default_allow or self.inherit_info_permissions
        ) and (
            not layer_restricted_for_public or layer_permitted_for_role
        ) and layer['name'] not in public_restrictions['info_layers'].get(service_name, {}):
            info_layer_permitted_for_role = True

        if layer_restricted_for_public and not layer_permitted_for_role:
            # WMS layer not permitted
            return wms_layers

        # NOTE: use ordered keys
        wms_layer = OrderedDict()
        wms_layer['name'] = layer['name']

        wms_layer['queryable'] = (
            not info_service_restricted_for_public or info_service_permitted_for_role
        ) and (
            not info_layer_restricted_for_public or info_layer_permitted_for_role
        )
        wms_layer['info_template'] = wms_layer['queryable']

        if 'layers' in layer:
            # group layer
            sublayers = []
            for sublayer in layer['layers']:
                # recursively collect sub layer
                sublayers += self.collect_wms_layer_permissions(
                    service_name, sublayer, is_public_role, role_permissions,
                    public_permissions, public_restrictions,
                    layer_or_parent_restricted,
                    info_service_restricted_for_public,
                    info_service_permitted_for_role
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
                # NOTE: attributes are always allowed by default
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
                        attributes = [
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
            elif (info_service_restricted_for_public or info_layer_restricted_for_public) and wms_layer['queryable'] == True:
                # add layer with restricted queryable status
                wms_layers.append(wms_layer)

        return wms_layers

    def permitted_print_layers(self, service_name, cap, is_public_role,
                               role_permissions, public_permissions,
                               public_restrictions, map_restricted):
        """Return permitted internal print layers for background layers from
        capabilities and permissions.

        :param str service_name: Name of parent WMS service
        :param obj cap: WMS Capabilities
        :param bool is_public_role: Whether current role is public
        :param obj role_permissions: Lookup for role permissions
        :param obj public_permissions: Lookup for public permissions
        :param obj public_restrictions: Lookup for public restrictions
        :param bool map_restricted: Whether parent map is restricted
                                    for public
        """
        print_layers = []

        # collect print layer permissions and restrictions
        role_permitted_layers = set(
            role_permissions['layers'].get(service_name, {}).keys()
        )
        public_permitted_layers = set(
            public_permissions['layers'].get(service_name, {}).keys()
        )
        public_restricted_layers = set(
            public_restrictions['layers'].get(service_name, {}).keys()
        )

        internal_print_layers = cap.get('internal_print_layers', [])
        if is_public_role:
            # collect all permitted print layers
            if self.permissions_default_allow:
                internal_print_layers = [
                    layer for layer in internal_print_layers
                    if layer not in public_restricted_layers
                ]
            else:
                internal_print_layers = [
                    layer for layer in internal_print_layers
                    if layer in public_permitted_layers
                ]
        else:
            # collect additional print layers
            if self.permissions_default_allow:
                if map_restricted:
                    # collect print layers permitted for role
                    #   including print layers permitted for public
                    public_print_layers = (
                        set(internal_print_layers) - public_restricted_layers
                    )
                    permitted_layers = (
                        role_permitted_layers | public_print_layers
                    )
                else:
                    # collect print layers permitted for role
                    #   and restricted for public
                    permitted_layers = (
                        role_permitted_layers & public_restricted_layers
                    )
            else:
                # collect print layers permitted for role
                #   and not permitted for public
                permitted_layers = (
                    role_permitted_layers - public_permitted_layers
                )

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

    def permitted_print_templates(self, service_name, cap, is_public_role,
                                  role_permissions, public_permissions,
                                  public_restrictions, map_restricted):
        """Return permitted print templates from capabilities and permissions.

        :param str service_name: Name of parent WMS service
        :param obj cap: WMS Capabilities
        :param bool is_public_role: Whether current role is public
        :param obj role_permissions: Lookup for role permissions
        :param obj public_permissions: Lookup for public permissions
        :param obj public_restrictions: Lookup for public restrictions
        :param bool map_restricted: Whether parent map is restricted
                                    for public
        """
        # collect print template permissions and restrictions
        role_permitted_templates = set(
            role_permissions['print_templates'].get(service_name, {}).keys()
        )
        public_permitted_templates = set(
            public_permissions['print_templates'].get(service_name, {}).keys()
        )
        public_restricted_templates = set(
            public_restrictions['print_templates'].get(service_name, {}).keys()
        )

        print_templates = cap.get('print_templates', [])
        if is_public_role:
            # collect all permitted print templates
            if self.permissions_default_allow:
                print_templates = [
                    template for template in print_templates
                    if template['name'] not in public_restricted_templates
                ]
            else:
                print_templates = [
                    template for template in print_templates
                    if template['name'] in public_permitted_templates
                ]
        else:
            # collect additional print templates
            if self.permissions_default_allow:
                if map_restricted:
                    # collect print templates permitted for role
                    #   including print templates permitted for public
                    public_templates = set(
                        template['name'] for template in print_templates
                        if template['name'] not in public_restricted_templates
                    ).union(set(
                        template['legendLayout'] for template in print_templates
                        if template['name'] not in public_restricted_templates and 'legendLayout' in template
                    ))
                    permitted_templates = (
                        role_permitted_templates | public_templates
                    )
                else:
                    # collect print templates permitted for role
                    #   and restricted for public
                    permitted_templates = (
                        role_permitted_templates & public_restricted_templates
                    )
            else:
                # collect print templates permitted for role
                #   and not permitted for public
                permitted_templates = (
                    role_permitted_templates - public_permitted_templates
                )

            print_templates = [
                template for template in print_templates
                if template['name'] in permitted_templates
            ]

        return print_templates

    def wfs_permissions(self, role, session):
        """Collect WFS Service permissions from capabilities and ConfigDB.

        NOTE: the same map, layer and attribute resources and permission
              in the ConfigDB are used for both WMS and WFS

        :param str role: Role name
        :param Session session: DB session
        """
        permissions = []

        # helper method aliases
        non_public_resources = self.permissions_query.non_public_resources
        permitted_resources = self.permissions_query.permitted_resources

        # collect role permissions from ConfigDB
        role_permissions = {
            'maps': permitted_resources('map', role, session),
            'layers': permitted_resources('layer', role, session),
            'attributes': permitted_resources('attribute', role, session)
        }

        # collect public permissions from ConfigDB
        public_role = self.permissions_query.public_role()
        public_permissions = {
            'maps': permitted_resources('map', public_role, session),
            'layers': permitted_resources('layer', public_role, session),
            'attributes':
                permitted_resources('attribute', public_role, session)
        }

        # collect public restrictions from ConfigDB
        public_restrictions = {
            'maps': non_public_resources('map', session),
            'layers': non_public_resources('layer', session),
            'attributes': non_public_resources('attribute', session)
        }

        is_public_role = (role == self.permissions_query.public_role())

        for service_name in self.themes_reader.wfs_service_names():
            # lookup permissions
            if self.permissions_default_allow:
                restricted_for_public = service_name in \
                    public_restrictions['maps']
            else:
                restricted_for_public = service_name not in \
                    public_permissions['maps']
            permitted_for_role = service_name in role_permissions['maps']
            if restricted_for_public and not permitted_for_role:
                # WFS not permitted
                continue

            cap = self.themes_reader.wfs_capabilities(service_name)
            if not cap or not 'name' in cap:
                continue

            # NOTE: use ordered keys
            wfs_permissions = OrderedDict()
            wfs_permissions['name'] = cap['name']

            # collect WFS layers
            layers = self.collect_wfs_layer_permissions(
                service_name, cap, is_public_role, role_permissions,
                public_permissions, public_restrictions, restricted_for_public
            )
            wfs_permissions['layers'] = layers

            if layers:
                permissions.append(wfs_permissions)

        return permissions

    def collect_wfs_layer_permissions(self, service_name, cap, is_public_role,
                                      role_permissions, public_permissions,
                                      public_restrictions, map_restricted):
        """Return permitted WFS layers from capabilities and permissions.

        :param str service_name: Name of parent WFS service
        :param obj cap: WFS Capabilities
        :param bool is_public_role: Whether current role is public
        :param obj role_permissions: Lookup for role permissions
        :param obj public_permissions: Lookup for public permissions
        :param obj public_restrictions: Lookup for public restrictions
        :param bool map_restricted: Whether parent map is restricted
                                    for public
        """
        wfs_layers = []

        # collect WFS layer permissions and restrictions
        for layer in cap['wfs_layers']:
            # lookup permissions
            if self.permissions_default_allow:
                restricted_for_public = layer['name'] in \
                    public_restrictions['layers'].get(service_name, {})
            else:
                restricted_for_public = layer['name'] not in \
                    public_permissions['layers'].get(service_name, {})

            role_permitted_layers = role_permissions[
                'layers'].get(service_name, {})
            all_layers_permitted = "*" in role_permitted_layers
            permitted_for_role = all_layers_permitted or \
                layer['name'] in role_permitted_layers
            layer_or_map_restricted = restricted_for_public or map_restricted

            if restricted_for_public and not permitted_for_role:
                # WFS layer not permitted
                continue

            # NOTE: use ordered keys
            wfs_layer = OrderedDict()
            wfs_layer['name'] = layer['name']

            # collect WFS attribute permissions
            # NOTE: attributes are always allowed by default
            if is_public_role:
                # collect all permitted attributes
                restricted_attributes = (
                    public_restrictions['attributes'].
                    get(service_name, {}).get(layer['name'], {})
                )
                wfs_layer['attributes'] = [
                    attr for attr in layer['attributes']
                    if attr not in restricted_attributes
                ]
            else:
                attributes = None

                if layer_or_map_restricted:
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
                    attributes = [
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
                    wfs_layer['attributes'] = attributes

            if is_public_role:
                # add public layer
                wfs_layers.append(wfs_layer)
            elif layer_or_map_restricted:
                # add layer permitted for role
                wfs_layers.append(wfs_layer)
            elif wfs_layer.get('attributes', []):
                # add layer with additional attributes
                wfs_layers.append(wfs_layer)

        return wfs_layers
