from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from eppy.modeleditor import IDF  # noqa: F401

from ..config import WorkflowConfig
from ..paths import ensure_dirs


def set_eppy_idd(idd_path: str | os.PathLike) -> None:
    from eppy.modeleditor import IDF

    try:
        IDF.setiddname(str(idd_path))
    except Exception:
        return


def parse_building_type_from_filename(idf_path: str | os.PathLike) -> str:
    """
    Replicates the notebook logic:
    extract building_type from the 3rd token in the filename (between the 2nd and 3rd underscores).
    Example: City_ID_Office_2005.idf -> Office
    """
    name = Path(idf_path).name
    first = name.find("_")
    second = name.find("_", first + 1)
    third = name.find("_", second + 1)
    if second == -1 or third == -1:
        return "Commercial"
    building_type = name[second + 1 : third]
    if "Residential" in building_type:
        building_type = "Residential"
    if building_type in {"Industry", "Industrial"}:
        building_type = "Industrial"
    elif building_type in {"Commercial", "Hotel"}:
        building_type = "Commercial"
    elif building_type in {"Hospital", "School"}:
        building_type = "Administration"
    return building_type


def template_idf_path(cfg: WorkflowConfig, building_type: str) -> Path:
    return (cfg.templates.templates_dir / f"Template_{building_type}.idf").resolve()


def clear_objects(idf: IDF, obj_type: str) -> None:
    objs = idf.idfobjects.get(obj_type, [])
    for _ in range(len(objs)):
        objs.pop(-1)


def replace_objects(dst: IDF, src: IDF, obj_type: str, post: Optional[Callable[[IDF, int], None]] = None) -> None:
    clear_objects(dst, obj_type)
    for i in range(len(src.idfobjects.get(obj_type, []))):
        dst.idfobjects[obj_type].append(src.idfobjects[obj_type][i])
        if post is not None:
            post(dst, i)


def set_ground_temperatures_building_surface(model_idf: IDF, temps_c: Iterable[float]) -> None:
    clear_objects(model_idf, "Site:GroundTemperature:BuildingSurface")
    model_idf.newidfobject("Site:GroundTemperature:BuildingSurface")
    obj = model_idf.idfobjects["Site:GroundTemperature:BuildingSurface"][0]
    months = [
        "January_Ground_Temperature",
        "February_Ground_Temperature",
        "March_Ground_Temperature",
        "April_Ground_Temperature",
        "May_Ground_Temperature",
        "June_Ground_Temperature",
        "July_Ground_Temperature",
        "August_Ground_Temperature",
        "September_Ground_Temperature",
        "October_Ground_Temperature",
        "November_Ground_Temperature",
        "December_Ground_Temperature",
    ]
    temps = list(temps_c)
    if len(temps) != 12:
        raise ValueError("ground temperatures must have 12 monthly values")
    for k, field in enumerate(months):
        setattr(obj, field, str(float(temps[k])))


def apply_climate_zone_schedule_tweaks(model_idf: IDF, climate_zone: str) -> None:
    """
    Notebook-aligned tweak: for HSWWZ, adjust heating/cooling setpoint schedule 'Through' fields.
    """
    if climate_zone != "HSWWZ":
        return

    for sch in model_idf.idfobjects.get("Schedule:Compact", []):
        if sch.Name == "Building_Heating_Sp_Schedule":
            sch.Field_1 = "Through: 02/01"
            sch.Field_12 = "Through: 12/15"
        elif sch.Name == "Building_Cooling_Sp_Schedule":
            sch.Field_1 = "Through: 04/30"
            sch.Field_5 = "Through: 10/30"


