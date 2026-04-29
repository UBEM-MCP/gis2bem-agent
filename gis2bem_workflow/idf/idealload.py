from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from eppy.modeleditor import IDF  # noqa: F401

from ..config import WorkflowConfig
from ..paths import ensure_dirs
from .baseline import parse_building_type_from_filename, set_eppy_idd


def thermal_zone_prototype_names(building_type: str) -> list[str]:
    if building_type == "Office":
        return ["Office_room"]
    if building_type == "Educational":
        return ["Educational_room"]
    if building_type == "Commercial":
        return ["Commercial_room"]
    if building_type in {"Industry", "Industrial"}:
        return ["Industrial_room"]
    if building_type == "Administration":
        return ["Administration_room"]
    if building_type in {"Residential", "Residential_1", "Residential_2", "Residential_3"}:
        return ["Residential_room"]
    if building_type == "Transport":
        return ["Transport_room"]
    return ["Commercial_room"]


def zone_match_tokens(file_name: str, building_type: str) -> Optional[list[str]]:
    if building_type == "Commercial" and "_Hotel_" in file_name:
        return ["Commercial", "Hotel"]
    if building_type == "Administration" and ("_Hospital_" in file_name or "_School_" in file_name):
        return ["Administration", "Hospital", "School"]
    if building_type == "Industrial":
        return ["Industrial", "Industry"]
    return None


def _add_zone_to_zonelist(zonelist_obj, zone_name: str, idx: int) -> None:
    setattr(zonelist_obj, f"Zone_{idx}_Name", zone_name)


def idealload_setup(
    cfg: WorkflowConfig,
    file_model: str | os.PathLike,
    *,
    out_dir: Optional[str | os.PathLike] = None,
    heating_availability_schedule: str = "ConditionedTime",
    cooling_availability_schedule: str = "ConditionedTime",
) -> Path:
    """
    Generate IdealLoads objects on top of a baseline model:
    - create ZoneList
    - create HVACTemplate:Zone:IdealLoadsAirSystem
    - tweak Sizing:Zone supply air temperature input method
    """
    set_eppy_idd(cfg.energyplus.idd_path)

    file_model = Path(file_model)
    building_type = parse_building_type_from_filename(file_model)
    file_name = file_model.name

    from eppy.modeleditor import IDF

    model_idf = IDF(str(file_model))

    tokens = zone_match_tokens(file_name, building_type)
    prototype_list = thermal_zone_prototype_names(building_type)

    if "ZoneList" in model_idf.idfobjects:
        model_idf.idfobjects["ZoneList"].clear()
    if "HVACTemplate:Zone:IdealLoadsAirSystem" in model_idf.idfobjects:
        model_idf.idfobjects["HVACTemplate:Zone:IdealLoadsAirSystem"].clear()

    num_total = 0
    for j, proto in enumerate(prototype_list):
        model_idf.newidfobject("ZoneList")
        zonelist = model_idf.idfobjects["ZoneList"][j]
        zonelist.Name = proto + "s"

        base_token = proto.split("_")[0]
        num_in_list = 0
        for zone in model_idf.idfobjects.get("Zone", []):
            zone_name = zone.Name
            matched = any(t in zone_name for t in tokens) if tokens is not None else (base_token in zone_name)
            if not matched:
                continue

            num_total += 1
            num_in_list += 1
            _add_zone_to_zonelist(zonelist, zone_name, num_in_list)

            model_idf.newidfobject("HVACTemplate:Zone:IdealLoadsAirSystem")
            hvac = model_idf.idfobjects["HVACTemplate:Zone:IdealLoadsAirSystem"][num_total - 1]
            hvac.Zone_Name = zone_name
            hvac.Heating_Availability_Schedule_Name = heating_availability_schedule
            hvac.Cooling_Availability_Schedule_Name = cooling_availability_schedule

    for sz in model_idf.idfobjects.get("Sizing:Zone", []):
        sz.Zone_Cooling_Design_Supply_Air_Temperature_Input_Method = "SupplyAirTemperature"
        sz.Zone_Cooling_Design_Supply_Air_Temperature = "12.8"
        sz.Zone_Heating_Design_Supply_Air_Temperature_Input_Method = "SupplyAirTemperature"
        sz.Zone_Heating_Design_Supply_Air_Temperature = "50"

    out_dir = Path(out_dir) if out_dir is not None else (file_model.parent / "Idealload")
    ensure_dirs(out_dir)

    out_path = out_dir / f"{file_model.stem}_Idealload.idf"
    model_idf.saveas(str(out_path))
    return out_path

