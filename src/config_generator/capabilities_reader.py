from collections import OrderedDict
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import re
import requests


class CapabilitiesReader():
    """CapabilitiesReader class

    Load and parse WMS GetProjectSettings.and WFS Capabilities
    """

    def __init__(self, generator_config, logger):
        """Constructor

        :param obj generator_config: ConfigGenerator config
        :param Logger logger: Logger
        """
        self.logger = logger

        # get default QGIS server URL from ConfigGenerator config
        self.default_qgis_server_url = generator_config.get(
            'default_qgis_server_url', 'http://localhost:8001/ows/'
        ).rstrip('/') + '/'

        # layer opacity values for QGIS <= 3.10 from ConfigGenerator config
        self.layer_opacities = generator_config.get("layer_opacities", {})

        # Skip group layers containing print layers
        self.skip_print_layer_groups = generator_config.get(
            'skip_print_layer_groups', False)

        self.project_settings_read_timeout = generator_config.get(
            "project_settings_read_timeout", 60
        )

    # WMS GetProjectSettings

    def read_wms_service_capabilities(self, url, service_name, item):
        """Load and parse WMS GetProjectSettings for a theme item.

        :param str url: service URL
        :param str service_name: service name
        :param object item: theme item
        """

        try:
            # get GetProjectSettings
            full_url = urljoin(self.default_qgis_server_url, url)

            if len(full_url) > 2000:
                self.logger.warning(
                    "WMS URL is longer than 2000 characters!")

            response = requests.get(
                full_url,
                params={
                    'SERVICE': 'WMS',
                    'VERSION': '1.3.0',
                    'REQUEST': 'GetProjectSettings',
                    'CLEARCACHE': '1'
                },
                timeout=self.project_settings_read_timeout
            )

            if response.status_code != requests.codes.ok:
                self.logger.critical(
                    "Could not get WMS GetProjectSettings from %s:\n%s" %
                    (full_url, response.content)
                )
                return {}

            self.logger.info(
                "Downloaded WMS GetProjectSettings from %s" % full_url
            )

            document = response.content

            # parse WMS GetProjectSettings XML
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
                return {}

            # NOTE: use ordered keys
            capabilities = OrderedDict()

            capabilities['name'] = service_name
            capabilities['wms_url'] = full_url

            # get service title
            service_title = root.find('%sService/%sTitle' % (np, np), ns)
            if service_title is not None:
                capabilities['title'] = service_title.text
                if capabilities['title'] == "Untitled":
                    capabilities['title'] = re.sub('.*/', '', service_name)

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
            internal_print_layers = item.get('extraPrintLayers', [])
            for bg_layer in item.get('backgroundLayers', []):
                printLayer = bg_layer.get('printLayer', None)
                if printLayer:
                    if isinstance(printLayer, str):
                        internal_print_layers.append(printLayer)
                    elif isinstance(printLayer, list):
                        for entry in printLayer:
                            internal_print_layers.append(entry.get('name'))

            # collect WMS layers
            default_root_name = urlparse(full_url).path.split('/')[-1]
            layer_names = []
            capabilities['root_layer'] = self.collect_wms_layers(
                root_layer, layer_names, internal_print_layers, ns, np, default_root_name
            )
            # collect geometryless WMS layers
            geometryless_layers = self.collect_geometryless_layers(
                root_layer, internal_print_layers, ns, np, default_root_name
            )
            if capabilities['root_layer'] is None:
                self.logger.warning(
                    "No (non geometryless) layers found for %s: %s" %
                    (full_url, response.content)
                )
                return {}
            # Check if a layer has the same name as the root layer - and if so, abort
            root_layer_name = capabilities['root_layer'].get('name')
            layers = capabilities['root_layer'].get('layers')
            if layers is not None:
                for layer in layers:
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

            # GetMap formats
            capabilities['map_formats'] = list(map(lambda el: el.text, root.findall(
                '%sCapability/%sRequest/%sGetMap/%sFormat' % (np, np, np, np), ns
            )))

            # GetFeatureInfo formats
            capabilities['info_formats'] = list(map(lambda el: el.text, root.findall(
                '%sCapability/%sRequest/%sGetFeatureInfo/%sFormat' % (np, np, np, np), ns
            )))

            # collect print templates
            print_templates = self.print_templates(root, np, ns)
            if print_templates:
                capabilities['print_templates'] = print_templates

            if internal_print_layers:
                capabilities['internal_print_layers'] = internal_print_layers

            if geometryless_layers:
                capabilities['geometryless_layers'] = geometryless_layers

            return capabilities
        except Exception as e:
            self.logger.critical(
                "Could not parse WMS GetProjectSettings from %s:\n%s" %
                (full_url, e)
            )
            return {}

    def collect_wms_layers(self, layer, layer_names, internal_print_layers, ns, np,
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

        if "," in layer_name:
            self.logger.warning(
                f"The layer '{layer_name}' contains a comma! "
                "The WMS name of a layer must not contain a comma! "
                "Either remove the comma or specify 'short_name' in the QGIS project."
            )
        if layer_name in layer_names:
            self.logger.warning(
                f"Duplicate layer name '{layer_name}'! "
                "Please rename the duplicate occurrences."
            )
        else:
            layer_names.append(layer_name)

        wms_layer['name'] = layer_name

        layer_title_tag = layer.find('%sTitle' % np, ns)
        if layer_title_tag is not None:
            wms_layer['title'] = layer_title_tag.text

        # collect dimensions
        wms_layer['dimensions'] = []
        for dim in layer.findall("%sDimension" % np, ns):
            wms_layer['dimensions'].append({
                'units': dim.get('units'),
                'name': dim.get('name'),
                'multiple': dim.get('multipleValues') == '1',
                'value': dim.text,
                'fieldName': dim.get('fieldName', None),
                'endFieldName': dim.get('endFieldName', None)
            })

        # collect sub layers if group layer
        group_layers = []
        for sub_layer in layer.findall('%sLayer' % np, ns):
            sub_layer_name = sub_layer.find('%sName' % np, ns).text

            if sub_layer_name in internal_print_layers:
                sublayer_names = []
                self.collect_wms_layers(
                    sub_layer, sublayer_names, internal_print_layers, ns, np
                )
                internal_print_layers += sublayer_names
                # skip internal print layers
                if self.skip_print_layer_groups:
                    return None
                else:
                    continue

            sub_wms_layer = self.collect_wms_layers(
                sub_layer, layer_names, internal_print_layers, ns, np
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

        if 'visibilityChecked' in layer.attrib:
            wms_layer['visible'] = layer.get('visibilityChecked') == '1'
        else:
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

    def collect_geometryless_layers(self, layer, internal_print_layers, ns, np,
                           fallback_name="", geometryless_layer_names=set()):
        """Recursively collect layer names of geometryless layers from
        WMS GetProjectSettings.

        :param Element layer: GetProjectSettings layer node
        :param list(str) internal_print_layers: List of internal print layers
                                                to filter
        :param obj ns: Namespace dict
        :param str np: Namespace prefix
        :param str fallback_name: Layer name if empty in GetProjectSettings
        :param set geometryless_layer_names: A set of geometryless layer names
        """
        # NOTE: use ordered keys
        layer_name_tag = layer.find('%sName' % np, ns)
        if layer_name_tag is not None:
            layer_name = layer_name_tag.text
        else:
            layer_name = fallback_name

        # collect sub layers if group layer
        group_layers = set()
        for sub_layer in layer.findall('%sLayer' % np, ns):
            sub_layer_name = sub_layer.find('%sName' % np, ns).text

            if sub_layer_name in internal_print_layers:
                continue

            sub_wms_layer = self.collect_geometryless_layers(
                sub_layer, internal_print_layers, ns, np
            )
            if sub_wms_layer is not None and isinstance(sub_wms_layer, list):
                group_layers.update(sub_wms_layer)
            elif sub_wms_layer is not None:
                group_layers.add(sub_wms_layer)

        if group_layers:
            # group layer
            geometryless_layer_names.update(group_layers)
        else:
            # layer
            if (
                layer.get('geometryType') == 'WKBNoGeometry'
                or layer.get('geometryType') == 'NoGeometry'
            ):
                # skip layer without geometry
                return layer_name
            else:
                return None

        return list(geometryless_layer_names)

    def print_templates(self, root, np, ns):
        """Collect print templates from WMS GetProjectSettings.

        :param Element root: GetProjectSettings root node
        :param obj ns: Namespace dict
        :param str np: Namespace prefix
        """
        print_templates = []
        composer_template_map = {}
        for template in root.findall('.//%sComposerTemplate' % np, ns):
            composer_template_map[template.get('name')] = template

        for template in composer_template_map.values():
            template_name = template.get('name')
            if template_name.endswith("_legend") and template_name[:-7] in composer_template_map:
                continue

            # NOTE: use ordered keys
            print_template = OrderedDict()
            print_template['name'] = template.get('name')
            if template_name + "_legend" in composer_template_map:
                print_template["legendLayout"] = template_name + "_legend";

            composer_map = template.find('%sComposerMap' % np, ns)
            if composer_map is not None:
                print_map = OrderedDict()
                print_map['name'] = composer_map.get('name')
                print_map['width'] = float(composer_map.get('width'))
                print_map['height'] = float(composer_map.get('height'))
                print_template['map'] = print_map
            if template.get('atlasEnabled') == '1':
                atlasLayer = template.get('atlasCoverageLayer')
                try:
                    pk = root.find(".//%sLayer/[%sName = '%s']" % (np, np, atlasLayer), ns).find('./%sPrimaryKey/%sPrimaryKeyAttribute' % (np, np), ns).text
                    print_template['atlasCoverageLayer'] = atlasLayer
                    print_template['atlas_pk'] = pk
                except:
                    self.logger.warning("Failed to determine primary key for atlas layer %s!" % atlasLayer)
                    pass

            labels = []
            for label in template.findall('%sComposerLabel' % np, ns):
                labels.append(label.get('name'))
            if labels:
                print_template['labels'] = labels

            print_templates.append(print_template)

        return print_templates

    # WFS Capabilities

    def read_wfs_service_capabilities(self, url, service_name, item):
        """Load and parse WFS GetCapabilities for a theme item.

        NOTE: returns empty result if WFS does not contains any layers

        :param str url: service URL
        :param str service_name: service name
        :param object item: theme item
        """
        try:
            # get GetProjectSettings
            full_url = urljoin(self.default_qgis_server_url, url)

            if len(full_url) > 2000:
                self.logger.warning(
                    "WFS URL is longer than 2000 characters!")

            response = requests.get(
                full_url,
                params={
                    'SERVICE': 'WFS',
                    'VERSION': '1.1.0',
                    'REQUEST': 'GetCapabilities',
                    'CLEARCACHE': '1'
                },
                timeout=self.project_settings_read_timeout
            )

            if response.status_code != requests.codes.ok:
                self.logger.critical(
                    "Could not get WFS GetCapabilities from %s:\n%s" %
                    (full_url, response.content)
                )
                return {}

            self.logger.info(
                "Downloaded WFS GetCapabilities from %s" % full_url
            )

            document = response.content

            # parse WFS Capabilities XML
            ElementTree.register_namespace('', 'http://www.opengis.net/wfs')
            ElementTree.register_namespace('ows', 'http://www.opengis.net/ows')
            ElementTree.register_namespace('gml', 'http://www.opengis.net/gml')
            ElementTree.register_namespace('ogc', 'http://www.opengis.net/ogc')
            ElementTree.register_namespace(
                'xlink', 'http://www.w3.org/1999/xlink'
            )
            root = ElementTree.fromstring(document)

            # use default namespace for XML search
            # namespace dict
            ns = {
                'ns': 'http://www.opengis.net/wfs',
                'ows': 'http://www.opengis.net/ows'
            }
            # namespace prefix
            np = 'ns:'
            np_ows = 'ows:'
            if not root.tag.startswith('{http://'):
                # do not use namespace
                ns = {}
                np = ''

            feature_type_list = root.find('%sFeatureTypeList' % np, ns)
            if feature_type_list is None:
                self.logger.warning(
                    "No FeatureTypeList found for %s: %s" %
                    (full_url, response.content)
                )
                return {}

            if feature_type_list.find('%sFeatureType' % np, ns) is None:
                self.logger.debug("No WFS layers found for %s" % full_url)
                return {}

            # NOTE: use ordered keys
            capabilities = OrderedDict()

            capabilities['name'] = service_name
            capabilities['wfs_url'] = full_url

            # get service title
            service_title = root.find('%sServiceIdentification/%sTitle' % (np_ows, np_ows), ns)
            if service_title is not None:
                capabilities['title'] = service_title.text

            # get service abstract
            service_abstract = root.find('%sServiceIdentification/%sAbstract' % (np_ows, np_ows), ns)
            if service_abstract is not None:
                capabilities['abstract'] = service_abstract.text

            # collect service keywords
            keyword_list = root.find('%sServiceIdentification/%sKeywords' % (np_ows, np_ows), ns)
            if keyword_list is not None:
                keywords = [
                    keyword.text for keyword
                    in keyword_list.findall('%sKeyword' % np_ows, ns)
                ]
                if keywords:
                    capabilities['keywords'] = ', '.join(keywords)

            # service provider
            provider_name = root.find("%sServiceProvider/%sProviderName" % (np_ows, np_ows), ns)
            individual_name = root.find("%sServiceProvider/%sServiceContact/%sIndividualName" % (np_ows, np_ows, np_ows), ns)
            position_name = root.find("%sServiceProvider/%sServiceContact/%sPositionName" % (np_ows, np_ows, np_ows), ns)

            capabilities["contact"] = {
                "person": individual_name.text if individual_name is not None else None,
                "organization": provider_name.text if provider_name is not None else None,
                "position": position_name.text if position_name is not None else None
            }

            # collect WFS layer attributes
            wfs_layers_attributes = self.collect_wfs_layers_attributes(full_url)

            # collect WFS layers
            wfs_layers = []
            for layer in feature_type_list.findall('%sFeatureType' % np, ns):
                # NOTE: use ordered keys
                wfs_layer = OrderedDict()

                layer_name = layer.find('%sName' % np, ns).text
                wfs_layer['name'] = layer_name
                wfs_layer['title'] = layer.find('%sTitle' % np, ns).text
                wfs_layer['attributes'] = wfs_layers_attributes.get(layer_name, [])

                wfs_layers.append(wfs_layer)

            capabilities["wfs_layers"] = wfs_layers

            return capabilities
        except Exception as e:
            self.logger.error(
                "Could not parse WFS GetCapabilities from %s:\n%s" %
                (full_url, e)
            )
            return {}

    def collect_wfs_layers_attributes(self, full_url):
        """Get all WFS layer attributes from WFS DescribeFeatureType.

        Returns dict as {<layer name>: [<attributes>]}

        :param str full_url: WFS URL
        """
        try:
            response = requests.get(
                full_url,
                params={
                    'SERVICE': 'WFS',
                    'VERSION': '1.1.0',
                    'REQUEST': 'DescribeFeatureType'
                },
                timeout=self.project_settings_read_timeout
            )

            if response.status_code != requests.codes.ok:
                self.logger.error(
                    "Could not get WFS DescribeFeatureType from %s:\n%s" %
                    (full_url, response.content)
                )
                return {}

            self.logger.info(
                "Downloaded WFS DescribeFeatureType from %s" % full_url
            )

            document = response.content

            # parse WFS Capabilities XML
            ElementTree.register_namespace('', 'http://www.w3.org/2001/XMLSchema')
            ElementTree.register_namespace('gml', 'http://www.opengis.net/gml')
            ElementTree.register_namespace('qgs', 'http://www.qgis.org/wms')
            ElementTree.register_namespace('ogc', 'http://www.opengis.net/ogc')
            root = ElementTree.fromstring(document)

            # use default namespace for XML search
            # namespace dict
            ns = {'ns': 'http://www.w3.org/2001/XMLSchema'}
            # namespace prefix
            np = 'ns:'
            if not root.tag.startswith('{http://'):
                # do not use namespace
                ns = {}
                np = ''

            layers_attributes = {}

            for complex_type in root.findall('%scomplexType' % np, ns):
                # extract layer name from complexType by removing "Type" suffix
                # e.g. "edit_pointsType" -> "edit_points"
                layer_name = complex_type.get('name').removesuffix('Type')

                attributes = []
                for element in complex_type.findall('%scomplexContent/%sextension/%ssequence/%selement' % (np, np, np, np), ns):
                    attributes.append(element.get('name'))

                layers_attributes[layer_name] = attributes

            return layers_attributes
        except Exception as e:
            self.logger.error(
                "Could not parse WFS DescribeFeatureType from %s:\n%s" %
                (full_url, e)
            )
            return {}