def simulation_setup(cfg: WorkflowConfig, file_model: str | os.PathLike, *, out_dir: Optional[str | os.PathLike] = None) -> Path:
    """
    Upgrade a "mass model" IDF into a simulation-ready baseline IDF:
    - remove unused objects
    - replace key objects using `Template_<building_type>.idf`
    - write to the baseline output directory
    """
    set_eppy_idd(cfg.energyplus.idd_path)

    file_model = Path(file_model)
    building_type = parse_building_type_from_filename(file_model)

    from eppy.modeleditor import IDF

    info_idf = IDF(str(template_idf_path(cfg, building_type)))
    model_idf = IDF(str(file_model))

    # Remove unused objects (same list as the notebook).
    for obj_type in [
        "Schedule:Day:Interval",
        "Schedule:Week:Daily",
        "Schedule:Year",
        "Schedule:Constant",
        "Material:AirGap",
        "Windowmaterial:Glazing",
        "Windowmaterial:Blind",
        "Construction:AirBoundary",
        "WindowProperty:FrameAndDivider",
        "LifeCycleCost:Parameters",
        "LifeCycleCost:NonrecurringCost",
        "LifeCycleCost:UsePriceEscalation",
        "OutdoorAir:Node",
        "Site:WaterMainsTemperature",
        "WindowMaterial:Gas",
        "ZoneHVAC:IdealLoadsAirSystem",
        "ZoneHVAC:EquipmentList",
        "ZoneHVAC:EquipmentConnections",
        "NodeList",
    ]:
        if obj_type in model_idf.idfobjects:
            clear_objects(model_idf, obj_type)

    # replace groups from template
    def _no_hvac_sizing(idf: IDF, idx: int) -> None:
        idf.idfobjects["SimulationControl"][idx].Do_HVAC_Sizing_Simulation_for_Sizing_Periods = "No"

    replace_objects(model_idf, info_idf, "SimulationControl", post=_no_hvac_sizing)
    replace_objects(model_idf, info_idf, "Timestep")
    if model_idf.idfobjects.get("Timestep"):
        model_idf.idfobjects["Timestep"][0].Number_of_Timesteps_per_Hour = 1
    replace_objects(model_idf, info_idf, "ConvergenceLimits")

    # Sizing periods: use WeatherFileDays instead of DesignDay.
    if "SizingPeriod:DesignDay" in model_idf.idfobjects:
        clear_objects(model_idf, "SizingPeriod:DesignDay")
    clear_objects(model_idf, "SizingPeriod:WeatherFileDays")
    model_idf.newidfobject("SizingPeriod:WeatherFileDays")
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][0].Name = "DesignDayWinter"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][0].Begin_Month = "1"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][0].Begin_Day_of_Month = "1"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][0].End_Month = "12"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][0].End_Day_of_Month = "31"
    model_idf.newidfobject("SizingPeriod:WeatherFileDays")
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][1].Name = "DesignDaySummer"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][1].Begin_Month = "1"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][1].Begin_Day_of_Month = "1"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][1].End_Month = "12"
    model_idf.idfobjects["SizingPeriod:WeatherFileDays"][1].End_Day_of_Month = "31"

    replace_objects(model_idf, info_idf, "RunPeriod")

    # Ground temperatures: the notebook used Xiamen fixed values; kept as defaults here (override upstream if needed).
    set_ground_temperatures_building_surface(
        model_idf, temps_c=[12.0, 13.0, 16.0, 19.5, 23.5, 27.5, 29.5, 30.0, 27.5, 23.5, 19.5, 14.0]
    )

    replace_objects(model_idf, info_idf, "ScheduleTypeLimits")
    replace_objects(model_idf, info_idf, "Schedule:Compact")
    apply_climate_zone_schedule_tweaks(model_idf, cfg.climate_zone)

    # Clear ZoneList / IdealLoads placeholders; idealload_setup will generate the real ones.
    if "ZoneList" in model_idf.idfobjects:
        clear_objects(model_idf, "ZoneList")
    if "HVACTemplate:Zone:IdealLoadsAirSystem" in model_idf.idfobjects:
        clear_objects(model_idf, "HVACTemplate:Zone:IdealLoadsAirSystem")

    for obj_type in [
        "People",
        "Lights",
        "ElectricEquipment",
        "ZoneInfiltration:DesignFlowRate",
        "DesignSpecification:OutdoorAir",
        "Sizing:Parameters",
        "Sizing:Zone",
        "ZoneControl:Thermostat",
        "ThermostatSetpoint:DualSetpoint",
        "Output:VariableDictionary",
        "Output:Constructions",
        "Output:Table:SummaryReports",
        "OutputControl:Table:Style",
        "Output:Variable",
        "Output:Meter",
        "Output:Meter:MeterFileOnly",
        "Output:SQLite",
    ]:
        if obj_type in info_idf.idfobjects:
            replace_objects(model_idf, info_idf, obj_type)

    # modify GlobalGeometryRules
    if model_idf.idfobjects.get("GlobalGeometryRules"):
        model_idf.idfobjects["GlobalGeometryRules"][0].Starting_Vertex_Position = "UpperRightCorner"

    # output path
    out_dir = Path(out_dir) if out_dir is not None else (file_model.parent / "Baseline")
    ensure_dirs(out_dir)
    out_path = out_dir / file_model.name
    model_idf.saveas(str(out_path))
    return out_path

