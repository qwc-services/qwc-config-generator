from collections import OrderedDict
import os
import re
from xml.etree import ElementTree

from sqlalchemy.sql import text as sql_text

from qwc_services_core.database import DatabaseEngine


class QGSReader:
    """QGSReader class

    Read QGIS 2.18 or 3.x projects and extract data for QWC config.
    """

    def __init__(self, logger, qgs_resources_path):
        """Constructor

        :param Logger logger: Application logger
        :param str qgs_resources_path: Path to qgis server data dir
        """
        self.logger = logger
        self.root = None
        self.qgis_version = 0

        self.qgs_resources_path = qgs_resources_path

        self.db_engine = DatabaseEngine()

    def read(self, qgs_path):
        """Read QGIS project file and return True on success.

        :param str qgs_path: QGS name with optional path relative to
                             QGIS server data dir
        """
        qgs_file = "%s.qgs" % qgs_path
        qgs_path = os.path.join(self.qgs_resources_path, qgs_file)
        if not os.path.exists(qgs_path):
            self.logger.warn("Could not find QGS file '%s'" % qgs_path)
            return False

        try:
            tree = ElementTree.parse(qgs_path)
            self.root = tree.getroot()
            if self.root.tag != 'qgis':
                self.logger.warn("'%s' is not a QGS file" % qgs_path)
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
            else:
                maplayer_name = maplayer.find('layername').text
            if maplayer_name == layer_name:
                provider = maplayer.find('provider').text
                if provider != 'postgres':
                    self.logger.info("Not a PostgreSQL layer")
                    continue

                datasource = maplayer.find('datasource').text
                config['database'] = self.db_connection(datasource)
                config.update(self.table_metadata(datasource))
                config.update(self.attributes_metadata(maplayer))

                break

        return config

    def db_connection(self, datasource):
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
                connection_string += "%s:%s@" % (user, password)

            connection_string += "%s:%s/%s" % (host, port, dbname)

        return connection_string

    def table_metadata(self, datasource):
        """Parse QGIS datasource URI and return table metadata.

        :param str datasource: QGIS datasource URI
        """
        # NOTE: use ordered keys
        metadata = OrderedDict()

        # parse schema, table and geometry column
        m = re.search(r'table="(.+?)" \((\w+)\)', datasource)
        if m is not None:
            table = m.group(1)
            parts = table.split('"."')
            metadata['schema'] = parts[0]
            metadata['table_name'] = parts[1]

            metadata['geometry_column'] = m.group(2)
        else:
            m = re.search(r'table="(.+?)"."(.+?)"', datasource)
            if m is not None:
                metadata['schema'] = m.group(1)
                metadata['table_name'] = m.group(2)

        m = re.search(r"key='(.+?)' \w+=", datasource)
        if m is not None:
            metadata['primary_key'] = m.group(1)

        m = re.search(r"type=([\w.]+)", datasource)
        if m is not None:
            metadata['geometry_type'] = m.group(1).upper()

        m = re.search(r"srid=([\d.]+)", datasource)
        if m is not None:
            metadata['srid'] = int(m.group(1))

        return metadata

    def attributes_metadata(self, maplayer):
        """Collect layer attributes.

        :param Element maplayer: QGS maplayer node
        """
        attributes = []
        # NOTE: use ordered keys
        fields = OrderedDict()

        # Get fieldnames from attributeEditorForm if possible (to preserve order), otherwise from aliases
        fieldnames = []

        formfields = maplayer.find('attributeEditorForm')
        if formfields:
            for formfield in formfields.findall('attributeEditorField'):
                fieldnames.append(formfield.get('name'))
        else:
            aliases = maplayer.find('aliases')
            for alias in aliases.findall('alias'):
                fieldnames.append(alias.get('field'))

        for field in fieldnames:

            if self.field_hidden(maplayer, field):
                # skip hidden fields
                continue

            attributes.append(field)
            # NOTE: use ordered keys
            fields[field] = OrderedDict()

            # get alias
            alias = maplayer.find("aliases/alias[@field='%s']" % field)
            if alias is not None and alias.get('name'):
                fields[field]['alias'] = alias.get('name')

            # get any constraints from edit widgets
            constraints = self.edit_widget_constraints(maplayer, field)
            if constraints:
                fields[field]['constraints'] = constraints

            expressionfields_field = maplayer.find(
                "expressionfields/field[@name='%s']" % field
            )
            if expressionfields_field is not None:
                fields[field]['expression'] = expressionfields_field.get('expression').lstrip("'").rstrip("'")

        return {
            'attributes': attributes,
            'fields': fields
        }

    def edit_widget_constraints(self, maplayer, field):
        """Get any constraints from edit widget config.

        :param Element maplayer: QGS maplayer node
        :param str field: Field name
        """
        if self.qgis_version > 30000:
            return self.edit_widget_constraints_v3(maplayer, field)
        else:
            return self.edit_widget_constraints_v2(maplayer, field)

    def edit_widget_constraints_v2(self, maplayer, field):
        """Get any constraints from edit widget config (QGIS 2.18).

        :param Element maplayer: QGS maplayer node
        :param str field: Field name
        """
        # NOTE: use ordered keys
        constraints = OrderedDict()

        edittype = maplayer.find("edittypes/edittype[@name='%s']" % field)
        widget_config = edittype.find('widgetv2config')
        if widget_config.get('fieldEditable') == '0':
            constraints['readonly'] = True

        if (not constraints.get('readonly', False) and
                widget_config.get('notNull') == '1'):
            constraints['required'] = True

        constraint_desc = widget_config.get('constraintDescription', '')
        if len(constraint_desc) > 0:
            constraints['placeholder'] = constraint_desc

        if edittype.get('widgetv2type') == 'Range':
            constraints['min'] = self.parse_number(widget_config.get('Min'))
            constraints['max'] = self.parse_number(widget_config.get('Max'))
            constraints['step'] = self.parse_number(widget_config.get('Step'))
        elif edittype.get('widgetv2type') == 'ValueMap':
            values = []
            for value in widget_config.findall('value'):
                # NOTE: use ordered keys
                value_item = OrderedDict()
                value_item['label'] = value.get('key')
                value_item['value'] = value.get('value')
                values.append(value_item)

            if values:
                constraints['values'] = values

        return constraints

    def edit_widget_constraints_v3(self, maplayer, field):
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
            constraints['readonly'] = True

        if not constraints.get('readonly', False):
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
            constraints['min'] = self.parse_number(
                min_option.get('value')) if min_option else -2147483648
            constraints['max'] = self.parse_number(
                max_option.get('value')) if max_option else 2147483647
            constraints['step'] = self.parse_number(
                step_option.get('value')) if step_option else 1
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

        return constraints

    def field_hidden(self, maplayer, field):
        """Return whether field is hidden.

        :param Element maplayer: QGS maplayer node
        :param str field: Field name
        """
        if self.qgis_version > 30000:
            edit_widget = maplayer.find(
                "fieldConfiguration/field[@name='%s']/editWidget" % field
            )
            return edit_widget.get('type') == 'Hidden'
        else:
            edittype = maplayer.find("edittypes/edittype[@name='%s']" % field)
            return edittype.get('widgetv2type') == 'Hidden'

    def parse_number(self, value):
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

    def lookup_attribute_data_types(self, meta):
        """Query column data types from GeoDB and add them to table metadata.

        :param obj meta: Table metadata
        """
        conn = None
        upload_fields = []
        try:
            connection_string = meta.get('database')
            schema = meta.get('schema')
            table_name = meta.get('table_name')

            # connect to GeoDB
            geo_db = self.db_engine.db_engine(connection_string)
            conn = geo_db.connect()

            for attr in meta.get('attributes'):
                # upload field
                if attr.endswith("__upload"):
                    upload_fields.append(attr)
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

                if attr not in meta.get('fields'):
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
                    meta['fields'][target_field]['data_type'] = 'file'
                    meta['fields'][target_field]['constraints'] = {"accept": meta['fields'][field].get('expression', "")}
                if field in meta['fields']:
                    del meta['fields'][field]

        except Exception as e:
            self.logger.error(
                "Error while querying attribute data types:\n\n%s" % e
            )
            if conn:
                conn.close()
            raise
