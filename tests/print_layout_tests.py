import logging
import unittest
from xml.etree import ElementTree

from config_generator.qgs_reader import QGSReader


def layout_xml(maps):
    """ Build a minimal <Layout> element containing the given map items.

    Each entry of maps is a dict with keys: locked (bool), extent (tuple or None),
    item_crs (str or None), size (str, defaults to '200,150,mm'), follow_preset (bool),
    preset_name (str).
    """
    items = []
    for entry in maps:
        extent = ''
        if entry.get('extent') is not None:
            extent = '<Extent xmin="%s" ymin="%s" xmax="%s" ymax="%s"/>' % entry['extent']
        item_crs = ''
        if 'item_crs' in entry:
            item_crs = '<crs><spatialrefsys><authid>%s</authid></spatialrefsys></crs>' % (entry['item_crs'] or '')
        items.append(
            '<LayoutItem type="65639" size="%s" positionOnPage="10,20,mm" '
            'keepLayerSet="%s" followPreset="%s" followPresetName="%s">%s%s</LayoutItem>' % (
                entry.get('size', '200,150,mm'),
                'true' if entry.get('locked') else 'false',
                'true' if entry.get('follow_preset') else 'false',
                entry.get('preset_name', ''),
                extent, item_crs
            )
        )
    return ElementTree.fromstring(
        '<Layout name="A4" printResolution="300">%s</Layout>' % ''.join(items)
    )


class PrintLayoutTestCase(unittest.TestCase):
    """ Test print layout metadata extraction """

    def setUp(self):
        self.reader = QGSReader({}, logging.getLogger('print_layout_tests'), '', False)

    def test_stale_preset_name_is_ignored_when_follow_is_off(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4), 'follow_preset': False, 'preset_name': 'Situation'}
        ])
        template = self.reader.print_layout_metadata(layout)
        self.assertIsNone(template['map']['followPresetName'])

    def test_preset_name_is_reported_when_follow_is_on(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4), 'follow_preset': True, 'preset_name': 'Situation'}
        ])
        template = self.reader.print_layout_metadata(layout)
        self.assertEqual('Situation', template['map']['followPresetName'])
