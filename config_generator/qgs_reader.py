from collections import OrderedDict
import math
import os
import re
from xml.etree import ElementTree
import psycopg2
import shutil
import time
from urllib.parse import quote as urlquote

from sqlalchemy.sql import text as sql_text

from qwc_services_core.database import DatabaseEngine
from .dnd_form_generator import DnDFormGenerator


class QGSReader:
    """QGSReader class

    Read QGIS 3.x projects and extract data for QWC config.
    """

    def __init__(self, logger, qgs_resources_path, qgs_path):
        """Constructor

        :param Logger logger: Application logger
        :param str qgs_resources_path: Path to qgis server data dir
        :param str qgs_path: QGS name with optional path relative to
                             QGIS server data dir
        """
        self.logger = logger
        self.root = None
        self.qgis_version = 0

        self.map_prefix = qgs_path
        qgs_file = "%s.qgs" % qgs_path
        self.qgs_path = os.path.join(qgs_resources_path, qgs_file)
        if not os.path.exists(self.qgs_path):
            self.logger.warn("Could not find QGS file '%s'" % self.qgs_path)

        self.db_engine = DatabaseEngine()

    def read(self):
        """Read QGIS project file and return True on success.
        """
        self.logger.info("Reading '%s.qgs'" % self.map_prefix)
        try:
            tree = ElementTree.parse(self.qgs_path)
            self.root = tree.getroot()
            if self.root.tag != 'qgis':
                self.logger.warn("'%s' is not a QGS file" % self.qgs_path)
                return False

            # extract QGIS version
            version = self.root.get('version')
            major, minor, rev = [
                int(v) for v in version.split('-')[0].split('.')
            ]
            self.qgis_version = major * 10000 + minor * 100 + rev

        except Exception as e:
            self.logger.error(e)
            return False

        return True

    def pg_layers(self):
        """Collect PostgreSQL layers in QGS.

        """
        layers = []

        if self.root is None:
            self.logger.warning("Root element is empty")
            return layers

        for maplayer in self.root.findall('.//maplayer'):
            layerid = maplayer.find('id')
            # Skip layers which are embedded projects
            if layerid is None:
                continue
            if maplayer.find('shortname') is not None:
                maplayer_name = maplayer.find('shortname').text
            elif maplayer.find('layername') is None:
                self.logger.info("maplayer layername undefined - skipping")
                continue
            else:
                maplayer_name = maplayer.find('layername').text
            provider = maplayer.find('provider').text

            if provider == 'postgres':
                layers.append(maplayer_name)

        return layers

    def layer_metadata(self, layer_name):
        """Collect layer metadata from QGS.

        :param str layer_name: Layer shortname
        """
        # NOTE: use ordered keys
        config = OrderedDict()

        if self.root is None:
            self.logger.warning("Root element is empty")
            return config

        # find layer by shortname
        for maplayer in self.root.findall('.//maplayer'):
            if maplayer.find('shortname') is not None:
                maplayer_name = maplayer.find('shortname').text
            elif maplayer.find('layername') is None:
                continue
            else:
                maplayer_name = maplayer.find('layername').text
            if maplayer_name == layer_name:
                provider = maplayer.find('provider').text
                if provider != 'postgres':
                    self.logger.info("Not a PostgreSQL layer")
                    continue

                datasource = maplayer.find('datasource').text
                config['database'] = self.__db_connection(datasource)
                config.update(self.__table_metadata(datasource, maplayer))
                config.update(self.__attributes_metadata(maplayer))
                config.update(self.__dimension_metadata(maplayer))

                self.__lookup_attribute_data_types(config)

                break

        return config

    def __db_connection(self, datasource):
        """Parse QGIS datasource URI and return SQLALchemy DB connection
        string for a PostgreSQL database or connection service.

        :param str datasource: QGIS datasource URI
        """
        connection_string = None

        if 'service=' in datasource:
            # PostgreSQL connection service
            m = re.search(r"service='([\w ]+)'", datasource)
            if m is not None:
                connection_string = 'postgresql:///?service=%s' % m.group(1)

        elif 'dbname=' in datasource:
            # PostgreSQL database
            dbname, host, port, user, password = '', '', '', '', ''

            m = re.search(r"dbname='(.+?)' \w+=", datasource)
            if m is not None:
                dbname = m.group(1)

            m = re.search(r"host=(\S+)", datasource)
            if m is not None:
                host = m.group(1)

            m = re.search(r"port=(\d+)", datasource)
            if m is not None:
                port = m.group(1)

            m = re.search(r"user='(.+?)' \w+=", datasource)
            if m is not None:
                user = m.group(1)
                # unescape \' and \\'
                user = re.sub(r"\\'", "'", user)
                user = re.sub(r"\\\\", r"\\", user)

            m = re.search(r"password='(.+?)' \w+=", datasource)
            if m is not None:
                password = m.group(1)
                # unescape \' and \\'
                password = re.sub(r"\\'", "'", password)
                password = re.sub(r"\\\\", r"\\", password)

            # postgresql://user:password@host:port/dbname
            connection_string = 'postgresql://'
            if user and password:
                connection_string += "%s:%s@" % (
                    urlquote(user), urlquote(password)
                )

            connection_string += "%s:%s/%s" % (host, port, dbname)

        return connection_string

    def __table_metadata(self, datasource, maplayer=None):
        """Parse QGIS datasource URI and return table metadata.

        :param str datasource: QGIS datasource URI
        """
        # NOTE: use ordered keys
        metadata = OrderedDict()

        # parse schema, table and geometry column
        m = re.search(r'table="([^"]+)"\."([^"]+)" \((\w+)\)', datasource)
        if m is not None:
            metadata['schema'] = m.group(1)
            metadata['table_name'] = m.group(2)
            metadata['geometry_column'] = m.group(3)
        else:
            m = re.search(r'table="([^"]+)"\."([^"]+)"', datasource)
            if m is not None:
                metadata['schema'] = m.group(1)
                metadata['table_name'] = m.group(2)

        m = re.search(r"key='(.+?)' \w+=", datasource)
        if m is not None:
            metadata['primary_key'] = m.group(1)

        m = re.search(r"type=([\w.]+)", datasource)
        if m is not None:
            metadata['geometry_type'] = m.group(1).upper()
        else:
            metadata['geometry_type'] = None

        m = re.search(r"srid=([\d.]+)", datasource)
        if m is not None:
            metadata['srid'] = int(m.group(1))
        elif maplayer:
            srid = maplayer.find('srs/spatialrefsys/srid')
            if srid is not None:
                metadata['srid'] = int(srid.text)

        return metadata

    def __attributes_metadata(self, maplayer):
        """Collect layer attributes.

        :param Element maplayer: QGS maplayer node
        """
        attributes = []
        # NOTE: use ordered keys
        fields = OrderedDict()

        # Get fieldnames from attributeEditorForm if possible (to preserve order), otherwise from aliases
        fieldnames = []

        editorlayout = maplayer.find('editorlayout')
        formfields = maplayer.find('attributeEditorForm')
        if editorlayout.text == "tablayout" and formfields is not None:
            for formfield in formfields.findall('.//attributeEditorField'):
                # NOTE: skip missing fields with index="-1"
                if formfield.get('index') != '-1':
                    fieldnames.append(formfield.get('name'))
        else:
            aliases = maplayer.find('aliases')
            for alias in aliases.findall('alias'):
                fieldnames.append(alias.get('field'))

        keyvaltables = {}
        for field in fieldnames:

            attributes.append(field)
            # NOTE: use ordered keys
            fields[field] = OrderedDict()

            # get alias
            alias = maplayer.find("aliases/alias[@field='%s']" % field)
            if alias is not None and alias.get('name'):
                fields[field]['alias'] = alias.get('name')

            # get any constraints from edit widgets
            constraints = self.__edit_widget_constraints(maplayer, field, keyvaltables)
            if constraints:
                fields[field]['constraints'] = constraints

            expressionfields_field = maplayer.find(
                "expressionfields/field[@name='%s']" % field
            )
            if expressionfields_field is not None:
                fields[field]['expression'] = expressionfields_field.get('expression').lstrip("'").rstrip("'")

        displayField = None
        previewExpression = maplayer.find('previewExpression')
        if previewExpression is not None and previewExpression.text is not None:
            m = re.match(r'^"([^"]+)"$', previewExpression.text)
            if m:
                displayField = m.group(1)

        return {
            'attributes': attributes,
            'fields': fields,
            'keyvaltables': keyvaltables,
            'displayField': displayField
        }

    def __dimension_metadata(self, maplayer):
        wmsDimensions = maplayer.findall("wmsDimensions/dimension")
        dimensions = {}
        for dimension in wmsDimensions:
            dimensions[dimension.get('name')] = {
                'fieldName': dimension.get('fieldName'),
                'endFieldName': dimension.get('endFieldName')
            }

        return {
            'dimensions': dimensions
        }

    def __edit_widget_constraints(self, maplayer, field, keyvaltables):
        """Get any constraints from edit widget config (QGIS 3.x).

        :param Element maplayer: QGS maplayer node
        :param str field: Field name
        """
        # NOTE: use ordered keys
        constraints = OrderedDict()

        # NOTE: <editable /> is empty if Attributes Form is not configured
        editable_field = maplayer.find("editable/field[@name='%s']" % field)
        if (editable_field is not None and
                editable_field.get('editable') == '0'):
            constraints['readOnly'] = True

        if not constraints.get('readOnly', False):
            # ConstraintNotNull = 1
            constraints['required'] = int(
                maplayer.find("constraints/constraint[@field='%s']" % field)
                .get('constraints')
            ) & 1 > 0

        constraint_desc = maplayer.find(
            "constraintExpressions/constraint[@field='%s']" % field
        ).get('desc')
        if len(constraint_desc) > 0:
            constraints['placeholder'] = constraint_desc

        edit_widget = maplayer.find(
            "fieldConfiguration/field[@name='%s']/editWidget" % field
        )

        if edit_widget.get('type') == 'Range':
            min_option = edit_widget.find(
                        "config/Option/Option[@name='Min']")
            max_option = edit_widget.find(
                        "config/Option/Option[@name='Max']")
            step_option = edit_widget.find(
                        "config/Option/Option[@name='Step']")
            prec_option = edit_widget.find(
                        "config/Option/Option[@name='Precision']")
            constraints['min'] = self.__parse_number(
                min_option.get('value')) if min_option is not None else -2147483648
            constraints['max'] = self.__parse_number(
                max_option.get('value')) if max_option is not None else 2147483647
            constraints['step'] = self.__parse_number(
                step_option.get('value')) if step_option is not None else 1
            constraints['prec'] = self.__parse_number(
                prec_option.get('value')) if step_option is not None else math.ceil(abs(math.log10(constraints['step'])))

        elif edit_widget.get('type') == 'ValueMap':
            values = []
            for option_map in edit_widget.findall(
                    "config/Option/Option[@type='List']/Option"
            ):
                option = option_map.find("Option")
                # NOTE: use ordered keys
                value = OrderedDict()
                value['label'] = option.get('name')
                value['value'] = option.get('value')
                values.append(value)

            if values:
                constraints['values'] = values
        elif edit_widget.get('type') == 'ValueRelation':
            key = edit_widget.find(
                        "config/Option/Option[@name='Key']").get('value')
            value = edit_widget.find(
                        "config/Option/Option[@name='Value']").get('value')
            layerName = edit_widget.find(
                        "config/Option/Option[@name='LayerName']").get('value')
            layerSource = edit_widget.find(
                        "config/Option/Option[@name='LayerSource']").get('value')
            constraints['keyvalrel'] = self.map_prefix + "." + layerName + ":" + key + ":" + value

            keyvaltables[self.map_prefix + "." + layerName] = self.__table_metadata(layerSource)
            keyvaltables[self.map_prefix + "." + layerName]['layername'] = layerName
            keyvaltables[self.map_prefix + "." + layerName]['database'] = self.__db_connection(layerSource)
            keyvaltables[self.map_prefix + "." + layerName]['fields'] = {
                key: {},
                value: {}
            }


        elif edit_widget.get('type') == 'TextEdit':
            multilineOpt = edit_widget.find(
                        "config/Option/Option[@name='IsMultiline']")
            constraints['multiline'] = multilineOpt is not None and multilineOpt.get('value') == "true"

        elif edit_widget.get("type") == "ExternalResource":
            filterOpt = edit_widget.find("config/Option/Option[@name='FileWidgetFilter']")
            constraints['fileextensions'] = self.__parse_fileextensions(filterOpt.get('value')) if filterOpt is not None else ""
        elif edit_widget.get('type') == 'Hidden':
            constraints['hidden'] = True
            constraints['readOnly'] = True

        return constraints

    def __parse_number(self, value):
        """Parse string as int or float, or return string if neither.

        :param str value: Number value as string
        """
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
        """Parse string as a comma separated list of file extensions of the form *.ext,
         returning array of file extensions [".ext1", ".ext2", ...]

        :param str value: File filter string
        """
        return list(map(lambda x: x.strip().lstrip('*'), value.lower().split(",")))

    def __lookup_attribute_data_types(self, meta):
        """Query column data types from GeoDB and add them to table metadata.

        :param obj meta: Table metadata
        """
        conn = None
        upload_fields = []
        try:
            connection_string = meta.get('database')
            schema = meta.get('schema')
            table_name = meta.get('table_name')

            if not schema or not table_name:
                self.logger.warn("Skipping attribute lookup for dataset with unknown table and/or schema name")
                return

            # connect to GeoDB
            geo_db = self.db_engine.db_engine(connection_string)
            conn = geo_db.connect()
            fields = meta.get('fields')

            for attr in meta.get('attributes'):
                # upload field
                if attr.endswith("__upload"):
                    self.logger.warn("Using virtual <fieldname>__upload fields is deprecated, set the field widget type to 'Attachment' in the QGIS layer attribute form configuration instead.")
                    upload_fields.append(attr)
                    continue

                # expression field
                if attr in fields and 'expression' in fields.get(attr):
                    continue

                # build query SQL
                sql = sql_text("""
                    SELECT data_type, character_maximum_length,
                        numeric_precision, numeric_scale
                    FROM information_schema.columns
                    WHERE table_schema = '{schema}' AND table_name = '{table}'
                        AND column_name = '{column}'
                    ORDER BY ordinal_position;
                """.format(schema=schema, table=table_name, column=attr))

                # execute query
                data_type = None
                # NOTE: use ordered keys
                constraints = OrderedDict()
                result = conn.execute(sql)
                for row in result:
                    data_type = row['data_type']

                    # constraints from data type
                    if (data_type in ['character', 'character varying'] and
                            row['character_maximum_length']):
                        constraints['maxlength'] = \
                            row['character_maximum_length']
                    elif data_type in ['double precision', 'real']:
                        # NOTE: use text field with pattern for floats
                        constraints['pattern'] = '[0-9]+([\\.,][0-9]+)?'
                    elif data_type == 'numeric' and row['numeric_precision']:
                        step = pow(10, -row['numeric_scale'])
                        max_value = pow(
                            10, row['numeric_precision'] - row['numeric_scale']
                        ) - step
                        constraints['numeric_precision'] = \
                            row['numeric_precision']
                        constraints['numeric_scale'] = row['numeric_scale']
                        constraints['min'] = -max_value
                        constraints['max'] = max_value
                        constraints['step'] = step
                    elif data_type == 'smallint':
                        constraints['min'] = -32768
                        constraints['max'] = 32767
                    elif data_type == 'integer':
                        constraints['min'] = -2147483648
                        constraints['max'] = 2147483647
                    elif data_type == 'bigint':
                        constraints['min'] = -9223372036854775808
                        constraints['max'] = 9223372036854775807

                if attr not in fields:
                    meta['fields'][attr] = {}

                if data_type:
                    # add data type
                    meta['fields'][attr]['data_type'] = data_type
                else:
                    self.logger.warn(
                        "Could not find data type of column '%s' "
                        "of table '%s.%s'" % (attr, schema, table_name)
                    )

                if constraints:
                    if 'constraints' in meta['fields'][attr]:
                        # merge constraints from QGIS project
                        constraints.update(
                            meta['fields'][attr]['constraints']
                        )

                    # add constraints
                    meta['fields'][attr]['constraints'] = constraints

            # close database connection
            conn.close()

            attributes = meta.get('attributes')
            for field in upload_fields:
                target_field = field[0:len(field) - 8]
                attributes.remove(field)
                if target_field in meta['fields']:
                    meta['fields'][target_field]['constraints'] = {"fileextensions": meta['fields'][field].get('expression', "").split(",")}
                if field in meta['fields']:
                    del meta['fields'][field]

        except Exception as e:
            self.logger.error(
                "Error while querying attribute data types:\n\n%s" % e
            )
            if conn:
                conn.close()
            raise

    def collect_ui_forms(self, qwc_base_dir, edit_datasets):
        """ Collect UI form files from project

        :param str qwc_base_dir: The qwc base dir
        """
        gen = DnDFormGenerator(self.logger, qwc_base_dir)
        projectname = os.path.splitext(os.path.basename(self.qgs_path))[0]
        result = {}
        for maplayer in self.root.findall('.//maplayer'):

            if maplayer.find('shortname') is not None:
                layername = maplayer.find('shortname').text
            elif maplayer.find('layername') is None:
                continue
            else:
                layername = maplayer.find('layername').text

            if layername not in edit_datasets:
                # skip layers not in datasets
                continue

            editorlayout = maplayer.find('editorlayout')
            if editorlayout is None:
                continue

            uipath = None
            if editorlayout.text == "uifilelayout":
                editform = maplayer.find('editform')
                if editform is not None:
                    formpath = editform.text
                    if not os.path.isabs(formpath):
                        formpath = os.path.join(os.path.dirname(self.qgs_path), formpath)
                    outputdir = os.path.join(qwc_base_dir, 'assets', 'forms', 'autogen')
                    dest = os.path.join(outputdir, "%s_%s.ui" % (projectname, layername))
                    try:
                        os.makedirs(outputdir, exist_ok=True)
                        shutil.copy(formpath, dest)
                        self.logger.info("Copied form for layer %s_%s" % (projectname, layername))
                        uipath = ":/forms/autogen/%s_%s.ui?v=%d" % (projectname, layername, int(time.time()))
                    except Exception as e:
                        self.logger.warning("Failed to copy form for layer %s: %s" % (layername, str(e)))

            elif editorlayout.text == "tablayout" or editorlayout.text == "generatedlayout":
                uipath = gen.generate_form(maplayer, projectname, layername, self.root)

            if uipath:
                result[layername] = uipath

        return result
