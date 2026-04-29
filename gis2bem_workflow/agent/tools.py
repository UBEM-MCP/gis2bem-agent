from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import as_dict, load_config
from ..paths import resolve_paths


ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    func: ToolFn


def ok(**data: Any) -> dict[str, Any]:
    return {"success": True, **data}


def required(args: dict[str, Any], key: str) -> Any:
    value = args.get(key)
    if value in (None, ""):
        raise ValueError(f"Missing required argument: {key}")
    return value


def inspect_config_tool(args: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config(required(args, "config_path"))
    paths = resolve_paths(cfg)
    return ok(
        config=as_dict(cfg),
        resolved_paths={
            "project_root": str(paths.project_root),
            "buildings_csv_path": str(paths.buildings_csv_path),
            "mass_idf_out_dir": str(paths.mass_idf_out_dir),
            "baseline_out_dir": str(paths.baseline_out_dir),
            "idealload_out_dir": str(paths.idealload_out_dir),
            "weather_dir": None if paths.weather_dir is None else str(paths.weather_dir),
            "sim_output_root": str(paths.sim_output_root),
        },
    )


def vector_to_polygon_csv_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..gis.vector_to_csv import vector_polygons_to_csv

    out_csv = vector_polygons_to_csv(
        input_path=required(args, "input_path"),
        output_dir=required(args, "output_dir"),
        layer_name=args.get("layer_name"),
        layer_index=int(args.get("layer_index", 0)),
        output_csv_name=args.get("output_csv_name"),
    )
    return ok(output_csv=str(out_csv))


def preprocess_buildings_csv_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..preprocess.building_csv import preprocess_buildings_csv_inplace

    out = preprocess_buildings_csv_inplace(required(args, "csv_path"))
    return ok(csv_path=str(out))


def generate_mass_idfs_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..geometry.polygons import load_building_polygons_from_csv
    from ..idf.mass import generate_mass_idfs

    cfg = load_config(required(args, "config_path"))
    paths = resolve_paths(cfg)
    buildings = load_building_polygons_from_csv(paths.buildings_csv_path)
    written = generate_mass_idfs(cfg, buildings, out_dir=paths.mass_idf_out_dir)
    return ok(count=len(written), written=[str(p) for p in written], output_dir=str(paths.mass_idf_out_dir))


def setup_baseline_idf_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..idf.baseline import simulation_setup

    cfg = load_config(required(args, "config_path"))
    paths = resolve_paths(cfg)
    out_dir = args.get("out_dir") or paths.baseline_out_dir
    out = simulation_setup(cfg, required(args, "file_model"), out_dir=out_dir)
    return ok(output_idf=str(out))


def setup_idealload_idf_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..idf.idealload import idealload_setup

    cfg = load_config(required(args, "config_path"))
    paths = resolve_paths(cfg)
    out_dir = args.get("out_dir") or paths.idealload_out_dir
    out = idealload_setup(cfg, required(args, "file_model"), out_dir=out_dir)
    return ok(output_idf=str(out))


def run_idealload_batch_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..run.eplus import run_idealload_idfs_by_epw

    cfg = load_config(required(args, "config_path"))
    paths = resolve_paths(cfg)
    if paths.weather_dir is None:
        raise ValueError("weather_dir is required in config")
    results = run_idealload_idfs_by_epw(
        cfg,
        idealload_idf_dir=paths.idealload_out_dir,
        weather_dir=paths.weather_dir,
        output_root=paths.sim_output_root,
    )
    return ok(results=results)


def summarize_results_tool(args: dict[str, Any]) -> dict[str, Any]:
    from ..results.summary import summarize_sim_results

    output_excel_path = required(args, "output_excel_path")
    df = summarize_sim_results(required(args, "results_root"), output_excel_path)
    return ok(rows=int(len(df)), output_excel_path=str(output_excel_path))


def default_tools() -> dict[str, AgentTool]:
    tools = [
        AgentTool(
            name="inspect_config",
            description=(
                "Read a workflow YAML config and return resolved paths. "
                "Use this first to understand where inputs, templates, EnergyPlus, and outputs are located. "
                "Read-only."
            ),
            input_schema={"config_path": "string, required"},
            func=inspect_config_tool,
        ),
        AgentTool(
            name="vector_to_polygon_csv",
            description=(
                "Convert a SHP/GPKG building footprint layer into the GIS2BEM polygon CSV. "
                "Writes one row per polygon vertex. Use only when the user starts from vector data."
            ),
            input_schema={
                "input_path": "string, required",
                "output_dir": "string, required",
                "layer_name": "string|null, optional",
                "layer_index": "integer, optional, default 0",
                "output_csv_name": "string|null, optional",
            },
            func=vector_to_polygon_csv_tool,
        ),
        AgentTool(
            name="preprocess_buildings_csv",
            description=(
                "Clean a building polygon CSV in place. It infers missing floors from Height and "
                "creates Construction_year_modified from Age bins. Use before IDF generation."
            ),
            input_schema={"csv_path": "string, required"},
            func=preprocess_buildings_csv_tool,
        ),
        AgentTool(
            name="generate_mass_idfs_from_config",
            description=(
                "Generate one EnergyPlus mass-model IDF per building using the config's building CSV "
                "and private template paths. Use after CSV preprocessing."
            ),
            input_schema={"config_path": "string, required"},
            func=generate_mass_idfs_tool,
        ),
        AgentTool(
            name="setup_baseline_idf",
            description=(
                "Convert one mass-model IDF into one simulation-ready baseline IDF using Template_<building_type>.idf. "
                "Use after mass IDFs exist."
            ),
            input_schema={"config_path": "string, required", "file_model": "string, required", "out_dir": "string|null, optional"},
            func=setup_baseline_idf_tool,
        ),
        AgentTool(
            name="setup_idealload_idf",
            description=(
                "Add IdealLoads HVAC objects to one baseline IDF. Use after setup_baseline_idf."
            ),
            input_schema={"config_path": "string, required", "file_model": "string, required", "out_dir": "string|null, optional"},
            func=setup_idealload_idf_tool,
        ),
        AgentTool(
            name="run_idealload_batch",
            description=(
                "Run all *_Idealload.idf files against all EPW files in the configured weather folder. "
                "This launches EnergyPlus and may be slow; use only when simulation is explicitly requested."
            ),
            input_schema={"config_path": "string, required"},
            func=run_idealload_batch_tool,
        ),
        AgentTool(
            name="summarize_results",
            description=(
                "Summarize EnergyPlus result folders containing *-meter.csv and *-table.htm(l) files into Excel."
            ),
            input_schema={"results_root": "string, required", "output_excel_path": "string, required"},
            func=summarize_results_tool,
        ),
    ]
    return {tool.name: tool for tool in tools}


def render_tools_for_prompt(tools: dict[str, AgentTool]) -> str:
    lines: list[str] = []
    for tool in tools.values():
        lines.append(f"- {tool.name}: {tool.description}\n  Input schema: {tool.input_schema}")
    return "\n".join(lines)

