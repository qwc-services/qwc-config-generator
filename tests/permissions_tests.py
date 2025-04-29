from jsonpath_ng.ext import parse
import os
import psycopg2
import shutil
import tempfile
import unittest
from urllib.parse import urlparse, parse_qs, unquote, urlencode

from flask import Response, json
from flask.testing import FlaskClient

import server

ROLE_PUBLIC = 1
ROLE_ADMIN = 2

class PermissionsTests(unittest.TestCase):
    """Test generated permissions"""

    def tearDown(self):
        pass

    @classmethod
    def setUpClass(cls):
        """ Setup database connection for tests. """
        cls.conn = psycopg2.connect(service="qwc_configdb")
        cls.conn.autocommit = False

    @classmethod
    def tearDownClass(cls):
        """ Close the database connection after all tests. """
        cls.conn.close()

    def setUp(self):
        """ Setup test case. """
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)

        self.cursor = PermissionsTests.conn.cursor()

    def tearDown(self):
        """ Revert DB changes after test case. """
        self.cursor.close()

    def __run_config_generator(self, generator_config):

        with tempfile.TemporaryDirectory() as tmpdirpath:
            os.makedirs(os.path.join(tmpdirpath, "config-in", "default"))
            os.makedirs(os.path.join(tmpdirpath, "config", "default"))

            # Copy and adjust tenantConfig.json
            with open('qwc-docker/volumes/config-in/default/tenantConfig.json', 'r') as fh:
                data = json.load(fh)

            data["config"].update(generator_config)
            data["config"]["validate_schema"] = False
            data["config"]["default_qgis_server_url"] = "http://localhost:8001/ows"
            data["config"]["qgis_projects_base_dir"] = "qwc-docker/volumes/qgs-resources"
            data["config"]["qgis_projects_scan_base_dir"] = "qwc-docker/volumes/qgs-resources/scan"
            for serviceConfig in data["services"]:
                if serviceConfig["name"] == "mapViewer":
                    serviceConfig["config"]["qwc2_path"] = os.path.join(tmpdirpath, "qwc2")
                    serviceConfig["generator_config"]["qwc2_config"]["qwc2_config_file"] = os.path.join(tmpdirpath, "config-in", "default", "config.json")
                    serviceConfig["generator_config"]["qwc2_config"]["qwc2_index_file"] = os.path.join(tmpdirpath, "config-in", "default", "index.html")

            with open(os.path.join(tmpdirpath, "config-in", "default", "tenantConfig.json"), "w") as fh:
                json.dump(data, fh)

            # Copy index.html, config.json, themesConfig.json
            for fileName in ["config.json", "index.html", "themesConfig.json"]:
                shutil.copyfile(
                    os.path.join('qwc-docker', 'volumes', 'config-in', 'default', fileName),
                    os.path.join(tmpdirpath, "config-in", "default", fileName)
                )

            os.environ["INPUT_CONFIG_PATH"] = os.path.join(tmpdirpath, "config-in")
            os.environ["OUTPUT_CONFIG_PATH"] = os.path.join(tmpdirpath, "config")

            url = "/generate_configs?tenant=default&use_cached_project_metadata=true"
            response = self.app.post(url)

            if response.status_code != 200:
                print(response.text)
            self.assertEqual(response.status_code, 200)

            with open(os.path.join(tmpdirpath, "config", "default", "permissions.json"), 'r') as fh:
                permissions = json.load(fh)

        return permissions

    def __role_permissions(self, permissions, role):
        for role in permissions["role"]:
            if role["role"] == role:
                return role["permissions"]

    def test_public_permissions(self):
        """ Test public permissions (permissions_default_allow and no explicit permissions). """

        self.cursor.execute("""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({})
        # print(perm)

        # Map and layers permitted for public, layers are queryable
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')].attributes[?(@=='Name')]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')].attributes.`len`").find(perm)[0].value, 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes.`len`").find(perm)[0].value, 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')].attributes[?(@=='Name')]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')].attributes.`len`").find(perm)[0].value, 1)

        # No additional permissions for role admin, as they are public
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 0)

    def test_restricted_layer_and_attribute(self):
        """ Test restricted layers / attributes (permissions_default_allow and one restricted layer / attribute). """

        self.cursor.execute(f"""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
            INSERT INTO qwc_config.resources (id, parent_id, type, name)
            VALUES
            (1, NULL, 'map', 'qwc_demo'),
            (2, 1, 'layer', 'edit_points'),
            (3, 1, 'layer', 'edit_lines'),
            (4, 3, 'attribute', 'Name');
            INSERT INTO qwc_config.permissions (id, role_id, resource_id, priority, write)
            VALUES
            (1, {ROLE_PUBLIC}, 1, 0, FALSE),
            (2, {ROLE_ADMIN},  2, 0, FALSE), -- restrict qwc_points layer
            (3, {ROLE_ADMIN},  4, 0, FALSE); -- restrict edit_lines->Name attribute
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({})

        # Map and layers permitted for public, layers are queryable, except for layer edit_points
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 0)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 0)
        self.assertGreater(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes.`len`").find(perm)[0].value, 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')].attributes[?(@=='Name')]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')].attributes.`len`").find(perm)[0].value, 1)

        # Permission for layer edit_points for admin
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')].attributes[?(@=='Name')]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')].attributes.`len`").find(perm)[0].value, 1)

        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 1)
        self.assertEqual(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes.`len`").find(perm)[0].value, 1)


    def test_restricted_info_service(self):
        """ Test restricted info service. """

        self.cursor.execute(f"""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
            INSERT INTO qwc_config.resources (id, parent_id, type, name)
            VALUES
            (1, NULL, 'feature_info_service', 'qwc_demo');
            INSERT INTO qwc_config.permissions (id, role_id, resource_id, priority, write)
            VALUES
            (1, {ROLE_ADMIN}, 1, 0, FALSE); -- restrict info_service
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({})

        # Map and layers permitted for public, layers are not queryable
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template!=true)]").find(perm)), 1)

        # Additional queryable permissions for admin
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template==true)]").find(perm)), 1)

    def test_restricted_info_layer(self):
        """ Test restricted info layer. """

        self.cursor.execute(f"""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
            INSERT INTO qwc_config.resources (id, parent_id, type, name)
            VALUES
            (1, NULL, 'feature_info_service', 'qwc_demo'),
            (2, 1, 'feature_info_layer', 'edit_points');
            INSERT INTO qwc_config.permissions (id, role_id, resource_id, priority, write)
            VALUES
            (1, {ROLE_ADMIN}, 2, 0, FALSE); -- restrict edit_points
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({})

        # Map and layers permitted for public, edit_points is not queryable, the others are
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template!=true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template==true)]").find(perm)), 1)

        # Additional queryable permissions for role admin and layer edit_points
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 0)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 0)


    def test_data_permissions(self):
        """ Test data permissions. """

        self.cursor.execute(f"""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
            INSERT INTO qwc_config.resources (id, parent_id, type, name)
            VALUES
            (1, NULL, 'map', 'qwc_demo'),
            (2, 1, 'data', 'edit_points'),
            (3, 1, 'data', 'edit_lines'),
            (4, 1, 'data', 'edit_polygons'),
            (5, 1, 'data_create', 'edit_polygons'),
            (6, 4, 'attribute', 'description');
            INSERT INTO qwc_config.permissions (id, role_id, resource_id, priority, write)
            VALUES
            (1, {ROLE_PUBLIC}, 1, 0, FALSE),
            (2, {ROLE_ADMIN}, 2, 0, TRUE),
            (3, {ROLE_ADMIN}, 3, 0, FALSE),
            (4, {ROLE_PUBLIC}, 4, 0, FALSE),
            (5, {ROLE_ADMIN}, 5, 0, FALSE),
            (6, {ROLE_ADMIN}, 6, 0, FALSE);
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({})

        # Map and layers permitted for public, edit_polygons has public read-only permissions with restricted attribute
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.writable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.creatable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.readable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.updatable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.deletable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons')].attributes[?(@=='description')]").find(perm)), 0)


        # Additional data permissions for role admin and layers edit_points (writable), edit_lines (not writable) and edit_polygons (creatable, with description attribute)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_points' & @.writable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_points' & @.creatable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_points' & @.readable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_points' & @.updatable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_points' & @.deletable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_lines' & @.writable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_lines' & @.creatable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_lines' & @.readable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_lines' & @.updatable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_lines' & @.deletable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.creatable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.readable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.updatable)]").find(perm)), 0)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons' & @.deletable)]").find(perm)), 0)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.data_datasets[?(@.name=='qwc_demo.edit_polygons')].attributes[?(@=='description')]").find(perm)), 1)

    def test_public_permissions_default_restrict_no_permissions(self):
        """ Test permissions_default_allow=false and no permissions. """

        self.cursor.execute("""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({"permissions_default_allow": False})
        # print(perm)

        # No permissions for no roles
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 0)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 0)

    def test_public_permissions_default_restrict_selected_permissions(self):
        """ Test permissions_default_allow=false and selected permissions. """

        self.cursor.execute(f"""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
            INSERT INTO qwc_config.resources (id, parent_id, type, name)
            VALUES
            (1, NULL, 'map', 'qwc_demo'),
            (2, 1, 'layer', 'qwc_demo'),
            (3, 1, 'layer', 'edit_demo'),
            (4, 1, 'layer', 'edit_points'),
            (5, 1, 'layer', 'edit_lines'),
            (6, 5, 'attribute', 'Name');
            INSERT INTO qwc_config.permissions (id, role_id, resource_id, priority, write)
            VALUES
            (1, {ROLE_PUBLIC}, 1, 0, FALSE), -- permit qwc_demo map for public
            (2, {ROLE_PUBLIC}, 2, 0, FALSE), -- permit qwc_demo root group for public
            (3, {ROLE_PUBLIC}, 3, 0, FALSE), -- permit edit_demo group for public
            (4, {ROLE_ADMIN},  4, 0, FALSE), -- permit qwc_points layer for admin
            (5, {ROLE_PUBLIC},  5, 0, FALSE), -- permit edit_lines for public
            (6, {ROLE_ADMIN},  6, 0, FALSE); -- permit edit_lines->Name attribute for admin
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({"permissions_default_allow": False})

        # Map is permitted for public, and layer edit_lines (but not queryable and no Name attribute)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 0)

        # edit_points is permitted for admin (with all attributes, but not queryable), and Name is permitted for edit_lines
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template==false)]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')].attributes.`len`").find(perm)[0].value, 1)

        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 1)

    def test_public_permissions_default_restrict_selected_permissions_inherit_info_permissions(self):
        """ Test permissions_default_allow=false and inherit_info_permissions=true and selected permissions. """

        self.cursor.execute(f"""
            DELETE FROM qwc_config.permissions;
            DELETE FROM qwc_config.resources;
            INSERT INTO qwc_config.resources (id, parent_id, type, name)
            VALUES
            (1, NULL, 'map', 'qwc_demo'),
            (2, 1, 'layer', 'qwc_demo'),
            (3, 1, 'layer', 'edit_demo'),
            (4, 1, 'layer', 'edit_points'),
            (5, 1, 'layer', 'edit_lines'),
            (6, 5, 'attribute', 'Name'),
            (7, 1, 'layer', 'edit_polygons'),
            (8, NULL, 'feature_info_service', 'qwc_demo'),
            (9, 8, 'feature_info_layer', 'edit_polygons');
            INSERT INTO qwc_config.permissions (id, role_id, resource_id, priority, write)
            VALUES
            (1, {ROLE_PUBLIC}, 1, 0, FALSE), -- permit qwc_demo map for public
            (2, {ROLE_PUBLIC}, 2, 0, FALSE), -- permit qwc_demo root group for public
            (3, {ROLE_PUBLIC}, 3, 0, FALSE), -- permit edit_demo group for public
            (4, {ROLE_ADMIN},  4, 0, FALSE), -- permit qwc_points layer for admin
            (5, {ROLE_PUBLIC},  5, 0, FALSE), -- permit edit_lines for public
            (6, {ROLE_ADMIN},  6, 0, FALSE), -- permit edit_lines->Name attribute for admin
            (7, {ROLE_PUBLIC}, 7, 0, FALSE), -- permit edit_polygons for public
            (8, {ROLE_ADMIN}, 9, 0, FALSE); -- permit edit_plygons queryable only for admin
        """)
        PermissionsTests.conn.commit()

        perm = self.__run_config_generator({"permissions_default_allow": False, "inherit_info_permissions": True})

        # Map is permitted for public, and layer edit_lines (queryable, no Name attribute) and layer edit_polygons (not queryable)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines' & @.info_template==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 0)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable==false)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='public')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template==false)]").find(perm)), 1)

        # edit_points is permitted for admin (with all attributes, queryable), and Name is permitted for edit_lines, and queryable for edit_polygons
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points' & @.info_template==true)]").find(perm)), 1)
        self.assertGreater(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_points')].attributes.`len`").find(perm)[0].value, 1)

        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_lines')].attributes[?(@=='Name')]").find(perm)), 1)

        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons')]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.queryable==true)]").find(perm)), 1)
        self.assertEqual(len(parse("$.roles[?(@.role=='admin')].permissions.wms_services[?(@.name=='qwc_demo')].layers[?(@.name=='edit_polygons' & @.info_template==true)]").find(perm)), 1)
