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

    def test_single_map_is_unchanged(self):
        layout = layout_xml([{'locked': False, 'extent': (1, 2, 3, 4)}])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertEqual(200, template['map']['width'])
        self.assertEqual(150, template['map']['height'])
        self.assertNotIn('fixedMaps', template)

    def test_locked_map_is_reported_as_fixed_map(self):
        layout = layout_xml([
            {'locked': True, 'extent': (2600000, 1190000, 2610000, 1200000), 'size': '300,100,mm'},
            {'locked': False, 'extent': (1, 2, 3, 4), 'size': '200,150,mm'}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map1', template['map']['name'])
        self.assertEqual(200, template['map']['width'])
        self.assertEqual(150, template['map']['height'])
        self.assertEqual(
            [{
                'name': 'map0',
                'extent': [2600000.0, 1190000.0, 2610000.0, 1200000.0],
                'crs': 'EPSG:2056'
            }],
            template['fixedMaps']
        )

    def test_unlocked_extra_map_is_not_reported(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (5, 6, 7, 8)}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertNotIn('fixedMaps', template)

    def test_extra_map_with_only_follow_preset_is_not_reported(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (5, 6, 7, 8), 'follow_preset': True}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertNotIn('fixedMaps', template)

    def test_locked_map_without_extent_is_skipped(self):
        layout = layout_xml([
            {'locked': True, 'extent': None},
            {'locked': False, 'extent': (1, 2, 3, 4)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertNotIn('fixedMaps', template)

    def test_locked_map_with_own_crs_is_skipped(self):
        layout = layout_xml([
            {'locked': True, 'extent': (1, 2, 3, 4), 'item_crs': 'EPSG:3857'},
            {'locked': False, 'extent': (1, 2, 3, 4)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertNotIn('fixedMaps', template)

    def test_locked_map_with_empty_authid_is_skipped(self):
        layout = layout_xml([
            {'locked': True, 'extent': (1, 2, 3, 4), 'item_crs': ''},
            {'locked': False, 'extent': (1, 2, 3, 4)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertNotIn('fixedMaps', template)

    def test_locked_map_with_non_finite_extent_is_skipped(self):
        layout = layout_xml([
            {'locked': True, 'extent': (float('nan'), 2, 3, 4)},
            {'locked': False, 'extent': (1, 2, 3, 4)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertNotIn('fixedMaps', template)

    def test_all_maps_locked_keeps_first_as_interactive(self):
        layout = layout_xml([
            {'locked': True, 'extent': (1, 2, 3, 4)},
            {'locked': True, 'extent': (5, 6, 7, 8)}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertEqual(['map1'], [m['name'] for m in template['fixedMaps']])

    def test_project_crs_absent_omits_fixed_maps(self):
        layout = layout_xml([
            {'locked': True, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (1, 2, 3, 4)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout)
        self.assertNotIn('fixedMaps', template)
