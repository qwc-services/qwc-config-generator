from collections import OrderedDict
import json
import os
from pathlib import Path
import requests
import traceback
import urllib.parse

from .external_layer_utils import resolve_external_layer
from .permissions_query import PermissionsQuery
from .service_config import ServiceConfig


class MapViewerConfig(ServiceConfig):
    """MapViewerConfig class

    Generate Map Viewer service config and permissions.
    """

    # lookup for edit geometry types:
    #     PostGIS geometry type -> QWC2 edit geometry type
    EDIT_GEOM_TYPES = {
        None: None,
        'POINT': 'Point',
        'POINTZ': 'PointZ',
        'MULTIPOINT': 'MultiPoint',
        'MULTIPOINTZ': 'MultiPointZ',
        'LINESTRING': 'LineString',
        'LINESTRINGZ': 'LineStringZ',
        'MULTILINESTRING': 'MultiLineString',
        'MULTILINESTRINGZ': 'MultiLineStringZ',
        'POLYGON': 'Polygon',
        'POLYGONZ': 'PolygonZ',
        'MULTIPOLYGON': 'MultiPolygon',
        'MULTIPOLYGONZ': 'MultiPolygonZ'
    }

    # lookup for edit field types:
    #     PostgreSQL data_type -> QWC2 edit field type
    EDIT_FIELD_TYPES = {
        'bigint': 'number',
        'boolean': 'boolean',
        'character varying': 'text',
        'date': 'date',
        'double precision': 'number',
        'file': 'file',
        'integer': 'number',
        'numeric': 'number',
        'real': 'number',
        'smallint': 'number',
        'text': 'text',
        'time': 'time',
        'timestamp with time zone': 'date',
        'timestamp without time zone': 'date',
        'uuid': 'text'
    }

    def __init__(self, tenant_path, generator_config, themes_reader,
                 config_models, schema_url, service_config, logger,
                 use_cached_project_metadata, cache_dir):
        """Constructor

        :param str tenant_path: Path to config files of tenant
        :param obj generator_config: ConfigGenerator config
        :param CapabilitiesReader themes_reader: ThemesReader
        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        :param bool use_cached_project_metadata: Whether to use cached project metadata if available
        :param str cache_dir: Project metadata cache directory
        """
        super().__init__('mapViewer', schema_url, service_config, logger)

        self.tenant_path = tenant_path
        self.themes_reader = themes_reader
        self.config_models = config_models
        self.use_cached_project_metadata = use_cached_project_metadata
        self.cache_dir = cache_dir
        self.permissions_query = PermissionsQuery(config_models, logger)
        # helper method alias
        self.permitted_resources = self.permissions_query.permitted_resources

        # get qwc2 directory from mapviewer config
        self.qwc_base_dir = service_config.get('config').get('qwc2_path')

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        # Use default map thumbnail instead of generating via GetMap
        self.use_default_map_thumbnail = generator_config.get(
            'use_default_map_thumbnail', False
        )

        # Timeout for generating thumbnail via GetMap request
        self.generate_thumbnail_timeout = generator_config.get(
            "generate_thumbnail_timeout", 10
        )

        self.project_settings_read_timeout = generator_config.get(
            "project_settings_read_timeout", 60
        )

        qgis_projects_base_dir = generator_config.get(
            'qgis_projects_base_dir').rstrip('/') + '/'
        qgis_projects_scan_base_dir = generator_config.get(
            'qgis_projects_scan_base_dir')
        if qgis_projects_scan_base_dir:
            self.scan_prefix = os.path.relpath(qgis_projects_scan_base_dir, qgis_projects_base_dir) + "/"
            self.strip_scan_prefix = generator_config.get('strip_scan_prefix_from_theme_names', False)
        else:
            self.strip_scan_prefix = False

        # keep track of theme IDs for uniqueness
        self.theme_ids = []

        # group counter
        self.groupCounter = 0

        self.default_theme = None

    def config(self):
        """Return service config."""
        # get base config
        config = super().config()

        config['service'] = 'map-viewer'

        resources = OrderedDict()
        config['resources'] = resources

        # collect resources from QWC2 config, capabilities and ConfigDB
        resources['qwc2_config'] = self.qwc2_config()
        assets_dir = os.path.join(
            self.qwc_base_dir,
            resources['qwc2_config']['config'].get('assetsPath', 'assets').lstrip('/')
        )
        resources['qwc2_themes'] = self.qwc2_themes(assets_dir)

        # copy index.html
        self.copy_index_html()

        return config

    def permissions(self, role):
        """Return service permissions for a role.

        :param str role: Role name
        """
        # NOTE: use ordered keys
        permissions = OrderedDict()

        # collect permissions from ConfigDB
        with self.config_models.session() as session:
            # NOTE: WMS service permissions collected by OGC service config
            permissions['wms_services'] = []
            permissions['background_layers'] = self.permitted_background_layers(
                role
            )
            # NOTE: Data permissions collected by Data service config
            permissions['data_datasets'] = []
            permissions['viewer_tasks'] = self.permitted_viewer_tasks(
                role, session
            )
            permissions['theme_info_links'] = self.permitted_theme_info_links(
                role, session
            )
            permissions['plugin_data'] = self.permitted_plugin_data_resources(
                role, session
            )

        return permissions

    # service config

    def qwc2_config(self):
        """Collect QWC2 application configuration from config.json."""
        # NOTE: use ordered keys
        qwc2_config = OrderedDict()

        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_qwc2_config = cfg_generator_config.get('qwc2_config', {})

        # collect restricted menu items from ConfigDB
        qwc2_config['restricted_viewer_tasks'] = self.restricted_viewer_tasks()

        # read QWC2 config.json
        config = OrderedDict()
        try:
            config_file = cfg_qwc2_config.get(
                'qwc2_config_file', 'config.json'
            )
            with open(config_file, encoding='utf-8') as f:
                # parse config JSON with original order of keys
                config = json.load(f, object_pairs_hook=OrderedDict)
        except Exception as e:
            self.logger.critical("Could not load QWC2 config.json:\n%s" % e)
            config['ERROR'] = str(e)

        # remove service URLs
        service_urls = [
            'authServiceUrl',
            'editServiceUrl',
            'elevationServiceUrl',
            'featureReportService',
            'documentServiceUrl',
            'mapInfoService',
            'permalinkServiceUrl',
            'searchDataServiceUrl',
            'searchServiceUrl'
        ]
        for service_url in service_urls:
            config.pop(service_url, None)

        qwc2_config['config'] = config

        return qwc2_config

    def restricted_viewer_tasks(self):
        """Collect restricted viewer tasks from ConfigDB."""
        with self.config_models.session() as session:
            viewer_tasks = self.permissions_query.non_public_resources(
                'viewer_task', session
            )

        return sorted(list(viewer_tasks))

    def qwc2_themes(self, assets_dir):
        """Collect QWC2 themes configuration from capabilities,
        and edit config from ConfigDB.

        :param str assets_dir: Assets dir
        """
        # NOTE: use ordered keys
        qwc2_themes = OrderedDict()

        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_qwc2_themes = cfg_generator_config.get('qwc2_themes', {})

        # QWC2 themes config
        themes_config = self.themes_reader.themes_config
        themes_config_themes = themes_config.get('themes', {})

        # reset theme IDs,  default theme and group counter
        self.theme_ids = []
        self.default_theme = None
        self.groupCounter = 0

        # collect resources from capabilities
        themes = OrderedDict()
        themes['title'] = 'root'

        # collect theme items
        items = []
        autogenExternalLayers = []
        bgLayerCrs = {}
        for item in themes_config_themes.get('items', []):
            theme_item = self.theme_item(item, themes_config, assets_dir, autogenExternalLayers, bgLayerCrs)
            if theme_item is not None and not theme_item['wmsOnly']:
                items.append(theme_item)
        themes['items'] = items

        # collect theme groups
        groups = []
        for group in themes_config_themes.get('groups', []):
            groups.append(self.theme_group(group, themes_config, assets_dir, autogenExternalLayers, bgLayerCrs))
        themes['subdirs'] = groups

        if not self.default_theme and self.theme_ids:
            self.default_theme = self.theme_ids[0]

        themes['defaultTheme'] = themes_config.get(
            'defaultTheme', self.default_theme) or self.default_theme
        themes['externalLayers'] = themes_config_themes.get(
            'externalLayers', []
        )
        themes['backgroundLayers'] = themes_config_themes.get(
            'backgroundLayers', []
        )
        for backgroundLayer in themes['backgroundLayers']:
            backgroundLayer["attribution"] = {
                "Title": backgroundLayer["attribution"] if "attribution" in backgroundLayer else None,
                "OnlineResource": backgroundLayer["attributionUrl"] if "attributionUrl" in backgroundLayer else None
            }
            backgroundLayer.pop("attributionUrl", None)

            imgPath = backgroundLayer.get("thumbnail", "")
            if not os.path.isfile(os.path.join(assets_dir, imgPath)):
                imgPath = "img/mapthumbs/" + backgroundLayer.get("thumbnail", "default.jpg")
                if not os.path.isfile(os.path.join(assets_dir, imgPath)):
                    imgPath = "img/mapthumbs/default.jpg"
            backgroundLayer["thumbnail"] = imgPath

        # Resolve background layers
        for entry in themes['backgroundLayers']:
            if not "name" in entry or not entry["name"] in bgLayerCrs:
                self.logger.warn("Skipping unused background layer %s" % entry.get("name", ""))
                continue
            if "resource" in entry:
                layer = resolve_external_layer(entry["resource"], self.logger, self.project_settings_read_timeout, bgLayerCrs[entry["name"]], self.use_cached_project_metadata, self.cache_dir)
                if layer:
                    layer["name"] = entry["name"]
                    entry.update(layer)
                    del entry["resource"]

        # Resolve external layers
        for entry in autogenExternalLayers:
            layer = resolve_external_layer(entry, self.logger, self.project_settings_read_timeout, None, self.use_cached_project_metadata, self.cache_dir)
            if layer:
                themes["externalLayers"].append(layer)

        themes['pluginData'] = themes_config_themes.get('pluginData', {})
        themes['themeInfoLinks'] = themes_config_themes.get(
            'themeInfoLinks', []
        )

        themes['defaultMapCrs'] = themes_config.get('defaultMapCrs')
        themes['defaultWMSVersion'] = themes_config.get(
            'defaultWMSVersion', '1.3.0'
        )
        themes['defaultScales'] = themes_config.get('defaultScales')
        themes['defaultPrintScales'] = themes_config.get('defaultPrintScales')
        themes['defaultPrintResolutions'] = themes_config.get('defaultPrintResolutions')
        themes['defaultPrintGrid'] = themes_config.get('defaultPrintGrid')
        themes['defaultSearchProviders'] = themes_config.get('defaultSearchProviders')
        themes['defaultBackgroundLayers'] = themes_config.get('defaultBackgroundLayers', [])

        qwc2_themes['themes'] = themes

        return qwc2_themes

    def theme_group(self, cfg_group, themes_config, assets_dir, autogenExternalLayers, bgLayerCrs):
        """Recursively collect theme item group.

        :param obj theme_group: Themes config group
        :param str assets_dir: Assets dir
        """
        # NOTE: use ordered keys
        group = OrderedDict()
        self.groupCounter += 1
        group['id'] = "g%d" % self.groupCounter
        group['title'] = cfg_group.get('title')

        # collect sub theme items
        items = []
        for item in cfg_group.get('items', []):
            theme_item = self.theme_item(item, themes_config, assets_dir, autogenExternalLayers, bgLayerCrs)
            if theme_item is not None and not theme_item['wmsOnly']:
                items.append(theme_item)
        group['items'] = items

        # recursively collect sub theme groups
        subgroups = []
        for subgroup in cfg_group.get('groups', []):
            subgroups.append(self.theme_group(subgroup, themes_config, assets_dir, autogenExternalLayers, bgLayerCrs))
        group['subdirs'] = subgroups

        return group

    def theme_item(self, cfg_item, themes_config, assets_dir, autogenExternalLayers, bgLayerCrs):
        """Collect theme item from capabilities.

        :param obj cfg_item: Themes config item
        :param str assets_dir: Assets dir
        """
        # NOTE: use ordered keys
        item = OrderedDict()

        # get capabilities
        service_name = self.themes_reader.service_name(cfg_item['url'])
        cap = self.themes_reader.wms_capabilities(service_name)
        if not cap or not 'name' in cap:
            return None

        root_layer = cap.get('root_layer', {})

        name = service_name

        if self.strip_scan_prefix:
            if name.startswith(self.scan_prefix):
                name = name[len(self.scan_prefix):]

        item['id'] = cfg_item.get('id', self.unique_theme_id(name))
        item['name'] = name

        if cfg_item.get('default', False) is True:
            # set default theme
            self.default_theme = item['id']

        # title from themes config or capabilities
        title = cfg_item.get('title', cap.get('title'))
        if title is None:
            title = root_layer.get('title', service_name)
        item['title'] = title

        item['description'] = cfg_item.get('description', '')

        item['wmsOnly'] = cfg_item.get('wmsOnly', False)
        if item['wmsOnly'] == True:
            self.logger.info("Configuring %s as WMS-only theme" % cfg_item['url'])

        # URL relative to OGC service
        item['wms_name'] = service_name
        item['url'] = cfg_item['url']

        attribution = OrderedDict()
        attribution['Title'] = cfg_item.get('attribution')
        attribution['OnlineResource'] = cfg_item.get('attributionUrl')
        item['attribution'] = attribution

        item['abstract'] = cap.get('abstract', '')
        item['keywords'] = cap.get('keywords', '')
        item['onlineResource'] = cap.get('onlineResource', '')
        item['contact'] = cap.get('contact', {})


        item['mapCrs'] = cfg_item.get('mapCrs', themes_config.get('defaultMapCrs', 'EPSG:3857'))
        self.set_optional_config(cfg_item, 'additionalMouseCrs', item)
        featureReports = cfg_item.get("featureReport", {})

        bbox = OrderedDict()
        bbox['crs'] = 'EPSG:4326'
        bbox['bounds'] = root_layer.get('bbox')
        item['bbox'] = bbox

        if 'extent' in cfg_item:
            initial_bbox = OrderedDict()
            initial_bbox['crs'] = cfg_item.get('mapCrs', item['mapCrs'])
            initial_bbox['bounds'] = cfg_item.get('extent')
            item['initialBbox'] = initial_bbox
        else:
            item['initialBbox'] = item['bbox']

        # get search layers from searchProviders
        search_providers = cfg_item.get('searchProviders', themes_config.get('defaultSearchProviders', []))
        search_layers = {}
        for search_provider in search_providers:
            if (
                'provider' in search_provider
                and (
                    search_provider.get('provider') == 'solr' or
                    search_provider.get('provider') == 'fulltext'
                )
            ):
                search_layers = search_provider.get('params', {}).get('layers', search_provider.get('layers', {}))
                break

        # collect layers
        layers = []
        collapseLayerGroupsBelowLevel = cfg_item.get(
            'collapseLayerGroupsBelowLevel', -1)

        externalLayers = cfg_item.get("externalLayers") if "externalLayers" in cfg_item else []
        newExternalLayers = []
        for layer in root_layer.get('layers', []):
            layers.append(self.collect_layers(
                layer, search_layers, 1, collapseLayerGroupsBelowLevel, newExternalLayers, service_name, featureReports))

        # Inject crs in wmts resource string
        for entry in newExternalLayers:
            if entry["name"].startswith("wmts:"):
                urlobj = urllib.parse.urlparse(entry["name"][5:])
                params = dict(urllib.parse.parse_qsl(urlobj.query))
                params["crs"] = item['mapCrs']
                urlobj = urlobj._replace(query=urllib.parse.urlencode(params))
                entry["name"] = "wmts:" + urllib.parse.urlunparse(urlobj)

        item['sublayers'] = layers
        item['expanded'] = True
        item['drawingOrder'] = cap.get('drawing_order', [])
        item['externalLayers'] = externalLayers + newExternalLayers

        self.set_optional_config(cfg_item, 'backgroundLayers', item)
        # Collect crs of background layers
        for entry in item.get('backgroundLayers', []):
            bgLayerCrs[entry['name']] = item['mapCrs']

        print_templates = cap.get('print_templates', [])
        if print_templates:
            # NOTE: copy print templates to not overwrite original config
            print_templates = [
                template.copy() for template in print_templates
            ]
            for print_template in print_templates:
                if 'printLabelBlacklist' in cfg_item:
                    # filter print labels
                    labels = [
                        label for label in print_template.get('labels', [])
                        if label not in cfg_item['printLabelBlacklist']
                    ]
                    print_template['labels'] = labels

                print_template['default'] = print_template['name'] == cfg_item.get('defaultPrintLayout')
            item['print'] = print_templates

        self.set_optional_config(cfg_item, 'printLabelConfig', item)
        self.set_optional_config(cfg_item, 'printLabelForSearchResult', item)
        self.set_optional_config(cfg_item, 'printLabelForAttribution', item)

        self.set_optional_config(cfg_item, 'extraLegendParameters', item)
        self.set_optional_config(cfg_item, 'extraDxfParameters', item)
        self.set_optional_config(cfg_item, 'extraPrintParameters', item)

        self.set_optional_config(cfg_item, 'skipEmptyFeatureAttributes', item)

        if "minSearchScaleDenom" in cfg_item.keys():
            item["minSearchScaleDenom"] = cfg_item.get("minSearchScaleDenom")
        elif "minSearchScale" in cfg_item.keys():  # Legacy name
            item["minSearchScaleDenom"] = cfg_item.get("minSearchScale")

        self.set_optional_config(cfg_item, "visibility", item)

        item['searchProviders'] = search_providers

        # edit config
        item['editConfig'] = self.edit_config(service_name, cfg_item, assets_dir)

        self.set_optional_config(cfg_item, 'watermark', item)
        self.set_optional_config(cfg_item, 'config', item)
        self.set_optional_config(cfg_item, 'flags', item)
        self.set_optional_config(cfg_item, 'mapTips', item)
        self.set_optional_config(cfg_item, 'userMap', item)
        self.set_optional_config(cfg_item, 'pluginData', item)
        self.set_optional_config(cfg_item, 'snapping', item)
        self.set_optional_config(cfg_item, 'themeInfoLinks', item)
        self.set_optional_config(cfg_item, 'layerTreeHiddenSublayers', item)
        self.set_optional_config(cfg_item, 'predefinedFilters', item)
        self.set_optional_config(cfg_item, 'map3d', item)

        if not cfg_item.get('wmsOnly', False):
            item['thumbnail'] = self.get_thumbnail(cfg_item, service_name, cap, assets_dir)

        self.set_optional_config(cfg_item, 'version', item)
        self.set_optional_config(cfg_item, 'format', item)
        self.set_optional_config(cfg_item, 'tiled', item)
        self.set_optional_config(cfg_item, 'tileSize', item)

        item['availableFormats'] = cap['map_formats']
        item['infoFormats'] = cap['info_formats']

        self.set_optional_config(cfg_item, 'scales', item)
        self.set_optional_config(cfg_item, 'printScales', item)
        self.set_optional_config(cfg_item, 'printResolutions', item)
        self.set_optional_config(cfg_item, 'printGrid', item)

        autogenExternalLayers += list(map(lambda entry: entry["name"], newExternalLayers))

        return item

    def get_thumbnail(self, cfg_item, service_name, capabilities, assets_dir):
        """Return thumbnail for item config if present in QWC2 default directory.
        Else new thumbnail is created with GetMap request.

        :param obj cfg_item: Themes config item
        :param str service_name: Service name as relative path to default QGIS server URL
        :param obj capabilities: Capabilities for theme item
        :param str assets_dir: Assets dir
        """
        thumbnail_directory = os.path.join(assets_dir, 'img/mapthumbs')
        if 'thumbnail' in cfg_item:
            if os.path.exists(os.path.join(thumbnail_directory, cfg_item['thumbnail'])):
                return os.path.join('img/mapthumbs', cfg_item['thumbnail'])
            else:
                self.logger.warn("Specified thumbnail %s for theme %s does not exist" % (
                    cfg_item['thumbnail'], service_name))

        # Scanning for thumbnail
        thumbnail_filename = "%s.png" % Path(service_name).stem
        thumbnail_path = os.path.join(
                thumbnail_directory, thumbnail_filename)

        if os.path.exists(thumbnail_path):
            self.logger.info("Using manually provided thumbnail %s for theme %s" % (
                thumbnail_filename, service_name))
            return os.path.join('img/mapthumbs', thumbnail_filename)

        if self.use_default_map_thumbnail:
            self.logger.info("Using default map thumbnail for " + service_name)
            return os.path.join('img/mapthumbs', 'default.jpg')

        basename = cfg_item["url"].rsplit("/")[-1].rstrip("?") + ".png"
        thumbnail = os.path.join(assets_dir, "img/genmapthumbs", basename)
        if self.use_cached_project_metadata:
            if os.path.isfile(thumbnail):
                self.logger.info("Using pre-existing autogenerated thumbnail for " + service_name)
                return 'img/genmapthumbs/' + basename

        self.logger.info("Using WMS GetMap to generate thumbnail for " + service_name)

        root_layer = capabilities.get('root_layer', {})

        crs = root_layer['crs']

        extent = None
        bbox = root_layer['bbox']
        extent = [
            float(bbox[0]), # minx
            float(bbox[1]), # miny
            float(bbox[2]), # maxx
            float(bbox[3])  # maxy
        ]

        layers = []
        for layer in root_layer.get('layers', []):
            layers.append(layer['name'])

        # WMS GetMap request
        url = urllib.parse.urljoin(self.default_qgis_server_url, service_name)

        bboxw = extent[2] - extent[0]
        bboxh = extent[3] - extent[1]
        bboxcx = 0.5 * (extent[0] + extent[2])
        bboxcy = 0.5 * (extent[1] + extent[3])
        imgratio = 200. / 100.
        if bboxw > bboxh:
            bboxratio = bboxw / bboxh
            if bboxratio > imgratio:
                bboxh = bboxw / imgratio
            else:
                bboxw = bboxh * imgratio
        else:
            bboxw = bboxh * imgratio
        adjustedExtent = [bboxcx - 0.5 * bboxw, bboxcy - 0.5 * bboxh,
                          bboxcx + 0.5 * bboxw, bboxcy + 0.5 * bboxh]

        try:
            response = requests.get(
                url,
                params={
                    'SERVICE': 'WMS',
                    'VERSION': '1.3.0',
                    'REQUEST': 'GetMap',
                    'FORMAT': 'image/png',
                    'WIDTH': '200',
                    'HEIGHT': '100',
                    'CRS': crs,
                    'BBOX': (",".join(map(str, adjustedExtent))),
                    'LAYERS': (",".join(layers).encode('utf-8'))
                },
                timeout=self.generate_thumbnail_timeout
            )

            if response.status_code != requests.codes.ok:
                self.logger.warn(
                    "Error generating thumbnail for WMS %s:\n%s" %
                    (service_name, response.content)
                )
                return 'img/mapthumbs/default.jpg'

            document = response.content

            try:
                os.makedirs(os.path.join(assets_dir, "img/genmapthumbs/"))
            except Exception as e:
                if not isinstance(e, FileExistsError):
                    self.logger.warn("The directory for auto generated thumbnails could not be created\n %s" % (str(e)))
            with open(thumbnail, "wb") as fh:
                fh.write(document)
            return 'img/genmapthumbs/' + basename
        except Exception as e:
            self.logger.warn("Error generating thumbnail for WMS " + service_name + ":\n" + str(e))
            return 'img/mapthumbs/default.jpg'

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

    def collect_layers(self, layer, search_layers, level, collapseBelowLevel, externalLayers, service_name, featureReports):
        """Recursively collect layer tree from capabilities.

        :param obj layer: Layer or group layer
        :param obj search_layers: Lookup for search layers
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
                sublayers.append(self.collect_layers(
                    sublayer, search_layers, level + 1, collapseBelowLevel, externalLayers, service_name, featureReports))

            # abstract
            if 'abstract' in layer:
                item_layer['abstract'] = layer.get('abstract')

            item_layer['sublayers'] = sublayers

            # expanded
            if layer.get("expanded") is True:
                item_layer['expanded'] = False if collapseBelowLevel >= 0 and \
                    level >= collapseBelowLevel else True
            else:
                item_layer['expanded'] = False

            # mutuallyExclusive
            item_layer["mutuallyExclusive"] = layer.get("mutuallyExclusive")

            # visible
            item_layer['visibility'] = layer['visible']
        else:
            # layer
            item_layer['visibility'] = layer['visible']
            item_layer['geometryType'] = layer['geometryType']
            item_layer['category_sublayer'] = layer['category_sublayer']
            item_layer['queryable'] = layer['queryable']
            item_layer['styles'] = layer['styles']
            if 'default' in item_layer['styles']:
                item_layer['style'] = 'default'
            elif len(item_layer['styles']) > 0:
                item_layer['style'] = list(item_layer['styles'])[0]
            else:
                item_layer['style'] = ''
            if 'display_field' in layer:
                item_layer['displayField'] = layer.get('display_field')
            item_layer['opacity'] = layer['opacity']
            if 'bbox' in layer:
                item_layer['bbox'] = {
                    'crs': 'EPSG:4326',
                    'bounds': layer.get('bbox')
                }

            # min/max scale
            minScale = layer.get("minScale")
            maxScale = layer.get("maxScale")
            if minScale:
                item_layer["minScale"] = int(float(minScale))
            if maxScale:
                item_layer["maxScale"] = int(float(maxScale))

            if 'dimensions' in layer:
                item_layer["dimensions"] = layer.get('dimensions')
                # Fallback for pre qgis-3.26.0
                meta = None
                for dimension in item_layer["dimensions"]:
                    if not dimension["fieldName"]:
                        if not meta:
                            meta = self.themes_reader.layer_metadata(service_name, layer['name'])
                            if not meta or 'dimensions' not in meta:
                                break
                        dimmeta = meta['dimensions']
                        if dimension['name'] in dimmeta:
                            dimension["fieldName"] = dimmeta[dimension['name']]["fieldName"]
                            dimension["endFieldName"] = dimmeta[dimension['name']]["endFieldName"]

            # abstract
            if 'abstract' in layer:
                item_layer['abstract'] = layer.get('abstract')
            # keywords
            if 'keywords' in layer:
                item_layer['keywords'] = layer.get('keywords')
            # attribution
            attribution = OrderedDict()
            attribution['Title'] = layer.get('attribution')
            attribution['OnlineResource'] = layer.get('attributionUrl')
            item_layer['attribution'] = attribution
            # dataUrl
            if 'dataUrl' in layer:
                item_layer['dataUrl'] = layer.get('dataUrl', '')
                if item_layer["dataUrl"].startswith("wms:") or item_layer["dataUrl"].startswith("wmts:") or item_layer["dataUrl"].startswith("mvt:"):
                    externalLayers.append({"internalLayer": layer['name'], "name": item_layer["dataUrl"]})
                item_layer["dataUrl"] = ""

            # metadataUrl
            if 'metadataUrl' in layer:
                item_layer['metadataUrl'] = layer.get('metadataUrl', '')

            # search
            if layer['name'] in search_layers:
                item_layer['searchterms'] = [search_layers.get(layer['name'])]

            # featureReport
            if layer['name'] in featureReports:
                item_layer['featureReport'] = featureReports[layer['name']]

        return item_layer

    def edit_config(self, map_name, cfg_item, assets_dir):
        """Collect edit config for a map from ConfigDB.

        :param str map_name: Map name (matches WMS and QGIS project)
        :param obj cfg_item: Theme config item
        :param str assets_dir: Assets dir
        """
        # NOTE: use ordered keys
        edit_config = OrderedDict()

        Permission = self.config_models.model('permissions')
        Resource = self.config_models.model('resources')

        with self.config_models.session() as session:
            # find map resource
            query = session.query(Resource) \
                .filter(Resource.type == 'map') \
                .filter(Resource.name == map_name)
            map_id = None
            for map_obj in query.all():
                map_id = map_obj.id

            if map_id is None:
                # map not found
                return edit_config

            # query writable data permissions
            resource_types = [
                'data',
                'data_create', 'data_read', 'data_update', 'data_delete'
            ]
            datasets_query = session.query(Permission) \
                .join(Permission.resource) \
                .filter(Resource.parent_id == map_obj.id) \
                .filter(Resource.type.in_(resource_types)) \
                .distinct(Resource.name, Resource.type) \
                .order_by(Resource.name)

            edit_datasets = []
            for permission in datasets_query.all():
                edit_datasets.append(permission.resource.name)

        if not edit_datasets:
            # no edit datasets for this map
            return edit_config

        # collect edit datasets
        for layer_name in self.themes_reader.pg_layers(map_name):
            if layer_name not in edit_datasets:
                # skip layers not in datasets
                continue

            dataset_name = "%s.%s" % (map_name, layer_name)

            try:
                # get layer metadata from QGIS project
                meta = self.themes_reader.layer_metadata(map_name, layer_name)
            except Exception as e:
                self.logger.error(
                    "Could not get metadata for edit dataset '%s':\n%s" %
                    (dataset_name, e)
                )
                self.logger.debug(traceback.format_exc())
                continue

            # check geometry type
            if not 'geometry_type' in meta or meta['geometry_type'] not in self.EDIT_GEOM_TYPES:
                table = (
                    "%s.%s" % (meta.get('schema'), meta.get('table_name'))
                )
                self.logger.warning(
                    "Unsupported geometry type '%s' for edit dataset '%s' "
                    "on table '%s'" %
                    (meta.get('geometry_type', None), dataset_name, table)
                )
                continue

            # NOTE: use ordered keys
            dataset = OrderedDict()
            dataset['layerName'] = layer_name
            dataset['displayField'] = meta['displayField']
            dataset['editDataset'] = dataset_name
            dataset['geomType'] = self.EDIT_GEOM_TYPES.get(
                meta['geometry_type']
            )
            
            nested_nrels = cfg_item.get('editConfig', {}).get(layer_name, {}).get('generate_nested_nrel_forms', False)
            forms = self.themes_reader.collect_ui_forms(map_name, assets_dir, layer_name, nested_nrels)

            if layer_name in forms:
                dataset['form'] = forms[layer_name]

            # collect fields
            fields = []
            for attr in meta.get('attributes'):
                field = meta['fields'].get(attr, {})

                if field.get('expression'):
                    # Skip expression field
                    continue

                alias = field.get('alias', attr)
                data_type = self.EDIT_FIELD_TYPES.get(
                    field.get('data_type'), 'text'
                )

                # NOTE: use ordered keys
                edit_field = OrderedDict()
                edit_field['id'] = attr
                edit_field['name'] = alias
                edit_field['type'] = data_type
                edit_field['data_type'] = data_type

                if 'defaultValue' in field:
                    edit_field['defaultValue'] = field['defaultValue']

                if 'filterExpression' in field:
                    edit_field['filterExpression'] = field['filterExpression']

                if 'constraints' in field:
                    # add any constraints
                    edit_field['constraints'] = field['constraints']
                    if 'values' in field['constraints']:
                        edit_field['type'] = 'list'

                    if 'fileextensions' in field['constraints']:
                        edit_field['type'] = 'file'

                fields.append(edit_field)

            dataset['fields'] = fields


            edit_config[layer_name] = dataset

        # Preserve manually specified edit configs
        if 'editConfig' in cfg_item:
            for layer_name in cfg_item['editConfig']:
                if layer_name in edit_config:
                    edit_config[layer_name].update(cfg_item['editConfig'][layer_name])

        return edit_config

    def copy_index_html(self):
        """Copy index.html to tenant dir."""

        # copy index.html
        # additional service config
        cfg_generator_config = self.service_config.get('generator_config', {})
        cfg_qwc2_config = cfg_generator_config.get('qwc2_config', {})
        index_file = cfg_qwc2_config.get('qwc2_index_file', 'index.html')

        if not os.path.exists(index_file):
            self.logger.warning("Could not copy QWC2 index.html: File was not found")
            return

        self.logger.info("Copying 'index.html' to tenant dir")
        try:
            # read index.html
            index_contents = None
            with open(index_file, encoding='utf-8') as f:
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
        themes_config = self.themes_reader.themes_config
        themes_config_themes = themes_config.get('themes', {})

        for bg_layer in themes_config_themes.get('backgroundLayers', []):
            background_layers.append(bg_layer.get('name'))

        return background_layers

    def permitted_viewer_tasks(self, role, session):
        """Return permitted viewer tasks from ConfigDB.

        :param str role: Role name
        :param Session session: DB session
        """
        # collect role permissions from ConfigDB
        viewer_tasks = self.permitted_resources(
            'viewer_task', role, session
        ).keys()

        return sorted(list(viewer_tasks))

    def permitted_theme_info_links(self, role, session):
        """Return permitted theme info links from ConfigDB.

        :param str role: Role name
        :param Session session: DB session
        """
        # collect role permissions from ConfigDB
        theme_info_links = self.permitted_resources(
            'theme_info_link', role, session
        ).keys()

        return sorted(list(theme_info_links))

    def permitted_plugin_data_resources(self, role, session):
        """Return permitted plugin data resources from ConfigDB.

        NOTE: 'plugin_data' require explicit permissions,
              permissions for 'plugin' are disregarded

        :param str role: Role name
        :param Session session: DB session
        """
        plugin_permissions = []

        # collect role permissions from ConfigDB
        for plugin, plugin_data in self.permitted_resources(
            'plugin_data', role, session
        ).items():
            # add permitted plugin data resources grouped by plugin
            # NOTE: use ordered keys
            plugin_permission = OrderedDict()
            plugin_permission['name'] = plugin
            plugin_permission['resources'] = sorted(list(plugin_data.keys()))
            plugin_permissions.append(plugin_permission)

        # order by plugin name
        return sorted(
            plugin_permissions, key=lambda plugin: plugin.get('name')
        )
