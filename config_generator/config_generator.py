import json
import jsonschema
import os
import requests
import tempfile

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from shutil import move, copyfile, rmtree
from urllib.parse import urljoin, urlparse

from qwc_services_core.config_models import ConfigModels
from qwc_services_core.database import DatabaseEngine
from .theme_reader import ThemeReader
from .data_service_config import DataServiceConfig
from .ext_service_config import ExtServiceConfig
from .feature_info_service_config import FeatureInfoServiceConfig
from .map_viewer_config import MapViewerConfig
from .ogc_service_config import OGCServiceConfig
from .permissions_config import PermissionsConfig
from .print_service_config import PrintServiceConfig
from .search_service_config import SearchServiceConfig
from .legend_service_config import LegendServiceConfig
from .service_config import ServiceConfig
from .permissions_query import PermissionsQuery

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
    from a tenantConfig.json and QWC ConfigDB.
    """

    def __init__(self, config, logger, config_file_dir):
        """Constructor

        :param obj config: ConfigGenerator config
        :param Logger logger: Logger
        """
        self.logger = Logger(logger)

        self.config = config
        generator_config = config.get('config', {})
        self.tenant = generator_config.get('tenant', 'default')
        self.logger.debug("Using tenant '%s'" % self.tenant)

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.ows_prefix = generator_config.get(
            'ows_prefix', urlparse(self.default_qgis_server_url).path
        ).rstrip('/') + '/'

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
        self.logger.info("Config destination: '%s'" % self.tenant_path)

        self.temp_config_path = tempfile.mkdtemp(prefix='qwc_')
        self.temp_tenant_path = os.path.join(
            self.temp_config_path, self.tenant
        )

        self.do_validate_schema = str(generator_config.get(
            'validate_schema', True)).lower() != 'false'

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

        themes_config = config.get("themesConfig", None)

        if isinstance(themes_config, str):
            try:
                if not os.path.isabs(themes_config):
                    themes_config = os.path.join(config_file_dir, themes_config)
                with open(themes_config) as f:
                    themes_config = json.load(f)
            except:
                msg = "Failed to read themes configuration %s" % themes_config
                self.logger.error(msg)
                raise Exception(msg)
        elif not isinstance(themes_config, dict):
            msg = "Missing or invalid themes configuration in tenantConfig.json"
            self.logger.error(msg)
            raise Exception(msg)

        # Preprocess QGS projects
        self.preprocess_qgs_projects(generator_config, self.tenant)

        # Search for QGS projects in scan dir and automatically generate theme items
        self.search_qgs_projects(generator_config, themes_config)

        # load metadata for all QWC2 theme items
        self.theme_reader = ThemeReader(
            generator_config, themes_config, self.logger
        )

        # lookup for additional service configs by name
        self.service_configs = {}
        for service_config in self.config.get('services', []):
            self.service_configs[service_config['name']] = service_config

        # load schema-versions.json
        schema_versions = {}
        schema_versions_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            '../schemas/schema-versions.json'
        )
        try:
            with open(schema_versions_path) as f:
                schema_versions = json.load(f)
        except Exception as e:
            msg = (
                "Could not load JSON schema versions from %s:\n%s" %
                (schema_versions_path, e)
            )
            self.logger.error(msg)
            raise Exception(msg)

        # lookup for JSON schema URLs by service name
        self.schema_urls = {}
        for schema in schema_versions.get('schemas', []):
            self.schema_urls[schema.get('service')] = schema.get('schema_url', '')

        # get path to downloaded JSON schema files
        self.json_schemas_path = os.environ.get('JSON_SCHEMAS_PATH', '/tmp/')

        # create service config handlers
        self.config_handler = {
            # services with resources
            'ogc': OGCServiceConfig(
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('ogc'), self.service_config('ogc'),
                self.logger
            ),
            'mapViewer': MapViewerConfig(
                self.temp_tenant_path,
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('mapViewer'),
                self.service_config('mapViewer'), self.logger
            ),
            'featureInfo': FeatureInfoServiceConfig(
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('featureInfo'),
                self.service_config('featureInfo'), self.logger
            ),
            'print': PrintServiceConfig(
                self.theme_reader, self.schema_urls.get('print'),
                self.service_config('print'), self.logger
            ),
            'search': SearchServiceConfig(
                self.config_models, self.schema_urls.get('search'),
                self.service_config('search'), self.logger
            ),
            'legend': LegendServiceConfig(
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('legend'), self.service_config('legend'),
                self.logger
            ),
            'data': DataServiceConfig(
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('data'), self.service_config('data'),
                self.logger
            ),
            'ext': ExtServiceConfig(
                self.config_models, self.schema_urls.get('ext'),
                self.service_config('ext'), self.logger
            ),

            # config-only services
            'adminGui': ServiceConfig(
                'adminGui', self.schema_urls.get('adminGui'),
                self.service_config('adminGui'), self.logger, 'admin-gui'
            ),
            'dbAuth': ServiceConfig(
                'dbAuth', self.schema_urls.get('dbAuth'),
                self.service_config('dbAuth'), self.logger, 'db-auth'
            ),
            'elevation': ServiceConfig(
                'elevation', self.schema_urls.get('elevation'),
                self.service_config('elevation'), self.logger
            ),
            'mapinfo': ServiceConfig(
                'mapinfo', self.schema_urls.get('mapinfo'),
                self.service_config('mapinfo'), self.logger
            ),
            'permalink': ServiceConfig(
                'permalink', self.schema_urls.get('permalink'),
                self.service_config('permalink'), self.logger
            )
        }

        try:
            # check tenant dirs
            if not os.path.isdir(self.temp_tenant_path):
                # create temp tenant dir
                self.logger.debug(
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
            self.logger.debug("Collecting '%s' service config" % service)

            # generate service config
            config = config_handler.config()

            # validate JSON schema
            if self.validate_schema(config, config_handler.schema):
                self.logger.debug(
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
        permissions_config = PermissionsConfig(
            self.config_models, self.schema_urls.get('permissions'),
            self.logger
        )
        permissions_query = PermissionsQuery(self.config_models, self.logger)
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

        # write permissions for custom resources
        custom_resource_types = self.config.get('custom_resource_types', [])
        for resource_type in custom_resource_types:
            for role in permissions['roles']:

                res_permissions = OrderedDict()
                session = self.config_models.session()
                permitted_resources = permissions_query.permitted_resources
                resources = permitted_resources(resource_type, role['role'], session).keys()
                res_permissions[resource_type] = sorted(list(resources))
                session.close()

                permissions_config.merge_service_permissions(
                    role['permissions'], res_permissions
                )

        # validate JSON schema
        if self.validate_schema(permissions, permissions_config.schema):
            self.logger.debug("Service permissions validate against schema")
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
            with open(path, 'wb') as f:
                # NOTE: keep order of keys
                f.write(json.dumps(
                    config, sort_keys=False, ensure_ascii=False, indent=2
                ).encode('utf8'))
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
        if not self.do_validate_schema:
            self.logger.debug("Skipping schema validation")
            return True

        # load local JSON schema file
        schema = None
        try:
            # parse schema URL
            file_name = os.path.basename(urlparse(schema_url).path)
            file_path = os.path.join(self.json_schemas_path, file_name)
            with open(file_path) as f:
                schema = json.load(f)
        except Exception as e:
            self.logger.warning(
                "Could not load JSON schema from %s:\n%s" % (file_path, e)
            )

        if not schema:
            # download JSON schema
            self.logger.info("Downloading JSON schema from %s" % schema_url)
            try:
                response = requests.get(schema_url)
            except Exception as e:
                self.logger.error(
                    "Could not download JSON schema from %s:\n%s" %
                    (schema_url, str(e))
                )
                return False

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

    def preprocess_qgs_projects(self, generator_config, tenant):
        config_in_path = os.environ.get(
            'INPUT_CONFIG_PATH', 'config-in/'
        )

        if os.path.exists(config_in_path) is False:
            self.logger.warning(
                "The specified path does not exist: " + config_in_path)
            return

        qgs_projects_dir = os.path.join(
            config_in_path, tenant, "qgis_projects")
        if os.path.exists(qgs_projects_dir):
            self.logger.info(
                "Searching for projects files in " + qgs_projects_dir)
        else:
            self.logger.debug(
                "The qgis_projects sub directory does not exist: " +
                qgs_projects_dir)
            return

        # Output directory for processed projects
        qgis_projects_gen_base_dir = generator_config.get(
            'qgis_projects_gen_base_dir')
        if not qgis_projects_gen_base_dir:
            self.logger.warning("Skipping preprocessing qgis projects in " +
                                qgs_projects_dir +
                                ": qgis_projects_gen_base_dir is not set")
            return

        for dirpath, dirs, files in os.walk(qgs_projects_dir,
                                            followlinks=True):
            for filename in files:
                if Path(filename).suffix in [".qgs", ".qgz"]:
                    fname = os.path.join(dirpath, filename)
                    relpath = os.path.relpath(fname, qgs_projects_dir)
                    self.logger.info("Processing " + fname)

                    # convert project
                    dest_path = os.path.join(
                        qgis_projects_gen_base_dir, relpath)

                    if generator_config.get('split_categorized_layers', False) is True:
                        from .categorize_groups_script import split_categorized_layers
                        split_categorized_layers(fname, dest_path)
                    else:
                        copyfile(fname, dest_path)
                    if not os.path.exists(dest_path):
                        self.logger.warning(
                            "The project: " + dest_path +
                            " could not be generated.\n"
                            "Please check if needed permissions to create the"
                            " file are granted.")
                        continue
                    self.logger.info("Written to " + dest_path)

    def search_qgs_projects(self, generator_config, themes_config):

        qgis_projects_base_dir = generator_config.get(
            'qgis_projects_base_dir')
        qgis_projects_scan_base_dir = generator_config.get(
            'qgis_projects_scan_base_dir')
        qwc_base_dir = generator_config.get("qwc2_base_dir")

        if not qgis_projects_scan_base_dir:
            self.logger.info(
                "Skipping scanning for projects" +
                " (qgis_projects_scan_base_dir not set)")
            return

        if os.path.exists(qgis_projects_scan_base_dir):
            self.logger.info(
                "Searching for projects files in " + qgis_projects_scan_base_dir)
        else:
            self.logger.error(
                "The qgis_projects_scan_base_dir sub directory" +
                " does not exist: " + qgis_projects_scan_base_dir)
            return

        # collect existing item urls
        items = themes_config.get("themes", {}).get(
            "items", [])
        wms_urls = []
        has_default = False
        for item in items:
            if item.get("url"):
                wms_urls.append(item["url"])
            if item.get("default", False):
                has_default = True

        # This is needed because we don't want to
        # print the error message "thumbnail dir not found"
        # multiple times
        thumbnail_dir_exists = True
        thumbnail_directory = ""
        if qwc_base_dir is None:
            thumbnail_dir_exists = False
            self.logger.info(
                            "Skipping automatic thumbnail search "
                            "(qwc2_base_dir was not set)")
        else:
            thumbnail_directory = os.path.join(
                qwc_base_dir, "assets/img/mapthumbs")

        for dirpath, dirs, files in os.walk(qgis_projects_scan_base_dir,
                                            followlinks=True):
            for filename in files:
                if Path(filename).suffix in [".qgs", ".qgz"]:
                    fname = os.path.join(dirpath, filename)
                    relpath = os.path.relpath(dirpath,
                                              qgis_projects_base_dir)
                    wmspath = os.path.join(self.ows_prefix, relpath, Path(filename).stem)

                    # Add to themes items
                    item = OrderedDict()
                    item["url"] = wmspath
                    item["backgroundLayers"] = themes_config.get(
                        "defaultBackgroundLayers", [])
                    item["searchProviders"] = themes_config.get(
                        "defaultSearchProviders", [])
                    item["mapCrs"] = themes_config.get(
                        "defaultMapCrs")

                    # Check if thumbnail directory exists
                    if thumbnail_dir_exists and not os.path.exists(
                            thumbnail_directory):
                        self.logger.info(
                            "Thumbnail directory: %s does not exist" % (
                                thumbnail_directory))
                        thumbnail_dir_exists = False

                    # Scanning for thumbnail
                    if thumbnail_dir_exists:
                        thumbnail_filename = "%s.png" % Path(filename).stem
                        self.logger.info("Scanning for thumbnail(%s) under %s" % (
                            thumbnail_filename, thumbnail_directory))
                        thumbnail_path = os.path.join(
                                thumbnail_directory, thumbnail_filename)

                        if os.path.exists(thumbnail_path):
                            self.logger.info("Thumbnail: %s was found" % (
                                thumbnail_filename))
                            item["thumbnail"] = thumbnail_filename
                        else:
                            self.logger.info(
                                "Thumbnail: %s could not be found under %s" % (
                                    thumbnail_filename, thumbnail_path))

                    if item["url"] not in wms_urls:
                        self.logger.info("Adding project " + fname)
                        if not has_default:
                            item["default"] = True
                            has_default = True
                        items.append(item)
                    else:
                        self.logger.info("Skipping project " + fname)

    def get_logger(self):
        return self.logger

    def maps(self):
        """Return list of map names from QWC2 theme items."""
        return self.theme_reader.wms_service_names()

    def map_details(self, map_name, with_attributes=False):
        """Return details for a map from capabilities

        :param str map_name: Map name
        """
        map_details = OrderedDict()
        map_details['map'] = map_name
        map_details['layers'] = []

        # find map in capabilities
        theme_metadata = self.theme_reader.theme_metadata.get(map_name)
        if theme_metadata is None:
            map_details['error'] = "Map not found"
        else:
            cap = theme_metadata['wms_capabilities']
            # collect list of layer names
            root_layer = cap.get('root_layer', {})
            if with_attributes is False:
                map_details['layers'] = self.collect_layer_names(root_layer)
            else:
                map_details['layers'] = self.collect_layers(root_layer)
                for print_layer in cap.get('internal_print_layers', []):
                    map_details['layers'].append({print_layer: []})

                for geometryless_layer in cap.get('geometryless_layers', []):
                    map_details['layers'].append({geometryless_layer: []})

        return map_details

    def collect_layer_names(self, layer):
        """Recursively collect list of layer names from capabilities.

        :param obj layer: Layer or group layer
        """
        layers = []

        if 'layers' in layer:
            # group layer
            for sublayer in layer['layers']:
                layers += self.collect_layer_names(sublayer)
        else:
            layers.append(layer['name'])

        return layers

    def collect_layers(self, layer):
        """Recursively collect list of layer names from capabilities.

        :param obj layer: Layer or group layer
        """
        # dict containing all layers and atrributes of a map
        layers = []

        if 'attributes' in layer:
            layers.append({layer['name']: layer['attributes']})
        elif 'layers' in layer:
            # group layer
            layers.append({layer['name']: []})
            for sublayer in layer['layers']:
                layers += self.collect_layers(sublayer)

        return layers
