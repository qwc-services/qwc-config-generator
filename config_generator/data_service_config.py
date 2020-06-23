from flask import json
from collections import OrderedDict
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import text as sql_text

from qwc_services_core.database import DatabaseEngine

from .service_config import ServiceConfig

from .permissions_query import PermissionsQuery
from .qgs_reader import QGSReader


class DataServiceConfig(ServiceConfig):
    """DataServiceConfig class

    Generate Data service config.
    """

    def __init__(self, service_config, generator_config,
                 config_models, logger):
        """Constructor

        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__(
            'data',
            'https://github.com/qwc-services/qwc-data-service/raw/master/schemas/qwc-data-service.json',
            service_config,
            logger
        )

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)

        self.db_engine = DatabaseEngine()
        self.generator_config = generator_config

    def config(self):
        """Return service config.

        :param obj service_config: Additional service config
        """
        config = super().config()

        resources = OrderedDict()

        session = self.config_models.session()
        resources['datasets'] = self._datasets(config, session)

        config['resources'] = resources
        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # collect permissions from ConfigDB
        session = self.config_models.session()

        permissions['data_datasets'] = self._dataset_permissions(role, session)

        # collect feature reports
        session.close()

        return permissions

    def _datasets(self, config, session):
        """Return data service resources.

        :param Session session: DB session
        """
        datasets = []

        Resource = self.config_models.model('resources')

        # get layer metadata from QGIS project
        qgs_reader = QGSReader(self.logger, self.generator_config.get(
            "qgis_projects_output_dir"))

        # Query all map resources
        query = session.query(Resource). \
            filter(Resource.type == 'map')
        for resource in query.all():
            qgs_name = resource.name
            self.logger.info("Reading '%s'" % qgs_name)
            if qgs_reader.read(qgs_name):
                for layer_name in qgs_reader.pg_layers():
                    try:
                        meta = qgs_reader.layer_metadata(layer_name)
                        self._lookup_attribute_data_types(meta)
                    except Exception as e:
                        self.logger.error(e)
                        continue

                    # NOTE: use ordered keys
                    dataset = OrderedDict()
                    dataset['name'] = qgs_name + '.' + layer_name
                    dataset['db_url'] = meta.get('database')
                    dataset['schema'] = meta.get('schema')
                    dataset['table_name'] = meta.get('table_name')
                    dataset['primary_key'] = meta.get('primary_key')

                    dataset['fields'] = []
                    for key, attr_meta in meta.get('fields', {}).items():
                        # NOTE: use ordered keys
                        field = OrderedDict()
                        field['name'] = key
                        field['data_type'] = attr_meta.get('data_type')
                        if attr_meta.get('constraints'):
                            # add any constraints
                            field['constraints'] = attr_meta.get('constraints')
                        dataset['fields'].append(field)

                    if meta.get('geometry_column'):
                        # NOTE: use ordered keys
                        geometry = OrderedDict()
                        geometry['geometry_column'] = meta['geometry_column']
                        geometry['geometry_type'] = meta['geometry_type']
                        geometry['srid'] = meta['srid']

                        dataset['geometry'] = geometry

                    datasets.append(dataset)

        return datasets

    def _dataset_permissions(self, role, session):
        """Collect edit dataset permissions from ConfigDB.

        :param str role: Role name
        :param Session session: DB session
        """
        permissions = []

        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')
        resource_types = [
            'data',
            'data_create', 'data_read', 'data_update', 'data_delete'
        ]
        query = self.permissions_query.role_permissions_query(
                role, session
            ).join(Permission.resource). \
            filter(Resource.type.in_(resource_types)). \
            order_by(Permission.priority.desc()). \
            distinct(Permission.priority)

        for permission in query.all():
            # NOTE: use ordered keys
            dataset_permissions = OrderedDict()
            dataset_permissions['name'] = permission.resource.name

            # collect attribute names
            attributes = []
            # TODO
            dataset_permissions['attributes'] = attributes

            writable = True  # TODO
            dataset_permissions['writable'] = writable
            dataset_permissions['creatable'] = writable
            dataset_permissions['readable'] = True
            dataset_permissions['updatable'] = writable
            dataset_permissions['deletable'] = writable

            if attributes or writable:
                # only add additional permissions
                permissions.append(dataset_permissions)

        return permissions

    # ---- Adapted query methods from qwc-config-service (untested!)

    def _permissions(self, params, role, session):
        """Query permissions for editing a dataset.

        Return dataset edit permissions if available and permitted.

        Dataset ID can be either '<QGS name>.<Data layer name>' for a specific
        QGIS project or '<Data layer name>' if the data layer name is unique.

        :param obj params: Request parameters with dataset='<Dataset ID>'
        :param str username: User name
        :param str group: Group name
        :param Session session: DB session
        """
        permissions = {}

        dataset = params.get('dataset', '')
        parts = dataset.split('.')
        if len(parts) > 1:
            map_name = parts[0]
            layer_name = parts[1]
        else:
            # no map name given
            map_name = None
            layer_name = dataset

        data_permissions = self._data_permissions(
            map_name, layer_name, role, session
        )

        if data_permissions['permitted']:
            # get layer metadata from QGIS project
            qgs_reader = QGSReader(self.logger, self.generator_config.get(
                "qgis_projects_output_dir"))
            if qgs_reader.read(data_permissions['map_name']):
                permissions = qgs_reader.layer_metadata(layer_name)

            if permissions:
                permissions.update({
                    'dataset': dataset,
                    'writable': data_permissions['writable'],
                    'creatable': data_permissions['creatable'],
                    'readable': data_permissions['readable'],
                    'updatable': data_permissions['updatable'],
                    'deletable': data_permissions['deletable']
                })

                self._filter_restricted_attributes(
                    data_permissions['restricted_attributes'],
                    permissions
                )

                self._lookup_attribute_data_types(permissions)

        return permissions

    def _data_permissions(self, map_name, layer_name, role, session):
        """Query resource permissions and return whether map and data layer are
        permitted and writable (with CRUD permissions), and any restricted
        attributes.

        If map_name is None, the data permission with highest priority is used.

        :param str map_name: Map name
        :param str layer_name: Data layer name
        :param str role: Role name
        :param Session session: DB session
        """
        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        map_id = None
        if map_name is None:
            # find map for data layer name
            data_resource_types = [
                'data',
                'data_create', 'data_read', 'data_update', 'data_delete'
            ]
            data_query = self.permissions_query.role_permissions_query(
                    role, session
                ).join(Permission.resource). \
                filter(Resource.type.in_(data_resource_types)). \
                filter(Resource.name == layer_name). \
                order_by(Permission.priority.desc()). \
                distinct(Permission.priority)
            # use data permission with highest priority
            data_permission = data_query.first()
            if data_permission is not None:
                map_id = data_permission.resource.parent_id
                map_query = session.query(Resource). \
                    filter(Resource.type == 'map'). \
                    filter(Resource.id == map_id)
                map_obj = map_query.first()
                if map_obj is not None:
                    map_name = map_obj.name
                    self.logger.info(
                        "No map name given, using map '%s'" % map_name
                    )
        else:
            # query map permissions
            maps_query = self.permissions_query.role_permissions_query(
                    role, session
                ).join(Permission.resource).filter(Resource.type == 'map'). \
                filter(Resource.name == map_name)
            for map_permission in maps_query.all():
                map_id = map_permission.resource.id

        if map_id is None:
            # map not found or not permitted
            # NOTE: map without resource record cannot have data layers
            return {
                'permitted': False
            }

        # query data permissions
        permitted = False
        writable = False
        creatable = False
        readable = False
        updatable = False
        deletable = False
        restricted_attributes = []

        # NOTE: use permission with highest priority
        base_query = self.permissions_query.role_permissions_query(role, session). \
            join(Permission.resource). \
            filter(Resource.parent_id == map_id). \
            filter(Resource.name == layer_name). \
            order_by(Permission.priority.desc()). \
            distinct(Permission.priority)

        # query 'data' permission
        data_query = base_query.filter(Resource.type == 'data')
        data_permission = data_query.first()
        if data_permission is not None:
            # 'data' permitted
            permitted = True
            writable = data_permission.write
            creatable = writable
            readable = True
            updatable = writable
            deletable = writable

            # query attribute restrictions
            attrs_query = self.resource_restrictions_query(
                'attribute', role, session
            ).filter(Resource.parent_id == data_permission.resource_id)
            for attr in attrs_query.all():
                restricted_attributes.append(attr.name)

        else:
            # query detailed CRUD data permissions
            create_query = base_query.filter(Resource.type == 'data_create')
            creatable = create_query.first() is not None

            read_query = base_query.filter(Resource.type == 'data_read')
            readable = read_query.first() is not None

            update_query = base_query.filter(Resource.type == 'data_update')
            updatable = update_query.first() is not None

            delete_query = base_query.filter(Resource.type == 'data_delete')
            deletable = delete_query.first() is not None

            permitted = creatable or readable or updatable or deletable
            writable = creatable and readable and updatable and deletable

            # TODO: restricted attributes

        return {
            'map_name': map_name,
            'permitted': permitted,
            'writable': writable,
            'creatable': creatable,
            'readable': readable,
            'updatable': updatable,
            'deletable': deletable,
            'restricted_attributes': restricted_attributes
        }

    def _filter_restricted_attributes(self, restricted_attributes, permissions):
        """Filter restricted attributes from Data service permissions.

        :param list[str] restricted_attributes: List of restricted attributes
        :param obj permissions: Data service permissions
        """
        for attr in restricted_attributes:
            if attr in permissions['attributes']:
                permissions['attributes'].remove(attr)

    def _lookup_attribute_data_types(self, meta):
        """Query column data types and add them to Data service meta data.

        :param obj meta: Data service meta
        """
        try:
            connection_string = meta.get('database')
            schema = meta.get('schema')
            table_name = meta.get('table_name')

            # connect to GeoDB
            geo_db = self.db_engine.db_engine(connection_string)
            conn = geo_db.connect()

            for attr in meta.get('attributes'):
                # build query SQL
                sql = sql_text("""
                    SELECT data_type, character_maximum_length,
                        numeric_precision, numeric_scale
                    FROM information_schema.columns
                    WHERE table_schema = '{schema}' AND table_name = '{table}'
                        AND column_name = '{column}'
                    ORDER BY ordinal_position;
                """.format(schema=schema, table=table_name, column=attr))

                # execute query
                data_type = None
                constraints = {}
                result = conn.execute(sql)
                for row in result:
                    data_type = row['data_type']

                    # constraints from data type
                    if (data_type in ['character', 'character varying'] and
                            row['character_maximum_length']):
                        constraints = {
                            'maxlength': row['character_maximum_length']
                        }
                    elif data_type in ['double precision', 'real']:
                        # NOTE: use text field with pattern for floats
                        constraints['pattern'] = '[0-9]+([\\.,][0-9]+)?'
                    elif data_type == 'numeric' and row['numeric_precision']:
                        step = pow(10, -row['numeric_scale'])
                        max_value = pow(
                            10, row['numeric_precision'] - row['numeric_scale']
                        ) - step
                        constraints = {
                            'numeric_precision': row['numeric_precision'],
                            'numeric_scale': row['numeric_scale'],
                            'min': -max_value,
                            'max': max_value,
                            'step': step
                        }
                    elif data_type == 'smallint':
                        constraints = {'min': -32768, 'max': 32767}
                    elif data_type == 'integer':
                        constraints = {'min': -2147483648, 'max': 2147483647}
                    elif data_type == 'bigint':
                        constraints = {
                            'min': -9223372036854775808,
                            'max': 9223372036854775807
                        }

                if attr not in meta.get('fields'):
                    meta['fields'][attr] = {}

                if data_type:
                    # add data type
                    meta['fields'][attr]['data_type'] = data_type
                else:
                    self.logger.warn(
                        "Could not find data type of column '%s' "
                        "of table '%s.%s'" % (attr, schema, table_name)
                    )

                if constraints:
                    if 'constraints' in meta['fields'][attr]:
                        # merge constraints from QGIS project
                        constraints.update(
                            meta['fields'][attr]['constraints']
                        )

                    # add constraints
                    meta['fields'][attr]['constraints'] = constraints

            # close database connection
            conn.close()

        except Exception as e:
            self.logger.error(
                "Error while querying attribute data types:\n\n%s" % e
            )
            raise
