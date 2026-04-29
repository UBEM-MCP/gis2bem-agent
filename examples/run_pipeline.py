from __future__ import annotations

import argparse
from pathlib import Path

from gis2bem_workflow import load_config
from gis2bem_workflow.gis.vector_to_csv import vector_polygons_to_csv
from gis2bem_workflow.geometry.polygons import load_building_polygons_from_csv
from gis2bem_workflow.idf.baseline import simulation_setup
from gis2bem_workflow.idf.idealload import idealload_setup
from gis2bem_workflow.idf.mass import generate_mass_idfs
from gis2bem_workflow.paths import ensure_dirs, resolve_paths
from gis2bem_workflow.preprocess.building_csv import preprocess_buildings_csv_inplace
from gis2bem_workflow.results.summary import summarize_sim_results
from gis2bem_workflow.run.eplus import run_idealload_idfs_by_epw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to config.yaml")
    ap.add_argument("--skip-gis", action="store_true")
    ap.add_argument("--skip-mass", action="store_true")
    ap.add_argument("--skip-baseline", action="store_true")
    ap.add_argument("--skip-idealload", action="store_true")
    ap.add_argument("--skip-run", action="store_true")
    ap.add_argument("--skip-summary", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    rp = resolve_paths(cfg)
    ensure_dirs(rp.mass_idf_out_dir, rp.baseline_out_dir, rp.idealload_out_dir, rp.sim_output_root)

    # 1) GIS -> CSV
    if not args.skip_gis:
        if cfg.input_vector_path is None:
            raise SystemExit("Missing required config key: input_vector_path")
        out_csv = vector_polygons_to_csv(
            cfg.input_vector_path,
            output_dir=rp.project_root,
            layer_name=cfg.input_vector_layer_name,
            layer_index=cfg.input_vector_layer_index,
            output_csv_name=rp.buildings_csv_path.stem,
        )
        print("GIS->CSV:", out_csv)

    # 2) CSV preprocess
    preprocess_buildings_csv_inplace(rp.buildings_csv_path)

    # 3) CSV -> polygons
    buildings = load_building_polygons_from_csv(rp.buildings_csv_path)

    # 4) Mass IDF generation
    if not args.skip_mass:
        written = generate_mass_idfs(cfg, buildings, out_dir=rp.mass_idf_out_dir)
        print("Mass IDFs:", len(written))

    # 5) Baseline + Idealload
    idf_files = [p for p in Path(rp.mass_idf_out_dir).glob("*.idf") if not p.name.endswith("_Idealload.idf")]

    if not args.skip_baseline:
        for p in idf_files:
            out = rp.baseline_out_dir / p.name
            if not out.exists():
                simulation_setup(cfg, p, out_dir=rp.baseline_out_dir)

    if not args.skip_idealload:
        baseline_files = list(Path(rp.baseline_out_dir).glob("*.idf"))
        for p in baseline_files:
            out = rp.idealload_out_dir / f"{p.stem}_Idealload.idf"
            if not out.exists():
                idealload_setup(cfg, p, out_dir=rp.idealload_out_dir)

    # 6) Run EnergyPlus
    if not args.skip_run:
        if rp.weather_dir is None:
            raise SystemExit("Missing required config key: weather_dir")
        run_idealload_idfs_by_epw(
            cfg,
            idealload_idf_dir=rp.idealload_out_dir,
            weather_dir=rp.weather_dir,
            output_root=rp.sim_output_root,
        )

    # 7) Summary
    if not args.skip_summary:
        out_xlsx = rp.sim_output_root / "summary.xlsx"
        df = summarize_sim_results(rp.sim_output_root, out_xlsx)
        print("Summary rows:", len(df), "->", out_xlsx)


if __name__ == "__main__":
    main()

