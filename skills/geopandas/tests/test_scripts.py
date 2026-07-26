"""Dependency-free help and exact-stack synthetic tests for local GeoPandas CLIs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
CLI_NAMES = (
    "crs_reprojection_plan.py",
    "export_plan.py",
    "geometry_validity_report.py",
    "sensitive_coordinates_checklist.py",
    "spatial_join_audit.py",
    "vector_inventory.py",
)
PINNED = {
    "geopandas": "1.1.4",
    "numpy": "2.5.1",
    "packaging": "26.2",
    "pandas": "3.0.5",
    "pyarrow": "25.0.0",
    "pyogrio": "0.13.0",
    "pyproj": "3.7.2",
    "shapely": "2.1.2",
}


def run_script(
    name: str,
    *arguments: str,
    cwd: Path | None = None,
    no_site: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PROJ_NETWORK"] = "OFF"
    command = [sys.executable]
    if no_site:
        command.append("-S")
    command.extend([str(SCRIPTS / name), *map(str, arguments)])
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        cwd=cwd,
        env=environment,
        text=True,
        timeout=90,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"invalid JSON\nstdout={result.stdout}\nstderr={result.stderr}"
        ) from exc


def require_stack() -> tuple[object, object, object, object, object]:
    try:
        import geopandas
        import pyarrow
        import pyogrio
        import pyproj
        import shapely
    except ImportError as exc:
        raise unittest.SkipTest("run with the pinned GeoPandas stack") from exc
    return geopandas, pyarrow, pyogrio, pyproj, shapely


def write_join_fixtures(root: Path) -> tuple[Path, Path]:
    geopandas, _, _, _, shapely = require_stack()
    from shapely.geometry import Point, box

    points = geopandas.GeoDataFrame(
        {
            "point_id": ["p-1", "p-2", "p-3"],
            "geometry": [Point(0.5, 0.5), Point(1.0, 0.5), Point(3.0, 3.0)],
        },
        crs="EPSG:3857",
    )
    zones = geopandas.GeoDataFrame(
        {
            "zone_id": ["duplicate", "duplicate"],
            "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)],
        },
        crs="EPSG:3857",
    )
    points_path = root / "synthetic-points.geojson"
    zones_path = root / "synthetic-zones.geojson"
    points.to_file(points_path, driver="GeoJSON", engine="pyogrio", index=False)
    zones.to_file(zones_path, driver="GeoJSON", engine="pyogrio", index=False)
    del shapely
    return points_path, zones_path


class DependencyFreeHelpTests(unittest.TestCase):
    def test_all_cli_helps_succeed_without_site_packages(self) -> None:
        for name in CLI_NAMES:
            with self.subTest(name=name):
                result = run_script(name, "--help", no_site=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.casefold())

    def test_nonlocal_and_archive_paths_fail_closed(self) -> None:
        remote = run_script("vector_inventory.py", "https://example.invalid/data.gpkg")
        self.assertEqual(remote.returncode, 2)
        self.assertIn("local path", payload(remote)["error"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data.zip").write_bytes(b"synthetic")
            archive = run_script(
                "vector_inventory.py",
                "data.zip",
                "--root",
                ".",
                cwd=root,
            )
            self.assertEqual(archive.returncode, 2)
            self.assertIn("archive", payload(archive)["error"])


class ExactPinnedStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gpd, cls.pyarrow, cls.pyogrio, cls.pyproj, cls.shapely = require_stack()

    def test_exact_package_and_native_versions(self) -> None:
        self.assertEqual({name: version(name) for name in PINNED}, PINNED)
        self.assertEqual(
            ".".join(map(str, self.pyogrio.__gdal_version__)),
            "3.12.4",
        )
        self.assertEqual(self.shapely.geos_version_string, "3.13.1")
        self.assertEqual(self.pyproj.proj_version_str, "9.5.1")

    def test_core_geometry_join_overlay_dissolve_and_arrow_apis(self) -> None:
        from shapely.geometry import Point, Polygon, box

        coverage = self.gpd.GeoDataFrame(
            {
                "group": ["a", "a"],
                "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)],
            },
            crs="EPSG:3857",
        )
        points = self.gpd.GeoDataFrame(
            {"geometry": [Point(0.5, 0.5), Point(1.0, 0.5)]},
            crs=coverage.crs,
        )
        self.assertTrue(coverage.geometry.is_valid_coverage())
        self.assertTrue(coverage.geometry.union_all(method="coverage").is_valid)
        dissolved = coverage.dissolve(
            by="group",
            method="unary",
            grid_size=0.001,
        )
        self.assertTrue(dissolved.geometry.is_valid.all())
        self.assertEqual(
            len(self.gpd.sjoin(points, coverage, predicate="intersects")),
            3,
        )
        self.assertEqual(
            len(
                self.gpd.overlay(
                    coverage.iloc[[0]],
                    coverage.iloc[[1]],
                    how="union",
                    keep_geom_type=False,
                )
            ),
            3,
        )
        self.assertEqual(
            len(self.gpd.clip(points, (0.0, 0.0, 1.0, 1.0))),
            2,
        )

        invalid = self.gpd.GeoSeries(
            [Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])],
            crs=coverage.crs,
        )
        repaired = invalid.make_valid(method="structure", keep_collapsed=True)
        self.assertTrue(repaired.is_valid.all())
        snapped = coverage.geometry.set_precision(0.001)
        self.assertEqual(float(snapped.get_precision().min()), 0.001)

        arrow_table = coverage.to_arrow(geometry_encoding="WKB")
        arrow_roundtrip = self.gpd.GeoDataFrame.from_arrow(arrow_table)
        self.assertEqual(len(arrow_roundtrip), len(coverage))
        self.assertTrue(arrow_roundtrip.crs.equals(coverage.crs))

    def test_geoparquet_11_bbox_roundtrip(self) -> None:
        from shapely.geometry import box

        frame = self.gpd.GeoDataFrame(
            {
                "feature_id": ["a", "b"],
                "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)],
            },
            crs="EPSG:3857",
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.parquet"
            frame.to_parquet(
                path,
                index=False,
                schema_version="1.1.0",
                geometry_encoding="WKB",
                write_covering_bbox=True,
            )
            filtered = self.gpd.read_parquet(path, bbox=(0, 0, 0.5, 0.5))
            self.assertEqual(filtered["feature_id"].tolist(), ["a"])


class LocalCliSyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        require_stack()

    def test_inventory_and_join_cardinality_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            points, zones = write_join_fixtures(root)
            inventory = run_script(
                "vector_inventory.py",
                points.name,
                "--root",
                ".",
                "--max-features",
                "10",
                cwd=root,
            )
            self.assertEqual(inventory.returncode, 0, inventory.stderr)
            inventory_report = payload(inventory)
            self.assertFalse(inventory_report["coordinates_emitted"])
            self.assertFalse(
                inventory_report["technical_inventory"]["feature_data_loaded"]
            )
            self.assertNotIn(str(root), inventory.stdout)
            self.assertNotIn("point_id", inventory.stdout)

            intersects = run_script(
                "spatial_join_audit.py",
                points.name,
                zones.name,
                "--root",
                ".",
                "--predicate",
                "intersects",
                "--left-id",
                "point_id",
                "--right-id",
                "zone_id",
                "--max-features",
                "10",
                cwd=root,
            )
            self.assertEqual(intersects.returncode, 0, intersects.stderr)
            joined = payload(intersects)
            self.assertEqual(joined["pair_audit"]["pair_count"], 3)
            self.assertEqual(
                joined["pair_audit"]["left"]["features_with_multiple_matches"],
                1,
            )
            self.assertEqual(
                joined["right"]["stable_id_audit"]["duplicate_rows"],
                2,
            )
            self.assertTrue(joined["pair_audit"]["many_to_many_observed"])
            self.assertNotIn('"duplicate"', intersects.stdout)

            within = run_script(
                "spatial_join_audit.py",
                points.name,
                zones.name,
                "--root",
                ".",
                "--predicate",
                "within",
                "--max-features",
                "10",
                cwd=root,
            )
            self.assertEqual(within.returncode, 0, within.stderr)
            self.assertEqual(payload(within)["pair_audit"]["pair_count"], 1)

    def test_validity_dry_run_and_new_output_only(self) -> None:
        geopandas, _, _, _, _ = require_stack()
        from shapely.geometry import Polygon

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "invalid.gpkg"
            frame = geopandas.GeoDataFrame(
                {
                    "feature_id": ["invalid", "empty", "missing"],
                    "geometry": [
                        Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]),
                        Polygon(),
                        None,
                    ],
                },
                crs="EPSG:3857",
            )
            frame.to_file(
                source,
                layer="input",
                driver="GPKG",
                engine="pyogrio",
                index=False,
            )
            before_bytes = source.read_bytes()
            dry = run_script(
                "geometry_validity_report.py",
                source.name,
                "--root",
                ".",
                "--layer",
                "input",
                "--id-column",
                "feature_id",
                "--method",
                "structure",
                "--max-features",
                "10",
                cwd=root,
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            dry_report = payload(dry)
            self.assertTrue(dry_report["dry_run"])
            self.assertEqual(dry_report["before"]["invalid"], 1)
            self.assertEqual(dry_report["simulated_after"]["invalid"], 0)
            self.assertEqual(source.read_bytes(), before_bytes)

            written = run_script(
                "geometry_validity_report.py",
                source.name,
                "--root",
                ".",
                "--layer",
                "input",
                "--method",
                "structure",
                "--repair-output",
                "repaired.gpkg",
                "--max-features",
                "10",
                cwd=root,
            )
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertTrue((root / "repaired.gpkg").is_file())
            repaired_bytes = (root / "repaired.gpkg").read_bytes()
            second = run_script(
                "geometry_validity_report.py",
                source.name,
                "--root",
                ".",
                "--layer",
                "input",
                "--method",
                "structure",
                "--repair-output",
                "repaired.gpkg",
                "--max-features",
                "10",
                cwd=root,
            )
            self.assertEqual(second.returncode, 2)
            self.assertEqual((root / "repaired.gpkg").read_bytes(), repaired_bytes)

    def test_crs_export_and_privacy_planners(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            points, _ = write_join_fixtures(root)
            crs = run_script(
                "crs_reprojection_plan.py",
                "--source-crs",
                "EPSG:4326",
                "--target-crs",
                "EPSG:32631",
                "--operation",
                "distance",
                "--bbox",
                "-1",
                "40",
                "1",
                "42",
                cwd=root,
            )
            self.assertEqual(crs.returncode, 0, crs.stderr)
            crs_report = payload(crs)
            self.assertTrue(crs_report["source_crs"]["geographic"])
            self.assertTrue(crs_report["target_crs"]["projected"])
            self.assertFalse(crs_report["operation_policy"]["proj_network_enabled"])
            self.assertFalse(crs_report["bbox"]["values_emitted"])

            dateline = run_script(
                "crs_reprojection_plan.py",
                "--source-crs",
                "EPSG:4326",
                "--target-crs",
                "EPSG:3857",
                "--bbox",
                "170",
                "-10",
                "-170",
                "10",
                cwd=root,
            )
            self.assertIn(dateline.returncode, (0, 2))
            self.assertTrue(payload(dateline)["bbox"]["crosses_antimeridian"])

            export = run_script(
                "export_plan.py",
                points.name,
                "result.parquet",
                "--root",
                ".",
                "--format",
                "geoparquet",
                "--stable-id-column",
                "point_id",
                "--id-unique-verified",
                cwd=root,
            )
            self.assertEqual(export.returncode, 0, export.stderr)
            export_report = payload(export)
            self.assertFalse(export_report["executed"])
            self.assertFalse((root / "result.parquet").exists())
            self.assertTrue(
                export_report["geoparquet"]["default_stable_contract"]
            )

            bad_schema = run_script(
                "export_plan.py",
                points.name,
                "native.parquet",
                "--root",
                ".",
                "--stable-id-column",
                "point_id",
                "--id-unique-verified",
                "--geometry-encoding",
                "geoarrow",
                cwd=root,
            )
            self.assertEqual(bad_schema.returncode, 2)
            self.assertIn(
                "schema 1.1.0",
                " ".join(payload(bad_schema)["blockers"]),
            )

            blocked = run_script(
                "sensitive_coordinates_checklist.py",
                "--public-output",
                "--precise-points",
                "--contains-addresses",
                cwd=root,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertTrue(payload(blocked)["blockers"])

            ready = run_script(
                "sensitive_coordinates_checklist.py",
                "--public-output",
                "--precise-points",
                "--contains-addresses",
                "--generalization",
                "aggregate",
                "--generalization",
                "remove-sensitive-fields",
                "--generalization",
                "suppress-small-groups",
                "--minimum-group-size",
                "10",
                "--direct-identifiers-removed",
                "--attribute-review-complete",
                "--reidentification-review-complete",
                "--visual-review-complete",
                "--provenance-recorded",
                "--tile-and-cdn-access-disabled",
                cwd=root,
            )
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertTrue(payload(ready)["ok"])


if __name__ == "__main__":
    unittest.main()
