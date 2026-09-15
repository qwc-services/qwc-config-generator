import logging
import unittest
from xml.etree import ElementTree

from config_generator.qgs_reader import QGSReader


def layout_xml(maps):
    """ Build a minimal <Layout> element containing the given map items.

    Each entry of maps is a dict with keys: locked (bool), extent (tuple or None),
    item_crs (str or None), size (str, defaults to '200,150,mm'), follow_preset (bool),
    preset_name (str), atlas_driven (bool), grid (tuple of (show, intervalX, intervalY)).
    """
    items = []
    for entry in maps:
        extent = ''
        if entry.get('extent') is not None:
            extent = '<Extent xmin="%s" ymin="%s" xmax="%s" ymax="%s"/>' % entry['extent']
        item_crs = ''
        if 'item_crs' in entry:
            item_crs = '<crs><spatialrefsys><authid>%s</authid></spatialrefsys></crs>' % (entry['item_crs'] or '')
        atlas = ''
        if entry.get('atlas_driven'):
            atlas = '<AtlasMap atlasDriven="1" scalingMode="0" margin="0.1"/>'
        grid = ''
        if entry.get('grid') is not None:
            grid = '<ComposerMapGrid show="%s" intervalX="%s" intervalY="%s"/>' % entry['grid']
        items.append(
            '<LayoutItem type="65639" size="%s" positionOnPage="10,20,mm" '
            'keepLayerSet="%s" followPreset="%s" followPresetName="%s">%s%s%s%s</LayoutItem>' % (
                entry.get('size', '200,150,mm'),
                'true' if entry.get('locked') else 'false',
                'true' if entry.get('follow_preset') else 'false',
                entry.get('preset_name', ''),
                extent, item_crs, atlas, grid
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
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertNotIn('fixedMaps', template)

    def test_follow_preset_without_a_preset_name_is_not_reported(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (5, 6, 7, 8), 'follow_preset': True}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertNotIn('fixedMaps', template)

    def test_map_following_a_theme_is_reported_with_its_preset_name(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (5, 6, 7, 8), 'follow_preset': True, 'preset_name': 'winter'}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertEqual(
            [{
                'name': 'map1',
                'extent': [5.0, 6.0, 7.0, 8.0],
                'crs': 'EPSG:2056',
                'followPresetName': 'winter'
            }],
            template['fixedMaps']
        )

    def test_locked_map_is_not_reported_with_a_preset_name(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': True, 'extent': (5, 6, 7, 8), 'follow_preset': True, 'preset_name': 'winter'}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertNotIn('followPresetName', template['fixedMaps'][0])

    def test_interactive_map_is_the_first_unfrozen_one(self):
        layout = layout_xml([
            {'locked': False, 'extent': (5, 6, 7, 8), 'follow_preset': True, 'preset_name': 'winter',
             'size': '300,100,mm'},
            {'locked': False, 'extent': (1, 2, 3, 4), 'size': '200,150,mm'}
        ])
        template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map1', template['map']['name'])
        self.assertEqual(200, template['map']['width'])
        self.assertEqual(['map0'], [m['name'] for m in template['fixedMaps']])

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
        with self.assertLogs(self.reader.logger, level='WARNING') as logs:
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertEqual(['map1'], [m['name'] for m in template['fixedMaps']])
        self.assertTrue(any('map0' in line for line in logs.output))

    def test_project_crs_absent_omits_fixed_maps(self):
        layout = layout_xml([
            {'locked': True, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (1, 2, 3, 4)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout)
        self.assertNotIn('fixedMaps', template)

    def test_extra_non_frozen_map_is_warned_about(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': False, 'extent': (5, 6, 7, 8)}
        ])
        with self.assertLogs('print_layout_tests', level='WARNING') as logs:
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertTrue(any('map1' in line for line in logs.output))

    def test_atlas_driven_map_is_preferred_as_the_main_map(self):
        layout = layout_xml([
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': True, 'extent': (5, 6, 7, 8), 'atlas_driven': True}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map1', template['map']['name'])

    def test_atlas_driven_map_is_never_a_fixed_map(self):
        layout = layout_xml([
            {'locked': True, 'extent': (5, 6, 7, 8), 'atlas_driven': True},
            {'locked': False, 'extent': (1, 2, 3, 4)},
            {'locked': True, 'extent': (9, 10, 11, 12)}
        ])
        with self.assertLogs(self.reader.logger, level='WARNING'):
            template = self.reader.print_layout_metadata(layout, project_crs='EPSG:2056')
        self.assertEqual('map0', template['map']['name'])
        self.assertEqual(['map2'], [entry['name'] for entry in template['fixedMaps']])
