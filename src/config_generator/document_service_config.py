from collections import OrderedDict

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class DocumentServiceConfig(ServiceConfig):
    """DocumentServiceConfig class

    Generate Document service config.
    """

    def __init__(self, config_models, schema_url, service_config, logger):
        """Constructor

        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__('document', schema_url, service_config, logger)

        self.config_models = config_models

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        # additional service config
        cfg_resources = self.service_config.get('resources', {})

        # get resources directly from service config
        resources = OrderedDict()
        resources['document_templates'] = cfg_resources.get('document_templates', {})
        config['resources'] = resources

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        if 'permissions' not in self.service_config:
            # collect permissions from ConfigDB
            with self.config_models.session() as session:
                # helper method alias
                permitted_resources = self.permissions_query.permitted_resources

                # collect role permissions from ConfigDB
                document_templates = permitted_resources(
                    'document_templates', role, session
                ).keys()
                permissions['document_templates'] = sorted(list(document_templates))
        else:
            # use permissions from additional service config if present
            self.logger.debug("Reading permissions from tenantConfig")

            # additional service config
            cfg_permissions = self.service_config.get('permissions', [])

            for role_permissions in cfg_permissions:
                # find role in permissions
                if role_permissions.get('role') == role:
                    # get permissions for role directly from service config
                    document_permissions = role_permissions.get(
                        'permissions', {}
                    )
                    if 'document_templates' in document_permissions:
                        permissions['document_templates'] = \
                            document_permissions['document_templates']

                    break

        return permissions