import argparse
from collections import OrderedDict
from datetime import datetime
import json
import os

import jsonschema
import requests

from qwc_services_core.config_models import ConfigModels
from qwc_services_core.database import DatabaseEngine
from capabilities_reader import CapabilitiesReader
from map_viewer_config import MapViewerConfig
from ogc_service_config import OGCServiceConfig
from permissions_config import PermissionsConfig
from service_config import ServiceConfig


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
            # load ORM models for ConfigDB
            config_db_url = generator_config.get(
                'config_db_url', 'postgresql:///?service=qwc_configdb'
            )
            db_engine = DatabaseEngine()
            self.config_models = ConfigModels(db_engine, config_db_url)
        except Exception as e:
            msg = (
                "Could not load ConfigModels for ConfigDB at '%s':\n%s" %
                (config_db_url, e)
            )
            self.logger.error(msg)
            raise Exception(msg)

        # load capabilites for all QWC2 theme items
        capabilities_reader = CapabilitiesReader(
            generator_config, self.logger
        )
        capabilities_reader.load_all_project_settings()

        # lookup for additional service configs by name
        self.service_configs = {}
        for service_config in self.config.get('services', []):
            self.service_configs[service_config['name']] = service_config

        # create service config handlers
        self.config_handler = {
            # services with resources
            'ogc': OGCServiceConfig(
                generator_config, capabilities_reader,
                self.service_config('ogc'), self.logger
            ),
            'mapViewer': MapViewerConfig(
                capabilities_reader, self.service_config('mapViewer'),
                self.logger
            ),

            # config-only services
            'adminGui': ServiceConfig(
                'adminGui',
                'https://raw.githubusercontent.com/qwc-services/qwc-admin-gui/master/schemas/qwc-admin-gui.json',
                self.service_config('adminGui'), self.logger, 'admin-gui'
            ),
            'dbAuth': ServiceConfig(
                'dbAuth',
                'https://raw.githubusercontent.com/qwc-services/qwc-db-auth/master/schemas/qwc-db-auth.json',
                self.service_config('dbAuth'), self.logger, 'db-auth'
            ),
            'elevation': ServiceConfig(
                'elevation',
                'https://github.com/qwc-services/qwc-elevation-service/raw/master/schemas/qwc-elevation-service.json',
                self.service_config('elevation'), self.logger
            ),
            'mapinfo': ServiceConfig(
                'mapinfo',
                'https://raw.githubusercontent.com/qwc-services/qwc-mapinfo-service/master/schemas/qwc-mapinfo-service.json',
                self.service_config('mapinfo'), self.logger
            ),
            'permalink': ServiceConfig(
                'permalink',
                'https://raw.githubusercontent.com/qwc-services/qwc-permalink-service/master/schemas/qwc-permalink-service.json',
                self.service_config('permalink'), self.logger
            )
        }

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

    def service_config(self, service):
        """Return any additional service config for service.

        :param str service: Service name
        """
        return self.service_configs.get(service, {})

    def write_configs(self):
        """Generate and save service config files."""
        for service_config in self.config.get('services', []):
            self.write_service_config(service_config['name'])

    def write_service_config(self, service):
        """Write service config file as JSON.

        :param str service: Service name
        """
        config_handler = self.config_handler.get(service)
        if config_handler:
            # generate service config
            config = config_handler.config()

            # validate JSON schema
            if self.validate_schema(config, config_handler.schema):
                self.logger.info(
                    "'%s' service config validates against schema" % service
                )
            else:
                self.logger.error(
                    "'%s' service config failed schema validation" % service
                )

            # write service config file
            filename = '%sConfig.json' % config_handler.service_name
            self.logger.info("Writing '%s' service config file" % filename)
            self.write_json_file(config, filename)
        else:
            self.logger.warning("Service '%s' not found" % service)

    def write_permissions(self):
        """Generate and save service permissions."""
        permissions_config = PermissionsConfig(self.config_models, self.logger)
        permissions = permissions_config.base_config()

        # collect service permissions
        for service_config in self.config.get('services', []):
            service = service_config['name']
            config_handler = self.config_handler.get(service)
            if config_handler:
                self.logger.info(
                    "Collecting '%s' service permissions" % service
                )
                for role in permissions['roles']:
                    permissions_config.merge_service_permissions(
                        role['permissions'],
                        config_handler.permissions(role['role'])
                    )
            else:
                self.logger.warning("Service '%s' not found" % service)

        # validate JSON schema
        if self.validate_schema(permissions, permissions_config.schema):
            self.logger.info("Service permissions validate against schema")
        else:
            self.logger.error("Service permissions failed schema validation")

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

    def validate_schema(self, config, schema_url):
        """Validate config against its JSON schema.

        :param OrderedDict config: Config data
        :param str schema_url: JSON schema URL
        """
        # download JSON schema
        response = requests.get(schema_url)
        if response.status_code != requests.codes.ok:
            self.logger.error(
                "Could not download JSON schema from %s:\n%s" %
                (schema_url, response.text)
            )
            return False

        # parse JSON
        try:
            schema = json.loads(response.text)
        except Exception as e:
            self.logger.error("Could not parse JSON schema:\n%s" % e)
            return False

        # FIXME: remove external schema refs from MapViewer schema for now
        #        until QWC2 JSON schemas are available
        if config.get('service') == 'map-viewer':
            self.logger.warning(
                "Removing external QWC2 schema refs from MapViewer JSON schema"
            )
            resources = schema['properties']['resources']['properties']
            # QWC2 application configuration as simple dict
            resources['qwc2_config']['properties']['config'] = {
                'type': 'object'
            }
            # QWC2 themes configuration as simple dict with 'themes'
            resources['qwc2_themes'] = {
                'type': 'object',
                'properties': {
                    'themes': {
                        'type': 'object'
                    }
                },
                'required': [
                    'themes'
                ]
            }

        # validate against schema
        valid = True
        validator = jsonschema.validators.validator_for(schema)(schema)
        for error in validator.iter_errors(config):
            valid = False

            # collect error messages
            messages = [
                e.message for e in error.context
            ]
            if not messages:
                messages = [error.message]

            # collect path to concerned subconfig
            # e.g. ['resources', 'wms_services', 0]
            #      => ".resources.wms_services[0]"
            path = ""
            for p in error.absolute_path:
                if isinstance(p, int):
                    path += "[%d]" % p
                else:
                    path += ".%s" % p

            # get concerned subconfig
            instance = error.instance
            if isinstance(error.instance, dict):
                # get first level of properties of concerned subconfig
                instance = OrderedDict()
                for key, value in error.instance.items():
                    if isinstance(value, dict) and value.keys():
                        first_value_key = list(value.keys())[0]
                        instance[key] = {
                            first_value_key: '...'
                        }
                    elif isinstance(value, list):
                        instance[key] = ['...']
                    else:
                        instance[key] = value

            # log errors
            message = ""
            if len(messages) == 1:
                message = "Validation error: %s" % messages[0]
            else:
                message = "\nValidation errors:\n"
                for msg in messages:
                    message += "  * %s\n" % msg
            self.logger.error(message)
            self.logger.warning("Location: %s" % path)
            self.logger.warning(
                "Value: %s" %
                json.dumps(
                    instance, sort_keys=False, indent=2, ensure_ascii=False
                )
            )

        return valid


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
