from collections import OrderedDict
from datetime import datetime
import json
import os
from shutil import copyfile, rmtree
import tempfile

import jsonschema
import requests

from qwc_services_core.config_models import ConfigModels
from qwc_services_core.database import DatabaseEngine
from .capabilities_reader import CapabilitiesReader
from .data_service_config import DataServiceConfig
from .feature_info_service_config import FeatureInfoServiceConfig
from .map_viewer_config import MapViewerConfig
from .ogc_service_config import OGCServiceConfig
from .permissions_config import PermissionsConfig
from .print_service_config import PrintServiceConfig
from .search_service_config import SearchServiceConfig
from .service_config import ServiceConfig

from logging import Logger as Log


class Logger:
    """Logger class

    Show and collect log entries.
    """

    LEVEL_DEBUG = 'debug'
    LEVEL_INFO = 'info'
    LEVEL_WARNING = 'warning'
    LEVEL_ERROR = 'error'
    LEVEL_CRITICAL = 'critical'

    def __init__(self, logger=None):
        """Constructor

        :param Logger logger: Logger
        """
        if logger:
            self.logger = logger
        else:
            self.logger = Log("Config Generator")

        self.logs = []

    def clear(self):
        """Clear log entries."""
        self.logs = []

    def log_entries(self):
        """Return log entries."""
        return self.logs

    def debug(self, msg):
        """Show debug log entry.

        :param str msg: Log message
        """
        self.logger.debug(msg)
        # do not collect debug entries

    def info(self, msg):
        """Add info log entry.

        :param str msg: Log message
        """
        self.logger.info(msg)
        self.add_log_entry(msg, self.LEVEL_INFO)

    def warning(self, msg):
        """Add warning log entry.

        :param str msg: Log message
        """
        self.logger.warning(msg)
        self.add_log_entry(msg, self.LEVEL_WARNING)

    def warn(self, msg):
        self.warning(msg)

    def error(self, msg):
        """Add error log entry.

        :param str msg: Log message
        """
        self.logger.error(msg)
        self.add_log_entry(msg, self.LEVEL_ERROR)

    def critical(self, msg):
        """Add critical log entry.

        :param str msg: Log message
        """
        self.logger.critical(msg)
        self.add_log_entry(msg, self.LEVEL_CRITICAL)

    def add_log_entry(self, msg, level):
        """Append log entry with level.

        :param str msg: Log message
        :param str level: Log level
        """
        self.logs.append({
            'msg': msg,
            'level': level
        })


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
        self.logger = Logger(logger)

        self.config = config
        generator_config = config.get('config', {})
        self.tenant = generator_config.get('tenant', 'default')
        self.logger.info("Using tenant '%s'" % self.tenant)
        # Set output config path for the generated configuration files.
        # If `config_path` is not set in the configGeneratorConfig.json,
        # then either use the `OUTPUT_CONFIG_PATH` ENV variable (if it is set)
        # or default back to the `/tmp/` directory
        self.config_path = generator_config.get(
            'config_path',
            os.environ.get(
               'OUTPUT_CONFIG_PATH', '/tmp/'
               ))
        self.tenant_path = os.path.join(self.config_path, self.tenant)

        self.temp_config_path = tempfile.mkdtemp(prefix='qwc_')
        self.temp_tenant_path = os.path.join(
            self.temp_config_path, self.tenant
        )

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
        self.capabilities_reader = CapabilitiesReader(
            generator_config, config.get("themesConfig"), self.logger
        )
        self.capabilities_reader.preprocess_qgs_projects(
            generator_config, self.tenant)
        self.capabilities_reader.search_qgs_projects(
            generator_config)
        self.capabilities_reader.load_all_project_settings()

        # lookup for additional service configs by name
        self.service_configs = {}
        for service_config in self.config.get('services', []):
            self.service_configs[service_config['name']] = service_config

        # create service config handlers
        self.config_handler = {
            # services with resources
            'ogc': OGCServiceConfig(
                generator_config, self.capabilities_reader, self.config_models,
                self.service_config('ogc'), self.logger
            ),
            'mapViewer': MapViewerConfig(
                self.temp_tenant_path,
                generator_config, self.capabilities_reader, self.config_models,
                self.service_config('mapViewer'), self.logger
            ),
            'featureInfo': FeatureInfoServiceConfig(
                generator_config, self.capabilities_reader, self.config_models,
                self.service_config('featureInfo'), self.logger
            ),
            'print': PrintServiceConfig(
                self.capabilities_reader,
                self.service_config('print'), self.logger
            ),
            'search': SearchServiceConfig(
                self.config_models, self.service_config('search'), self.logger
            ),
            'data': DataServiceConfig(
                self.service_config('data'), generator_config,
                self.config_models, self.logger
            ),

            # config-only services
            'adminGui': ServiceConfig(
                'adminGui',
                'https://github.com/qwc-services/qwc-admin-gui/raw/master/schemas/qwc-admin-gui.json',
                self.service_config('adminGui'), self.logger, 'admin-gui'
            ),
            'dbAuth': ServiceConfig(
                'dbAuth',
                'https://github.com/qwc-services/qwc-db-auth/raw/master/schemas/qwc-db-auth.json',
                self.service_config('dbAuth'), self.logger, 'db-auth'
            ),
            'elevation': ServiceConfig(
                'elevation',
                'https://github.com/qwc-services/qwc-elevation-service/raw/master/schemas/qwc-elevation-service.json',
                self.service_config('elevation'), self.logger
            ),
            'mapinfo': ServiceConfig(
                'mapinfo',
                'https://github.com/qwc-services/qwc-mapinfo-service/raw/master/schemas/qwc-mapinfo-service.json',
                self.service_config('mapinfo'), self.logger
            ),
            'permalink': ServiceConfig(
                'permalink',
                'https://github.com/qwc-services/qwc-permalink-service/raw/master/schemas/qwc-permalink-service.json',
                self.service_config('permalink'), self.logger
            )
        }

        try:
            # check tenant dirs
            if not os.path.isdir(self.temp_tenant_path):
                # create temp tenant dir
                self.logger.info(
                    "Creating temp tenant dir %s" % self.temp_tenant_path
                )
                os.mkdir(self.temp_tenant_path)

            if not os.path.isdir(self.tenant_path):
                # create tenant dir
                self.logger.info(
                    "Creating tenant dir %s" % self.tenant_path
                )
                os.mkdir(self.tenant_path)
        except Exception as e:
            self.logger.error("Could not create tenant dir:\n%s" % e)

    def service_config(self, service):
        """Return any additional service config for service.

        :param str service: Service name
        """
        return self.service_configs.get(service, {})

    def write_configs(self):
        """Generate and save service config files.

        Return True if the config files could be generated.
        """
        for service_config in self.config.get('services', []):
            self.write_service_config(service_config['name'])

        for log in self.logger.log_entries():
            if log["level"] == self.logger.LEVEL_CRITICAL:
                self.logger.critical(
                    "The generation of the configuration"
                    " files resulted in a failure")
                self.logger.critical(
                    "The configuration files were not updated!")
                return False

        for file_name in os.listdir(os.path.join(self.temp_tenant_path)):
            file_path = os.path.join(self.temp_tenant_path, file_name)
            if os.path.isfile(file_path):
                copyfile(
                    file_path, os.path.join(self.tenant_path, file_name)
                )

        self.logger.info(
            "The generation of the configuration files was successful")
        self.logger.info("Configuration files were updated!")
        return True

    def write_service_config(self, service):
        """Write service config file as JSON.

        :param str service: Service name
        """
        config_handler = self.config_handler.get(service)
        if config_handler:
            self.logger.info("Collecting '%s' service config" % service)

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
        """Generate and save service permissions.

        Return True if the service permissions could be generated.
        """
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

        for log in self.logger.log_entries():
            if log["level"] == self.logger.LEVEL_CRITICAL:
                self.logger.critical(
                    "The generation of the permission"
                    " files resulted in a failure.")
                self.logger.critical(
                    "The permission files were not updated!")
                return False

        copyfile(
            os.path.join(self.temp_tenant_path, 'permissions.json'),
            os.path.join(self.tenant_path, 'permissions.json')
        )
        self.logger.info(
            "The generation of the permission files was successful")
        self.logger.info("permission files were updated!")
        return True

    def write_json_file(self, config, filename):
        """Write config to JSON file in config path.

        :param OrderedDict config: Config data
        """
        try:
            path = os.path.join(self.temp_tenant_path, filename)
            with open(path, 'w') as f:
                # NOTE: keep order of keys
                f.write(json.dumps(
                    config, sort_keys=False, ensure_ascii=False, indent=2
                ))
        except Exception as e:
            self.logger.error(
                "Could not write '%s' config file:\n%s" % (filename, e)
            )

    def cleanup_temp_dir(self):
        """Remove temporary config dir."""
        try:
            if os.path.isdir(self.temp_config_path):
                self.logger.debug(
                    "Removing temp config dir %s" % self.temp_config_path
                )
                rmtree(self.temp_config_path)
        except Exception as e:
            self.logger.error("Could not remove temp config dir:\n%s" % e)

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
            self.logger.info(
                "Skipping JSON schema check for MapViewer"
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

    def get_logger(self):
        return self.logger

    def maps(self):
        """Return list of map names from QWC2 theme items."""
        return self.capabilities_reader.wms_service_names()

    def map_details(self, map_name):
        """Return details for a map from capabilities

        :param str map_name: Map name
        """
        map_details = OrderedDict()
        map_details['map'] = map_name
        map_details['layers'] = []

        # find map in capabilities
        cap = self.capabilities_reader.wms_capabilities.get(map_name)
        if cap is None:
            map_details['error'] = "Map not found"
        else:
            # collect list of layer names
            root_layer = cap.get('root_layer', {})
            map_details['layers'] = self.collect_layers(root_layer)

        return map_details

    def collect_layers(self, layer):
        """Recursively collect list of layer names from capabilities.

        :param obj layer: Layer or group layer
        """
        layers = []

        layers.append(layer['name'])
        if 'layers' in layer:
            # group layer
            for sublayer in layer['layers']:
                layers += self.collect_layers(sublayer)

        return layers
