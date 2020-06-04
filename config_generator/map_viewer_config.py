from collections import OrderedDict
import json
import os

from .service_config import ServiceConfig


class MapViewerConfig(ServiceConfig):
    """MapViewerConfig class

    Generate Map Viewer service config and permissions.
    """

    def __init__(self, tenant_path, capabilities_reader, service_config,
                 logger):
        """Constructor

        :param str tenant_path: Path to config files of tenant
        :param CapabilitiesReader capabilities_reader: CapabilitiesReader
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        """
        super().__init__(
            'mapViewer',
            'https://raw.githubusercontent.com/qwc-services/qwc-map-viewer/v2/schemas/qwc-map-viewer.json',
            service_config,
            logger
        )

        self.tenant_path = tenant_path
        self.capabilities_reader = capabilities_reader

        # keep track of theme IDs for uniqueness
        self.theme_ids = []

        self.default_theme = None

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        config['service'] = 'map-viewer'

        resources = OrderedDict()
        config['resources'] = resources

        # collect resources from QWC2 config and capabilities
        resources['qwc2_config'] = self.qwc2_config()
        resources['qwc2_themes'] = self.qwc2_themes()

        # copy index.html
        self.copy_index_html()

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # TODO: collect permissions from ConfigDB
        permissions['wms_services'] = []
        permissions['background_layers'] = self.permitted_background_layers(
            role
        )
        permissions['data_datasets'] = []

        return permissions

    # service config

    def qwc2_config(self):
        """Collect QWC2 application configuration from config.json."""
        # NOTE: use ordered keys
        qwc2_config = OrderedDict()

        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_qwc2_config = cfg_generator_config.get('qwc2_config', {})

        # read QWC2 config.json
        config = OrderedDict()
        try:
            config_file = cfg_qwc2_config.get(
                'qwc2_config_file', 'config.json'
            )
            with open(config_file) as f:
                # parse config JSON with original order of keys
                config = json.load(f, object_pairs_hook=OrderedDict)
        except Exception as e:
            self.logger.error("Could not load QWC2 config.json:\n%s" % e)
            config['ERROR'] = str(e)

        # remove service URLs
        service_urls = [
            'authServiceUrl',
            'editServiceUrl',
            'elevationServiceUrl',
            'featureReportService',
            'mapInfoService',
            'permalinkServiceUrl',
            'searchDataServiceUrl',
            'searchServiceUrl'
        ]
        for service_url in service_urls:
            config.pop(service_url, None)

        qwc2_config['config'] = config

        return qwc2_config

    def qwc2_themes(self):
        """Collect QWC2 themes configuration from capabilities."""
        # NOTE: use ordered keys
        qwc2_themes = OrderedDict()

        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_qwc2_themes = cfg_generator_config.get('qwc2_themes', {})

        # QWC2 themes config
        themes_config = self.capabilities_reader.themes_config
        themes_config_themes = themes_config.get('themes', {})

        # reset theme IDs and default theme
        self.theme_ids = []
        self.default_theme = None

        # collect resources from capabilities
        themes = OrderedDict()
        themes['title'] = 'root'

        # collect theme items
        items = []
        for item in themes_config_themes.get('items', []):
            theme_item = self.theme_item(item)
            if theme_item is not None:
                items.append(theme_item)
        themes['items'] = items

        # collect theme groups
        groups = []
        for group in themes_config_themes.get('groups', []):
            groups.append(self.theme_group(group))
        themes['subdirs'] = groups

        themes['defaultTheme'] = self.default_theme
        themes['externalLayers'] = themes_config_themes.get(
            'externalLayers', []
        )
        themes['backgroundLayers'] = themes_config_themes.get(
            'backgroundLayers', []
        )

        themes['pluginData'] = themes_config_themes.get('pluginData', [])
        themes['themeInfoLinks'] = themes_config_themes.get(
            'themeInfoLinks', []
        )

        themes['defaultWMSVersion'] = themes_config.get(
            'defaultWMSVersion', '1.3.0'
        )
        themes['defaultScales'] = themes_config.get('defaultScales')
        themes['defaultPrintScales'] = themes_config.get('defaultPrintScales')
        themes['defaultPrintResolutions'] = themes_config.get(
            'defaultPrintResolutions'
        )
        themes['defaultPrintGrid'] = themes_config.get('defaultPrintGrid')

        qwc2_themes['themes'] = themes

        return qwc2_themes

    def theme_group(self, cfg_group):
        """Recursively collect theme item group.

        :param obj theme_group: Themes config group
        """
        # NOTE: use ordered keys
        group = OrderedDict()
        group['title'] = cfg_group.get('title')

        # collect sub theme items
        items = []
        for item in cfg_group.get('items', []):
            theme_item = self.theme_item(item)
            if theme_item is not None:
                items.append(theme_item)
        group['items'] = items

        # recursively collect sub theme groups
        subgroups = []
        for subgroup in cfg_group.get('groups', []):
            subgroups.append(self.theme_group(subgroup))
        group['subdirs'] = subgroups

        return group

    def theme_item(self, cfg_item):
        """Collect theme item from capabilities.

        :param obj cfg_item: Themes config item
        """
        # NOTE: use ordered keys
        item = OrderedDict()

        # additional service config
        cfg_config = self.service_config.get('config', {})
        ogc_service_url = cfg_config.get(
            'ogc_service_url', '/ows/'
        ).rstrip('/') + '/'

        # get capabilities
        service_name = self.capabilities_reader.service_name(cfg_item['url'])
        cap = self.capabilities_reader.wms_capabilities.get(service_name)
        if cap is None:
            self.logger.warning(
                "Skipping theme item '%s': Could not get capabilities for %s" %
                (cfg_item.get('title', ""), cfg_item['url'])
            )
            return None

        root_layer = cap.get('root_layer', {})

        name = service_name

        item['id'] = self.unique_theme_id(name)
        item['name'] = name

        if cfg_item.get('default', False) is True:
            # set default theme
            self.default_theme = item['id']

        # title from themes config or capabilities
        title = cfg_item.get('title', cap.get('title'))
        if title is None:
            title = root_layer.get('title', name)
        item['title'] = title

        item['description'] = cfg_item.get('description', '')

        # URL relative to OGC service
        item['wms_name'] = name
        item['url'] = "%s%s" % (ogc_service_url, name)

        attribution = OrderedDict()
        attribution['Title'] = cfg_item.get('attribution')
        attribution['OnlineResource'] = cfg_item.get('attributionUrl')
        item['attribution'] = attribution

        # TODO: get abstract
        item['abstract'] = ''
        # TODO: get keywords
        item['keywords'] = ''
        item['mapCrs'] = cfg_item.get('mapCrs', 'EPSG:3857')
        self.set_optional_config(cfg_item, 'additionalMouseCrs', item)

        bbox = OrderedDict()
        bbox['crs'] = 'EPSG:4326'
        bbox['bounds'] = root_layer.get('bbox')
        item['bbox'] = bbox

        if 'extent' in cfg_item:
            initial_bbox = OrderedDict()
            initial_bbox['crs'] = cfg_item.get('mapCrs', 'EPSG:4326')
            initial_bbox['bounds'] = cfg_item.get('extent')
            item['initialBbox'] = initial_bbox
        else:
            item['initialBbox'] = item['bbox']

        # collect layers
        layers = []
        for layer in root_layer.get('layers', []):
            layers.append(self.collect_layers(layer))
        item['sublayers'] = layers
        item['expanded'] = True
        item['drawingOrder'] = cap.get('drawing_order', [])

        self.set_optional_config(cfg_item, 'externalLayers', item)
        self.set_optional_config(cfg_item, 'backgroundLayers', item)

        print_templates = cap.get('print_templates', [])
        if print_templates:
            if 'printLabelBlacklist' in cfg_item:
                # NOTE: copy print templates to not overwrite original config
                print_templates = [
                    template.copy() for template in print_templates
                ]
                for print_template in print_templates:
                    # filter print labels
                    labels = [
                        label for label in print_template['labels']
                        if label not in cfg_item['printLabelBlacklist']
                    ]
                    print_template['labels'] = labels
            item['print'] = print_templates

        self.set_optional_config(cfg_item, 'printLabelConfig', item)
        self.set_optional_config(cfg_item, 'printLabelForSearchResult', item)

        self.set_optional_config(cfg_item, 'extraLegendParameters', item)

        self.set_optional_config(cfg_item, 'skipEmptyFeatureAttributes', item)

        item['searchProviders'] = cfg_item.get('searchProviders', [])

        # TODO edit config
        item['editConfig'] = None

        self.set_optional_config(cfg_item, 'watermark', item)
        self.set_optional_config(cfg_item, 'config', item)
        self.set_optional_config(cfg_item, 'mapTips', item)
        self.set_optional_config(cfg_item, 'userMap', item)
        self.set_optional_config(cfg_item, 'pluginData', item)
        self.set_optional_config(cfg_item, 'themeInfoLinks', item)

        # TODO: generate thumbnail
        item['thumbnail'] = "img/mapthumbs/%s" % cfg_item.get(
            'thumbnail', 'default.jpg'
        )

        self.set_optional_config(cfg_item, 'version', item)
        self.set_optional_config(cfg_item, 'format', item)
        self.set_optional_config(cfg_item, 'tiled', item)

        # TODO: availableFormats
        item['availableFormats'] = [
            'image/jpeg',
            'image/png',
            'image/png; mode=16bit',
            'image/png; mode=8bit',
            'image/png; mode=1bit'
        ]
        # TODO: infoFormats
        item['infoFormats'] = [
            'text/plain',
            'text/html',
            'text/xml',
            'application/vnd.ogc.gml',
            'application/vnd.ogc.gml/3.1.1'
        ]

        self.set_optional_config(cfg_item, 'scales', item)
        self.set_optional_config(cfg_item, 'printScales', item)
        self.set_optional_config(cfg_item, 'printResolutions', item)
        self.set_optional_config(cfg_item, 'printGrid', item)

        return item

    def unique_theme_id(self, name):
        """Return unique theme id for item name.

        :param str name: Theme item name
        """
        theme_id = name

        # make sure id is unique
        suffix = 1
        while theme_id in self.theme_ids:
            # add suffix to name
            theme_id = "%s_%s" % (name, suffix)
            suffix += 1

        # add to used IDs
        self.theme_ids.append(theme_id)

        return theme_id

    def set_optional_config(self, cfg_item, field, item):
        """Set item config if present in themes config item.

        :param obj cfg_item: Themes config item
        :param str key: Config field
        :param obj item: Target theme item
        """
        if field in cfg_item:
            item[field] = cfg_item.get(field)

    def collect_layers(self, layer):
        """Recursively collect layer tree from capabilities.

        :param obj layer: Layer or group layer
        """
        # NOTE: use ordered keys
        item_layer = OrderedDict()

        item_layer['name'] = layer['name']
        if 'title' in layer:
            item_layer['title'] = layer['title']

        if 'layers' in layer:
            # group layer
            sublayers = []
            for sublayer in layer['layers']:
                # recursively collect sub layer
                sublayers.append(self.collect_layers(sublayer))

            item_layer['sublayers'] = sublayers

            # TODO: expanded
            item_layer['expanded'] = True

            # TODO: mutuallyExclusive
        else:
            # layer
            item_layer['visibility'] = layer['visible']
            item_layer['queryable'] = layer['queryable']
            if 'display_field' in layer:
                item_layer['displayField'] = layer.get('display_field')
            # TODO: opacity
            item_layer['opacity'] = 255
            if 'bbox' in layer:
                item_layer['bbox'] = layer.get('bbox')

            # TODO: metadata
            # TODO: min/max scale
            # TODO: featureReport

        return item_layer

    def copy_index_html(self):
        """Copy index.html to tenant dir."""

        # copy index.html
        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_qwc2_config = cfg_generator_config.get('qwc2_config', {})

        self.logger.info("Copying 'index.html' to tenant dir")
        try:
            # read index.html
            index_file = cfg_qwc2_config.get('qwc2_index_file', 'index.html')
            index_contents = None
            with open(index_file) as f:
                index_contents = f.read()

            # write to tenant dir
            target_path = os.path.join(self.tenant_path, 'index.html')
            with open(target_path, 'w') as f:
                f.write(index_contents)
        except Exception as e:
            self.logger.error("Could not copy QWC2 index.html:\n%s" % e)

    # permissions

    def permitted_background_layers(self, role):
        """Return permitted internal print layers for background layers from
        capabilities and ConfigDB.

        :param str role: Role name
        """
        background_layers = []

        # TODO: get permissions and restrictions from ConfigDB
        #       everything permitted to public role for now
        if role != 'public':
            return []

        # QWC2 themes config
        themes_config = self.capabilities_reader.themes_config
        themes_config_themes = themes_config.get('themes', {})

        for bg_layer in themes_config_themes.get('backgroundLayers', []):
            background_layers.append(bg_layer.get('name'))

        return background_layers
