from collections import OrderedDict

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class MapInfoServiceConfig(ServiceConfig):
    """MapInfoServiceConfig class

    Generate mapinfo service config and permissions.
    """

    def __init__(self, generator_config, config_models, schema_url, service_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__('mapinfo', schema_url, service_config, logger)

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)
        self.permitted_resources = self.permissions_query.permitted_resources
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )


    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        # additional service config
        config['config'] = self.service_config.get('config', {})

        return config


    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = {'mapinfo_query': []}

        mapinfo_ids = [
            query.get('info_id') for query in
            self.service_config.get('config', {}).get('queries', [])
            if query.get('info_id')
        ]

        with self.config_models.session() as session:

            # helper method aliases
            non_public_resources = self.permissions_query.non_public_resources
            permitted_resources = self.permissions_query.permitted_resources

            # collect role permissions from ConfigDB
            role_permissions = permitted_resources('mapinfo_query', role, session)

            # collect public permissions from ConfigDB
            public_role = self.permissions_query.public_role()
            public_permissions = permitted_resources('mapinfo_query', public_role, session)

            # collect public restrictions from ConfigDB
            public_restrictions = non_public_resources('mapinfo_query', session)

            is_public_role = (role == self.permissions_query.public_role())


            for mapinfo_id in mapinfo_ids:
                # lookup permissions
                if self.permissions_default_allow:
                    mapinfo_restricted_for_public = mapinfo_id in \
                        public_restrictions
                else:
                    mapinfo_restricted_for_public = mapinfo_id not in \
                        public_permissions

                mapinfo_permitted_for_role = mapinfo_id in role_permissions

                if (is_public_role and not mapinfo_restricted_for_public) \
                    or (mapinfo_restricted_for_public and mapinfo_permitted_for_role) \
                :
                    permissions['mapinfo_query'].append(mapinfo_id)

        return permissions
