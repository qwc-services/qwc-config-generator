from collections import OrderedDict


class PermissionsConfig():
    """PermissionsConfig class

    Collect and generate QWC service permissions.
    """

    def __init__(self, config_models, logger):
        """Constructor

        :param ConfigModels config_models: Helper for ORM models
        :param Logger logger: Logger
        """
        self.config_models = config_models
        self.logger = logger

        self.schema = 'https://github.com/qwc-services/qwc-services-core/raw/master/schemas/qwc-services-permissions.json'

    def base_config(self):
        """Return basic config with user, groups and roles."""
        # NOTE: use ordered keys
        permissions = OrderedDict()

        session = self.config_models.session()

        permissions['users'] = self.users(session)
        permissions['groups'] = self.groups(session)
        permissions['roles'] = self.roles(session)

        session.close()

        return permissions

    def users(self, session):
        """Collect users from ConfigDB.

        :param Session session: DB session
        """
        users = []

        User = self.config_models.model('users')
        query = session.query(User).order_by(User.name)
        for user in query.all():
            # NOTE: use ordered keys
            user_config = OrderedDict()
            user_config['name'] = user.name
            user_config['groups'] = [
                group.name for group in user.sorted_groups
            ]
            user_config['roles'] = [
                role.name for role in user.sorted_roles
            ]

            users.append(user_config)

        return users

    def groups(self, session):
        """Collect groups from ConfigDB.

        :param Session session: DB session
        """
        groups = []

        Group = self.config_models.model('groups')
        query = session.query(Group).order_by(Group.name)
        for group in query.all():
            # NOTE: use ordered keys
            group_config = OrderedDict()
            group_config['name'] = group.name
            group_config['roles'] = [
                role.name for role in group.sorted_roles
            ]

            groups.append(group_config)

        return groups

    def roles(self, session):
        """Collect roles from ConfigDB.

        :param Session session: DB session
        """
        roles = []
        public_index = 0

        Role = self.config_models.model('roles')
        query = session.query(Role).order_by(Role.name)
        index = 0
        for role in query.all():
            # NOTE: use ordered keys
            role_config = OrderedDict()
            role_config['role'] = role.name

            # empty base permissions
            # NOTE: use ordered keys
            permissions = OrderedDict()
            permissions['wms_services'] = []
            permissions['wfs_services'] = []
            permissions['background_layers'] = []
            permissions['data_datasets'] = []
            permissions['viewer_tasks'] = []
            permissions['theme_info_links'] = []
            permissions['plugin_data'] = []
            permissions['dataproducts'] = []
            permissions['document_templates'] = []
            permissions['print_templates'] = []
            permissions['solr_facets'] = []
            permissions['external_links'] = []

            role_config['permissions'] = permissions

            if role.name == 'public':
                public_index = index
            index += 1

            roles.append(role_config)

        if public_index != 0:
            # move public role to start of list
            public_role = roles.pop(public_index)
            roles.insert(0, public_role)

        return roles

    def merge_service_permissions(self, role_permissions, service_permissions):
        """Merge service permissions for a role into role permissions.

        :param obj role_permissions: Role permissions
        :param obj service_permissions: Service permissions
        """
        for resource_key in service_permissions:
            # merge resource type from service permissions
            self.merge_list(
                role_permissions[resource_key],
                service_permissions[resource_key]
            )

    def merge_list(self, target, source):
        """Recursively merge source list into target list.

        :param list target: Target list
        :param list source: Source list
        """
        if len(target) == 0:
            # take source list if target list is empty
            target += source
            return

        # lookup for target list items by name
        target_lookup = {}
        for item in target:
            if isinstance(item, dict):
                # list of dicts
                target_lookup[item['name']] = item
            else:
                # list of names
                target_lookup[item] = item

        # merge source items
        for item in source:
            if isinstance(item, dict):
                # list of dicts
                name = item['name']
                if name in target_lookup:
                    # merge items
                    self.merge_dict(target_lookup[name], item)
                else:
                    # add new item
                    target.append(item)
            else:
                # list of names
                if item not in target_lookup:
                    # add new item
                    target.append(item)

    def merge_dict(self, target, source):
        """Recursively merge source dict into target dict.

        Add any new keys and merge existing values.

        :param OrderedDict target: Target dict
        :param OrderedDict source: Source dict
        """
        if not target:
            # take source dict if target dict is empty
            target.update(source)

        for key, value in source.items():
            if key in target:
                # merge values
                if isinstance(value, dict):
                    self.merge_dict(target[key], value)
                elif isinstance(value, list):
                    self.merge_list(target[key], value)
                else:
                    if value != target[key]:
                        self.logger.warning(
                            "Values for '%s' differ: %s != %s" %
                            (key, target[key], value)
                        )
            else:
                # add new key
                target[key] = value
