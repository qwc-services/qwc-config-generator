from collections import OrderedDict


class ServiceConfig():
    """ServiceConfig base class

    Base class for generating service configs and permissions.
    """

    def __init__(self, service_name, schema_url, logger):
        """Constructor

        :param str service_name: Service name for config file
        :param str schema_url: JSON schema URL for service config
        :param Logger logger: Logger
        """
        self.service_name = service_name
        self.schema = schema_url
        self.logger = logger

    def config(self, service_config):
        """Return service config.

        Implement in subclass

        :param obj service_config: Additional service config
        """
        # NOTE: use ordered keys
        config = OrderedDict()
        config['$schema'] = self.schema
        config['service'] = self.service_name
        # additional service config
        config['config'] = service_config.get('config', {})

        # return base service config
        return config

    def permissions(self, role):
        """Return service permissions for a role.

        Implement in subclass

        :param str role: Role name
        """
        # Note: empty if service has no permissions
        return {}
