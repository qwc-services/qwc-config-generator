from collections import OrderedDict
from urllib.parse import urljoin, urlparse

from .capabilities_reader import CapabilitiesReader
from .qgs_reader import QGSReader


class ThemeReader():
    """ThemeReader class

    Reads project metadata for all theme items in the QWC2 theme configuration.
    """

    def __init__(self, generator_config, themes_config, logger, print_layouts, use_cached_project_metadata, cache_dir):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param dict themes_config: themes config
        :param Logger logger: Logger
        :param list print_layouts: Found print layouts
        :param bool use_cached_project_metadata: Whether to use cached project metadata if available
        :param str cache_dir: Project metadata cache directory
        """
        self.config = generator_config
        self.logger = logger
        self.print_layouts = print_layouts

        self.themes_config = themes_config

        # Dictionary storing theme metadata
        self.theme_metadata = OrderedDict()

        self.capabilities_reader = CapabilitiesReader(generator_config, logger, use_cached_project_metadata, cache_dir)

        self.qgis_project_extension = generator_config.get(
            'qgis_project_extension', '.qgs')

        self.qgis_projects_base_dir = generator_config.get(
            'qgis_projects_base_dir', '/tmp/'
        )

        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.ows_prefix = urlparse(self.default_qgis_server_url).path.rstrip('/') + '/'

        self.generate_wfs_services = generator_config.get(
            'generate_wfs_services', False
        )

        self.read_metadata_for_group(
            themes_config.get('themes', {}),
            themes_config
        )

    def wms_service_names(self):
        """Return all WMS service names in alphabetical order."""
        return sorted(self.theme_metadata.keys())

    def wfs_service_names(self):
        """Return all WFS service names in alphabetical order."""
        # collect services with WFS capabilites
        wfs_services = []
        for service_name in self.theme_metadata:
            if self.theme_metadata[service_name]['wfs_capabilities']:
                wfs_services.append(service_name)
        return sorted(wfs_services)

    def read_metadata_for_group(self, item_group, themes_config):
        """Recursively read theme metadata for theme item group."""
        for item in item_group.get('items', []):
            self.read_metadata_for_theme(item, themes_config)

        for group in item_group.get('groups', []):
            # collect group items
            self.read_metadata_for_group(group, themes_config)

    def read_metadata_for_theme(self, item, themes_config):
        """Read theme metadata for a theme item.

        :param obj item: QWC2 themes config item.
        """
        # get service name
        url = item.get('url')
        # check if theme is disabled
        if item.get('disabled', False):
            self.logger.info(f"Theme {url} {"(" + item.get("title") + ")" if item.get("title") else ""} has been disabled")
            return
        service_name = self.service_name(url)
        if service_name in self.theme_metadata:
            # skip service already in cache
            return

        self.logger.info("<b>Reading theme %s</b>" % url)

        wms_capabilities = self.capabilities_reader.read_wms_service_capabilities(url, service_name, item, themes_config)

        wfs_capabilities = {}
        if self.generate_wfs_services:
            wfs_capabilities = self.capabilities_reader.read_wfs_service_capabilities(url, service_name, item)

        qgs_reader = QGSReader(
            self.config, self.logger, self.qgis_projects_base_dir,
            self.qgis_project_extension, service_name)
        project_read = qgs_reader.read()

        project_layouts = qgs_reader.print_templates() if project_read else []
        project_layouts_names = [layout['name'] for layout in project_layouts]
        wms_capabilities["print_templates"] = project_layouts + \
            [layout for layout in self.print_layouts if layout["name"] not in project_layouts_names]

        self.theme_metadata[service_name] = {
            'service_name': service_name,
            'url': url,
            'wms_capabilities': wms_capabilities,
            'wfs_capabilities': wfs_capabilities,
            'project': qgs_reader if project_read else None,
            'pg_layers': None,
            'layer_metadata': {}
        }

    def wms_capabilities(self, service_name):
        return self.theme_metadata[service_name]['wms_capabilities']

    def wfs_capabilities(self, service_name):
        return self.theme_metadata[service_name]['wfs_capabilities']

    def pg_layers(self, service_name):
        if not service_name in self.theme_metadata:
            return []

        if not self.theme_metadata[service_name]['project']:
            return []

        if not self.theme_metadata[service_name]['pg_layers']:
            pg_layers = self.theme_metadata[service_name]['project'].pg_layers()
            self.theme_metadata[service_name]['pg_layers'] = pg_layers
        return self.theme_metadata[service_name]['pg_layers']

    def layer_metadata(self, service_name, layername):
        if not self.theme_metadata[service_name]['project']:
            return {}

        if not layername in self.theme_metadata[service_name]['layer_metadata']:
            metadata = self.theme_metadata[service_name]['project'].layer_metadata(layername)
            self.theme_metadata[service_name]['layer_metadata'][layername] = metadata
        return self.theme_metadata[service_name]['layer_metadata'][layername]

    def collect_ui_forms(self, service_name, assets_dir, edit_dataset, nested_nrels):
        metadata = self.layer_metadata(service_name, edit_dataset)
        return self.theme_metadata[service_name]['project'].collect_ui_forms(assets_dir, edit_dataset, metadata, nested_nrels)

    def visibility_presets(self, service_name):
        if not self.theme_metadata[service_name]['project']:
            return {}
        return self.theme_metadata[service_name]['project'].visibility_presets()

    def service_name(self, url):
        """Return service name as relative path to default QGIS server URL.

        :param str url:  Theme item URL
        """
        if url.startswith(self.ows_prefix):
            return url[len(self.ows_prefix):]
        return url
