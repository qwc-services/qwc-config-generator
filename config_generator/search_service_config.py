from collections import OrderedDict
import json

from .service_config import ServiceConfig


class SearchServiceConfig(ServiceConfig):
    """SearchServiceConfig class

    Generate Search service config and permissions.
    """

    def __init__(self, service_config, logger):
        """Constructor

        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__(
            'search',
            'https://github.com/qwc-services/qwc-fulltext-search-service/raw/master/schemas/qwc-search-service.json',
            service_config,
            logger
        )

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        # additional service config
        cfg_resources = self.service_config.get('resources', {})

        # get resources directly from service config
        resources = OrderedDict()
        resources['facets'] = cfg_resources.get('facets', {})
        config['resources'] = resources

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # additional service config
        cfg_permissions = self.service_config.get('permissions', [])

        for role_permissions in cfg_permissions:
            # find role in permissions
            if role_permissions.get('role') == role:
                # get permissions for role directly from service config
                permissions = role_permissions.get('permissions', {})
                break

        return permissions
