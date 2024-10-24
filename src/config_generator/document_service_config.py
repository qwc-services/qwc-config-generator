from collections import OrderedDict
import os

from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class DocumentServiceConfig(ServiceConfig):
    """DocumentServiceConfig class

    Generate Document service config.
    """

    def __init__(self, generator_config, config_models, schema_url, service_config, logger):
        """Constructor

        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__('document', schema_url, service_config, logger)

        self.report_dir = generator_config.get("document_templates_dir", "/reports")
        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )

        self.config_models = config_models
        self.permissions_query = PermissionsQuery(config_models, logger)

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        # additional service config
        cfg_resources = self.service_config.get('resources', {})

        # scan for reports
        scanned_document_templates = []
        for root, dirs, files in os.walk(self.report_dir):
            subdir = os.path.relpath(root, self.report_dir)
            scanned_document_templates += [
                os.path.join(subdir, file[:-6]) for file in files if file.endswith(".jrxml")
            ]

        # additional service config
        config['resources'] = cfg_resources
        resources = config['resources']

        # get resources directly from service config()
        resources['document_templates'] = resources.get('document_templates', [])

        # add templates from scanned_document_templates which are not already manually defined
        for entry in resources['document_templates']:
            try:
                scanned_document_templates.remove(entry["template"])
            except:
                pass

        for template in scanned_document_templates:
            resources['document_templates'].append({"template": template})

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        if 'permissions' not in self.service_config:
            # helper method alias
            non_public_resources = self.permissions_query.non_public_resources
            permitted_resources = self.permissions_query.permitted_resources

            # collect permissions from ConfigDB
            with self.config_models.session() as session:

                # collect role permissions from ConfigDB
                role_permissions = {
                    'document_templates': permitted_resources(
                        'document_templates', role, session
                    )
                }

                # collect public permissions from ConfigDB
                public_role = self.permissions_query.public_role()
                public_permissions = {
                    'document_templates': permitted_resources(
                        'document_templates', public_role, session
                    )
                }

                # collect public restrictions from ConfigDB
                public_restrictions = {
                    'document_templates': non_public_resources('document_templates', session)
                }

                # Collect available templates
                available_document_templates = []
                for root, dirs, files in os.walk(self.report_dir):
                    subdir = os.path.relpath(root, self.report_dir)
                    available_document_templates += [
                        os.path.join(subdir, file[:-6]) for file in files if file.endswith(".jrxml")
                    ]
                available_document_templates += [
                    entry["template"]
                    for entry in self.service_config.get('resources', {}).get('document_templates', [])
                ]
                available_document_templates = list(set(available_document_templates))

                permitted_templates = []
                for template in available_document_templates:
                    # lookup permissions
                    if self.permissions_default_allow:
                        template_restricted_for_public = template in public_restrictions['document_templates']
                    else:
                        template_restricted_for_public = template not in public_permissions['document_templates']

                    template_permitted_for_role = template in role_permissions['document_templates']

                    # If map is not permitted, skip
                    if (
                        template_restricted_for_public
                        and not template_permitted_for_role
                    ):
                        continue

                    permitted_templates.append(template)

                permissions['document_templates'] = permitted_templates

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
