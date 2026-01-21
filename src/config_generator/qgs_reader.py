import html
import io
import json
import math
import os
import re
import shutil
import time
import traceback
import zipfile
from collections import OrderedDict
from sqlalchemy.sql import text as sql_text
from urllib.parse import quote as urlquote
from xml.etree import ElementTree

from qwc_services_core.database import DatabaseEngine
from .dnd_form_generator import DnDFormGenerator


def element_attr(element, attr, default=None):
    """ Safely queries the attribute of an element which may be none. """
    return element.get(attr, default) if element is not None else default

def deep_merge(d1, d2):
    """Recursively merge two dictionaries."""
    result = d1.copy()
    for k, v in d2.items():
        if (
            k in result
            and isinstance(result[k], dict)
            and isinstance(v, dict)
        ):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result

class QGSReader:
    """ Read QGIS projects and extract data for QWC config """

    def __init__(self, config, logger, assets_dir, use_cached_project_metadata, global_print_layouts):
        """Constructor

        :param obj config: Config generator config
        :param Logger logger: Application logger
        :param string assets_dir: Assets directory
        :param bool use_cached_project_metadata: Whether to use cached project metadata
        :param list global_print_layouts: Global print layouts
        """
        self.config = config
        self.logger = logger
        self.assets_dir = assets_dir
        self.use_cached_project_metadata = use_cached_project_metadata
        self.global_print_layouts = global_print_layouts

        self.qgs_resources_path = config.get('qgis_projects_base_dir', '/tmp/')
        self.qgs_ext = config.get('qgis_project_extension', '.qgs')
        self.nested_nrels = config.get('generate_nested_nrel_forms', False)

        self.db_engine = DatabaseEngine()


    def read(self, map_prefix, theme_item, edit_datasets):
        """Read QGIS project file and return project metadata on success

        :param str map_prefix: QGS basename with the path component relative to projects base dir
        :param object theme_item: theme item
        ;param list edit_datasets: list of datasets for which to gather edit metadata
        """
        root = None
        try:
            if map_prefix.startswith("pg/"):
                parts = map_prefix.split("/")
                qgs_dir = self.qgs_resources_path
                qgs_filename = 'postgresql:///?service=qgisprojects&schema=%s&project=%s' % (parts[1], parts[2])
                projectname = parts[2]

                qgis_projects_db = self.db_engine.db_engine("postgresql:///?service=qgisprojects")

                with qgis_projects_db.connect() as conn:
                    sql = sql_text("""
                        SELECT content FROM "{schema}"."{table}"
                        WHERE name = '{project}';
                    """.format(schema=parts[1], table="qgis_projects", project=parts[2]))
                    result = conn.execute(sql)
                    row = result.mappings().fetchone()
                    if not row:
                        self.logger.error("Could not find QGS project '%s'" % qgs_filename)
                        return None

                    qgz = zipfile.ZipFile(io.BytesIO(row['content']))
                    for filename in qgz.namelist():
                        if filename.endswith('.qgs'):
                            fh = qgz.open(filename)
                            tree = ElementTree.parse(fh)
                            fh.close()
                            break

            else:
                qgs_filename = map_prefix + self.qgs_ext
                qgs_path = os.path.join(self.qgs_resources_path, qgs_filename)
                qgs_dir = os.path.dirname(qgs_path)
                projectname = os.path.basename(qgs_path).removesuffix(self.qgs_ext)
                if not os.path.exists(qgs_path):
                    self.logger.error("Could not find QGS project '%s'" % qgs_filename)
                    return None

                if self.qgs_ext == ".qgz":

                    with zipfile.ZipFile(qgs_path, 'r') as qgz:
                        for filename in qgz.namelist():
                            if filename.endswith('.qgs'):
                                fh = qgz.open(filename)
                                tree = ElementTree.parse(fh)
                                fh.close()
                                break
                else:

                    tree = ElementTree.parse(qgs_path)

            if tree is None or tree.getroot().tag != 'qgis':
                self.logger.error("'%s' is not a QGS file" % qgs_filename)
                return None
            root = tree.getroot()
            self.logger.info("Read '%s'" % qgs_filename)

        except Exception as e:
            self.logger.error(e)
            self.logger.debug(traceback.format_exc())
            return None

        # Check if WMSUseLayerIDs is set
        wmsUseLayerIds = root.find('./properties/WMSUseLayerIDs')
        if wmsUseLayerIds is not None and wmsUseLayerIds.text == "true":
            self.logger.warning(
                "'Use layer ids as names' is checked in the QGIS Server properites of '%s', which is not properly supported by QWC"
                % qgs_filename
            )

        # Build layername -> shortname lookup
        shortname_map = {}
        for maplayer in root.findall('.//maplayer'):
            layernameEl = maplayer.find('layername')
            if layernameEl is not None:
                shortnameEl = maplayer.find('shortname')
                shortname = shortnameEl.text if shortnameEl is not None else layernameEl.text
                shortname_map[layernameEl.text] = shortname

        return {
            "project_crs": self.__project_crs(root),
            "print_templates": self.__print_templates(root, shortname_map, theme_item),
            "visibility_presets": self.__visibility_presets(root, theme_item),
            "layer_metadata": self.__layer_metadata(root, shortname_map, map_prefix, edit_datasets, theme_item, qgs_dir),
        }


    def __project_crs(self, root):
        """ Read project CRS from QGS. """
        authid = root.find('./projectCrs/spatialrefsys/authid')
        return authid.text if authid is not None else None

    def __print_templates(self, root, shortname_map, theme_item):
        """ Collect print templates from QGS and merge with global print layouts. """

        printTemplateBlacklist = theme_item.get("printTemplateBlacklist", [])
        restrictedLayouts = [el.text for el in root.findall('./properties/WMSRestrictedComposers/value')]
        print_templates = []
        composer_template_map = {}
        for template in root.findall('.//Layout'):
            if template.get('name') not in restrictedLayouts and template.get('name') not in printTemplateBlacklist:
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

            composer_map = template.find(".//LayoutItem[@type='65639']")
            if template.tag != "Layout" or composer_map is None:
                self.logger.warning("Skipping invalid print template " + template.get('name') + " (may not contain a layout map element)")
                continue

            size = composer_map.get('size').split(',')
            position = composer_map.get('positionOnPage').split(',')
            resolution = float(template.get('printResolution'))
            tomm = {
                'mm': 1,
                'cm': 10,
                'm': 1000,
                'in': 25.4,
                'ft': 304.8,
                'pt': 25.4 / 72,
                'pica': 25.4 / 6,
                'px': 25.4 / resolution
            }
            print_template = {}
            print_template['name'] = template.get('name')
            print_template['title'] = template.get('name')
            print_map = {}
            print_map['name'] = "map0"
            print_map['x'] = float(position[0]) * tomm.get(position[2], 1)
            print_map['y'] = float(position[1]) * tomm.get(position[2], 1)
            print_map['width'] = float(size[0]) * tomm.get(size[2], 1)
            print_map['height'] = float(size[1]) * tomm.get(size[2], 1)
            print_template['map'] = print_map

            atlas = template.find("Atlas")
            if atlas is not None and atlas.get("enabled") == "1":
                tableMetadata = self.__datasource_metadata(atlas.get('coverageLayerSource'))
                if 'primary_key' in tableMetadata:
                    atlasLayer = atlas.get('coverageLayerName')
                    print_template['atlasCoverageLayer'] = shortname_map.get(atlasLayer, atlasLayer)
                    print_template['atlas_pk'] = tableMetadata['primary_key']

            labels = []
            for label in template.findall(".//LayoutItem[@type='65641']"):
                if label.get('visibility') == '1' and label.get('id'):
                    labels.append(label.get('id'))
            if labels:
                print_template['labels'] = labels

            print_templates.append(print_template)

        project_template_titles = [template['title'] for template in print_templates]
        return print_templates + [
            template for template in self.global_print_layouts
            if template["title"] not in project_template_titles and template["title"] not in printTemplateBlacklist
        ]


    def __visibility_presets(self, root, theme_item):
        """ Read layer visibility presets from QGS. """
        visibilityPresets = root.find('./visibility-presets')
        if visibilityPresets is None:
            return {}

        # layerId => (short)name map
        layer_map = {}
        geom_types = {}
        for mapLayer in root.findall('.//maplayer'):
            layerId = mapLayer.find('./id')
            if layerId is not None:
                geom_types[layerId.text] = mapLayer.get('wkbType')
                if mapLayer.find('shortname') is not None:
                    layer_map[layerId.text] = mapLayer.find('shortname').text
                elif mapLayer.find('layername') is not None:
                    layer_map[layerId.text] = mapLayer.find('layername').text

        tree = root.find('layer-tree-group')
        parent_map = {c: p for p in tree.iter() for c in p}

        def layer_path(layer_id):
            child = tree.find(".//layer-tree-layer[@id='%s']" % layer_id)
            if child is None:
                return None
            path = [layer_map[layer_id]]
            while (parent := parent_map.get(child)) is not None:
                path.insert(0, parent.get('name'))
                child = parent
            return "/".join(path[1:])


        hidden_layers = theme_item.get('layerTreeHiddenSublayers', [])
        result = {}
        for visibilityPreset in visibilityPresets.findall('./visibility-preset'):
            name = visibilityPreset.get('name')
            result[name] = {}
            for layer in visibilityPreset.findall('./layer'):
                layer_id = layer.get('id')
                if layer_id not in layer_map:
                    continue
                path = layer_path(layer_id)
                if layer_map[layer_id] not in hidden_layers and \
                    geom_types[layer_id] != 'WKBNoGeometry' and geom_types[layer_id] != 'NoGeometry' and \
                    layer.get('visible') == "1" and path \
                :
                    result[name][path] = layer.get('style')
            for checkedGroupNode in visibilityPreset.findall('./checked-group-nodes/checked-group-node'):
                groupid = checkedGroupNode.get('id')
                if groupid is not None and os.path.basename(groupid) not in hidden_layers:
                    result[name][groupid] = ""

        return result


    def __layer_metadata(self, root, shortname_map, map_prefix, edit_datasets, theme_item, qgs_dir):
        """ Read additional layer metadata from QGS. """
        layers_metadata = {}
        # Collect metadata for layers
        for maplayer in root.findall('.//maplayer'):
            if maplayer.find('shortname') is not None:
                layername = maplayer.find('shortname').text
            elif maplayer.find('layername') is not None:
                layername = maplayer.find('layername').text
            else:
                continue

            editable = layername in edit_datasets

            self.logger.info(f"Collecting metadata for {'editable ' if editable else ''}layer <b>{layername}</b>")

            layer_metadata = {}

            # Refresh interval
            layer_metadata["refresh_interval"] = int(maplayer.get('autoRefreshTime', 0))

            # Dimensions
            layer_metadata["dimensions"] = dict([(
                dim.get('name'), {'fieldName': dim.get('fieldName'), 'endFieldName': dim.get('endFieldName')}
            ) for dim in maplayer.findall("wmsDimensions/dimension")])

            # Edit metadata
            if editable:
                self.__layer_edit_metadata(root, layer_metadata, maplayer, layername, map_prefix, shortname_map, qgs_dir, theme_item)

            layers_metadata[layername] = layer_metadata

        # Warn about non-existing datasets
        shortnames = shortname_map.values()
        invalid_datasets = [
            dataset for dataset in edit_datasets if not dataset in shortnames
        ]
        if invalid_datasets:
            self.logger.warn("The following data resources did not match any layer in the project %s: %s" % (map_prefix, ",".join(invalid_datasets)))

        return layers_metadata


    def __layer_edit_metadata(self, root, layer_metadata, maplayer, layername, map_prefix, shortnames, qgs_dir, theme_item):
        """ Read layer metadata relevant for editing from QGS. """

        provider = maplayer.find('provider').text
        if provider != 'postgres':
            self.logger.warning(f"Skipping edit metadata for layer {layername}: not a postgres layer")
            return

        # Read datasource
        layer_metadata.update(self.__datasource_metadata(maplayer.find('datasource').text, maplayer))
        if not layer_metadata.get('database') or not layer_metadata.get('table_name'):
            self.logger.warning(f"Skipping edit metadata for layer {layername}: could not parse datasource")
            return

        layer_metadata["editable"] = True

        # Read joins
        joinfields = {}
        jointables = {}
        for join in maplayer.findall('vectorjoins/join'):
            joinlayer = root.find(".//maplayer[id='%s']" % join.get('joinLayerId'))
            if joinlayer is not None:
                jointable = joinlayer.find('layername').text
                if join.find('joinFieldsSubset') is not None:
                    jointablefields = join.find('joinFieldsSubset').findall('field')
                else:
                    jointablefields = joinlayer.find('fieldConfiguration').findall('field')

                for field in jointablefields:
                    if not jointable in jointables:
                        jointables[jointable] = self.__datasource_metadata(joinlayer.find('datasource').text, joinlayer)
                        jointables[jointable]['targetField'] = join.get('targetFieldName')
                        jointables[jointable]['joinField'] = join.get('joinFieldName')

                    prefix = join.get('customPrefix', jointable + '_')
                    joinfieldname = '%s%s' % (prefix, field.get('name'))
                    joinfields[joinfieldname] = {
                        'field': field.get('name'),
                        'table': jointable
                    }
        layer_metadata["jointables"] = jointables

        # Read fields
        layer_metadata["keyvaltables"] = {}
        layer_metadata["fields"] = OrderedDict()
        for alias in maplayer.findall('aliases/alias'):
            fieldname = alias.get('field')
            field = {}

            # Alias
            field['alias'] = alias.get('name') or fieldname

            # Default value
            field['defaultValue'] = element_attr(
                maplayer.find("defaults/default[@field='%s']" % fieldname), 'expression')

            # Virtual field expression
            field['expression'] = element_attr(
                maplayer.find("expressionfields/field[@name='%s']" % fieldname), 'expression')

            # Filter expression
            field['filterExpression'] = element_attr(
                maplayer.find("fieldConfiguration/field[@name='%s']/editWidget[@type='ValueRelation']/config/Option/Option[@name='FilterExpression']" % fieldname), 'value')

            # Widget constraints
            field['constraints'] = self.__field_constraints(root, maplayer, fieldname, map_prefix, shortnames, layer_metadata["keyvaltables"])

            # Join field
            field['joinfield'] = joinfields.get(fieldname, None)

            # Lookup DB column type
            if field['joinfield']:
                self.__column_metadata(
                    field, jointables[field['joinfield']['table']], field['joinfield']['field']
                )
            elif field['expression']:
                field['data_type'] = element_attr(
                    maplayer.find("expressionfields/field[@name='%s']" % fieldname), 'typeName')
            else:
                self.__column_metadata(
                    field, layer_metadata, fieldname
                )

            if field.get('data_type') != 'geometry':
                layer_metadata["fields"][fieldname] = field
            else:
                self.logger.warn("Skipping edit field %s with unhandled data-type %s" % (fieldname, field.get('data_type')))

        # Display field
        previewExpression = maplayer.find('previewExpression')
        if previewExpression is not None:
            m = re.match(r'^"([^"]+)"$', previewExpression.text if previewExpression.text is not None else "")
        layer_metadata["displayField"] = m.group(1) if m else None

        # Generate form
        layer_metadata["edit_form"] = self.__generate_edit_form(
            root, qgs_dir, map_prefix, shortnames, maplayer, layer_metadata, layername, theme_item
        )


    def __datasource_metadata(self, datasource, maplayer=None):
        """ Read datasource metadata from a QGS datasource URI. """
        metadata = {}
        params = self.__parse_datasource(datasource)

        # Parse DB connection
        if params.get('service'):
            metadata["database"] = 'postgresql:///?service=%s' % params['service']

        elif params.get('dbname'):
            dbname = params['dbname']
            host = params.get('host')
            port = params.get('port')
            user = params.get('user')
            password = params.get('password')

            # postgresql://user:password@host:port/dbname
            credentials = "%s:%s@" % (
                urlquote(user), urlquote(password)
            ) if user and password else ""

            metadata["database"] = f'postgresql://{credentials}{host}:{port}/{dbname}'

        # Datasource filter
        metadata["datasource_filter"] = params.get('sql')

        # Parse schema, table, primary key, and geometry column, type and srid
        if params.get('table'):
            pattern = re.compile(
                r'(?:from\s+)?'                       # optional "from"
                r'(?:"(?P<schema_q>[^"]+)"|'          # quoted schema
                r'(?P<schema_u>\w+))'                 # or unquoted schema
                r'\.'                                 # dot separator
                r'(?:"(?P<table_q>[^"]+)"|'           # quoted table
                r'(?P<table_u>\w+))',                 # or unquoted table
                re.IGNORECASE
            )
            match = pattern.search(params['table'].strip('()'))
            if match:
                metadata['schema'] = match.group('schema_q') or match.group('schema_u')
                metadata['table_name'] = match.group('table_q') or match.group('table_u')

        metadata['primary_key'] = params.get('key')

        if params.get('geom'):
            metadata['geometry_column'] = params["geom"].strip('()')

        if params.get('type'):
            metadata['geometry_type'] = params['type'].upper()
        elif maplayer and maplayer.get('wkbType'):
            # Try to fall back to wkbType attr of maplayer element
            metadata['geometry_type'] = maplayer.get('wkbType').upper()

        if params.get('srid'):
            metadata['srid'] = int(params['srid'])
        elif maplayer:
            srid = maplayer.find('srs/spatialrefsys/srid')
            if srid is not None:
                metadata['srid'] = int(srid.text)

        return metadata

    def __field_constraints(self, root, maplayer, field, map_prefix, shortnames, keyvaltables):
        """ Get field constraints from QGS edit widget config. """

        constraints = {}

        # ReadOnly
        field_editable = element_attr(maplayer.find("editable/field[@name='%s']" % field), 'editable')
        constraints['readOnly'] = field_editable == '0'

        # Required
        if not constraints['readOnly']:
            # ConstraintNotNull = 1
            constraints['required'] = int(
                maplayer.find("constraints/constraint[@field='%s']" % field)
                .get('constraints')
            ) & 1 > 0

        # Constraint expression
        constraints['expression'] = element_attr(maplayer.find(
            "constraintExpressions/constraint[@field='%s']" % field), 'exp')

        # Constraint expression description
        constraints['placeholder'] = element_attr(maplayer.find(
            "constraintExpressions/constraint[@field='%s']" % field
        ), 'desc')

        # Edit widget config
        edit_widget = maplayer.find("fieldConfiguration/field[@name='%s']/editWidget" % field)

        if edit_widget is None:
            pass
        if edit_widget.get('type') == 'Range':
            min_option = element_attr(edit_widget.find("config/Option/Option[@name='Min']"), 'value')
            max_option = element_attr(edit_widget.find("config/Option/Option[@name='Max']"), 'value')
            step_option = element_attr(edit_widget.find("config/Option/Option[@name='Step']"), 'value')
            prec_option = element_attr(edit_widget.find("config/Option/Option[@name='Precision']"), 'value')
            constraints['min'] = self.__parse_number(min_option, -2147483648)
            constraints['max'] = self.__parse_number(max_option, 2147483647)
            constraints['step'] = self.__parse_number(step_option, 1)
            step_prec = math.ceil(abs(math.log10(constraints['step'] or 1)))
            constraints['prec'] = self.__parse_number(prec_option, step_prec)

        elif edit_widget.get('type') == 'ValueMap':
            values = []
            for option_map in edit_widget.findall(
                    "config/Option/Option[@type='List']/Option"
            ):
                option = option_map.find("Option")
                if option.get('type') != "invalid":
                    values.append({
                        'label': option.get('name'),
                        'value': option.get('value')
                    })
            if values:
                constraints['values'] = values

        elif edit_widget.get('type') == 'ValueRelation':
            key = edit_widget.find(
                        "config/Option/Option[@name='Key']").get('value')
            value = edit_widget.find(
                        "config/Option/Option[@name='Value']").get('value')
            layerId = edit_widget.find(
                        "config/Option/Option[@name='Layer']").get('value')
            layerName = edit_widget.find(
                        "config/Option/Option[@name='LayerName']").get('value')
            layerSource = edit_widget.find(
                        "config/Option/Option[@name='LayerSource']").get('value')
            allowMulti = edit_widget.find(
                        "config/Option/Option[@name='AllowMulti']").get('value') == "true"

            # Lookup shortname
            layerName = shortnames.get(layerName, layerName)

            constraints['keyvalrel'] = map_prefix + "." + layerName + ":" + key + ":" + value
            constraints['allowMulti'] = allowMulti

            kvlayer = root.find(".//maplayer[id='%s']" % layerId)
            if kvlayer is None:
                # Try to resolve by layer name
                for ml in root.findall(".//maplayer"):
                    mlname = ml.find("layername")
                    if mlname is not None and mlname.text == layerName:
                        kvlayer = ml
                        break
            if kvlayer is None:
                self.logger.warning(f"Cannot generate keyvalrel config for field {field}: the referenced relation table {layerName} does not exist in the project")
            elif kvlayer.find('provider').text != 'postgres':
                self.logger.warning(f"Cannot generate keyvalrel config for field {field}: relation table {layerName} is not a postgres layer")
            else:
                # NOTE: could use layerSource, but in certain QGIS projects it does not match the datasource of the actual layer
                keyvaltable_metadata = self.__datasource_metadata(kvlayer.find('datasource').text)
                keyvaltable_metadata['fields'] = []
                for kvlayer_field in kvlayer.findall('fieldConfiguration/field'):
                    kvlayer_field_metadata = {"name": kvlayer_field.get('name')}
                    self.__column_metadata(kvlayer_field_metadata, keyvaltable_metadata, kvlayer_field_metadata['name'], True)
                    keyvaltable_metadata['fields'].append(kvlayer_field_metadata)
                keyvaltables[map_prefix + "." + layerName] = keyvaltable_metadata

        elif edit_widget.get('type') == 'TextEdit':
            multilineOpt = element_attr(edit_widget.find("config/Option/Option[@name='IsMultiline']"), 'value')
            constraints['multiline'] = multilineOpt == "true"

        elif edit_widget.get("type") == "ExternalResource":
            filterOpt = element_attr(edit_widget.find("config/Option/Option[@name='FileWidgetFilter']"), 'value', "")
            constraints['fileextensions'] = self.__parse_fileextensions(filterOpt)

        elif edit_widget.get('type') == 'Hidden':
            constraints['hidden'] = True

        elif edit_widget.get('type') == 'CheckBox':
            constraints['required'] = False

        return constraints

    def __column_metadata(self, field_metadata, datasource, column, data_type_only = False):
        """ Get column metadata from database. """

        # build query SQL for tables and views
        sql = sql_text("""
            SELECT data_type, udt_name, character_maximum_length,
                numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = '{schema}' AND table_name = '{table}'
                AND column_name = '{column}'
            ORDER BY ordinal_position;
        """.format(
            schema=datasource["schema"],
            table=datasource["table_name"],
            column=column
        ))
        db = self.db_engine.db_engine(datasource["database"])
        try:
            with db.connect() as conn:
                # execute query
                results = conn.execute(sql)

                if results.rowcount == 0:
                    # fallback to query SQL for materialized views

                    # SQL partially based on definition of information_schema.columns:
                    #   https://github.com/postgres/postgres/tree/master/src/backendsrc/backend/catalog/information_schema.sql#L674
                    sql_mv = sql_text("""
                        SELECT
                            ns.nspname AS table_schema,
                            c.relname AS table_name,
                            a.attname AS column_name,
                            CASE
                                WHEN t.typelem <> 0 THEN 'ARRAY'
                                ELSE format_type(a.atttypid, NULL)
                            END AS data_type,
                            t.typname AS udt_name,
                            CASE
                                WHEN a.atttypmod = -1 /* default typmod */
                                    THEN NULL
                                WHEN a.atttypid IN (1042, 1043) /* char, varchar */
                                    THEN a.atttypmod - 4
                                WHEN a.atttypid IN (1560, 1562) /* bit, varbit */
                                    THEN a.atttypmod
                                ELSE
                                    NULL
                            END AS character_maximum_length,
                            CASE a.atttypid
                                WHEN 21 /*int2*/ THEN 16
                                WHEN 23 /*int4*/ THEN 32
                                WHEN 20 /*int8*/ THEN 64
                                WHEN 1700 /*numeric*/ THEN
                                    CASE
                                        WHEN a.atttypmod = -1
                                            THEN NULL
                                        ELSE ((a.atttypmod - 4) >> 16) & 65535
                                    END
                                WHEN 700 /*float4*/ THEN 24 /*FLT_MANT_DIG*/
                                WHEN 701 /*float8*/ THEN 53 /*DBL_MANT_DIG*/
                                ELSE NULL
                            END AS numeric_precision,
                            CASE
                                WHEN a.atttypid IN (21, 23, 20) /* int */ THEN 0
                                WHEN a.atttypid IN (1700) /* numeric */ THEN
                                    CASE
                                        WHEN a.atttypmod = -1
                                            THEN NULL
                                        ELSE (a.atttypmod - 4) & 65535
                                    END
                                ELSE NULL
                            END AS numeric_scale
                        FROM pg_catalog.pg_class c
                            JOIN pg_catalog.pg_namespace ns ON ns.oid = c.relnamespace
                            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
                            JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
                        WHERE
                            /* tables, views, materialized views */
                            c.relkind in ('r', 'v', 'm')
                            AND ns.nspname = '{schema}'
                            AND c.relname = '{table}'
                            AND a.attname = '{column}'
                        ORDER BY nspname, relname, attnum
                    """.format(
                        schema=datasource["schema"],
                        table=datasource["table_name"],
                        column=column
                    ))
                    results = conn.execute(sql_mv)


                row = results.mappings().fetchone()
                if not row:
                    self.logger.warn(f"Failed to query column metadata of column {column} from table {datasource["schema"]}.{datasource["table_name"]} of {datasource["database"]}")
                    return

                # Field data type
                data_type = row['data_type']
                udt_name = row['udt_name']
                if data_type == 'ARRAY':
                    array_types = {
                        "_int2": "smallint[]",
                        "_int4": "integer[]",
                        "_int8": "bigint[]",
                        "_text": "text[]",
                        "_numeric": "numeric[]"
                    }
                    data_type = array_types.get(row['udt_name'], 'ARRAY')
                field_metadata['data_type'] = data_type

                if not data_type_only:
                    # Constraints from data type
                    # NOTE: any existing QGIS field constraints take precedence
                    ranges = {
                        'smallint': {'min': -32768, 'max': 32767},
                        'integer': {'min': -2147483648, 'max': 2147483647},
                        'bigint': {'min': -9223372036854775808, 'max': 9223372036854775807}
                    }
                    constraints = field_metadata['constraints']
                    if (data_type in ['character', 'character varying'] and
                            row['character_maximum_length']):
                        constraints['maxlength'] = row['character_maximum_length']
                    elif data_type == 'numeric' and row['numeric_precision']:
                        step = pow(10, -row['numeric_scale'])
                        max_value = pow(
                            10, row['numeric_precision'] - row['numeric_scale']
                        ) - step
                        constraints['numeric_precision'] = row['numeric_precision']
                        constraints['numeric_scale'] = row['numeric_scale']
                        if not 'step' in constraints:
                            constraints['step'] = step
                        ranges['numeric'] = {'min': -max_value, 'max': max_value}

                    if data_type in ranges:
                        if not 'min' in constraints:
                            constraints['min'] = ranges[data_type]['min']
                        if not 'max' in constraints:
                            constraints['max'] = ranges[data_type]['max']

        except:
            self.logger.warn(f"Failed to query column metadata of column {column} from table {datasource["schema"]}.{datasource["table_name"]} of {datasource["database"]}")
            return


    def __generate_edit_form(self, project, qgs_dir, map_prefix, shortnames, maplayer, layer_metadata, layername, theme_item):
        """ Copy / generate edit from from QGIS form settings. """

        projectname = os.path.basename(map_prefix)

        editorlayout = maplayer.find('editorlayout')
        if editorlayout is None:
            return None

        outputdir = os.path.join(self.assets_dir, 'forms', 'autogen')
        outputfile = os.path.join(outputdir, "%s_%s.ui" % (projectname, layername))

        uipath = None
        if self.use_cached_project_metadata and os.path.exists(outputfile):
            self.logger.info(f"Using cached edit form {projectname}_{layername}.ui")
            uipath = ":/forms/autogen/%s_%s.ui?v=%d" % (projectname, layername, int(time.time()))

        elif editorlayout.text == "uifilelayout":
            editform = maplayer.find('editform')
            if editform is not None:
                formpath = editform.text
                if not os.path.isabs(formpath):
                    formpath = os.path.join(qgs_dir, formpath)
                try:
                    os.makedirs(outputdir, exist_ok=True)
                    shutil.copy(formpath, outputfile)
                    self.logger.info(f"Copied edit form to {projectname}_{layerame}.ui")
                    uipath = ":/forms/autogen/%s_%s.ui?v=%d" % (projectname, layername, int(time.time()))
                except Exception as e:
                    self.logger.warning(f"Failed to copy edit form: {str(e)}")

        elif editorlayout.text == "tablayout" or editorlayout.text == "generatedlayout":


            editConfig = theme_item.get("editConfig", {}).get(layername, {})
            nested_nrels = self.nested_nrels or editConfig.get("generate_nested_nrel_forms", False)

            form = DnDFormGenerator(
                self.logger, self.assets_dir, self.db_engine, project,
                shortnames, maplayer, layer_metadata, nested_nrels
            ).generate_form(editorlayout)

            try:
                os.makedirs(outputdir, exist_ok=True)
                with open(outputfile, "wb") as fh:
                    fh.write(form)
                    self.logger.info(f"Wrote edit form to {projectname}_{layername}.ui")
                    uipath = ":/forms/autogen/%s_%s.ui?v=%d" % (projectname, layername, int(time.time()))
            except Exception as e:
                self.logger.warning(f"Failed to write edit form: {str(e)}")

        return uipath


    def __parse_datasource(self, datasource):
        """ Parse a QGS datasource URI string. """

        if not datasource:
            return {}

        result = {}

        # sql= is placed at end of datasource string, and can contain spaces even if it is not quoted (hurray)
        def extract_datasource_filter(match):
            result['sql'] = html.unescape(match.group(1))
            return ""

        datasource = re.sub("sql=(.*)$", extract_datasource_filter, datasource)

        # Parse remaining datasource key-values
        key = ''
        value = ''
        state = 'key'  # can be 'key', 'before_value', 'value'
        quote_char = None
        escape = False
        in_dquote = False

        def commit():
            nonlocal key, value, state, quote_char
            if key:
                result[key] = value
            key = ''
            value = ''
            state = 'key'
            quote_char = None
            in_dquote = False

        i = 0
        while i < len(datasource):
            c = datasource[i]

            if state == 'key':
                if c == '=':
                    key = key.strip()
                    state = 'before_value'
                elif c.isspace() and key:
                    # NOTE: geom is the only (?) param which is not in key=value format
                    value = key
                    key = 'geom'
                    commit()
                else:
                    key += c

            elif state == 'before_value':
                if c == "'":
                    state = 'value'
                    quote_char = c
                elif not c.isspace():
                    state = 'value'
                    value += c
                    if c == '"':
                        in_dquote = True

            elif state == 'value':
                if escape:
                    value += c
                    escape = False
                elif c == '\\':
                    escape = True
                elif quote_char:
                    if c == quote_char:
                        commit()
                    else:
                        value += c
                else:
                    if c.isspace() and not in_dquote:
                        commit()
                    else:
                        value += c
                        if c == '"':
                            in_dquote = not in_dquote
            i += 1

        # Final token
        if state == 'value':
            commit()
        elif state == 'key' and key:
            # NOTE: geom is the only (?) param which is not in key=value format
            value = key
            key = 'geom'
            commit()

        return result

    def __parse_number(self, value, default=None):
        """ Parse string as int or float, or return string if neither. """
        if value is None:
            return default

        result = value

        try:
            result = int(value)
        except ValueError:
            # int conversion failed
            try:
                result = float(value)
            except ValueError:
                # float conversion failed
                pass

        return result

    def __parse_fileextensions(self, value):
        """ Parse string as a comma separated list of file extensions of the form *.ext,
            returning array of file extensions [".ext1", ".ext2", ...]
        """
        return list(map(lambda x: x.strip().lstrip('*'), value.lower().split(",")))
