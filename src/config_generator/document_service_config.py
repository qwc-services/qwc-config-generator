from collections import OrderedDict

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
