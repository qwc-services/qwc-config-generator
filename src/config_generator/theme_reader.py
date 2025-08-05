import os
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from .capabilities_reader import CapabilitiesReader
from .qgs_reader import QGSReader


class ThemeReader():
    """ThemeReader class

    Reads project metadata for all theme items in the QWC2 theme configuration.
    """

    def __init__(self, config, logger, config_models, themes_config, assets_dir, use_cached_project_metadata, cache_dir):
        """Constructor

        :param obj config: ConfigGenerator config
        :param Logger logger: Logger
        :param ConfigModels config_models: Helper for ORM models
        :param dict themes_config: themes config
        :param str assets_dir: Viewer assets directory
        :param bool use_cached_project_metadata: Whether to use cached project metadata if available
        :param str cache_dir: Project metadata cache directory
        """
        self.config = config
        self.logger = logger
        self.themes_config = themes_config
        self.config_models = config_models

        # Dictionary storing theme metadata
        self.theme_metadata = OrderedDict()

        global_print_layouts = self.__search_global_print_layouts()

        self.capabilities_reader = CapabilitiesReader(config, logger, use_cached_project_metadata, cache_dir)
        self.qgs_reader = QGSReader(config, logger, assets_dir, use_cached_project_metadata, global_print_layouts)

        self.default_qgis_server_url = config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.ows_prefix = urlparse(self.default_qgis_server_url).path.rstrip('/') + '/'

        self.__read_metadata_for_group(themes_config.get('themes', {}))


    def __search_global_print_layouts(self):
        """ Search for global print layouts in qgis_print_layouts_dir. """
        qgis_print_layouts_dir = self.config.get(
            'qgis_print_layouts_dir', '/layouts')
        qgis_print_layouts_tenant_subdir = self.config.get(
            'qgis_print_layouts_tenant_subdir', None)
        subdirpath = None
        if qgis_print_layouts_tenant_subdir:
            subdirpath = os.path.join(
                qgis_print_layouts_dir,
                qgis_print_layouts_tenant_subdir.lstrip('/')
            ).rstrip('/')
            self.logger.info(
                "<b>Searching for print layouts in %s</b>" % subdirpath)
        else:
            self.logger.info(
                "<b>Searching for print layouts in %s</b>" % qgis_print_layouts_dir)

        print_layouts = {}
        legend_layout_names = []
        for dirpath, dirs, files in os.walk(qgis_print_layouts_dir, followlinks=True):
            if subdirpath and not dirpath.startswith(subdirpath):
                continue
            relpath = dirpath[len(qgis_print_layouts_dir.rstrip('/')) + 1:]

            for filename in files:
                if Path(filename).suffix != ".qpt":
                    continue

                path = os.path.join(dirpath, filename)
                with open(path, encoding='utf-8') as fh:
                    doc = ElementTree.parse(fh)

                layout = doc.getroot()
                composer_map = doc.find(".//LayoutItem[@type='65639']")
                if layout.tag != "Layout" or composer_map is None:
                    self.logger.warning("Skipping invalid print template " + filename + " (may not contain a layout map element)")
                    continue

                size = composer_map.get('size').split(',')
                position = composer_map.get('positionOnPage').split(',')
                print_template = OrderedDict()
                print_template['name'] = os.path.join(relpath, layout.get('name'))
                print_map = OrderedDict()
                print_map['name'] = "map0"
                print_map['x'] = float(position[0])
                print_map['y'] = float(position[1])
                print_map['width'] = float(size[0])
                print_map['height'] = float(size[1])
                print_template['map'] = print_map

                labels = []
                for label in doc.findall(".//LayoutItem[@type='65641']"):
                    if label.get('visibility') == '1' and label.get('id'):
                        labels.append(label.get('id'))
                if labels:
                    print_template['labels'] = labels

                self.logger.info("Found print template " + filename + " (" + layout.get('name') + ")")
                print_layouts[print_template['name']] = print_template
                if print_template['name'].endswith("_legend"):
                    legend_layout_names.append(print_template['name'])

        for legend_layout_name in legend_layout_names:
            base = legend_layout_name[:-7] # strip _legend suffix
            if base in print_layouts:
                print_layouts[base]["legendLayout"] = legend_layout_name
                del print_layouts[legend_layout_name]

        return list(print_layouts.values())

    def __read_metadata_for_group(self, item_group):
        """ Recursively read theme metadata for theme item group. """
        for item in item_group.get('items', []):
            self.__read_metadata_for_theme(item)

        for group in item_group.get('groups', []):
            self.__read_metadata_for_group(group)

    def __read_metadata_for_theme(self, item):
        """ Read theme metadata for a theme item. """
        # get service name
        url = item.get('url')

        # check if theme is disabled
        if item.get('disabled', False):
            self.logger.info(f"<b>Theme {url} {"(" + item["title"] + ")" if item.get("title") else ""} has been disabled</b>")
            return

        service_name = self.service_name(url)
        if service_name in self.theme_metadata:
            # Return if theme already read
            return

        self.logger.info("<b>Reading theme %s</b>" % url)

        wms_capabilities = self.capabilities_reader.read_wms_service_capabilities(service_name, item, self.themes_config)
        wfs_capabilities = self.capabilities_reader.read_wfs_service_capabilities(service_name, item)
        project_metadata = self.qgs_reader.read(service_name, item, self.__get_edit_datasets(service_name))

        self.theme_metadata[service_name] = {
            'service_name': service_name,
            'url': url,
            'wms_capabilities': wms_capabilities,
            'wfs_capabilities': wfs_capabilities,
            'project_metadata': project_metadata
        }

    def __get_edit_datasets(self, service_name):
        """ Return edit datasets from permissions for the specified service. """
        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        edit_datasets = []
        with self.config_models.session() as session:
            # find map resource
            query = session.query(Resource) \
                .filter(Resource.type == 'map') \
                .filter(Resource.name == service_name)
            map_id = None
            for map_obj in query.all():
                map_id = map_obj.id

            if map_id is None:
                # map not found
                return []

            # query writable data permissions
            resource_types = ['data']
            datasets_query = session.query(Permission) \
                .join(Permission.resource) \
                .filter(Resource.parent_id == map_obj.id) \
                .filter(Resource.type.in_(resource_types)) \
                .distinct(Resource.name, Resource.type) \
                .order_by(Resource.name)

            edit_datasets = [
                permission.resource.name for permission in datasets_query.all()
            ]
        return edit_datasets

    def wms_service_names(self):
        """Return all WMS service names in alphabetical order."""
        return sorted(self.theme_metadata.keys())

    def wfs_service_names(self):
        """Return all WFS service names in alphabetical order."""
        return sorted([
            service_name for service_name in self.theme_metadata
            if self.theme_metadata[service_name]['wfs_capabilities']
        ])

    def wms_capabilities(self, service_name):
        """ Return the WMS servcice capabilities for the specified OWS service. """
        return self.theme_metadata.get(service_name, {}).get('wms_capabilities', {})

    def wfs_capabilities(self, service_name):
        """ Return the WFS servcice capabilities for the specified OWS service. """
        return self.theme_metadata.get(service_name, {}).get('wfs_capabilities', {})

    def project_metadata(self, service_name):
        """ Return the QGS project metadata for the specified OWS service. """
        return self.theme_metadata.get(service_name, {}).get('project_metadata', {})

    def service_name(self, url):
        """Return service name as relative path to default QGIS server URL.

        :param str url:  Theme item URL
        """
        if url.startswith(self.ows_prefix):
            return url[len(self.ows_prefix):]
        return url
