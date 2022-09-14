import os
import time
import re
from xml.etree import ElementTree

from sqlalchemy.sql import text as sql_text
from qwc_services_core.database import DatabaseEngine

class DnDFormGenerator:
    def __init__(self, logger, qwc_base_dir, metadata):
        self.logger = logger
        self.qwc_base_dir = qwc_base_dir
        self.db_engine = DatabaseEngine()
        self.metadata = metadata
        
    def generate_form(self, maplayer, projectname, layername, project):
        widget = self.__generate_form_widget(maplayer, project)
        if not widget:
            return None

        ui = ElementTree.Element("ui")
        ui.set("version", "4.0")
        ui.append(widget)

        text = ElementTree.tostring(ui, 'utf-8')
        outputdir = os.path.join(self.qwc_base_dir, 'assets', 'forms', 'autogen')
        try:
            os.makedirs(outputdir, exist_ok=True)
            outputfile = os.path.join(outputdir, "%s_%s.ui" % (projectname, layername))
            with open(outputfile, "wb") as fh:
                fh.write(text)
                self.logger.info("Wrote %s_%s.ui" % (projectname, layername))
        except Exception as e:
            self.logger.warning("Failed to write form for layer %s: %s" % (layername, str(e)))
            return None

        return ":/forms/autogen/%s_%s.ui?v=%d" % (projectname, layername, int(time.time()))

    def __generate_form_widget(self, maplayer, project):
        editorlayout = maplayer.find('editorlayout')
        layerid = maplayer.find('id')
        if editorlayout is None or layerid is None:
            return None

        aliases = {}
        for entry in maplayer.find('aliases').findall('alias'):
            field = entry.get('field')
            alias = entry.get('name')
            aliases[field] = alias or field

        widget = ElementTree.Element("widget")
        widget.set("class", "QWidget")

        if editorlayout.text == "tablayout":
            attributeEditorForm = maplayer.find('attributeEditorForm')
            if not attributeEditorForm:
                return None
            self.__add_tablayout_fields(maplayer, project, widget, attributeEditorForm, aliases)
        elif editorlayout.text == "generatedlayout":
            self.__add_autolayout_fields(maplayer, project, widget, aliases)
        else:
            return None

        return widget

    def __add_widget_property(self, widget, name, valueEl, key, defaultValue="", propClass="property", valueClass="string"):
        property = ElementTree.Element(propClass)
        property.set("name", name)
        string = ElementTree.Element(valueClass)
        if valueEl is not None:
            string.text = str(valueEl.get(key))
        else:
            string.text = str(defaultValue)
        property.append(string)
        widget.append(property)

    def __create_editor_widget(self, maplayer, field, prefix=""):
        editWidget = maplayer.find("fieldConfiguration/field[@name='%s']/editWidget" % field)
        if (
            editWidget is None
            or editWidget.get("type") == "Hidden" or editWidget.get("type") == "RelationReference"
            or not editWidget.get("type")
        ):
            return None
        editableField = maplayer.find("editable/field[@name='%s']" % field)
        editable = editableField is None or editableField.get("editable") == "1"
        constraintField = maplayer.find("constraints/constraint[@field='%s']" % field)
        required = constraintField is not None and constraintField.get("notnull_strength") == "1"
        conn = self.db_engine.db_engine(self.metadata['database']).connect()

        widget = ElementTree.Element("widget")
        widget.set("name", prefix + field)
        self.__add_widget_property(widget, "readOnly", None, None, "false" if editable else "true", "property", "bool")
        self.__add_widget_property(widget, "required", None, None, "true" if required else "false", "property", "bool")

        # Compatibility with deprecated <filename>__upload convention
        uploadField = maplayer.find("expressionfields/field[@name='%s__upload']" % field)
        if uploadField is not None:
            widget.set("class", "QLineEdit")
            widget.set("name", "%s__upload" % (prefix + field))
            filterOpt = ",".join(map(lambda entry: "*" + entry, uploadField.get("expression", "").split(",")))
            self.__add_widget_property(widget, "text", None, "value", filterOpt)
            return widget

        if editWidget.get("type") == "TextEdit":
            optMultiline = editWidget.find("config/Option/Option[@name='IsMultiline']")
            className = "QLineEdit"
            if optMultiline is not None and optMultiline.get("value") == "true":
                className = "QTextEdit"
            widget.set("class", className)
            return widget
        elif editWidget.get("type") == "Range":
            optMin = editWidget.find("config/Option/Option[@name='Min']")
            optMax = editWidget.find("config/Option/Option[@name='Max']")
            optStep = editWidget.find("config/Option/Option[@name='Step']")
            optStyle = editWidget.find("config/Option/Option[@name='Style']")
            className = "QSpinBox"
            if optStyle is not None and optStyle.get("value") == "Slider":
                className = "QSlider"
                self.__add_widget_property(widget, "orientation", None, None, "Qt::Horizontal", "property", "enum")
            widget.set("class", className)
            self.__add_widget_property(widget, "minimum", optMin, "value", "-2147483648")
            self.__add_widget_property(widget, "maximum", optMax, "value", "2147483647")
            self.__add_widget_property(widget, "singleStep", optStep, "value", "1")
            return widget
        elif editWidget.get("type") == "DateTime":
            fieldFormatEl = editWidget.find("config/Option/Option[@name='field_format']")
            fieldFormat = fieldFormatEl.get("value") if fieldFormatEl is not None else ""
            optFormat = editWidget.find("config/Option/Option[@name='display_format']")
            if fieldFormat == "HH:mm:ss":
                widget.set("class", "QTimeEdit")
            elif fieldFormat == "yyyy-MM-dd":
                widget.set("class", "QDateEdit")
            else:
                widget.set("class", "QDateTimeEdit")
            self.__add_widget_property(widget, "displayFormat", optFormat, "value", "yyyy-MM-dd")
            return widget
        elif editWidget.get("type") == "CheckBox":
            widget.set("class", "QCheckBox")
            return widget
        elif editWidget.get("type") == "ValueMap":
            optMap = editWidget.findall("config/Option/Option[@name='map']/Option")
            widget.set("class", "QComboBox")
            if optMap is not None:
                for opt in optMap:
                    child = opt.find("Option")
                    if child is not None:
                        item = ElementTree.Element("item")
                        self.__add_widget_property(item, "value", child, "value")
                        self.__add_widget_property(item, "text", child, "name")
                        widget.append(item)
            return widget
        elif editWidget.get("type") == "Enumeration":
            values = {}
            sql =  sql_text(("""
            SELECT udt_schema::text ||'.'|| udt_name::text as defined_type
            FROM information_schema.columns
            WHERE table_schema = '{schema}' AND column_name = '{column}' and table_name = '{table}'
            GROUP BY defined_type
            LIMIT 1;
        """).format(schema = self.metadata['schema'], table = self.metadata['table_name'], column = field))
            result = conn.execute(sql)
            for row in result:
                defined_type = row['defined_type']
            try : 
                widget.set("class", "QComboBox")
                sql = sql_text("SELECT unnest(enum_range(NULL:: %s))::text as values ;" % defined_type)
                result = conn.execute(sql)
                for row in result : 
                    values['value'] = row['values']
                    values['name'] = row['values']
                    item = ElementTree.Element("item")
                    self.__add_widget_property(item, "value", values, "value")
                    self.__add_widget_property(item, "text", values, "name")
                    widget.append(item)
            except Exception: 
                widget.set("class", "QLineEdit")
                self.logger.warning("Failed to add Enumeration widget in %s for %s" % (self.metadata['table_name'], field))
                pass
            return widget
        elif editWidget.get("type") == "ValueRelation":
            widget.set("class", "QComboBox")
            key = editWidget.find("config/Option/Option[@name='Key']").get('value')
            value = editWidget.find("config/Option/Option[@name='Value']").get('value')
            layer = editWidget.find("config/Option/Option[@name='LayerName']").get('value')
            widget.set("name", "kvrel__{field}__{kvtable}__{keyfield}__{valuefield}".format(
                field=prefix + field, kvtable=layer, keyfield=key, valuefield=value
            ))
            return widget
        elif editWidget.get("type") == "ExternalResource":
            widget.set("class", "QLineEdit")
            widget.set("name", "%s__upload" % (prefix + field))
            filterOpt = editWidget.find("config/Option/Option[@name='FileWidgetFilter']")
            self.__add_widget_property(widget, "text", filterOpt, "value")
            return widget
        else:
            self.logger.warning("Warning: unhandled widget type %s" % editWidget.get("type"))
            return None

    def __create_relation_widget(self, project, relation, showlabel, label=""):
        if not relation:
            return None

        referencingLayer = project.find(".//maplayer[id='%s']" % relation.get("referencingLayer"))
        fieldRef = relation.find("./fieldRef")
        if referencingLayer is None or fieldRef is None:
            return None

        referencingLayerName = referencingLayer.find("layername").text
        fkField = fieldRef.get("referencingField")

        aliases = {}
        for entry in referencingLayer.find('aliases').findall('alias'):
            field = entry.get('field')
            alias = entry.get('name')
            aliases[field] = alias or field

        groupBox = ElementTree.Element("widget")
        groupBox.set("class", "QGroupBox")
        groupBox.set("name", "nrel__%s__%s" % (referencingLayerName, fkField))
        if showlabel:
            if label:
                self.__add_widget_property(groupBox, "title", None, None, label)
            else:
                self.__add_widget_property(groupBox, "title", relation, "name")

        layout = ElementTree.Element("layout")
        layout.set("class", "QGridLayout")

        fields = referencingLayer.findall("fieldConfiguration/field")
        col = 0
        for field in fields:
            # Skip expression fields
            if referencingLayer.find("expressionfields/field[@name='%s']" % field.get("name")) is not None:
                continue

            # Skip foreign key field
            if field.get("name") == fkField:
                continue

            editorWidget = self.__create_editor_widget(referencingLayer, field.get("name"), referencingLayerName + "__")
            if editorWidget is None:
                continue

            labelWidget = ElementTree.Element("widget")
            labelWidget.set("class", "QLabel")
            labelWidget.set("name", "header__" + field.get("name"))
            label = aliases.get(field.get("name"), field.get("name"))
            self.__add_widget_property(labelWidget, "text", None, None, label)

            labelItem = ElementTree.Element("item")
            labelItem.set("row", "0")
            labelItem.set("column", str(col))
            labelItem.append(labelWidget)

            editorItem = ElementTree.Element("item")
            editorItem.set("row", "1")
            editorItem.set("column", str(col))
            editorItem.append(editorWidget)

            layout.append(labelItem)
            layout.append(editorItem)

            col += 1

        groupBox.append(layout)
        return groupBox

    def __add_tablayout_fields(self, maplayer, project, parent, container, aliases):

        layout = ElementTree.Element("layout")
        layout.set("class", "QGridLayout")
        parent.append(layout)

        tabWidget = None
        row = 0
        col = 0
        ncols = int(container.get('columnCount', '1'))

        for child in container:
            if child.tag == "attributeEditorContainer":
                item = ElementTree.Element("item")
                item.set("row", str(row))
                item.set("column", str(col))
                item.set("colspan", "2")
                layout.append(item)

                if child.get('groupBox') == "0":
                    if not tabWidget:
                        tabWidget = ElementTree.Element("widget")
                        tabWidget.set("class", "QTabWidget")
                        item.append(tabWidget)

                    widget = ElementTree.Element("widget")
                    widget.set("class", "QWidget")
                    self.__add_widget_property(widget, "title", child, "name", "", "attribute")
                    tabWidget.append(widget)

                    self.__add_tablayout_fields(maplayer, project, widget, child, aliases)
                else:
                    tabWidget = None

                    widget = ElementTree.Element("widget")
                    if child.get('showLabel') == "1":
                        widget.set("class", "QGroupBox")
                        self.__add_widget_property(widget, "title", child, "name")
                    else:
                        widget.set("class", "QFrame")
                    item.append(widget)

                    self.__add_tablayout_fields(maplayer, project, widget, child, aliases)
            elif child.tag == "attributeEditorField":
                tabWidget = None

                editorWidget = self.__create_editor_widget(maplayer, child.get("name"))
                if editorWidget is None:
                    continue

                editorItem = ElementTree.Element("item")
                editorItem.set("row", str(row))
                editorItem.set("column", str(col + 1))
                editorItem.append(editorWidget)
                layout.append(editorItem)

                if child.get("showLabel") == "1":
                    labelItem = ElementTree.Element("item")
                    labelItem.set("row", str(row))
                    labelItem.set("column", str(col))
                    layout.append(labelItem)

                    labelWidget = ElementTree.Element("widget")
                    labelWidget.set("class", "QLabel")
                    label = aliases.get(child.get("name"), child.get("name"))
                    self.__add_widget_property(labelWidget, "text", None, None, label)
                    labelItem.append(labelWidget)
            elif child.tag == "attributeEditorRelation":
                tabWidget = None

                relation = project.find(".//relations/relation[@id='%s']" % child.get("relation"))
                relationWidget = self.__create_relation_widget(project, relation, child.get("showLabel") == "1", child.get("label"))
                if relationWidget is None:
                    continue

                relationItem = ElementTree.Element("item")
                relationItem.set("row", str(row))
                relationItem.set("column", str(col))
                relationItem.set("colspan", "2")
                relationItem.append(relationWidget)
                layout.append(relationItem)

            col += 2
            if col >= 2 * ncols:
                col = 0
                row += 1

        item = ElementTree.Element("item")
        item.set("row", str(row + 1))
        item.set("column", "0")
        item.set("colspan", str(2 * ncols))
        layout.append(item)

        spacer = ElementTree.Element("spacer")
        self.__add_widget_property(spacer, "orientation", None, None, "Qt::Vertical", "property", "enum")
        item.append(spacer)

    def __add_autolayout_fields(self, maplayer, project, parent, aliases):
        fields = maplayer.findall("fieldConfiguration/field")
        layout = ElementTree.Element("layout")
        layout.set("class", "QGridLayout")
        parent.append(layout)

        row = 0

        for field in fields:
            # Skip expression fields
            if maplayer.find("expressionfields/field[@name='%s']" % field.get("name")) is not None:
                continue

            editorWidget = self.__create_editor_widget(maplayer, field.get("name"))
            if editorWidget is None:
                continue

            labelWidget = ElementTree.Element("widget")
            labelWidget.set("class", "QLabel")
            label = aliases.get(field.get("name"), field.get("name"))
            self.__add_widget_property(labelWidget, "text", None, None, label)

            labelItem = ElementTree.Element("item")
            labelItem.set("row", str(row))
            labelItem.set("column", str(0))
            labelItem.append(labelWidget)

            editorItem = ElementTree.Element("item")
            editorItem.set("row", str(row))
            editorItem.set("column", str(1))
            editorItem.append(editorWidget)

            layout.append(labelItem)
            layout.append(editorItem)

            row += 1

        layerid = maplayer.find('id').text
        for relation in project.findall(".//relations/relation"):
            referencingLayer = project.find(".//maplayer[id='%s']" % relation.get("referencingLayer"))
            fieldRef = relation.find("./fieldRef")
            if relation.get("referencedLayer") != layerid or referencingLayer is None or fieldRef is None:
                continue

            widget = self.__create_relation_widget(project, relation, True)
            if not widget:
                continue

            item = ElementTree.Element("item")
            item.set("row", str(row))
            item.set("column", str(0))
            item.set("colspan", str(2))
            item.append(widget)

            layout.append(item)
            row += 1

        item = ElementTree.Element("item")
        item.set("row", str(row + 1))
        item.set("column", "0")
        item.set("colspan", str(2))
        layout.append(item)

        spacer = ElementTree.Element("spacer")
        self.__add_widget_property(spacer, "orientation", None, None, "Qt::Vertical", "property", "enum")
        item.append(spacer)
