from collections import OrderedDict

from .service_config import ServiceConfig


class PrintServiceConfig(ServiceConfig):
    """PrintServiceConfig class

    Generate Print service config.
    """

    def __init__(self, themes_reader, schema_url, service_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader themes_reader: ThemesReader
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__('print', schema_url, service_config, logger)

        self.themes_reader = themes_reader

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        resources = OrderedDict()
        config['resources'] = resources

        # collect resources from capabilities
        resources['print_templates'] = self.print_templates()

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # TODO: collect permissions from ConfigDB
        permissions['print_templates'] = []

        return permissions

    # service config

    def print_templates(self):
        """Collect print template resources from capabilities."""
        print_templates = []

        for service_name in self.themes_reader.wms_service_names():
            cap = self.themes_reader.wms_capabilities(service_name)
            if not cap:
                return None

            # collect print templates
            if 'print_templates' in cap:
                for template in cap['print_templates']:
                    # NOTE: use ordered keys
                    print_template = OrderedDict()
                    print_template['template'] = template['name']

                    print_templates.append(print_template)

        return print_templates
