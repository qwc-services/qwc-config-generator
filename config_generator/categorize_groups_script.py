import os

from qgis.core import *


def convert_layers(layers, project_path, override_project=False):
    """
    This method iterates over the layers list and replaces all QGIS layers
    with a QGIS group that has the same name as the layer.
    The new group contains all rules or categories, that were defined
    in the layer, as QGIS layers.

    Per deufault, the modified project will be saved in a new file.
    If you don't want to create a new file, then you have to set the parameter
    `override_project` to true. This would override the original project.

    :param list layer: This list should contain all layer names
        (saved as strings)
    :param string project_path: Absolute path to the project file(*.qgs file)
    :param boolean override_project: If this is set to True, then the original
        project will be overriden.
    """

    layer_order = []
    project_instance = QgsProject.instance()
    layer_tree_root = project_instance.layerTreeRoot()

    if project_instance.read(project_path) is False:
        print("There was a problem with reading the project file.")
        return

    for _layer in layer_tree_root.children():
        layer_order.append(_layer.name())

    if layers:
        save_custom_property(layers, project_instance)
    else:
        layers = []

        for layer in project_instance.mapLayers().values():
            if layer.customProperty(
                    "convert_categorized_layer", "false").lower() == "true":
                layers.append(layer.name())

    if not layers:
        return project_path

    for layer_name in layers:
        # Search for layer by name
        base_layer = project_instance.layerStore().mapLayersByName(layer_name)[0]
        if not base_layer.isValid():
            continue

        # This is the layer that will be splitted into multiple layers
        base_layer_renderer = base_layer.renderer()

        if base_layer.name() not in layer_order:
            continue

        group_index = layer_order.index(base_layer.name())
        group = layer_tree_root.insertGroup(group_index, base_layer.name())

        if isinstance(base_layer_renderer, QgsCategorizedSymbolRenderer):
            categories_list = base_layer_renderer.categories()
        elif isinstance(base_layer_renderer, QgsGraduatedSymbolRenderer):
            categories_list = base_layer_renderer.legendSymbolItems()
        elif isinstance(base_layer_renderer, QgsRuleBasedRenderer):
            categories_list = base_layer_renderer.rootRule().children()
        else:
            categories_list = []

        create_categorized_layer(
            categories_list, base_layer,
            project_instance, group)
        project_instance.removeMapLayer(base_layer)

    if override_project is True:
        save_project(project_instance)
        project_path = project_instance.absoluteFilePath()
    else:
        file_name, extension = os.path.splitext(
            project_instance.absoluteFilePath())
        project_path = file_name + "_categorized" + extension

        save_project(project_instance, project_path)

    return project_path


def save_custom_property(layers, project_instance):
    for layer in project_instance.mapLayers().values():
        if layer.name() in layers:
            layer.setCustomProperty("convert_categorized_layer", "true")
        else:
            layer.removeCustomProperty("convert_categorized_layer")
    save_project(project_instance)


def create_categorized_layer(categories_list, base_layer,
                             project_instance, group):

    for category in categories_list:
        category_layer = base_layer.clone()
        category_layer.setTitle(category.label())
        category_layer.setName(category.label())
        category_layer.setShortName(category.label())

        new_renderer = QgsRuleBasedRenderer.convertFromRenderer(
            base_layer.renderer())

        category_layer.setRenderer(new_renderer)
        root_rule = category_layer.renderer().rootRule()
        for rule in root_rule.children():
            if rule.label() != category.label():
                root_rule.removeChild(rule)

        project_instance.addMapLayer(category_layer, False)
        group.addLayer(category_layer)


def save_project(project_instance, new_project_path=None):

    if new_project_path is None:
        project_instance.write()
    else:
        project_instance.write(new_project_path)
