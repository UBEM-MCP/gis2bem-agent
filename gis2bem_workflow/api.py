from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request

from .config import as_dict, load_config
from .paths import resolve_paths


def _json_error(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _required(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value in (None, ""):
        raise ValueError(f"Missing required field: {key}")
    return value


def _run(handler: Callable[[], dict[str, Any]]):
    try:
        return jsonify({"success": True, **handler()})
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except FileNotFoundError as exc:
        return _json_error(str(exc), 404)
    except Exception as exc:
        return _json_error(f"{type(exc).__name__}: {exc}", 500)


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"success": True, "service": "gis2bem-workflow-api"})

    @app.post("/config/inspect")
    def inspect_config():
        """
        Inspect a workflow YAML config and return resolved paths.

        JSON body:
          {"config_path": "..."}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            cfg = load_config(_required(data, "config_path"))
            paths = resolve_paths(cfg)
            return {
                "config": as_dict(cfg),
                "resolved_paths": {
                    "project_root": str(paths.project_root),
                    "buildings_csv_path": str(paths.buildings_csv_path),
                    "mass_idf_out_dir": str(paths.mass_idf_out_dir),
                    "baseline_out_dir": str(paths.baseline_out_dir),
                    "idealload_out_dir": str(paths.idealload_out_dir),
                    "weather_dir": None if paths.weather_dir is None else str(paths.weather_dir),
                    "sim_output_root": str(paths.sim_output_root),
                },
            }

        return _run(handler)

    @app.post("/gis/vector-to-csv")
    def vector_to_csv():
        """
        Convert SHP/GPKG building polygons to the GIS2BEM polygon CSV format.

        JSON body:
          {
            "input_path": "...",
            "output_dir": "...",
            "layer_name": null,
            "layer_index": 0,
            "output_csv_name": "optional_stem"
          }
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .gis.vector_to_csv import vector_polygons_to_csv

            out_csv = vector_polygons_to_csv(
                input_path=_required(data, "input_path"),
                output_dir=_required(data, "output_dir"),
                layer_name=data.get("layer_name"),
                layer_index=int(data.get("layer_index", 0)),
                output_csv_name=data.get("output_csv_name"),
            )
            return {"output_csv": str(out_csv)}

        return _run(handler)

    @app.post("/csv/preprocess")
    def preprocess_csv():
        """
        Clean a building CSV in place (floor inference and construction-year bins).

        JSON body:
          {"csv_path": "..."}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .preprocess.building_csv import preprocess_buildings_csv_inplace

            out = preprocess_buildings_csv_inplace(_required(data, "csv_path"))
            return {"csv_path": str(out)}

        return _run(handler)

    @app.post("/idf/mass")
    def generate_mass_idfs():
        """
        Generate mass-model IDFs using server-side private templates from config.

        JSON body:
          {"config_path": "..."}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .geometry.polygons import load_building_polygons_from_csv
            from .idf.mass import generate_mass_idfs

            cfg = load_config(_required(data, "config_path"))
            paths = resolve_paths(cfg)
            buildings = load_building_polygons_from_csv(paths.buildings_csv_path)
            written = generate_mass_idfs(cfg, buildings, out_dir=paths.mass_idf_out_dir)
            return {"count": len(written), "written": [str(p) for p in written], "output_dir": str(paths.mass_idf_out_dir)}

        return _run(handler)

    @app.post("/idf/baseline")
    def baseline_idf():
        """
        Convert one mass-model IDF to one baseline IDF.

        JSON body:
          {"config_path": "...", "file_model": "...", "out_dir": null}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .idf.baseline import simulation_setup

            cfg = load_config(_required(data, "config_path"))
            paths = resolve_paths(cfg)
            out_dir = data.get("out_dir") or paths.baseline_out_dir
            out = simulation_setup(cfg, _required(data, "file_model"), out_dir=out_dir)
            return {"output_idf": str(out)}

        return _run(handler)

    @app.post("/idf/idealload")
    def idealload_idf():
        """
        Convert one baseline IDF to one IdealLoads IDF.

        JSON body:
          {"config_path": "...", "file_model": "...", "out_dir": null}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .idf.idealload import idealload_setup

            cfg = load_config(_required(data, "config_path"))
            paths = resolve_paths(cfg)
            out_dir = data.get("out_dir") or paths.idealload_out_dir
            out = idealload_setup(cfg, _required(data, "file_model"), out_dir=out_dir)
            return {"output_idf": str(out)}

        return _run(handler)

    @app.post("/simulate/idealload-batch")
    def run_idealload_batch():
        """
        Run all configured IdealLoads IDFs against all EPW files in config.

        JSON body:
          {"config_path": "..."}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .run.eplus import run_idealload_idfs_by_epw

            cfg = load_config(_required(data, "config_path"))
            paths = resolve_paths(cfg)
            if paths.weather_dir is None:
                raise ValueError("weather_dir is required in config")
            results = run_idealload_idfs_by_epw(
                cfg,
                idealload_idf_dir=paths.idealload_out_dir,
                weather_dir=paths.weather_dir,
                output_root=paths.sim_output_root,
            )
            return {"results": results}

        return _run(handler)

    @app.post("/results/summarize")
    def summarize_results():
        """
        Summarize EnergyPlus result folders to an Excel workbook.

        JSON body:
          {"results_root": "...", "output_excel_path": "..."}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .results.summary import summarize_sim_results

            df = summarize_sim_results(_required(data, "results_root"), _required(data, "output_excel_path"))
            return {"rows": int(len(df)), "output_excel_path": str(_required(data, "output_excel_path"))}

        return _run(handler)

    @app.post("/agent/run")
    def run_react_agent():
        """
        Run the ReAct agent with built-in local tools and optional user-provided external HTTP tools.

        JSON body:
          {"task": "...", "config_path": null, "max_steps": 8, "external_tools_path": null}
        """
        data = _payload()

        def handler() -> dict[str, Any]:
            from .agent.react_agent import run_agent

            return run_agent(
                task=_required(data, "task"),
                config_path=data.get("config_path"),
                max_steps=int(data.get("max_steps", 8)),
                external_tools_path=data.get("external_tools_path"),
            )

        return _run(handler)

    return app


app = create_app()


def main() -> None:
    host = os.environ.get("GIS2BEM_API_HOST", "127.0.0.1")
    port = int(os.environ.get("GIS2BEM_API_PORT", "8765"))
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()

