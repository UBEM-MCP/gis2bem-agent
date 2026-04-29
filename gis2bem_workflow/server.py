from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastmcp import FastMCP

from .config import as_dict, load_config
from .paths import resolve_paths


mcp = FastMCP("gis2bem-workflow")


def _ok(**data: Any) -> dict[str, Any]:
    return {"success": True, **data}


def _path_or_none(value: Optional[str]) -> Optional[Path]:
    return None if value in (None, "") else Path(value)


@mcp.tool
def inspect_config(config_path: str) -> dict[str, Any]:
    """
    Inspect a GIS2BEM workflow YAML config without running the workflow.

    Use this first when an agent needs to understand project paths, city name,
    EnergyPlus paths, template paths, and default output folders. This tool is
    read-only and does not create or modify files.

    Args:
        config_path: Absolute or relative path to a GIS2BEM workflow YAML file.

    Returns:
        A JSON object containing the raw config values and the resolved paths
        that downstream tools will use.
    """
    cfg = load_config(config_path)
    paths = resolve_paths(cfg)
    return _ok(
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


@mcp.tool
def vector_to_polygon_csv(
    input_path: str,
    output_dir: str,
    layer_name: Optional[str] = None,
    layer_index: int = 0,
    output_csv_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Convert a GIS vector polygon layer (SHP or GPKG) into the GIS2BEM polygon CSV format.

    Use this as the first data-processing step when the input is a building
    footprint vector file rather than an existing polygon CSV. The tool reads
    polygon geometry and attributes, transforms coordinates to a local UTM-based
    coordinate system, computes polygon area, and writes one CSV row per ring vertex.

    Args:
        input_path: Path to a `.shp`, `.gpkg`, or OGR-readable polygon vector file.
        output_dir: Directory where the output CSV should be written.
        layer_name: Optional GPKG layer name. If omitted, `layer_index` is used.
        layer_index: Layer index to read when `layer_name` is not provided.
        output_csv_name: Optional output CSV stem. Defaults to the input file stem.

    Returns:
        A JSON object with `output_csv`, the generated CSV path.

    Side effects:
        Creates `output_dir` if needed and writes a CSV file.
    """
    from .gis.vector_to_csv import vector_polygons_to_csv

    out_csv = vector_polygons_to_csv(
        input_path=input_path,
        output_dir=output_dir,
        layer_name=layer_name,
        layer_index=layer_index,
        output_csv_name=output_csv_name,
    )
    return _ok(output_csv=str(out_csv))


@mcp.tool
def preprocess_buildings_csv(csv_path: str) -> dict[str, Any]:
    """
    Clean a GIS2BEM building polygon CSV in place.

    Use this after `vector_to_polygon_csv` or before IDF generation when the
    building CSV may contain raw floor/year fields. The tool infers `Fnum` from
    `Height` when `Fnum == 0`, and creates `Construction_year_modified` by
    binning the `Age` column into standard year categories.

    Args:
        csv_path: Path to the building polygon CSV to modify.

    Returns:
        A JSON object containing `csv_path`.

    Side effects:
        Overwrites the CSV file in place.
    """
    from .preprocess.building_csv import preprocess_buildings_csv_inplace

    out = preprocess_buildings_csv_inplace(csv_path)
    return _ok(csv_path=str(out))


@mcp.tool
def generate_mass_idfs_from_config(config_path: str) -> dict[str, Any]:
    """
    Generate EnergyPlus mass-model IDFs from the building CSV specified in config.

    Use this after the building CSV has been created and preprocessed. The tool
    loads polygons and building attributes, creates one mass-model IDF per
    building, applies envelope constructions from the configured template IDFs,
    and writes outputs to `mass_idf_out_dir`.

    Args:
        config_path: Path to a GIS2BEM workflow YAML file. It must define
            `buildings_csv_path`, template paths, EnergyPlus IDD path, city name,
            climate zone, and `mass_idf_out_dir`.

    Returns:
        A JSON object with generated file count, file paths, and output directory.

    Side effects:
        Creates IDF files. Existing files with the same names are skipped.
    """
    from .geometry.polygons import load_building_polygons_from_csv
    from .idf.mass import generate_mass_idfs

    cfg = load_config(config_path)
    paths = resolve_paths(cfg)
    buildings = load_building_polygons_from_csv(paths.buildings_csv_path)
    written = generate_mass_idfs(cfg, buildings, out_dir=paths.mass_idf_out_dir)
    return _ok(count=len(written), written=[str(p) for p in written], output_dir=str(paths.mass_idf_out_dir))


@mcp.tool
def setup_baseline_idf(config_path: str, file_model: str, out_dir: Optional[str] = None) -> dict[str, Any]:
    """
    Convert one mass-model IDF into a simulation-ready baseline IDF.

    Use this after mass IDFs have been generated. The tool selects a
    `Template_<building_type>.idf` based on the model filename, replaces schedules,
    internal loads, sizing, output, and simulation-control objects, and writes a
    baseline IDF.

    Args:
        config_path: Path to a GIS2BEM workflow YAML file.
        file_model: Path to one mass-model IDF.
        out_dir: Optional output directory. If omitted, `baseline_out_dir` from
            config is used.

    Returns:
        A JSON object with `output_idf`.

    Side effects:
        Writes one baseline IDF.
    """
    from .idf.baseline import simulation_setup

    cfg = load_config(config_path)
    paths = resolve_paths(cfg)
    target_dir = _path_or_none(out_dir) or paths.baseline_out_dir
    out = simulation_setup(cfg, file_model, out_dir=target_dir)
    return _ok(output_idf=str(out))


@mcp.tool
def setup_idealload_idf(config_path: str, file_model: str, out_dir: Optional[str] = None) -> dict[str, Any]:
    """
    Add IdealLoads HVAC templates to one baseline IDF.

    Use this after `setup_baseline_idf`. The tool creates ZoneList objects,
    adds `HVACTemplate:Zone:IdealLoadsAirSystem` objects for matching zones, and
    adjusts `Sizing:Zone` supply-air temperature inputs.

    Args:
        config_path: Path to a GIS2BEM workflow YAML file.
        file_model: Path to one baseline IDF.
        out_dir: Optional output directory. If omitted, `idealload_out_dir` from
            config is used.

    Returns:
        A JSON object with `output_idf`.

    Side effects:
        Writes one `_Idealload.idf` file.
    """
    from .idf.idealload import idealload_setup

    cfg = load_config(config_path)
    paths = resolve_paths(cfg)
    target_dir = _path_or_none(out_dir) or paths.idealload_out_dir
    out = idealload_setup(cfg, file_model, out_dir=target_dir)
    return _ok(output_idf=str(out))


@mcp.tool
def run_idealload_batch(config_path: str) -> dict[str, Any]:
    """
    Run all `*_Idealload.idf` files against all EPW weather files in the configured weather folder.

    Use this only when the user explicitly wants to run EnergyPlus simulations.
    It can be slow because it launches EnergyPlus once per `(idf, epw)` pair.
    The tool writes simulation outputs into `sim_output_root`, grouped by weather
    scenario and IDF stem.

    Args:
        config_path: Path to a GIS2BEM workflow YAML file with `idealload_out_dir`,
            `weather_dir`, `sim_output_root`, `energyplus_exe`, and `idd_path`.

    Returns:
        A nested mapping `{scenario_name: {idf_stem: output_dir}}`.

    Side effects:
        Runs EnergyPlus processes and writes simulation result folders.
    """
    from .run.eplus import run_idealload_idfs_by_epw

    cfg = load_config(config_path)
    paths = resolve_paths(cfg)
    if paths.weather_dir is None:
        raise ValueError("weather_dir is required in config")

    results = run_idealload_idfs_by_epw(
        cfg,
        idealload_idf_dir=paths.idealload_out_dir,
        weather_dir=paths.weather_dir,
        output_root=paths.sim_output_root,
    )
    return _ok(results=results)


@mcp.tool
def summarize_results(results_root: str, output_excel_path: str) -> dict[str, Any]:
    """
    Summarize EnergyPlus simulation outputs into one Excel workbook.

    Use this after simulations have produced `*-meter.csv` and matching
    `*-table.htm` or `*-table.html` files. The tool parses floor area from the
    HTML table, converts hourly energy from J to W/kWh, and reports PLI
    (`W/sqm`) and EUI (`kWh/sqm`) metrics per building/scenario.

    Args:
        results_root: Root folder containing simulation result folders, usually
            `<sim_output_root>/<scenario>/<idf_stem>/...`.
        output_excel_path: Path to the summary Excel workbook to write.

    Returns:
        A JSON object with output path and number of summary rows.

    Side effects:
        Writes an Excel file.
    """
    from .results.summary import summarize_sim_results

    df = summarize_sim_results(results_root, output_excel_path)
    return _ok(rows=int(len(df)), output_excel_path=str(output_excel_path))


@mcp.tool
def run_react_agent(
    task: str,
    config_path: Optional[str] = None,
    max_steps: int = 8,
    external_tools_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run the ReAct agent for GIS2BEM workflow orchestration.

    The agent uses an LLM for planning and tool selection. Built-in GIS2BEM
    workflow actions are executed through local Python functions. Optionally,
    the agent can also load user-provided external HTTP tools from a JSON/YAML
    file, enabling integration with open-source or private API services without
    embedding credentials in this package.

    Args:
        task: Natural language instruction for the agent.
        config_path: Optional workflow YAML path. Provide this when the task
            depends on project paths or IDF generation.
        max_steps: Maximum ReAct action/observation steps.
        external_tools_path: Optional JSON/YAML file defining user-provided
            external HTTP tools.

    Returns:
        Final answer and a structured list of intermediate ReAct steps.
    """
    from .agent.react_agent import run_agent

    return run_agent(
        task=task,
        config_path=config_path,
        max_steps=max_steps,
        external_tools_path=external_tools_path,
    )


def main() -> None:
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()

