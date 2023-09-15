import os
import glob
import shutil
from qgis.core import *


def get_prefix_path():
    return os.environ.get("QGIS_APPLICATION_PREFIX_PATH", "/usr")


# Load QGIS providers (will be needed for the categozize groups script)
# https://gis.stackexchange.com/questions/263852/using-initqgis-on-headless-installation-of-qgis-3
os.environ["QT_QPA_PLATFORM"] = "offscreen"
QgsApplication.setPrefixPath(get_prefix_path(), True)
qgsApp = QgsApplication([], False)
qgsApp.initQgis()


def split_categorized_layers(src_path, dest_path=None):
    """
    This method replaces all QGIS layers
    with a QGIS group that has the same name as the layer.
    The new group contains all rules or categories, that were defined
    in the layer, as QGIS layers.

    :param string src_path: Absolute path to the project file(*.qgs file)
    :param string dest_path: Absolute path to the destination project
    """

    layer_order = []
    layers = []
    project_instance = QgsProject.instance()
    layer_tree_root = project_instance.layerTreeRoot()

    if project_instance.read(src_path) is False:
        print("There was a problem with reading the project file.")
        return None

    for _layer in layer_tree_root.children():
        layer_order.append(_layer.name())

    for layer in project_instance.mapLayers().values():
        context = QgsExpressionContextUtils.layerScope(layer)
        if context.hasVariable("convert_categorized_layer") and context.variable(
                "convert_categorized_layer").lower() == "true":
            layers.append(layer.name())

    if not layers:
        return src_path

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

    # Create new file name to not overide the old project
    file_name, extension = os.path.splitext(src_path)
    categorized_project_path = file_name + "_categorized" + extension
    project_instance.write(categorized_project_path)

    if dest_path is not None:

        # Specify destination directory
        if os.path.isdir(dest_path):
            dest_path_dir = dest_path
        else:
            dest_path_dir = os.path.dirname(dest_path)

        for file in glob.glob(os.path.splitext(categorized_project_path)[0] + "*"):
            # Specify destination file name
            if os.path.isdir(dest_path):
                # dest_path is only a directory so we don't have to change the file name
                dest_file_name = os.path.basename(file)
            else:
                # dest_path is a file that means we have to rename the project file
                # This is done by taking the current project file name and replacing
                # everything before our own "_categorized" infix with the new file name
                file_name, extension = os.path.splitext(os.path.basename(file))
                dest_file_name = (
                    os.path.splitext(os.path.basename(dest_path))[0]
                    + "_categorized"
                    + file_name.split("_categorized")[1]
                    + extension
                )

            shutil.move(file, os.path.join(dest_path_dir, dest_file_name))

    return dest_path


def create_categorized_layer(categories_list, base_layer,
                             project_instance, group):

    for category in categories_list:
        category_layer = base_layer.clone()
        category_layer.setTitle(category.label())
        category_layer.setName(category.label())
        category_layer.setShortName(category.label())
        category_layer.setCrs(base_layer.crs())

        new_renderer = QgsRuleBasedRenderer.convertFromRenderer(
            base_layer.renderer())

        category_layer.setRenderer(new_renderer)
        root_rule = category_layer.renderer().rootRule()
        for rule in root_rule.children():
            if rule.label() != category.label():
                root_rule.removeChild(rule)

        project_instance.addMapLayer(category_layer, False)
        group.addLayer(category_layer)
