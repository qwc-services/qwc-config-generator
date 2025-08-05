from collections import OrderedDict
from sqlalchemy.orm import joinedload

from .service_config import ServiceConfig

from .permissions_query import PermissionsQuery


class DataServiceConfig(ServiceConfig):
    """DataServiceConfig class

    Generate Data service config.
    """

    def __init__(self, generator_config, themes_reader,
                 config_models, schema_url, service_config, logger,
                 force_readonly_datasets):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader themes_reader: ThemesReader
        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        :param bool force_readonly_datasets: Whether to force read-only datasets
        """
        super().__init__('data', schema_url, service_config, logger)

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )

        self.generator_config = generator_config
        self.themes_reader = themes_reader
        self.force_readonly_datasets = force_readonly_datasets

    def config(self):
        """Return service config.

        :param obj service_config: Additional service config
        """
        config = super().config()

        resources = OrderedDict()

        with self.config_models.session() as session:
            resources['datasets'] = self._dataset_resources(config, session)

        config['resources'] = resources
        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # collect permissions from ConfigDB
        with self.config_models.session() as session:
            permissions['data_datasets'] = self._dataset_permissions(role, session)

        # collect feature reports

        return permissions

    def available_datasets(self, session):
        """Collect all available datasets from ConfigDB, grouped by map name.

        :param Session session: DB session
        :param bool quiet: Whether to log warnings
        """
        # NOTE: use ordered keys
        available_datasets = OrderedDict()

        Resource = self.config_models.model('resources')

        query = session.query(Resource) \
            .filter(Resource.type == 'map') \
            .order_by(Resource.name)
        for map_obj in query.all():

            project_metadata = self.themes_reader.project_metadata(map_obj.name)
            if not project_metadata:
                # Resource does not match any existing project
                continue

            # collect unique datasets for each map resource
            resource_types = [
                'data',
                'data_create', 'data_update', 'data_delete'
            ]
            datasets_query = session.query(Resource) \
                .filter(Resource.parent_id == map_obj.id) \
                .filter(Resource.type.in_(resource_types)) \
                .distinct(Resource.name) \
                .order_by(Resource.name)
            available_datasets[map_obj.name] = []
            invalid_datasets = list()
            for resource in datasets_query.all():
                if project_metadata['layer_metadata'].get(resource.name, {}).get('editable'):
                    available_datasets[map_obj.name].append(resource.name)

        return available_datasets

    def _dataset_resources(self, config, session):
        """Return data service resources.

        :param Session session: DB session
        """
        datasets = []
        keyvaltables = {}
        added_datasets = set()
        autogen_keyvaltable_datasets = self.generator_config.get('autogen_keyvaltable_datasets', False)

        for qgs_name, map_datasets in self.available_datasets(session).items():

            for map_dataset in map_datasets:
                meta = self.themes_reader.project_metadata(qgs_name)['layer_metadata'][map_dataset]
                if autogen_keyvaltable_datasets:
                    keyvaltables.update(meta.get('keyvaltables', {}))

                # NOTE: use ordered keys
                dataset = OrderedDict()
                dataset['name'] = qgs_name + '.' + map_dataset
                dataset['db_url'] = meta.get('database')
                dataset['schema'] = meta.get('schema')
                dataset['datasource_filter'] = meta.get('datasource_filter')
                dataset['table_name'] = meta.get('table_name')
                dataset['primary_key'] = meta.get('primary_key')

                if not dataset['primary_key'] in meta['fields']:
                    self.logger.warn("The dataset %s.%s does not appear to have a valid primary key" % (dataset['schema'], dataset['table_name']))

                dataset['fields'] = []
                for key, attr_meta in meta.get('fields', {}).items():

                    if attr_meta.get('expression'):
                        # Skip expression field
                        continue

                    # NOTE: use ordered keys
                    field = OrderedDict()
                    field['name'] = key
                    field['data_type'] = attr_meta.get('data_type')
                    if attr_meta.get('constraints'):
                        # add any constraints
                        field['constraints'] = attr_meta.get('constraints')
                    field['joinfield'] = attr_meta.get('joinfield')
                    dataset['fields'].append(field)
                    dataset['jointables'] = meta.get('jointables')

                if meta.get('geometry_column'):
                    # NOTE: use ordered keys
                    geometry = OrderedDict()
                    geometry['geometry_column'] = meta['geometry_column']
                    geometry['geometry_type'] = meta['geometry_type']
                    geometry['srid'] = meta['srid']

                    dataset['geometry'] = geometry

                added_datasets.add(dataset['name'])
                datasets.append(dataset)

        for key, value in keyvaltables.items():
            if not key in added_datasets:
                dataset = OrderedDict()
                dataset['name'] = key
                dataset['db_url'] = value.get('database')
                dataset['datasource_filter'] = value.get('datasource_filter')
                dataset['schema'] = value.get('schema')
                dataset['table_name'] = value.get('table_name')
                dataset['primary_key'] = value.get('primary_key')
                dataset['fields'] = []

                qgs_name = value.get('qgs_name')
                map_dataset = value.get('layername')
                meta = self.themes_reader.project_metadata(qgs_name)['layer_metadata'][map_dataset]
                for key, attr_meta in meta.get('fields', {}).items():
                    if attr_meta.get('expression'):
                        # Skip expression field
                        continue
                    # NOTE: use ordered keys
                    field = OrderedDict()
                    field['name'] = key
                    field['data_type'] = attr_meta.get('data_type')
                    dataset['fields'].append(field)

                dataset['readonlypermitted'] = True
                datasets.append(dataset)

        return datasets

    def _dataset_permissions(self, role, session):
        """Collect edit dataset permissions from ConfigDB.

        NOTE: datasets are restricted by default and require
              explicit permissions
              attributes are allowed by default

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
            'data': permitted_resources('data', role, session),
            'data_create': permitted_resources('data_create', role, session),
            'data_update': permitted_resources('data_update', role, session),
            'data_delete': permitted_resources('data_delete', role, session),
            'attributes': permitted_resources('data_attribute', role, session)
        }

        # collect public permissions from ConfigDB
        public_role = self.permissions_query.public_role()
        public_permissions = {
            'maps': permitted_resources('map', public_role, session),
            'data': permitted_resources('data', public_role, session),
            'data_create':
                permitted_resources('data_create', public_role, session),
            'data_update':
                permitted_resources('data_update', public_role, session),
            'data_delete':
                permitted_resources('data_delete', public_role, session)
        }

        # collect public restrictions from ConfigDB
        public_restrictions = {
            'maps': non_public_resources('map', session),
            'attributes': non_public_resources('data_attribute', session)
        }

        # collect permitted datasets for role from all data resource types
        resource_types = [
            'data',
            'data_create', 'data_update', 'data_delete'
        ]
        role_permitted_datasets = {}
        for resource_type in resource_types:
            for map_name, datasets in role_permissions[resource_type].items():
                if map_name not in role_permitted_datasets:
                    # init lookup for map
                    role_permitted_datasets[map_name] = set()
                # add datasets to lookup
                role_permitted_datasets[map_name].update(datasets.keys())

        # collect public permitted datasets from all data resource types
        public_permitted_datasets = {}
        for resource_type in resource_types:
            for map_name, datasets in public_permissions[resource_type].items():
                if map_name not in public_permitted_datasets:
                    # init lookup for map
                    public_permitted_datasets[map_name] = set()
                # add datasets to lookup
                public_permitted_datasets[map_name].update(datasets.keys())

        # collect write permissions for role
        # with highest priority for all datasets
        role_writeable_datasets = {}
        examined_datasets = {}
        data_permissions = self.permissions_query.resource_permissions(
            'data', None, role, session
        )
        for permission in data_permissions:
            # lookup map resource for dataset
            if not permission.resource.parent_id:
                continue
            map_obj = self.permissions_query.get_resource(
                permission.resource.parent_id
            )
            map_name = map_obj.name

            if map_name not in role_writeable_datasets:
                # init lookup for map
                role_writeable_datasets[map_name] = set()
                examined_datasets[map_name] = set()

            dataset = permission.resource.name
            if dataset not in examined_datasets[map_name]:
                # check permission with highest priority
                if permission.write and not self.force_readonly_datasets:
                    # mark as writable
                    role_writeable_datasets[map_name].add(dataset)
                examined_datasets[map_name].add(dataset)

        is_public_role = (role == self.permissions_query.public_role())

        # collect edit dataset permissions for each map
        for map_name, datasets in self.available_datasets(session).items():

            if self.permissions_default_allow:
                map_restricted_for_public = map_name in public_restrictions['maps']
            else:
                map_restricted_for_public = map_name not in public_permissions['maps']
            map_permitted_for_role = map_name in role_permissions['maps']
            if map_restricted_for_public and not map_permitted_for_role:
                # map not permitted
                continue

            for layer_name in datasets:

                # lookup permissions (dataset restricted by default)
                restricted_for_public = layer_name not in \
                    public_permitted_datasets.get(map_name, {})
                permitted_for_role = layer_name in \
                    role_permitted_datasets.get(map_name, {})
                if restricted_for_public and not permitted_for_role:
                    # dataset not permitted
                    continue

                # get layer metadata from QGIS project
                meta = self.themes_reader.project_metadata(map_name)['layer_metadata'][layer_name]

                # NOTE: use ordered keys
                dataset_permissions = OrderedDict()
                dataset_permissions['name'] = (
                    "%s.%s" % (map_name, layer_name)
                )

                # collect attribute names (allowed by default)
                attributes = []
                if is_public_role:
                    # collect all permitted attributes
                    restricted_attributes = (
                        public_restrictions['attributes'].
                        get(map_name, {}).get(layer_name, {})
                    )
                    attributes = [
                        attr for attr in meta['fields']
                        if attr not in restricted_attributes
                    ]
                else:
                    if restricted_for_public:
                        # collect restricted attributes not permitted
                        # for role
                        restricted_attributes = set(
                            public_restrictions['attributes'].
                            get(map_name, {}).get(layer_name, {}).keys()
                        )
                        permitted_attributes = set(
                            role_permissions['attributes'].
                            get(map_name, {}).get(layer_name, {}).keys()
                        )
                        restricted_attributes -= permitted_attributes

                        # collect all permitted attributes
                        attributes = [
                            attr for attr in meta['fields']
                            if attr not in restricted_attributes
                        ]
                    else:
                        # collect additional attributes
                        permitted_attributes = (
                            role_permissions['attributes'].
                            get(map_name, {}).get(layer_name, {}).keys()
                        )
                        attributes = [
                            attr for attr in meta['fields']
                            if attr in permitted_attributes
                        ]

                dataset_permissions['attributes'] = attributes

                # collect CRUD permissions
                writable = False
                creatable = False
                readable = False
                updatable = False
                deletable = False
                additional_crud = False

                if (
                    layer_name in
                    role_permissions['data'].get(map_name, {})
                ):
                    # 'data' permitted
                    writable = layer_name in \
                        role_writeable_datasets.get(map_name, {})
                    creatable = writable
                    readable = True
                    updatable = writable
                    deletable = writable

                # combine with detailed CRUD data permissions
                creatable |= layer_name in \
                    role_permissions['data_create'].get(map_name, {})
                readable |= layer_name in \
                    role_permissions['data_create'].get(map_name, {}) \
                    or layer_name in \
                    role_permissions['data_update'].get(map_name, {}) \
                    or layer_name in \
                    role_permissions['data_delete'].get(map_name, {}) 
                updatable |= layer_name in \
                    role_permissions['data_update'].get(map_name, {})
                deletable |= layer_name in \
                    role_permissions['data_delete'].get(map_name, {})

                writable |= (
                    creatable and readable and updatable and deletable
                )

                if is_public_role or restricted_for_public:
                    # collect all CRUD permissions
                    dataset_permissions['writable'] = writable
                    dataset_permissions['creatable'] = creatable
                    dataset_permissions['readable'] = readable
                    dataset_permissions['updatable'] = updatable
                    dataset_permissions['deletable'] = deletable

                    additional_crud = restricted_for_public
                else:
                    # collect additional CRUD permissions
                    if writable:
                        dataset_permissions['writable'] = writable
                    if creatable:
                        dataset_permissions['creatable'] = creatable
                    if readable:
                        dataset_permissions['readable'] = readable
                    if updatable:
                        dataset_permissions['updatable'] = updatable
                    if deletable:
                        dataset_permissions['deletable'] = deletable

                    additional_crud = creatable or readable or updatable or deletable

                if is_public_role:
                    # add public dataset
                    permissions.append(dataset_permissions)
                elif restricted_for_public:
                    # add dataset permitted for role
                    permissions.append(dataset_permissions)
                elif attributes or additional_crud:
                    # only add additional permissions
                    permissions.append(dataset_permissions)

        return permissions
