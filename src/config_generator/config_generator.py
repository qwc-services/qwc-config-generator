import json
import os
import re
import tempfile
from concurrent.futures import CancelledError
from datetime import UTC, datetime
from logging import Logger as Log
from pathlib import Path
from shutil import copyfile, rmtree
from urllib.parse import urlparse

import deepmerge
import jsonschema
import requests
from qwc_services_core.config_models import ConfigModels
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.runtime_config import RuntimeConfig

from .data_service_config import DataServiceConfig
from .document_service_config import DocumentServiceConfig
from .ext_service_config import ExtServiceConfig
from .map_viewer_config import MapViewerConfig
from .mapinfo_service_config import MapInfoServiceConfig
from .ogc_service_config import OGCServiceConfig
from .permissions_config import PermissionsConfig
from .permissions_query import PermissionsQuery
from .search_service_config import SearchServiceConfig
from .service_config import ServiceConfig
from .theme_reader import ThemeReader


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


class ConfigGenerator:
    """ConfigGenerator class

    Generate JSON files for service configs and permissions
    from a tenantConfig.json and QWC ConfigDB.
    """

    def __init__(self, config_file, logger, cancelled_event, use_cached_project_metadata, force_readonly_datasets):
        """Constructor

        :param str config_file: ConfigGenerator config file
        :param Logger logger: Logger
        :param threading.Event cancelled_event: Event to signal that the config generator task is aborted
        :param bool use_cached_project_metadata: Whether to use cached project metadata if available
        :param bool force_readonly_datasets: Whether to force all datasets readonly
        """

        self.logger = Logger(logger)
        self.cancelled_event = cancelled_event

        config_file_dir = os.path.dirname(config_file)
        self.logger.info(f"Reading tenantConfig '{config_file_dir}'")
        try:
            with open(config_file, encoding='utf-8') as f:
                # parse config JSON with original order of keys
                config = json.load(f)
        except Exception as e:
            msg = f"Error loading ConfigGenerator config file {config_file}:\n{e}"
            self.logger.critical(msg)
            raise Exception(msg) from e

        self.tenant = config.get('config', {}).get('tenant', 'default')
        self.logger.info(f"Configuring tenant '{self.tenant}'")

        # Handle themesConfig in tenantConfig.json
        themes_config = config.get("themesConfig", None)
        if isinstance(themes_config, str):
            try:
                if not os.path.isabs(themes_config):
                    themes_config = os.path.join(config_file_dir, themes_config)
                with open(themes_config, encoding='utf-8') as f:
                    config["themesConfig"] = json.load(f)
            except Exception as e:
                msg = f"Failed to read themes configuration {themes_config}:\n{e!s}"
                self.logger.critical(msg)
                raise Exception(msg) from e
        elif not isinstance(themes_config, dict):
            msg = "Missing or invalid themes configuration in tenantConfig.json"
            self.logger.critical(msg)
            raise Exception(msg)

        if config.get('template', None):
            config_template_path = config.get('template')
            self.logger.info(f"Merging tenantConfig template '{config_template_path}'")
            if not os.path.isabs(config_template_path):
                config_template_path = os.path.join(config_file_dir, config_template_path)
            try:
                with open(config_template_path, encoding='utf-8') as fh:
                    config_template_data = fh.read().replace('$tenant$', self.tenant)
                    config_template = json.loads(config_template_data)

                    # Handle themesConfig if it has also been templated
                    themes_config_template = config_template.get("themesConfig", None)
                    if isinstance(themes_config_template, str):
                        try:
                            if not os.path.isabs(themes_config_template):
                                config_template_dir = os.path.dirname(config_template_path)
                                themes_config_template_path = os.path.join(config_template_dir, themes_config_template)
                            with open(themes_config_template_path, encoding='utf-8') as f:
                                config_template["themesConfig"] = json.load(f)
                        except Exception as e:
                            msg = f"Failed to read themes configuration {themes_config_template_path}:\n{e!s}"
                            self.logger.critical(msg)
                            raise Exception(msg) from e

                    config_services = {entry["name"]: entry for entry in config.get("services", [])}
                    config_template_services = {entry["name"]: entry for entry in config_template.get("services", [])}

                    config = deepmerge.always_merger.merge(config_template, config)
                    config["services"] = list(deepmerge.always_merger.merge(config_template_services, config_services).values())

                    # Get themesConfig from config because it could have been merged with a template
                    themes_config = config.get("themesConfig")
            except Exception as e:
                msg = f"Failed to merge config template {config_template_path}: {e!s}."
                self.logger.critical(msg)
                raise Exception(msg) from e

        self.config = config

        # Note: Wrap generator config in a RuntimeConfig so that config.get(...) honours environment variable overrides
        generator_config = RuntimeConfig("configGenerator", self.logger).set_config(config)

        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.ows_prefix = urlparse(self.default_qgis_server_url).path.rstrip('/') + '/'

        # Set output config path for the generated configuration files.
        # If `config_path` is not set in the configGeneratorConfig.json,
        # then either use the `OUTPUT_CONFIG_PATH` ENV variable (if it is set)
        # or default back to the `/tmp/` directory
        self.config_path = generator_config.get(
            'config_path',
            os.environ.get('OUTPUT_CONFIG_PATH', '/tmp/')
        )
        self.qwc_config_schema = generator_config.get('qwc_config_schema', 'qwc_config')
        self.tenant_path = os.path.join(self.config_path, self.tenant)
        self.logger.info(f"Config destination: {self.tenant_path}")

        self.temp_config_path = tempfile.mkdtemp(prefix='qwc_')
        self.temp_tenant_path = os.path.join(self.temp_config_path, self.tenant)

        self.do_validate_schema = str(generator_config.get(
            'validate_schema', True)).lower() != 'false'

        self.permissions_default_allow = generator_config.get(
            'permissions_default_allow', True
        )

        try:
            # load ORM models for ConfigDB
            config_db_url = generator_config.get(
                'config_db_url', 'postgresql:///?service=qwc_configdb'
            )
            db_engine = DatabaseEngine()
            self.config_models = ConfigModels(
                db_engine, config_db_url,
                qwc_config_schema=self.qwc_config_schema
            )
        except Exception as e:
            msg = f"Could not load ConfigModels for ConfigDB at '{config_db_url}':\n{e}"
            self.logger.error(msg)
            raise Exception(msg) from e

        # lookup for additional service configs by name
        self.service_configs = {}
        for service_config in self.config.get('services', []):
            self.service_configs[service_config['name']] = service_config

        # Read viewer config.json
        viewer_config = self.read_viewer_config()

        assets_dir = os.path.join(
            self.service_config('mapViewer')['config']['qwc2_path'],
            viewer_config.get('assetsPath', 'assets').lstrip('/')
        )
        viewer_languages = list(viewer_config.get('availableLocales', {}).keys()) or ["en-US"]
        self.logger.info(f"Assets destination: {assets_dir}")
        self.logger.info(f"Viewer languages: {viewer_languages}")

        self.check_cancelled()

        # Search for QGS projects in scan dir and automatically generate theme items
        self.search_qgs_projects(generator_config, config["themesConfig"])

        self.check_cancelled()

        # Load metadata for all QWC2 theme items
        capabilities_cache_dir = os.path.join(self.config_path, "__capabilities_cache")
        self.theme_reader = ThemeReader(
            generator_config, self.logger, self.check_cancelled, self.config_models, config["themesConfig"],
            assets_dir, viewer_languages, use_cached_project_metadata, capabilities_cache_dir
        )

        # load schema-versions.json
        schema_versions = {}
        schema_versions_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'schema-versions.json')
        try:
            with open(schema_versions_path, encoding='utf-8') as f:
                schema_versions = json.load(f)
        except Exception as e:
            msg = f"Could not load JSON schema versions from {schema_versions_path}:\n{e}"
            self.logger.warn(msg)

        # lookup for JSON schema URLs by service name
        self.schema_urls = {}
        for schema in schema_versions.get('schemas', []):
            self.schema_urls[schema.get('service')] = schema.get('schema_url', '')

        # get path to downloaded JSON schema files
        self.json_schemas_path = os.environ.get('JSON_SCHEMAS_PATH', '/tmp/')

        # validate config-generator JSON schema
        self.logger.debug("Validate qwc-config-generator schema URL")
        if self.validate_schema(self.config, self.schema_urls["configGenerator"]):
            self.logger.debug(
                "qwc-config-generator config validates against schema"
            )
        else:
            self.logger.error(
                "qwc-config-generator config failed schema validation"
            )
        self.check_cancelled()

        # create service config handlers
        self.config_handler = {
            # services with resources
            'ogc': OGCServiceConfig(
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('ogc'), self.service_config('ogc'),
                self.logger, force_readonly_datasets
            ),
            'mapViewer': MapViewerConfig(
                self.temp_tenant_path,
                generator_config, viewer_config, self.theme_reader, self.config_models,
                self.schema_urls.get('mapViewer'),
                self.service_config('mapViewer'), self.logger,
                use_cached_project_metadata, capabilities_cache_dir
            ),
            'search': SearchServiceConfig(
                self.config_models, self.schema_urls.get('search'),
                self.service_config('search'), self.logger
            ),
            'document': DocumentServiceConfig(
                generator_config, self.config_models, self.schema_urls.get('document'),
                self.service_config('document'), self.logger
            ),
            'data': DataServiceConfig(
                generator_config, self.theme_reader, self.config_models,
                self.schema_urls.get('data'), self.service_config('data'),
                self.logger, force_readonly_datasets
            ),
            'mapinfo': MapInfoServiceConfig(
                generator_config, self.config_models, self.schema_urls.get('mapinfo'),
                self.service_config('mapinfo'), self.logger
            ),
            'ext': ExtServiceConfig(
                self.config_models, self.schema_urls.get('ext'),
                self.service_config('ext'), self.logger
            ),
        }

        for service_name, service_config in self.service_configs.items():
            self.check_cancelled()
            # config-only services
            if service_name not in self.config_handler:
                # If service is not yet in config handler, it is a config-only service
                schema_url = self.schema_urls.get(service_name, service_config.get('schema_url', ''))
                config = ServiceConfig(
                    service_name, schema_url, self.service_config(service_name), self.logger,
                    re.sub(r'(?=[A-Z])', '-', service_name).lower()
                )
                self.config_handler[service_name] = config
                self.logger.debug(f"Add configuration for service {service_name}")
            else:
                self.logger.debug(f"Specific configuration for service {service_name} already exists")

        try:
            # check tenant dirs
            if not os.path.isdir(self.temp_tenant_path):
                # create temp tenant dir
                self.logger.debug(f"Creating temp tenant dir {self.temp_tenant_path}")
                os.mkdir(self.temp_tenant_path)

            if not os.path.isdir(self.tenant_path):
                # create tenant dir
                self.logger.info(f"Creating tenant dir {self.tenant_path}")
                os.mkdir(self.tenant_path)
        except Exception as e:
            self.logger.critical(f"Could not create tenant dir:\n{e}")

    def check_cancelled(self):
        """Checks whether the config generator run has been cancelled and, if yes, throws an exception.
        """
        if self.cancelled_event.is_set():
            raise CancelledError()

    def read_viewer_config(self):
        """ Read the viewer config file (config.json), merging any template if one is referenced. """
        map_viewer_config = self.service_config('mapViewer')
        viewer_config_file = map_viewer_config.get(
            'generator_config', {}).get('qwc2_config', {}).get('qwc2_config_file', 'config.json')

        try:
            self.logger.info(f"Reading viewer config '{viewer_config_file}'")
            with open(viewer_config_file, encoding='utf-8') as f:
                # parse config JSON with original order of keys
                viewer_config = json.load(f)
        except Exception as e:
            msg = f"Error loading viewer config file {viewer_config_file}:\n{e}"
            self.logger.critical(msg)
            raise Exception(msg) from e

        if viewer_config.get('template'):
            viewer_config_template_path = viewer_config.get('template')
            self.logger.info(f"Merging viewer config template '{viewer_config_template_path}'")
            if not os.path.isabs(viewer_config_template_path):
                viewer_config_file_dir = os.path.dirname(viewer_config_file)
                viewer_config_template_path = os.path.join(viewer_config_file_dir, viewer_config_template_path)
            try:
                with open(viewer_config_template_path, encoding='utf-8') as fh:
                    viewer_config_template_data = fh.read().replace('$tenant$', self.tenant)
                    viewer_config_template = json.loads(viewer_config_template_data)

                    viewer_config_plugins = {}
                    viewer_config_template_plugins = {}
                    for section in "common", "desktop", "mobile":
                        # NOTE: append cfg.task to name to handle TaskButton plugin entries
                        viewer_config_plugins[section] = {
                            entry["name"] + entry.get("cfg", {}).get("task", ""): entry
                            for entry in viewer_config.get("plugins", {}).get(section, [])
                        }
                        viewer_config_template_plugins[section] = {
                            entry["name"] + entry.get("cfg", {}).get("task", ""): entry
                            for entry in viewer_config_template.get("plugins", {}).get(section, [])
                        }

                    viewer_config = deepmerge.always_merger.merge(viewer_config_template, viewer_config)
                    viewer_config["plugins"] = viewer_config.get("plugins", {})
                    for section in "common", "desktop", "mobile":
                        viewer_config["plugins"][section] = list(
                            deepmerge.always_merger.merge(viewer_config_template_plugins[section],
                            viewer_config_plugins[section]).values()
                        )

            except Exception as e:
                msg = f"Failed to merge viewer config template {viewer_config_template_path}: {e!s}."
                self.logger.critical(msg)
                raise Exception(msg) from e

        return viewer_config

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
            self.check_cancelled()
            self.write_service_config(service_config['name'])

        criticals, errors = self.check_for_errors()
        if criticals or (not self.config.get("config").get("ignore_errors", False) and errors):
            self.logger.critical(
                "A critical error occurred while processing the configuration.")
            self.logger.critical(
                "The configuration files were not updated!")
            return False

        for file_name in os.listdir(os.path.join(self.temp_tenant_path)):
            file_path = os.path.join(self.temp_tenant_path, file_name)
            if os.path.isfile(file_path):
                copyfile(
                    file_path, os.path.join(self.tenant_path, file_name)
                )
                self.logger.info(f"Wrote '{file_name}' service config file")

        self.logger.info(
            '<b style="color: green">The generation of the configuration files was successful</b>')
        self.logger.info('<b style="color: green">Configuration files were updated!</b>')
        if errors:
            self.logger.warn('Some errors occured and have been ignored, please check the logs to resolve these.')
        return True

    def write_service_config(self, service):
        """Write service config file as JSON.

        :param str service: Service name
        """
        config_handler = self.config_handler.get(service)
        if config_handler:
            self.logger.info(f"<b>Generating '{service}' service config</b>")

            # generate service config
            config = config_handler.config()

            # validate JSON schema
            if self.validate_schema(config, config_handler.schema):
                self.logger.debug(f"'{service}' service config validates against schema")
            else:
                self.logger.error(f"'{service}' service config failed schema validation")

            # write service config file
            filename = f'{config_handler.service_name}Config.json'
            self.write_json_file(config, filename)
        else:
            self.logger.warning(f"Service '{service}' not found")

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
        permissions['permissions_default_allow'] = self.permissions_default_allow

        # collect service permissions
        for service_config in self.config.get('services', []):
            self.check_cancelled()
            service = service_config['name']
            config_handler = self.config_handler.get(service)
            if config_handler:
                self.logger.info(f"<b>Generating '{service}' service permissions</b>")
                for role in permissions['roles']:
                    permissions_config.merge_service_permissions(
                        role['permissions'],
                        config_handler.permissions(role['role'])
                    )
            else:
                self.logger.warning(f"Service '{service}' not found")

        # write permissions for custom resources
        custom_resource_types = self.config.get('custom_resource_types', [])
        for resource_type in custom_resource_types:
            for role in permissions['roles']:

                res_permissions = {}
                with self.config_models.session() as session:
                    permitted_resources = permissions_query.permitted_resources
                    resources = permitted_resources(resource_type, role['role'], session).keys()
                    res_permissions[resource_type] = sorted(resources)

                permissions_config.merge_service_permissions(
                    role['permissions'], res_permissions
                )

        # validate JSON schema
        if self.validate_schema(permissions, permissions_config.schema):
            self.logger.debug("Service permissions validate against schema")
        else:
            self.logger.error("Service permissions failed schema validation")

        self.write_json_file(permissions, 'permissions.json')

        criticals, errors = self.check_for_errors()
        if criticals or (not self.config.get("config").get("ignore_errors", False) and errors):
            self.logger.critical(
                "A critical error occurred while processing the configuration.")
            self.logger.critical(
                "The permission files were not updated!")
            return False

        copyfile(
            os.path.join(self.temp_tenant_path, 'permissions.json'),
            os.path.join(self.tenant_path, 'permissions.json')
        )
        self.logger.info("Wrote 'permissions.json' permissions file")
        self.logger.info(
            '<b style="color: green">The generation of the permission files was successful</b>')
        self.logger.info('<b style="color: green">Permission files were updated!</b>')
        if errors:
            self.logger.warn('Some errors occured and have been ignored, please check the logs to resolve these.')
        return True

    def write_json_file(self, config, filename):
        """Write config to JSON file in config path.

        :param OrderedDict config: Config data
        """
        try:
            path = os.path.join(self.temp_tenant_path, filename)
            with open(path, 'wb') as f:
                # NOTE: keep order of keys
                f.write(json.dumps(config, sort_keys=False, ensure_ascii=False, indent=2).encode('utf8'))
        except Exception as e:
            self.logger.critical(f"Could not write '{filename}' config file:\n{e}")

    def cleanup_temp_dir(self):
        """Remove temporary config dir."""
        try:
            if os.path.isdir(self.temp_config_path):
                self.logger.debug(f"Removing temp config dir {self.temp_config_path}")
                rmtree(self.temp_config_path)
        except Exception as e:
            self.logger.warn(f"Could not remove temp config dir:\n{e}")

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
            with open(file_path, encoding='utf-8') as f:
                schema = json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load JSON schema from {file_path}:\n{e}")

        if not schema:
            # download JSON schema
            self.logger.info(f"Downloading JSON schema from {schema_url}")
            try:
                response = requests.get(schema_url)
            except Exception as e:
                self.logger.warn(f"Could not download JSON schema from {schema_url}:\n{e!s}")
                return False

            if response.status_code != requests.codes.ok:
                self.logger.warn(f"Could not download JSON schema from {schema_url}:\n{response.text}")
                return False

            # parse JSON
            try:
                schema = json.loads(response.text)
            except Exception as e:
                self.logger.warn(f"Could not parse JSON schema:\n{e}")
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
                    path += f"[{p}]"
                else:
                    path += f".{p}"
            context = config
            for p in list(error.absolute_path)[:-1]:
                context = context[p]

            # get concerned subconfig
            instance = error.instance
            if isinstance(error.instance, dict):
                # get first level of properties of concerned subconfig
                instance = {}
                for key, value in error.instance.items():
                    if isinstance(value, dict) and value.keys():
                        first_value_key = next(iter(value.keys()))
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
                message = f"Validation error: {messages[0]}"
            else:
                message = "\nValidation errors:\n"
                for msg in messages:
                    message += f"  * {msg}\n"
            self.logger.error(message)
            self.logger.warning(f"Location: {path}")
            self.logger.warning(f"Value: {json.dumps(instance, sort_keys=False, indent=2, ensure_ascii=False)}")
            self.logger.warning(f"Context: {json.dumps(context, sort_keys=False, indent=2, ensure_ascii=False)}")

        return valid

    def search_qgs_projects(self, generator_config, themes_config):

        qgis_projects_base_dir = generator_config.get('qgis_projects_base_dir')
        qgis_projects_scan_base_dir = generator_config.get('qgis_projects_scan_base_dir')
        group_scanned_projects_by_dir = generator_config.get('group_scanned_projects_by_dir', False)
        save_scanned_projects_in_config = generator_config.get('save_scanned_projects_in_config', False)
        qgis_project_extension = generator_config.get('qgis_project_extension', '.qgs')

        if not qgis_projects_scan_base_dir:
            self.logger.info(
                "Skipping scanning for projects (qgis_projects_scan_base_dir not set)"
            )
            return

        if os.path.exists(qgis_projects_scan_base_dir):
            self.logger.info(f"<b>Searching for projects files in {qgis_projects_scan_base_dir}</b>")
        else:
            self.logger.warn(
                "The qgis_projects_scan_base_dir sub directory" +
                " does not exist: " + qgis_projects_scan_base_dir)
            return

        themes = themes_config.get("themes", {})
        # collect existing item urls
        items = themes.get("items", [])
        has_default = False
        for item in items:
            if item.get("default", False):
                has_default = True

        # collect existing groups
        groups = themes.get("groups", [])

        base_path = Path(qgis_projects_scan_base_dir)
        for item in base_path.glob('**/*'):
            self.check_cancelled()
            # Skip hidden files/folders
            if item.name.startswith("."):
                continue
            if group_scanned_projects_by_dir and item.is_dir():
                if item.parent == base_path:
                    # Search if dir is already a group
                    if not list(filter(lambda group: group["title"] == item.name, groups)):
                        self.logger.info(f"Create group {item.name} in themes configuration")
                        group = {}
                        group["title"] = item.name
                        group["items"] = []
                        group["groups"] = []
                        groups.append(group)
                    else:
                        self.logger.info(f"Group {item.name} already exists in themes configuration")
                else:
                    # Get group parent
                    group_parent = next(filter(lambda group: group["title"] == item.parent.name, groups))
                    # Search if dir is already a group in group parent
                    if not list(filter(lambda group: group["title"] == item.name, group_parent["groups"])):
                        self.logger.info(f"Create group {item.name} in themes configuration group {group_parent['title']}")
                        group = {}
                        group["title"] = item.name
                        group["items"] = []
                        group["groups"] = []
                        group_parent["groups"].append(group)
                    else:
                        self.logger.info(
                            f"Group {item.name} already exists in themes configuration group {group_parent['title']}"
                        )
            elif item.is_file() and item.suffix == qgis_project_extension:
                relpath = item.parent.relative_to(qgis_projects_base_dir)
                wmspath = os.path.join(self.ows_prefix, relpath, item.stem)
                if ' ' in wmspath:
                    self.logger.warning(
                        f"The project file '{os.path.join(relpath, item.stem)}' contains spaces, it will be ignored"
                    )
                    continue

                # Add to themes items
                theme_item = {}
                theme_item["url"] = wmspath
                theme_item["backgroundLayers"] = themes_config.get(
                    "defaultBackgroundLayers", [])
                theme_item["searchProviders"] = themes_config.get(
                    "defaultSearchProviders", [])

                if not has_default:
                    theme_item["default"] = True
                    has_default = True

                # Add theme to items or group
                if group_scanned_projects_by_dir and (item.parent != base_path):
                    if list(filter(lambda group: group["title"] == item.parent.name, groups)):
                        item_group = next(filter(lambda group: group["title"] == item.parent.name, groups))
                    else:
                        for group in groups:
                            if list(filter(lambda g: g["title"] == item.parent.name, group["groups"])):
                                item_group = next(filter(lambda g: g["title"] == item.parent.name, group["groups"]))
                    if not list(filter(lambda item: item["url"] == wmspath, item_group["items"])):
                        self.logger.info(f"Adding project {item.stem} to group {item.parent.name}")
                        item_group["items"].append(theme_item)
                    else:
                        self.logger.info(f"Project {item.stem} already exists in group {item.parent.name}")
                else:
                    # Search for theme if it already exists in items
                    if not list(filter(lambda item: item["url"] == wmspath, items)):
                        self.logger.info(f"Adding project {item.stem}")
                        items.append(theme_item)
                    else:
                        self.logger.info(f"Skipping project {item.name}")
        themes["groups"] = groups
        themes["items"] = items

        if save_scanned_projects_in_config:
            # Save themes_config in file to save scanned themes and groups
            base_themes_config = self.config.get("themesConfig", None)
            config_in_path = os.environ.get(
                'INPUT_CONFIG_PATH', 'config-in/'
            )
            config_file_dir = os.path.join(config_in_path, self.tenant)
            baksuffix = datetime.now(UTC).strftime("-%Y%m%d-%H%M%S") + ".bak"
            if isinstance(base_themes_config, str):
                themes_config_path = base_themes_config
                try:
                    if not os.path.isabs(themes_config_path):
                        themes_config_path = os.path.join(config_file_dir, themes_config_path)
                    with open(themes_config_path) as f:
                        base_themes_config = json.load(f)

                    if base_themes_config != themes_config:
                        with open(themes_config_path + baksuffix, "w", encoding="utf-8") as fh:
                            json.dump(base_themes_config, fh, indent=2, separators=(',', ': '))

                        with open(themes_config_path, "w", encoding="utf-8") as fh:
                            json.dump(themes_config, fh, indent=2, separators=(',', ': '))
                        self.logger.info("Themes configuration has been updated.")
                    else:
                        self.logger.info("Themes configuration did not change.")
                except OSError as e:
                    msg = f"Failed to backup/save themes configuration {themes_config_path}: {e.strerror}"
                    self.logger.error(msg)
            elif isinstance(base_themes_config, dict):
                tenant_config_path = os.path.join(
                    config_file_dir, 'tenantConfig.json'
                )
                # Read ConfigGenerator config file
                try:
                    with open(tenant_config_path, encoding='utf-8') as fh:
                        tenant_config = json.load(fh)
                except OSError as e:
                    self.logger.error(f"Error reading tenantConfig.json: {e.strerror}")
                if tenant_config["themesConfig"] != themes_config:
                    # Backup and save config file with new themes_config
                    try:
                        with open(tenant_config_path + baksuffix, "w", encoding="utf-8") as fh:
                            json.dump(tenant_config, fh, indent=2, separators=(',', ': '))

                        tenant_config["themesConfig"] = themes_config
                        with open(tenant_config_path, "w", encoding="utf-8") as fh:
                            json.dump(tenant_config, fh, indent=2, separators=(',', ': '))
                        self.logger.info("Themes configuration has been updated.")
                    except OSError as e:
                        msg = f"Failed to backup/save themes configuration {tenant_config_path}: {e.strerror}"
                        self.logger.error(msg)
                else:
                    self.logger.info("Themes configuration did not change.")
            else:
                msg = "Missing or invalid themes configuration in tenantConfig.json"
                self.logger.error(msg)

    def get_logger(self):
        return self.logger

    def maps(self):
        """Return list of map names from QWC2 theme items."""
        return self.theme_reader.wms_service_names()

    def map_details(self, map_name, with_attributes=False):
        """Return details for a map from capabilities

        :param str map_name: Map name
        """
        map_details = {}
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

    def check_for_errors(self):
        """Check if logs contain CRITICAL or ERROR level messages

        Return number of CRITICAL and ERROR messages.
        """
        criticals = [
            log_entry for log_entry in self.logger.log_entries()
            if log_entry.get('level', self.logger.LEVEL_INFO) == self.logger.LEVEL_CRITICAL
        ]
        errors = [
            log_entry for log_entry in self.logger.log_entries()
            if log_entry.get('level', self.logger.LEVEL_INFO) == self.logger.LEVEL_ERROR
        ]
        return (len(criticals), len(errors))
