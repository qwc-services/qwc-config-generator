from collections import OrderedDict
from urllib.parse import urljoin, urlparse

from .capabilities_reader import CapabilitiesReader
from .qgs_reader import QGSReader


class ThemeReader():
    """ThemeReader class

    Reads project metadata for all theme items in the QWC2 theme configuration.
    """

    def __init__(self, generator_config, themes_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param dict themes_config: themes config
        :param Logger logger: Logger
        """
        self.logger = logger

        self.themes_config = themes_config

        # Dictionary storing theme metadata
        self.theme_metadata = OrderedDict()

        # lookup for services names by URL: {<url>: <service_name>}
        self.service_name_lookup = {}

        self.capabilities_reader = CapabilitiesReader(generator_config, logger)

        self.qgis_projects_base_dir = generator_config.get(
            'qgis_projects_base_dir', '/tmp/'
        )

        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        self.read_metadata_for_group(
            themes_config.get('themes', {})
        )

    def wms_service_names(self):
        """Return all WMS service names in alphabetical order."""
        return sorted(self.theme_metadata.keys())

    def read_metadata_for_group(self, item_group):
        """Recursively read theme metadata for theme item group."""
        for item in item_group.get('items', []):
            self.read_metadata_for_theme(item)

        for group in item_group.get('groups', []):
            # collect group items
            self.read_metadata_for_group(group)

    def read_metadata_for_theme(self, item):
        """Read theme metadata for a theme item.

        :param obj item: QWC2 themes config item.
        """
        # get service name
        url = item.get('url')
        service_name = self.service_name(url)
        if service_name in self.theme_metadata:
            # skip service already in cache
            return

        capabilities = self.capabilities_reader.read_service_capabilities(url, service_name, item)
        if not capabilities:
            self.logger.warning(
                "Could not get capabilities for %s" % (cfg_item['url'])
            )

        qgs_reader = QGSReader(self.logger, self.qgis_projects_base_dir, service_name)
        success = qgs_reader.read()

        self.theme_metadata[service_name] = {
            'service_name': service_name,
            'url': url,
            'wms_capabilities': capabilities,
            'project': qgs_reader if success else None,
            'pg_layers': None,
            'layer_metadata': {}
        }

    def wms_capabilities(self, service_name):
        return self.theme_metadata[service_name]['wms_capabilities']

    def pg_layers(self, service_name):
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

    def collect_ui_forms(self, service_name, qwc_base_dir):
        return self.theme_metadata[service_name]['project'].collect_ui_forms(qwc_base_dir)

    def service_name(self, url):
        """Return service name as relative path to default QGIS server URL
        or last part of URL path if on a different WMS server.

        :param str url:  Theme item URL
        """
        # get full URL
        full_url = urljoin(self.default_qgis_server_url, url)

        if full_url in self.service_name_lookup:
            # service name from cache
            return self.service_name_lookup[full_url]

        service_name = full_url
        if service_name.startswith(self.default_qgis_server_url):
            # get relative path to default QGIS server URL
            service_name = service_name[len(self.default_qgis_server_url):]
        else:
            # get last part of URL path for other WMS server
            service_name = urlparse(full_url).path.split('/')[-1]

        # make sure service name is unique
        base_name = service_name
        suffix = 1
        while service_name in self.service_name_lookup.values():
            # add suffix to name
            service_name = "%s_%s" % (base_name, suffix)
            suffix += 1

        # add to lookup
        self.service_name_lookup[full_url] = service_name

        return service_name
