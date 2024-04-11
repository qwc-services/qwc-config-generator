from collections import OrderedDict

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig

import os
import glob


class ExtServiceConfig(ServiceConfig):
    """ExtServiceConfig class

    Generate external link service config and permissions.
    """

    def __init__(self, config_models, schema_url, service_config, logger):
        """Constructor

        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__('ext', schema_url, service_config, logger)

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        # additional service config
        config['config'] = self.service_config.get('config', {})

        # service resources
        config['resources'] = OrderedDict(self.service_config.get('resources', {}))

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        permissions = OrderedDict()

        # collect permissions from ConfigDB
        with self.config_models.session() as session:
            # helper method alias
            permitted_resources = self.permissions_query.permitted_resources

            # collect role permissions from ConfigDB
            external_links = permitted_resources(
                'external_links', role, session
            ).keys()
            permissions['external_links'] = sorted(list(external_links))

        return permissions
