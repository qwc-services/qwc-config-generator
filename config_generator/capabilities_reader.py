from collections import OrderedDict
import json
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
import os
from pathlib import Path
from shutil import move, copyfile

from .categorize_groups_script import categorize_layers


class CapabilitiesReader():
    """CapabilitiesReader class

    Load and parse GetProjectSettings for all theme items from a
    QWC2 themes config file (themesConfig.json).
    """

    def __init__(self, generator_config, themes_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param dict themes_config: themes config
        :param Logger logger: Logger
        """
        self.logger = logger

        # read QWC2 themes config file
        self.themes_config = themes_config

        if self.themes_config is None:
            self.logger.critical(
                "Error loading QWC2 themes config file")

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        # cache for capabilities: {<service name>: <capabilities>}
        self.wms_capabilities = OrderedDict()

        # lookup for services names by URL: {<url>: <service_name>}
        self.service_name_lookup = {}

        # get qwc2 directory from ConfigGenerator config
        self.qwc_base_dir = generator_config.get("qwc2_base_dir")

        # make mutual exclusive group subitems visible
        self.make_mutex_subitems_visible = generator_config.get(
            'make_mutex_subitems_visible', False)

        # layer opacity values for QGIS <= 3.10 from ConfigGenerator config
        self.layer_opacities = generator_config.get("layer_opacities", {})

        # Skip group layers containing print layers
        self.skip_print_layer_groups = generator_config.get(
            'skip_print_layer_groups', False)

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
        qgis_projects_base_dir = generator_config.get(
            'qgis_projects_base_dir')

        for dirpath, dirs, files in os.walk(qgs_projects_dir,
                                            followlinks=True):
            for filename in files:
                if Path(filename).suffix in [".qgs", ".qgz"]:
                    fname = os.path.join(dirpath, filename)
                    relpath = os.path.relpath(fname, qgs_projects_dir)
                    self.logger.info("Processing " + fname)

                    # convert project
                    dest_path = os.path.join(
                        qgis_projects_base_dir, relpath)
                    categorized_qgs_project_path = categorize_layers(
                        [], fname, dest_path)
                    if not os.path.exists(dest_path):
                        self.logger.warning(
                            "The project: " + dest_path +
                            " could not be generated.\n"
                            "Please check if needed permissions to create the"
                            " file are granted.")
                        continue
                    self.logger.info("Written to " + dest_path)

    def search_qgs_projects(self, generator_config):
        if self.themes_config is None:
            return

        qgis_projects_scan_base_dir = generator_config.get(
            'qgis_projects_scan_base_dir')
        if not qgis_projects_scan_base_dir:
            self.logger.info(
                "Skipping scanning for projects" +
                " (qgis_projects_scan_base_dir not set")
            return

        if os.path.exists(qgis_projects_scan_base_dir):
            self.logger.info(
                "Searching for projects files in " + qgis_projects_scan_base_dir)
        else:
            self.logger.error(
                "The qgis_projects_scan_base_dir sub directory" +
                " does not exist: " + qgis_projects_scan_base_dir)
            return

        scanned_projects_path_prefix = generator_config.get(
            'scanned_projects_path_prefix', '')
        base_url = urljoin(self.default_qgis_server_url,
                           scanned_projects_path_prefix)

        # collect existing item urls
        items = self.themes_config.get("themes", {}).get(
            "items", {})
        wms_urls = []
        has_default = False
        for item in items:
            if item.get("url"):
                wms_urls.append(item["url"])
            if item.get("default", False):
                has_default = True

        # This is needed because we don't want to
        # print the error message "thumbmail dir not found"
        # multiple times
        thumbnail_dir_exists = True
        thumbnail_directory = ""
        if self.qwc_base_dir is None:
            thumbnail_dir_exists = False
            self.logger.info(
                            "Skipping automatic thumbnail search "
                            "(qwc2_base_dir was not set)")
        else:
            thumbnail_directory = os.path.join(
                self.qwc_base_dir, "assets/img/mapthumbs")

        for dirpath, dirs, files in os.walk(qgis_projects_scan_base_dir,
                                            followlinks=True):
            for filename in files:
                if Path(filename).suffix in [".qgs", ".qgz"]:
                    fname = os.path.join(dirpath, filename)
                    relpath = os.path.relpath(dirpath,
                                              qgis_projects_scan_base_dir)
                    wmspath = os.path.join(relpath, Path(filename).stem)

                    # Add to themes items
                    item = OrderedDict()
                    item["url"] = urljoin(base_url, wmspath)
                    item["backgroundLayers"] = self.themes_config.get(
                        "defaultBackgroundLayers", [])
                    item["searchProviders"] = self.themes_config.get(
                        "defaultSearchProviders", [])
                    item["mapCrs"] = self.themes_config.get(
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

            if len(full_url) > 2000:
                self.logger.warning(
                    "WMS URL is longer than 2000 characters!")

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
                self.logger.critical(
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

            # get service title
            service_title = root.find('%sService/%sTitle' % (np, np), ns)
            if service_title is not None:
                capabilities['title'] = service_title.text

            # get service abstract
            service_abstract = root.find('%sService/%sAbstract' % (np, np), ns)
            if service_abstract is not None:
                capabilities['abstract'] = service_abstract.text

            # collect service keywords
            keyword_list = root.find('%sService/%sKeywordList' % (np, np), ns)
            if keyword_list is not None:
                keywords = [
                    keyword.text for keyword
                    in keyword_list.findall('%sKeyword' % np, ns)
                    if keyword.text != 'infoMapAccessService'
                ]
                if keywords:
                    capabilities['keywords'] = ', '.join(keywords)

            # service online resouce
            online_resource = root.find('%sService/%sOnlineResource' % (np, np), ns)
            if online_resource is not None:
                capabilities['online_resource'] = online_resource.get('{http://www.w3.org/1999/xlink}href')

            # service contact
            contact_person = root.find("%sService/%sContactInformation/%sContactPersonPrimary/%sContactPerson" % (np, np, np, np), ns)
            contact_organization = root.find("%sService/%sContactInformation/%sContactPersonPrimary/%sContactOrganization" % (np, np, np, np), ns)
            contact_position = root.find("%sService/%sContactInformation/%sContactPosition" % (np, np, np), ns)
            contact_phone = root.find("%sService/%sContactInformation/%sContactVoiceTelephone" % (np, np, np), ns)
            contact_email = root.find("%sService/%sContactInformation/%sContactElectronicMailAddress" % (np, np, np), ns)


            capabilities["contact"] = {
                "person": contact_person.text if contact_person is not None else None,
                "organization": contact_organization.text if contact_organization is not None else None,
                "position": contact_position.text if contact_position is not None else None,
                "phone": contact_phone.text if contact_phone is not None else None,
                "email": contact_email.text if contact_email is not None else None
            }

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
            if capabilities['root_layer'] is None:
                self.logger.warning(
                    "No (non geometryless) layers found for %s: %s" %
                    (full_url, response.content)
                )
                return
            # Check if a layer has the same name as the root layer - and if so, abort
            root_layer_name = capabilities['root_layer'].get('name')
            for layer in capabilities['root_layer'].get('layers'):
                if layer.get('name') == root_layer_name:
                    self.logger.critical(
                        "The service %s contains a layer with the same name as the service. Please rename the service or the layer."
                        % root_layer_name
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
            self.logger.critical(
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

    def make_sublayers_visible(self, layer):
        """Recursibely set sublayers of the specified layer visible

        :param obj layer: The layer object
        """
        for sublayer in layer.get('layers', []):
            sublayer['visible'] = True
            self.make_sublayers_visible(sublayer)

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
                if self.skip_print_layer_groups:
                    return None
                else:
                    continue

            sub_wms_layer = self.collect_wms_layers(
                sub_layer, internal_print_layers, ns, np
            )
            if sub_wms_layer is not None:
                group_layers.append(sub_wms_layer)

        if group_layers:
            # group layer
            wms_layer["expanded"] = layer.get(
                'expanded', '1') == '1'
            wms_layer["mutuallyExclusive"] = layer.get(
                'mutuallyExclusive') == '1'
            wms_layer['layers'] = group_layers
            if wms_layer["mutuallyExclusive"] and self.make_mutex_subitems_visible:
                for sublayer in group_layers:
                    self.make_sublayers_visible(sublayer)
        else:
            # layer
            if (
                layer.get('geometryType') == 'WKBNoGeometry'
                or layer.get('geometryType') == 'NoGeometry'
            ):
                # skip layer without geometry
                return None

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

        if layer.find('%sAbstract' % np, ns) is not None:
            wms_layer["abstract"] = layer.find('%sAbstract' % np, ns).text

        if layer.find('%sKeywordList' % np, ns):
            keywords = []
            for keyword in layer.find('%sKeywordList' % np, ns).findall(
                    '%sKeyword' % np, ns):
                keywords.append(keyword.text)
            wms_layer["keywords"] = ", ".join(keywords)


        try:
            wms_layer["attribution"] = layer.find('%sAttribution' % np, ns).find('%sTitle' % np, ns).text
            wms_layer["attributionUrl"] = layer.find('%sAttribution' % np, ns).find('%sOnlineResource' % np, ns).get('{http://www.w3.org/1999/xlink}href')
        except:
            pass

        try:
            wms_layer["dataUrl"] = layer.find('%sDataURL' % np, ns).find('%sOnlineResource' % np, ns).get('{http://www.w3.org/1999/xlink}href')
        except:
            pass

        try:
            wms_layer["metadataUrl"] = layer.find('%sMetadataURL' % np, ns).find('%sOnlineResource' % np, ns).get('{http://www.w3.org/1999/xlink}href')
        except:
            pass


        if layer.get('transparency'):
            wms_layer['opacity'] = 255 - int(float(
                layer.get('transparency')) / 100 * 255
            )
        elif layer.get('opacity'):
            wms_layer['opacity'] = int(float(layer.get("opacity")) * 255)
        else:
            # custom layer opacities (default: 255)
            # name = getChildElementValue(layer, [np['ns'] + "Name"], ns)
            opacity = self.layer_opacities.get(layer_name, 255)
            wms_layer['opacity'] = opacity

        minScale = layer.find('%sMinScaleDenominator' % np, ns)
        maxScale = layer.find('%sMaxScaleDenominator' % np, ns)
        if minScale is not None:
            wms_layer["minScale"] = minScale.text
        if maxScale is not None:
            wms_layer["maxScale"] = maxScale.text

        wms_layer['visible'] = layer.get('visible') == '1'
        wms_layer['geometryType'] = layer.get('geometryType')

        wms_layer['queryable'] = layer.get('queryable') == '1'
        if wms_layer['queryable'] and layer.get('displayField'):
            wms_layer['display_field'] = layer.get('displayField')

        # get default CRS (first CRS)
        wms_layer['crs'] = layer.find('%sCRS' %np, ns).text

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
