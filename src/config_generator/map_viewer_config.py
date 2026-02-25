from collections import OrderedDict
import json
import os
import re
from pathlib import Path
import posixpath
import requests
import traceback
import urllib.parse

from .external_layer_utils import resolve_external_layer, clear_capabilities_cache
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
        'NOGEOMETRY': None,
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
        'MULTIPOLYGONZ': 'MultiPolygonZ',
        'CURVE': 'Curve',
        'CURVEZ': 'CurveZ',
        'CIRCULARSTRING': 'CircularString',
        'CIRCULARSTRINGZ': 'CircularStringZ',
        'COMPOUNDCURVE': 'CompoundCurve',
        'COMPOUNDCURVEZ': 'CompoundCurveZ',
        'MULTICURVE': 'MultiCurve',
        'MULTICURVEZ': 'MultiCurveZ',
        'SURFACE': 'Surface',
        'SURFACEZ': 'SurfaceZ',
        'CURVEPOLYGON': 'CurvePolygon',
        'CURVEPOLYGONZ': 'CurvePolygonZ',
        'MULTISURFACE': 'MultiSurface',
        'MULTISURFACEZ': 'MultiSurfaceZ'
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
        'uuid': 'text',
        'smallint[]': 'number[]',
        'integer[]': 'number[]',
        'bigint[]': 'number[]',
        'numeric[]': 'number[]',
        'text[]': 'text[]'
    }

    def __init__(self, tenant_path, generator_config, themes_reader,
                 config_models, schema_url, service_config, logger,
                 use_cached_project_metadata, cache_dir):
        """Constructor

        :param str tenant_path: Path to config files of tenant
        :param obj generator_config: ConfigGenerator config
        :param ThemeReader themes_reader: ThemesReader
        :param ConfigModels config_models: Helper for ORM models
        :param str schema_url: JSON schema URL for service config
        :param obj service_config: Additional service config
        :param Logger logger: Logger
        :param bool use_cached_project_metadata: Whether to use cached project metadata if available
        :param str cache_dir: Project metadata cache directory
        """
        super().__init__('mapViewer', schema_url, service_config, logger)

        clear_capabilities_cache()

        self.tenant_path = tenant_path
        self.themes_reader = themes_reader
        self.config_models = config_models
        self.use_cached_project_metadata = use_cached_project_metadata
        self.cache_dir = cache_dir
        self.permissions_query = PermissionsQuery(config_models, logger)
        # helper method alias
        self.permitted_resources = self.permissions_query.permitted_resources

        # get qwc2 directory from mapviewer config
        self.qwc_base_dir = service_config.get('config').get('qwc2_path', '/qwc2/')

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'
        self.qgis_server_url_tenant_suffix = generator_config.get(
            'qgis_server_url_tenant_suffix', ''
        ).strip('/')

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

        # Read auth service URL from config.json as fallback
        config['config']['auth_service_url'] = config['config'].get('auth_service_url',
            resources['qwc2_config']['config'].get('authServiceUrl')
        )

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

            permissions['viewer_tasks'] = sorted(self.permitted_resources(
                'viewer_task', role, session
            ).keys())
            permissions['viewer_assets'] = sorted(self.permitted_resources(
                'viewer_asset', role, session
            ).keys())
            permissions['theme_info_links'] = sorted(self.permitted_resources(
                'theme_info_link', role, session
            ).keys())
            permissions['plugin_data'] = self.permitted_plugin_data_resources(
                role, session
            )
            permissions['oblique_image_datasets'] = sorted(self.permitted_resources(
                'oblique_image_dataset', role, session
            ).keys())

            tileset_3d_permissions = self.permitted_resources(
                'tileset3d', role, session
            )

            for service_name in self.themes_reader.wms_service_names():
                permitted_tilesets_3d = sorted(tileset_3d_permissions.get(service_name, {}).keys())

                if permitted_tilesets_3d:
                    permissions['wms_services'].append({
                        'name': service_name,
                        'tilesets_3d': permitted_tilesets_3d,
                        'layers': []
                    })

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
            with open(config_file, encoding='utf-8') as f:
                # parse config JSON with original order of keys
                config = json.load(f, object_pairs_hook=OrderedDict)
        except Exception as e:
            self.logger.critical("Could not load QWC2 config.json:\n%s" % e)
            config['ERROR'] = str(e)

        qwc2_config['config'] = config

        return qwc2_config

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
            if not imgPath:
                imgPath = "img/mapthumbs/default.jpg"
            elif not os.path.isfile(os.path.join(assets_dir, imgPath)):
                imgPath = "img/mapthumbs/" + backgroundLayer.get("thumbnail", "")
                if not os.path.isfile(os.path.join(assets_dir, imgPath)):
                    self.logger.warn("Could not find thumbnail %s for background layer %s, using default thumbnail" % (backgroundLayer.get("thumbnail", ""), backgroundLayer.get("name", "")))
                    imgPath = "img/mapthumbs/default.jpg"
            backgroundLayer["thumbnail"] = imgPath

        # Resolve background layers
        for entry in themes['backgroundLayers']:
            if "resource" in entry:
                layer = resolve_external_layer(entry["resource"], self.logger, self.project_settings_read_timeout, entry.get("projection", bgLayerCrs.get(entry["name"])), self.use_cached_project_metadata, self.cache_dir)
                if layer:
                    layer["name"] = entry["name"]
                    layer["title"] = entry.get("title", layer["title"])
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
        group['titleMsgId'] = cfg_group.get('titleMsgId')

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
        if cfg_item.get('disabled', False):
            return None

        service_name = self.themes_reader.service_name(cfg_item['url'])

        if cfg_item.get('wmsOnly') == True:
            self.logger.info("Configuring %s as WMS-only theme" % service_name)

        # get capabilities
        cap = self.themes_reader.wms_capabilities(service_name)
        if not cap or not 'name' in cap:
            return None

        project_metadata = self.themes_reader.project_metadata(service_name)

        root_layer = cap.get('root_layer', {})
        projectCrs = project_metadata.get('project_crs')
        name = service_name

        if self.strip_scan_prefix and name.startswith(self.scan_prefix):
            name = name[len(self.scan_prefix):]

        collapseLayerGroupsBelowLevel = cfg_item.get('collapseLayerGroupsBelowLevel', -1)
        featureReports = cfg_item.get("featureReport", {})
        internal_print_layers = cap.get('internal_print_layers', [])
        visibilityPresets = self.themes_reader.project_metadata(service_name)['visibility_presets']
        lockedPreset = visibilityPresets.get(cfg_item.get('lockedVisibilityPreset'))

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

        # NOTE: use ordered keys
        item = OrderedDict()
        item['id'] = self.unique_theme_id(cfg_item.get('id', name))
        item['mapCrs'] = cfg_item.get('mapCrs', projectCrs or themes_config.get('defaultMapCrs', 'EPSG:3857'))
        item['name'] = name
        item['title'] = cfg_item.get('title', cap.get('title', root_layer.get('title', service_name)))
        item['url'] = cfg_item['url']
        item['wms_name'] = service_name

        # collect layers
        layers = []
        newExternalLayers = []
        layer_titles = {}
        for layer in root_layer.get('layers', []):
            sublayer = self.collect_layers(
                layer, search_layers, 1, collapseLayerGroupsBelowLevel, newExternalLayers, project_metadata, featureReports, lockedPreset, layer_titles
            )
            if sublayer:
                layers.append(sublayer)

        # Inject crs in wmts resource string
        for entry in newExternalLayers:
            if entry["name"].startswith("wmts:"):
                urlobj = urllib.parse.urlparse(entry["name"][5:])
                params = dict(urllib.parse.parse_qsl(urlobj.query))
                params["crs"] = params.get('crs', params.get('CRS', item['mapCrs']))
                urlobj = urlobj._replace(query=urllib.parse.urlencode(params))
                entry["name"] = "wmts:" + urllib.parse.urlunparse(urlobj)

        item['abstract'] = cap.get('abstract', '')
        item['attribution'] = {
            'Title': cfg_item.get('attribution'),
            'OnlineResource': cfg_item.get('attributionUrl')
        }
        item['availableFormats'] = cap['map_formats']
        item['bbox'] = {
            'crs': 'EPSG:4326', 'bounds': root_layer.get('bbox')
        }
        item['contact'] = cap.get('contact', {})
        item['description'] = cfg_item.get('description', '')
        item['drawingOrder'] = cap.get('drawing_order', [])
        item['editConfig'] = self.edit_config(service_name, cfg_item, project_metadata, layer_titles)
        item['expanded'] = True
        item['externalLayers'] = cfg_item.get("externalLayers", []) + newExternalLayers
        item['infoFormats'] = cap['info_formats']
        item['initialBbox'] = {
            'crs': item['mapCrs'], 'bounds': cfg_item['extent']
        } if 'extent' in cfg_item else item['bbox']
        item['keywords'] = cap.get('keywords', '')
        item['onlineResource'] = cap.get('onlineResource', '')
        item['searchProviders'] = search_providers
        item['sublayers'] = layers
        item['translations'] = self.themes_reader.project_translations(service_name)
        item['wmsOnly'] = cfg_item.get('wmsOnly', False)

        # Print templates
        # NOTE: copy print templates to not overwrite original config
        print_templates = [
            template.copy() for template in project_metadata['print_templates']
        ]
        for print_template in print_templates:
            if 'printLabelBlacklist' in cfg_item:
                # filter print labels
                labels = [
                    label for label in print_template.get('labels', [])
                    if label not in cfg_item['printLabelBlacklist']
                ]
                print_template['labels'] = labels

            print_template['default'] = print_template['name'].split("/")[-1] == cfg_item.get('defaultPrintLayout')
        item['print'] = print_templates

        # Visibility presets
        if not lockedPreset:
            item['visibilityPresets'] = {}
            visibilityPresetsBlacklist = [
                re.compile(
                    '^' + '.*'.join(re.escape(part) for part in re.split(r'\*+', pattern)) + '$'
                )
                for pattern in cfg_item.get('visibilityPresetsBlacklist', [])
            ]
            for key in visibilityPresets:
                for pattern in visibilityPresetsBlacklist:
                    if pattern.match(key):
                        break
                else:
                    item['visibilityPresets'][key] = dict(
                        filter(lambda kv: kv[0] not in internal_print_layers, visibilityPresets[key].items())
                    )

        self.set_optional_config(cfg_item, 'additionalMouseCrs', item)
        self.set_optional_config(cfg_item, 'backgroundLayers', item)
        self.set_optional_config(cfg_item, 'config', item)
        self.set_optional_config(cfg_item, 'defaultDisplayCrs', item)
        self.set_optional_config(cfg_item, 'extraLegendParameters', item)
        self.set_optional_config(cfg_item, 'extraPrintParameters', item)
        self.set_optional_config(cfg_item, 'flags', item)
        self.set_optional_config(cfg_item, 'format', item)
        self.set_optional_config(cfg_item, 'layerTreeHiddenSublayers', item)
        self.set_optional_config(cfg_item, 'map3d', item)
        self.set_optional_config(cfg_item, 'mapTips', item)
        self.set_optional_config(cfg_item, 'minSearchScaleDenom', item)
        self.set_optional_config(cfg_item, 'obliqueDatasets', item)
        self.set_optional_config(cfg_item, 'pluginData', item)
        self.set_optional_config(cfg_item, 'predefinedFilters', item)
        self.set_optional_config(cfg_item, 'printGrid', item)
        self.set_optional_config(cfg_item, 'printLabelConfig', item)
        self.set_optional_config(cfg_item, 'printLabelForAttribution', item)
        self.set_optional_config(cfg_item, 'printLabelForSearchResult', item)
        self.set_optional_config(cfg_item, 'printResolutions', item)
        self.set_optional_config(cfg_item, 'printScales', item)
        self.set_optional_config(cfg_item, 'scales', item)
        self.set_optional_config(cfg_item, 'skipEmptyFeatureAttributes', item)
        self.set_optional_config(cfg_item, 'snapping', item)
        self.set_optional_config(cfg_item, 'startupView', item)
        self.set_optional_config(cfg_item, 'themeInfoLinks', item)
        self.set_optional_config(cfg_item, 'tiled', item)
        self.set_optional_config(cfg_item, 'tileSize', item)
        self.set_optional_config(cfg_item, 'userMap', item)
        self.set_optional_config(cfg_item, 'version', item)
        self.set_optional_config(cfg_item, 'visibility', item)
        self.set_optional_config(cfg_item, 'watermark', item)

        if not cfg_item.get('wmsOnly', False):
            item['thumbnail'] = self.get_thumbnail(cfg_item, service_name, cap, assets_dir)

        if cfg_item.get('default', False) is True:
            # set default theme
            self.default_theme = item['id']

        # Collect crs of background layers
        for entry in item.get('backgroundLayers', []):
            bgLayerCrs[entry['name']] = item['mapCrs']

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
        url = urllib.parse.urljoin(
            self.default_qgis_server_url,
            posixpath.join(self.qgis_server_url_tenant_suffix, service_name)
        )

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

    def collect_layers(self, layer, search_layers, level, collapseBelowLevel, externalLayers, project_metadata, featureReports, lockedPreset, layer_titles):
        """Recursively collect layer tree from capabilities.

        :param obj layer: Layer or group layer
        :param obj search_layers: Lookup for search layers
        """
        # NOTE: use ordered keys
        item_layer = OrderedDict()

        item_layer['name'] = layer['name']
        if 'title' in layer:
            item_layer['title'] = layer['title']
            layer_titles[layer['name']] = layer['title']

        if 'layers' in layer:
            # group layer
            sublayers = []
            for sublayer in layer['layers']:
                # recursively collect sub layer
                item_sublayer = self.collect_layers(
                    sublayer, search_layers, level + 1, collapseBelowLevel, externalLayers, project_metadata, featureReports, lockedPreset, layer_titles
                )
                if item_sublayer:
                    sublayers.append(item_sublayer)

            # Omit empty group
            if not sublayers:
                return None

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

            if lockedPreset:
                item_layer['visibility'] = layer['name'] in lockedPreset
        else:

            geometryType = layer.get('geometryType')
            if geometryType == 'WKBNoGeometry' or geometryType == 'NoGeometry':
                return None

            meta = project_metadata['layer_metadata'].get(layer['name'], {})

            # layer
            item_layer['visibility'] = layer['visible']
            item_layer['geometryType'] = geometryType
            item_layer['category_sublayer'] = layer['category_sublayer']
            item_layer['queryable'] = layer['queryable']
            item_layer['styles'] = layer['styles']
            if 'default' in item_layer['styles']:
                item_layer['style'] = 'default'
            elif len(item_layer['styles']) > 0:
                item_layer['style'] = list(item_layer['styles'])[0]
            else:
                item_layer['style'] = ''

            if lockedPreset:
                if layer['name'] in lockedPreset:
                    style = lockedPreset[layer['name']]
                    item_layer['styles'] = {style: style}
                    item_layer['style'] = style
                    item_layer['visibility'] = True
                else:
                    item_layer['visibility'] = False

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
                for dimension in item_layer["dimensions"]:
                    if not dimension["fieldName"]:
                        dimmeta = meta.get('dimensions', {})
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

            # refresh interval
            item_layer['refreshInterval'] = meta.get('refresh_interval', 0)

        return item_layer

    def edit_config(self, map_name, cfg_item, project_metadata, layer_titles):
        """Collect edit config for a map from ConfigDB.

        :param str map_name: Map name (matches WMS and QGIS project)
        :param obj cfg_item: Theme config item
        :param obj project_metadata: Theme project metadata
        """
        # NOTE: use ordered keys
        edit_config = OrderedDict()

        # collect edit datasets
        for layer_name, layer_metadata in project_metadata['layer_metadata'].items():
            if not layer_metadata.get('editable'):
                # No edit metadata available
                continue

            dataset_name = "%s.%s" % (map_name, layer_name)

            # check geometry type
            if layer_metadata.get('geometry_type') not in self.EDIT_GEOM_TYPES:
                table = (
                    "%s.%s" % (layer_metadata.get('schema'), layer_metadata.get('table_name'))
                )
                self.logger.warning(
                    "Unsupported geometry type '%s' for edit dataset '%s' on table '%s'" %
                    (layer_metadata.get('geometry_type'), dataset_name, table)
                )
                continue

            # NOTE: use ordered keys
            dataset = OrderedDict()
            dataset['layerName'] = layer_name
            dataset['layerTitle'] = layer_titles.get(layer_name)
            dataset['displayField'] = layer_metadata['displayField']
            dataset['editDataset'] = dataset_name
            dataset['geomType'] = self.EDIT_GEOM_TYPES.get(layer_metadata['geometry_type'])
            dataset['primaryKey'] = layer_metadata['primary_key']
            dataset['form'] = layer_metadata["edit_form"]
            dataset['reltables'] = layer_metadata.get('reltables', [])

            # collect fields
            fields = []
            for fieldname, field in layer_metadata['fields'].items():
                data_type = self.EDIT_FIELD_TYPES.get(
                    field.get('data_type'), 'text'
                )

                # NOTE: use ordered keys
                edit_field = OrderedDict()
                edit_field['id'] = fieldname
                edit_field['name'] = field['alias']
                edit_field['type'] = data_type
                edit_field['data_type'] = field.get('data_type')

                if 'defaultValue' in field:
                    edit_field['defaultValue'] = field['defaultValue']

                if 'filterExpression' in field:
                    edit_field['filterExpression'] = field['filterExpression']

                if 'expression' in field:
                    edit_field['expression'] = field['expression']

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


    # Permissions

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
