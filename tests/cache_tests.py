import calendar
import logging
import os
import shutil
import tempfile
import unittest

from flask import Response, json
from flask.testing import FlaskClient

import server
from config_generator.cache_utils import cached_file_valid, stamp_cached_file
from config_generator.qgs_reader import QGSReader
from config_generator.qgs_reader_utils import pg_project_mtime


class ProjectMtimeTests(unittest.TestCase):
    """ Test project modification times """

    def test_cached_file_valid(self):
        with tempfile.NamedTemporaryFile() as cached_file:
            project_mtime = 2000 * 10**9 + 5 * 10**6
            stamp_cached_file(cached_file.name, project_mtime)
            self.assertTrue(cached_file_valid(cached_file.name, project_mtime))
            self.assertFalse(cached_file_valid(cached_file.name, project_mtime + 10**6))

            # File systems which only store whole seconds
            os.utime(cached_file.name, (2000, 2000))
            self.assertTrue(cached_file_valid(cached_file.name, project_mtime))

            # A stamp which fails, as for a file owned by another user, is not an error
            stamp_cached_file(cached_file.name + ".missing", project_mtime)

    def test_pg_project_mtime(self):
        metadata = {"last_modified_time": "2026-10-12 19:39:08.758303", "last_modified_user": "qwc_admin"}
        self.assertEqual(pg_project_mtime(metadata), calendar.timegm((2026, 10, 12, 19, 39, 8)) * 10**9 + 758 * 10**6)
        self.assertIsNone(pg_project_mtime({}))

    def test_theme_mtime_follows_embedded_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            theme_project = os.path.join(tmpdir, "theme.qgs")
            embedded_project = os.path.join(tmpdir, "embedded.qgs")
            group_project = os.path.join(tmpdir, "group.qgs")
            with open(theme_project, "w") as fh:
                fh.write(
                    '<qgis><layer-tree-group><layer-tree-group><customproperties><Option type="Map">'
                    '<Option type="QString" name="embedded_project" value="./group.qgs"/>'
                    '</Option></customproperties></layer-tree-group></layer-tree-group><projectlayers>'
                    '<maplayer embedded="1" project="./embedded.qgs" id="a"/>'
                    '</projectlayers></qgis>'
                )
            for project in (embedded_project, group_project):
                with open(project, "w") as fh:
                    fh.write('<qgis/>')
                os.utime(project, (1000, 1000))
            os.utime(theme_project, (2000, 2000))

            def theme_mtime():
                reader = QGSReader({'qgis_projects_base_dir': tmpdir}, logging.getLogger('cache_tests'), '', False)
                reader.read("theme", {}, [], [])
                return reader.theme_mtimes["theme"]

            self.assertEqual(theme_mtime(), 2000 * 10**9)

            # Saving the embedded project also modifies the theme
            os.utime(embedded_project, (3000, 3000))
            self.assertEqual(theme_mtime(), 3000 * 10**9)

            # So does saving the project of an embedded group
            os.utime(group_project, (4000, 4000))
            self.assertEqual(theme_mtime(), 4000 * 10**9)


class CachedProjectMetadataTests(unittest.TestCase):
    """ Test that cached project metadata is only reused for unmodified projects """

    def setUp(self):
        """ Setup the config generator input and output in a directory which is kept for all runs of a test. """
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        tmpdirpath = tmpdir.name
        os.makedirs(os.path.join(tmpdirpath, "config-in", "default"))
        os.makedirs(os.path.join(tmpdirpath, "config", "default"))
        qwc_docker_dir = os.getenv("QWC_DOCKER_DIR", "qwc-docker")

        # Copy and adjust tenantConfig.json
        with open(f'{qwc_docker_dir}/volumes/config-in/default/tenantConfig.json') as fh:
            data = json.load(fh)

        data["services"] = [
            serviceConfig for serviceConfig in data["services"]
            if serviceConfig["name"] not in ["featureInfo", "legend", "print"]
        ]

        data["config"]["validate_schema"] = False
        data["config"]["default_qgis_server_url"] = "http://localhost:8001/ows"
        data["config"]["qgis_projects_base_dir"] = f"{qwc_docker_dir}/volumes/qgs-resources"
        data["config"]["qgis_projects_scan_base_dir"] = f"{qwc_docker_dir}/volumes/qgs-resources/scan"
        for serviceConfig in data["services"]:
            if serviceConfig["name"] == "mapViewer":
                serviceConfig["config"]["qwc2_path"] = os.path.join(tmpdirpath, "qwc2")
                serviceConfig["generator_config"]["qwc2_config"]["qwc2_config_file"] = \
                    os.path.join(tmpdirpath, "config-in", "default", "config.json")
                serviceConfig["generator_config"]["qwc2_config"]["qwc2_index_file"] = \
                    os.path.join(tmpdirpath, "config-in", "default", "index.html")

        with open(os.path.join(tmpdirpath, "config-in", "default", "tenantConfig.json"), "w") as fh:
            json.dump(data, fh)

        # Copy index.html, config.json, themesConfig.json
        for fileName in ["config.json", "index.html", "themesConfig.json"]:
            shutil.copyfile(
                os.path.join(qwc_docker_dir, 'volumes', 'config-in', 'default', fileName),
                os.path.join(tmpdirpath, "config-in", "default", fileName)
            )

        os.environ["INPUT_CONFIG_PATH"] = os.path.join(tmpdirpath, "config-in")
        os.environ["OUTPUT_CONFIG_PATH"] = os.path.join(tmpdirpath, "config")

        # Restore the modification time of the test project after the test
        self.project = f"{qwc_docker_dir}/volumes/qgs-resources/scan/wfs_test.qgs"
        project_stat = os.stat(self.project)
        self.addCleanup(os.utime, self.project, ns=(project_stat.st_atime_ns, project_stat.st_mtime_ns))

    def __generate_configs(self):
        url = "/generate_configs?tenant=default&stream_response=true&use_cached_project_metadata=true"
        response = self.app.post(url)
        log = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        return log

    def test_modified_project_is_read_again(self):
        """ Test that only the metadata of a modified project is read again from QGIS Server. """
        project_url = "http://localhost:8001/ows/scan/wfs_test"

        # The first run fills the cache, the second run uses it
        self.__generate_configs()
        log = self.__generate_configs()
        self.assertIn(f"Using cached WMS GetProjectSettings for {project_url}", log)
        self.assertNotIn("Downloaded WMS GetProjectSettings", log)

        # The modified project is read again, the other projects are read from the cache
        project_mtime = int(os.path.getmtime(self.project)) + 1
        os.utime(self.project, (project_mtime, project_mtime))
        log = self.__generate_configs()
        self.assertIn(f"Downloaded WMS GetProjectSettings from {project_url}", log)
        self.assertEqual(log.count("Downloaded WMS GetProjectSettings"), 1)
