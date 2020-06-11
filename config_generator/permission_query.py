from sqlalchemy import distinct
from sqlalchemy.sql import text as sql_text


class PermissionQuery:
    """PermissionQuery base class

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

    def public_role(self):
        """Return public role name."""
        return self.PUBLIC_ROLE_NAME

    def resource_permissions(self, resource_type, resource_name, role,
                             session):
        """Query permissions for a resource type and name.

        Return resource permissions sorted by priority.

        :param str resource_type: QWC resource type
        :param str resource_name: QWC resource name
        :param str role: Role name
        :param Session session: DB session
        """
        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        # base query for all permissions of user
        query = self.role_permissions_query(role, session)

        # filter permissions by QWC resource type and name
        query = query.join(Permission.resource) \
            .filter(Resource.type == resource_type) \
            .filter(Resource.name == resource_name)

        # order by priority
        query = query.order_by(Permission.priority.desc()) \
            .distinct(Permission.priority)

        # execute query and return results
        return query.all()

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
