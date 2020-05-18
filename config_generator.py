import argparse
from collections import OrderedDict
from datetime import datetime
import json
import os


class Logger():
    """Simple logger class"""
    def debug(self, msg):
        print("[%s] \033[36mDEBUG: %s\033[0m" % (self.timestamp(), msg))

    def info(self, msg):
        print("[%s] INFO: %s" % (self.timestamp(), msg))

    def warning(self, msg):
        print("[%s] \033[33mWARNING: %s\033[0m" % (self.timestamp(), msg))

    def error(self, msg):
        print("[%s] \033[31mERROR: %s\033[0m" % (self.timestamp(), msg))

    def timestamp(self):
        return datetime.now()


class ConfigGenerator():
    """ConfigGenerator class

    Generate JSON files for service configs and permissions
    from a themesConfig.json, WMS GetCapabilities and QWC ConfigDB.
    """

    def __init__(self, config, logger):
        """Constructor

        :param obj config: ConfigGenerator config
        :param Logger logger: Logger
        """
        self.logger = logger

        self.config = config
        generator_config = config.get('config', {})
        self.tenant = generator_config.get('tenant', 'default')
        self.logger.info("Using tenant '%s'" % self.tenant)
        self.config_path = generator_config.get('config_path', '/tmp/')

        try:
            # check tenant dir
            tenant_path = os.path.join(self.config_path, self.tenant)
            if not os.path.isdir(tenant_path):
                # create tenant dir
                self.logger.info(
                    "Creating tenant dir %s" % tenant_path
                )
                os.mkdir(tenant_path)
        except Exception as e:
            self.logger.error("Could not create tenant dir:\n%s" % e)

    def write_configs(self):
        """Generate and save service config files."""
        for service in self.config.get('services', []):
            self.write_service_config(service)

    def write_service_config(self, service_config):
        """Write service config file as JSON.

        :param obj service_config: Additional service config
        """
        # TODO: generate service configs
        pass

    def write_permissions(self):
        """Generate and save service permissions."""
        # TODO: collect service permissions
        permissions = {}

        self.logger.info("Writing 'permissions.json' permissions file")
        self.write_json_file(permissions, 'permissions.json')

    def write_json_file(self, config, filename):
        """Write config to JSON file in config path.

        :param OrderedDict config: Config data
        """
        try:
            path = os.path.join(self.config_path, self.tenant, filename)
            with open(path, 'w') as f:
                # NOTE: keep order of keys
                f.write(json.dumps(
                    config, sort_keys=False, ensure_ascii=False, indent=2
                ))
        except Exception as e:
            self.logger.error(
                "Could not write '%s' config file:\n%s" % (filename, e)
            )


# command line interface
if __name__ == '__main__':
    print("QWC ConfigGenerator")

    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'config_file', help="Path to ConfigGenerator config file"
    )
    parser.add_argument(
        "command", choices=['all', 'service_configs', 'permissions'],
        help="generate service configs and/or permissions"
    )
    args = parser.parse_args()

    # read ConfigGenerator config file
    try:
        with open(args.config_file) as f:
            # parse config JSON with original order of keys
            config = json.load(f, object_pairs_hook=OrderedDict)
    except Exception as e:
        print("Error loading ConfigGenerator config:\n%s" % e)
        exit(1)

    # create logger
    logger = Logger()

    # create ConfigGenerator
    generator = ConfigGenerator(config, logger)
    if args.command == 'all':
        generator.write_configs()
        generator.write_permissions()
    elif args.command == 'service_configs':
        generator.write_configs()
    elif args.command == 'permissions':
        generator.write_permissions()
