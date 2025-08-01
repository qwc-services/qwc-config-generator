import re
from xml.etree import ElementTree

from sqlalchemy.sql import text as sql_text

class DnDFormGenerator:
    def __init__(self, logger, assets_dir, db_engine, project, shortnames, maplayer, metadata, generate_nested_nrel_forms):
        self.logger = logger
        self.assets_dir = assets_dir
        self.db_engine = db_engine
        self.project = project
        self.shortnames = shortnames
        self.maplayer = maplayer
        self.metadata = metadata
        self.generate_nested_nrel_forms = generate_nested_nrel_forms
        
    def generate_form(self, editorlayout):
        widget = self.__generate_form_widget(editorlayout)
        if widget is None:
            return None

        ui = ElementTree.Element("ui")
        ui.set("version", "4.0")
        ui.append(widget)
        return ElementTree.tostring(ui, 'utf-8')


    def __generate_form_widget(self, editorlayout):
        aliases = {}
        for entry in self.maplayer.find('aliases').findall('alias'):
            field = entry.get('field')
            alias = entry.get('name')
            aliases[field] = alias or field

        widget = ElementTree.Element("widget")
        widget.set("class", "QWidget")

        if editorlayout.text == "tablayout":
            attributeEditorForm = self.maplayer.find('attributeEditorForm')
            if attributeEditorForm is None:
                return None
            self.__add_tablayout_fields(widget, attributeEditorForm, aliases)
        elif editorlayout.text == "generatedlayout":
            self.__add_autolayout_fields(widget, aliases)
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

    def __create_editor_widget(self, field, prefix=""):
        editWidget = self.maplayer.find("fieldConfiguration/field[@name='%s']/editWidget" % field)
        if (
            editWidget is None
            or editWidget.get("type") == "Hidden" or editWidget.get("type") == "RelationReference"
        ):
            return None
        if not editWidget.get("type"):
            self.logger.warning("Warning: field '%s' has empty widget type" % field)
            return None
        editableField = self.maplayer.find("editable/field[@name='%s']" % field)
        editable = editableField is None or editableField.get("editable") == "1"
        constraintField = self.maplayer.find("constraints/constraint[@field='%s']" % field)
        required = constraintField is not None and constraintField.get("notnull_strength") == "1"
        if editWidget.get("type") == "CheckBox":
            # Don't translate NOT NULL constraint into required for checkboxes
            required = False

        widget = ElementTree.Element("widget")
        widget.set("name", prefix + field)
        self.__add_widget_property(widget, "readOnly", None, None, "false" if editable else "true", "property", "bool")
        self.__add_widget_property(widget, "required", None, None, "true" if required else "false", "property", "bool")

        # Compatibility with deprecated <filename>__upload convention
        uploadField = self.maplayer.find("expressionfields/field[@name='%s__upload']" % field)
        if uploadField is not None:
            widget.set("class", "QLineEdit")
            widget.set("name", "%s__upload" % (prefix + field))
            filterOpt = ",".join(map(lambda entry: "*" + entry, list(filter(bool, re.split(r"[\s,]", uploadField.get("expression", ""))))))
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
            optPrecision = editWidget.find("config/Option/Option[@name='Precision']")
            optStyle = editWidget.find("config/Option/Option[@name='Style']")
            className = "QDoubleSpinBox"
            if optStyle is not None and optStyle.get("value") == "Slider":
                className = "QSlider"
                self.__add_widget_property(widget, "orientation", None, None, "Qt::Horizontal", "property", "enum")
            widget.set("class", className)
            self.__add_widget_property(widget, "minimum", optMin, "value", "-2147483648")
            self.__add_widget_property(widget, "maximum", optMax, "value", "2147483647")
            self.__add_widget_property(widget, "singleStep", optStep, "value", "1")
            self.__add_widget_property(widget, "decimals", optPrecision, "value", "0")
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
                    if child is not None and child.get("type") != "invalid":
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
            with self.db_engine.db_engine(self.metadata['database']).connect() as conn:
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
            allowMulti = editWidget.find("config/Option/Option[@name='AllowMulti']").get('value')
            # Lookup shortname
            layer = self.shortnames.get(layer, layer)
            widget.set("name", "kvrel__{field}__{kvtable}__{keyfield}__{valuefield}".format(
                field=prefix + field, kvtable=layer, keyfield=key, valuefield=value
            ))
            widget.set("allowMulti", allowMulti)
            return widget
        elif editWidget.get("type") == "ExternalResource":
            widget.set("class", "QLineEdit")
            widget.set("name", "%s__upload" % (prefix + field))
            filterOpt = editWidget.find("config/Option/Option[@name='FileWidgetFilter']")
            self.__add_widget_property(widget, "text", filterOpt, "value")
            return widget
        else:
            self.logger.warning("Warning: field %s has unhandled widget type %s" % (field, editWidget.get("type")))
            return None

    def __create_relation_widget(self, relation, showlabel, label=""):
        if not relation:
            return None

        referencingLayer = self.project.find(".//maplayer[id='%s']" % relation.get("referencingLayer"))
        fieldRef = relation.find("./fieldRef")
        if referencingLayer is None or fieldRef is None:
            return None

        if referencingLayer.find('shortname') is not None:
            referencingLayerName = referencingLayer.find("shortname").text
        else:
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

        if self.generate_nested_nrel_forms:

            # Display field for the button:
            # - Try the layer displayfield if it is a simple field
            # - Try the primary key from referencing layer
            # - Fall back to 'id'
            displayField = referencingLayer.find("previewExpression").text
            datasource = referencingLayer.find("datasource").text

            displayFieldMatch = re.search(r'^"(\w+)"$', displayField)
            pkMatch = re.search(r"key='(.+?)' \w+=", datasource)

            if displayFieldMatch:
                buttonLabelField = displayFieldMatch.group(1)
            elif pkMatch:
                buttonLabelField = pkMatch.group(1)
            else:
                buttonLabelField = 'id'

            buttonWidget = ElementTree.Element("widget")
            buttonWidget.set("class", "QPushButton")
            buttonWidget.set("name", "featurelink__%s__%s__%s" % (referencingLayerName, referencingLayerName, buttonLabelField))

            buttonItem = ElementTree.Element("item")
            buttonItem.set("row", "0")
            buttonItem.set("column", "0")
            buttonItem.append(buttonWidget)

            layout.append(buttonItem)

        else:
            fields = referencingLayer.findall("fieldConfiguration/field")
            col = 0
            for field in fields:

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

    def __add_tablayout_fields(self, parent, container, aliases):

        layout = ElementTree.Element("layout")
        layout.set("class", "QGridLayout")
        parent.append(layout)

        tabWidget = None
        row = 0
        col = 0
        ncols = int(container.get('columnCount', '1'))

        for child in container:
            added = False
            if child.tag == "attributeEditorContainer":

                if child.get('type') == "Tab":
                    if not tabWidget:
                        item = ElementTree.Element("item")
                        item.set("row", str(row))
                        item.set("column", str(col))
                        item.set("colspan", "2")
                        layout.append(item)
                        added = True
                        tabWidget = ElementTree.Element("widget")
                        tabWidget.set("class", "QTabWidget")
                        item.append(tabWidget)

                    widget = ElementTree.Element("widget")
                    widget.set("class", "QWidget")
                    visibilityExpression = child.get("visibilityExpression") if child.get("visibilityExpressionEnabled", "0") == "1" else ""
                    self.__add_widget_property(widget, "visibilityExpression", None, None, visibilityExpression)
                    self.__add_widget_property(widget, "title", child, "name", "", "attribute")
                    tabWidget.append(widget)

                    self.__add_tablayout_fields(widget, child, aliases)
                elif child.get('type') == "GroupBox":
                    item = ElementTree.Element("item")
                    item.set("row", str(row))
                    item.set("column", str(col))
                    item.set("colspan", "2")
                    layout.append(item)
                    added = True
                    tabWidget = None

                    widget = ElementTree.Element("widget")
                    if child.get('showLabel') == "1":
                        widget.set("class", "QGroupBox")
                        self.__add_widget_property(widget, "title", child, "name")
                        self.__add_label_style_properties(widget, child.find("labelStyle"))
                    else:
                        widget.set("class", "QFrame")
                    visibilityExpression = child.get("visibilityExpression") if child.get("visibilityExpressionEnabled", "0") == "1" else ""
                    self.__add_widget_property(widget, "visibilityExpression", None, None, visibilityExpression)
                    item.append(widget)

                    self.__add_tablayout_fields(widget, child, aliases)
            elif child.tag == "attributeEditorField":
                tabWidget = None

                editorWidget = self.__create_editor_widget(child.get("name"))
                if editorWidget is None:
                    continue

                editorItem = ElementTree.Element("item")
                editorItem.set("row", str(row))
                editorItem.set("column", str(col + 1))
                editorItem.append(editorWidget)
                layout.append(editorItem)
                added = True

                if child.get("showLabel") == "1":
                    labelItem = ElementTree.Element("item")
                    labelItem.set("row", str(row))
                    labelItem.set("column", str(col))
                    layout.append(labelItem)

                    labelWidget = ElementTree.Element("widget")
                    labelWidget.set("class", "QLabel")
                    label = aliases.get(child.get("name"), child.get("name"))
                    self.__add_widget_property(labelWidget, "text", None, None, label)
                    self.__add_label_style_properties(labelWidget, child.find("labelStyle"))
                    labelItem.append(labelWidget)
                else:
                    editorItem.set("column", str(col))
                    editorItem.set("colspan", "2")
            elif child.tag == "attributeEditorRelation":
                tabWidget = None

                relation = self.project.find(".//relations/relation[@id='%s']" % child.get("relation"))
                relationWidget = self.__create_relation_widget(relation, child.get("showLabel") == "1", child.get("label"))
                if relationWidget is None:
                    continue

                relationItem = ElementTree.Element("item")
                relationItem.set("row", str(row))
                relationItem.set("column", str(col))
                relationItem.set("colspan", "2")
                relationItem.append(relationWidget)
                layout.append(relationItem)
                added = True

            if added:
                col += 2
                if col >= 2 * ncols:
                    col = 0
                    row += 1

    def __add_autolayout_fields(self, parent, aliases):
        fields = self.maplayer.findall("fieldConfiguration/field")
        layout = ElementTree.Element("layout")
        layout.set("class", "QGridLayout")
        parent.append(layout)

        row = 0

        for field in fields:
            editorWidget = self.__create_editor_widget(field.get("name"))
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

        layerid = self.maplayer.find('id').text
        for relation in self.project.findall(".//relations/relation"):
            referencingLayer = self.project.find(".//maplayer[id='%s']" % relation.get("referencingLayer"))
            fieldRef = relation.find("./fieldRef")
            if relation.get("referencedLayer") != layerid or referencingLayer is None or fieldRef is None:
                continue

            widget = self.__create_relation_widget(relation, True)
            if widget is None:
                continue

            item = ElementTree.Element("item")
            item.set("row", str(row))
            item.set("column", str(0))
            item.set("colspan", str(2))
            item.append(widget)

            layout.append(item)
            row += 1

    def __add_label_style_properties(self, widget, labelStyle):
        if labelStyle is None:
            return
        added = False
        font = ElementTree.Element("font")
        if labelStyle.get("overrideLabelFont") == "1":
            labelFont = labelStyle.find("labelFont")
            if labelFont is not None:
                propMap = {"bold": "bold", "italic": "italic", "underline": "underline", "strikethrough": "strikeout"}
                for prop, elName in propMap.items():
                    if labelFont.get(prop) == "1":
                        propEl = ElementTree.Element(elName)
                        propEl.text = "true"
                        font.append(propEl)
                        added = True
        if added:
            prop = ElementTree.Element("property")
            prop.set("name", "font")
            prop.append(font)
            widget.append(prop)
