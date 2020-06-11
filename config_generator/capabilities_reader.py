from collections import OrderedDict
import json
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests


class CapabilitiesReader():
    """CapabilitiesReader class

    Load and parse GetProjectSettings for all theme items from a
    QWC2 themes config file (themesConfig.json).
    """

    def __init__(self, generator_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param Logger logger: Logger
        """
        self.logger = logger

        # read QWC2 themes config file
        self.themes_config = {}
        try:
            # get path to QWC themes config file from ConfigGenerator config
            themes_config_file = generator_config.get(
                'qwc2_themes_config_file', 'themesConfig.json'
            )
            with open(themes_config_file) as f:
                # parse QWC2 themes config JSON with original order of keys
                self.themes_config = json.load(
                  f, object_pairs_hook=OrderedDict
                )
        except Exception as e:
            self.logger.error("Error loading QWC2 themes config file:\n%s" % e)

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        # cache for capabilities: {<service name>: <capabilities>}
        self.wms_capabilities = OrderedDict()

        # lookup for services names by URL: {<url>: <service_name>}
        self.service_name_lookup = {}

    def load_all_project_settings(self):
        """Load and parse GetProjectSettings for all theme items from
        QWC2 themes config.
        """
        self.load_project_settings_for_group(
            self.themes_config.get('themes', {})
        )

    def wms_service_names(self):
        """Return all WMS service names in alphabetical order."""
        return sorted(self.wms_capabilities.keys())

    def load_project_settings_for_group(self, item_group):
        """Recursively load and parse GetProjectSettings for a
        theme item group."""
        for item in item_group.get('items', []):
            self.load_project_settings(item)

        for group in item_group.get('groups', []):
            # collect group items
            self.load_project_settings_for_group(group)

    def load_project_settings(self, item):
        """Load and parse GetProjectSettings for a theme item.

        :param obj item: QWC2 themes config item.
        """
        # get service name
        url = item.get('url')
        service_name = self.service_name(url)
        if service_name in self.wms_capabilities:
            # skip service already in cache
            return

        try:
            # get GetProjectSettings
            full_url = urljoin(self.default_qgis_server_url, url)
            self.logger.info(
                "Downloading GetProjectSettings from %s" % full_url
            )
            response = requests.get(
                full_url,
                params={
                    'SERVICE': 'WMS',
                    'VERSION': '1.3.0',
                    'REQUEST': 'GetProjectSettings'
                },
                timeout=60
            )

            if response.status_code != requests.codes.ok:
                self.logger.warning(
                    "Could not get GetProjectSettings from %s:\n%s" %
                    (full_url, response.content)
                )
                return

            document = response.content

            # parse GetProjectSettings XML
            ElementTree.register_namespace('', 'http://www.opengis.net/wms')
            ElementTree.register_namespace('qgs', 'http://www.qgis.org/wms')
            ElementTree.register_namespace('sld', 'http://www.opengis.net/sld')
            ElementTree.register_namespace(
                'xlink', 'http://www.w3.org/1999/xlink'
            )
            root = ElementTree.fromstring(document)

            # use default namespace for XML search
            # namespace dict
            ns = {'ns': 'http://www.opengis.net/wms'}
            # namespace prefix
            np = 'ns:'
            if not root.tag.startswith('{http://'):
                # do not use namespace
                ns = {}
                np = ''

            root_layer = root.find('%sCapability/%sLayer' % (np, np), ns)
            if root_layer is None:
                self.logger.warning(
                    "No root layer found for %s: %s" %
                    (full_url, response.content)
                )
                return

            # NOTE: use ordered keys
            capabilities = OrderedDict()

            capabilities['name'] = service_name
            capabilities['wms_url'] = full_url

            # collect internal print layers
            internal_print_layers = [
                bg_layer.get('printLayer') for bg_layer
                in item.get('backgroundLayers', [])
                if 'printLayer' in bg_layer
            ]

            # collect WMS layers
            default_root_name = urlparse(full_url).path.split('/')[-1]
            capabilities['root_layer'] = self.collect_wms_layers(
                root_layer, internal_print_layers, ns, np, default_root_name
            )

            # get drawing order
            drawing_order = root.find(
                '%sCapability/%sLayerDrawingOrder' % (np, np), ns
            )
            if drawing_order is not None:
                capabilities['drawing_order'] = drawing_order.text.split(',')

            # collect print templates
            print_templates = self.print_templates(root, np, ns)
            if print_templates:
                capabilities['print_templates'] = print_templates

            if internal_print_layers:
                capabilities['internal_print_layers'] = internal_print_layers

            self.wms_capabilities[service_name] = capabilities
        except Exception as e:
            self.logger.error(
                "Could not get GetProjectSettings from %s:\n%s" %
                (full_url, e)
            )

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

    def collect_wms_layers(self, layer, internal_print_layers, ns, np,
                           fallback_name=""):
        """Recursively collect layer info for layer subtree from
        WMS GetProjectSettings.

        :param Element layer: GetProjectSettings layer node
        :param list(str) internal_print_layers: List of internal print layers
                                                to filter
        :param obj ns: Namespace dict
        :param str np: Namespace prefix
        :param str fallback_name: Layer name if empty in GetProjectSettings
        """
        # NOTE: use ordered keys
        wms_layer = OrderedDict()

        layer_name_tag = layer.find('%sName' % np, ns)
        if layer_name_tag is not None:
            layer_name = layer_name_tag.text
        else:
            layer_name = fallback_name

        wms_layer['name'] = layer_name

        layer_title_tag = layer.find('%sTitle' % np, ns)
        if layer_title_tag is not None:
            wms_layer['title'] = layer_title_tag.text

        # collect sub layers if group layer
        group_layers = []
        for sub_layer in layer.findall('%sLayer' % np, ns):
            sub_layer_name = sub_layer.find('%sName' % np, ns).text

            if sub_layer_name in internal_print_layers:
                # skip internal print layers
                continue

            group_layers.append(
                self.collect_wms_layers(
                    sub_layer, internal_print_layers, ns, np
                )
            )

        if group_layers:
            # group layer
            wms_layer["expanded"] = layer.get(
                'expanded') == '1'
            wms_layer["mutuallyExclusive"] = layer.get(
                'mutuallyExclusive') == '1'
            wms_layer['layers'] = group_layers
        else:
            # layer

            # collect attributes
            attributes = []
            attrs = layer.find('%sAttributes' % np, ns)
            if attrs is not None:
                for attr in attrs.findall('%sAttribute' % np, ns):
                    attributes.append(attr.get('alias', attr.get('name')))
                attributes.append('geometry')
                attributes.append('maptip')

            if attributes:
                wms_layer['attributes'] = attributes

        minScale = layer.find('%sMinScaleDenominator' % np, ns)
        maxScale = layer.find('%sMaxScaleDenominator' % np, ns)
        if minScale:
            wms_layer["minScale"] = minScale.text
        if maxScale:
            wms_layer["maxScale"] = maxScale.text

        if layer.get("geometryType") is None or \
            layer.get("geometryType") == "WKBNoGeometry" or \
                layer.get("geometryType") == "NoGeometry":

            wms_layer['visible'] = False
        else:
            wms_layer['visible'] = layer.get('visible') == '1'

        wms_layer['queryable'] = layer.get('queryable') == '1'
        if wms_layer['queryable'] and layer.get('displayField'):
            wms_layer['display_field'] = layer.get('displayField')

        # NOTE: get geographic bounding box, as default CRS may have
        #       inverted axis order with WMS 1.3.0
        bbox = layer.find('%sEX_GeographicBoundingBox' % np, ns)
        if bbox is not None:
            wms_layer['bbox'] = [
                float(bbox.find('%swestBoundLongitude' % np, ns).text),
                float(bbox.find('%ssouthBoundLatitude' % np, ns).text),
                float(bbox.find('%seastBoundLongitude' % np, ns).text),
                float(bbox.find('%snorthBoundLatitude' % np, ns).text)
            ]

        return wms_layer

    def print_templates(self, root, np, ns):
        """Collect print templates from WMS GetProjectSettings.

        :param Element root: GetProjectSettings root node
        :param obj ns: Namespace dict
        :param str np: Namespace prefix
        """
        print_templates = []
        for template in root.findall('.//%sComposerTemplate' % np, ns):
            template_name = template.get('name')

            # NOTE: use ordered keys
            print_template = OrderedDict()
            print_template['name'] = template.get('name')

            composer_map = template.find('%sComposerMap' % np, ns)
            if composer_map is not None:
                print_map = OrderedDict()
                print_map['name'] = composer_map.get('name')
                print_map['width'] = float(composer_map.get('width'))
                print_map['height'] = float(composer_map.get('height'))
                print_template['map'] = print_map

            labels = []
            for label in template.findall('%sComposerLabel' % np, ns):
                labels.append(label.get('name'))
            if labels:
                print_template['labels'] = labels

            print_templates.append(print_template)

        return print_templates
