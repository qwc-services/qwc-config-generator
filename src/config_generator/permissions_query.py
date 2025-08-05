from sqlalchemy import distinct
from sqlalchemy.orm import aliased
from sqlalchemy.sql import text as sql_text


class PermissionsQuery:
    """PermissionsQuery class

    Query permissions for a QWC resource.
    """

    # name of public iam.role
    PUBLIC_ROLE_NAME = 'public'

    def __init__(self, config_models, logger):
        """Constructor

        :param ConfigModels config_models: Helper for ORM models
        :param Logger logger: Application logger
        """
        self.config_models = config_models
        self.logger = logger

        self.resources_lookup = self.load_resources_lookup()

    def public_role(self):
        """Return public role name."""
        return self.PUBLIC_ROLE_NAME

    def resource_permissions(self, resource_type, resource_name, role,
                             session):
        """Query permissions for a resource type and optional name.

        Return resource permissions sorted by priority.

        :param str resource_type: QWC resource type
        :param str resource_name: optional QWC resource name (None for all)
        :param str role: Role name
        :param Session session: DB session
        """
        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        # base query for all permissions of user
        query = self.role_permissions_query(role, session)

        # filter permissions by QWC resource type
        query = query.join(Permission.resource) \
            .filter(Resource.type == resource_type)

        if resource_name is not None:
            # filter by resource name
            query = query.filter(Resource.name == resource_name)

        # order by priority
        query = query.order_by(Permission.priority.desc())

        # execute query and return results
        return query.all()

    def resource_permissions_query(self, resource_type, role, session):
        """Create query for permissions for a QWC resource type and role.

        :param str resource_type: QWC resource type
        :param str role: Role name
        :param Session session: DB session
        """
        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        # resource permissions for user
        role_permissions = \
            self.role_permissions_query(role, session). \
            join(Permission.resource). \
            with_entities(Resource.id, Resource.name, Resource.parent_id). \
            filter(Resource.type == resource_type)

        return role_permissions

    def resource_restrictions_query(self, resource_type, role, session):
        """Create query for restrictions for a QWC resource type and role.

        :param str resource_type: QWC resource type
        :param str role: Role name
        :param Session session: DB session
        """
        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        # all resource restrictions
        all_restrictions = session.query(Permission). \
            join(Permission.resource). \
            with_entities(Resource.id, Resource.name, Resource.parent_id). \
            filter(Resource.type == resource_type)

        # resource permissions for role
        role_permissions = self.resource_permissions_query(
            resource_type, role, session
        )

        # restrictions without role permissions
        restrictions_query = all_restrictions.except_(role_permissions)

        return restrictions_query

    def role_permissions_query(self, role, session):
        """Create base query for all permissions of a role.

        :param str role: Role name
        :param Session session: DB session
        """
        Permission = self.config_models.model('permissions')
        Role = self.config_models.model('roles')

        # create query for permissions of role
        query = session.query(Permission). \
            join(Permission.role). \
            filter(Role.name == role)

        return query

    def permitted_resources(self, resource_type, role, session):
        """Collect hierarchy of resources permitted for a role
        for a resource type.

        NOTE: use 'attribute' resource type for layer attributes,
              'data_attribute' for data attributes and
              'info_attribute' for FeatureInfo layer attributes
              'wfs_attribute' for wfs_layer attributes

        :param str resource_type: QWC resource type
        :param Session session: DB session
        """
        parent_filter = None
        if resource_type == 'attribute':
            # only layer attributes
            parent_filter = 'layer'
        elif resource_type == 'data_attribute':
            # only data attributes
            resource_type = 'attribute'
            parent_filter = 'data'
        elif resource_type == 'info_attribute':
            # only info layer attributes
            resource_type = 'attribute'
            parent_filter = 'feature_info_layer'
        elif resource_type == 'wfs_attribute':
            resource_type = 'attribute'
            parent_filter = 'wfs_layer'

        # query resource permissions
        query = self.resource_permissions_query(
            resource_type, role, session
        )
        if parent_filter:
            # filter by attribute parent type
            Resource = self.config_models.model('resources')
            parent_alias = aliased(Resource)
            query = query.join(
                parent_alias, parent_alias.id == Resource.parent_id
            ).filter(parent_alias.type == parent_filter)

        return self.resource_hierarchy(query.all())

    def non_public_resources(self, resource_type, session):
        """Collect hierarchy of resources restricted for public role
        for a resource type.

        NOTE: use 'attribute' resource type for layer attributes,
              'data_attribute' for data attributes and
              'info_attribute' for FeatureInfo layer attributes
              'wfs_attribute' for wfs_layer attributes

        :param str resource_type: QWC resource type
        :param Session session: DB session
        """
        parent_filter = None
        if resource_type == 'attribute':
            # only layer attributes
            parent_filter = 'layer'
        elif resource_type == 'data_attribute':
            # only data attributes
            resource_type = 'attribute'
            parent_filter = 'data'
        elif resource_type == 'info_attribute':
            # only info layer attributes
            resource_type = 'attribute'
            parent_filter = 'feature_info_layer'
        elif resource_type == 'wfs_attribute':
            resource_type = 'attribute'
            parent_filter = 'wfs_layer'


        # query public resource restrictions
        query = self.resource_restrictions_query(
            resource_type, self.public_role(), session
        )
        if parent_filter:
            # filter by attribute parent type
            Resource = self.config_models.model('resources')
            parent_alias = aliased(Resource)
            query = query.join(
                parent_alias, parent_alias.id == Resource.parent_id
            ).filter(parent_alias.type == parent_filter)

        return self.resource_hierarchy(query.all())

    def resource_hierarchy(self, resources):
        """Return hierarchical nested dict for list of QWC resources.

        Example dict for resources of type attribute:
            resource_tree = {
                <map>: {
                    <layer>: {
                        <attribute>: {}
                    }
                }
            }

        :param list(obj) resources: List of QWC resources
        """
        resource_tree = {}

        for resource in resources:
            # collect resource hierarchy
            hierarchy = [resource.name]
            current_res = resource
            while current_res.parent_id is not None:
                parent = self.get_resource(current_res.parent_id)
                hierarchy.append(parent.name)
                current_res = parent

            # collect restricted resource tree
            hierarchy.reverse()
            target = resource_tree
            for res_name in hierarchy:
                if res_name not in target:
                    target[res_name] = {}
                target = target[res_name]

        return resource_tree

    def load_resources_lookup(self):
        """Load resources for lookup from ConfigDB."""
        resources_lookup = {}

        with self.config_models.session() as session:
            # collect resources lookup from ConfigDB
            Resource = self.config_models.model('resources')
            query = session.query(Resource).order_by(Resource.type)
            for resource in query.all():
                resources_lookup[resource.id] = resource

        return resources_lookup

    def get_resource(self, resource_id):
        """Lookup resource by ID.

        :param int resource_id: Resource ID
        """
        return self.resources_lookup[resource_id]
