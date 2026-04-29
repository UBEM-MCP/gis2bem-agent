from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from geomeppy import IDF as GIDF  # noqa: F401

from ..config import WorkflowConfig
from ..geometry.polygons import BuildingPolygons
from ..paths import ensure_dirs


MATERIAL_COPY_OBJECTS: tuple[str, ...] = ("MATERIAL", "WINDOWMATERIAL:SIMPLEGLAZINGSYSTEM", "CONSTRUCTION")


@dataclass(frozen=True)
class EnvelopeSpec:
    climate_zone: str
    archetype: str  # "Residential" | "Public&Industrial"
    year_bin: str

    @property
    def roof(self) -> str:
        return f"{self.climate_zone}_{self.archetype}_{self.year_bin}_Roof"

    @property
    def ext_wall(self) -> str:
        return f"{self.climate_zone}_{self.archetype}_{self.year_bin}_ExtWall"

    @property
    def int_wall(self) -> str:
        return f"{self.climate_zone}_{self.archetype}_{self.year_bin}_IntWall"

    @property
    def floor_slab(self) -> str:
        return f"{self.climate_zone}_{self.archetype}_{self.year_bin}_FloorSlab"

    @property
    def floor_ground(self) -> str:
        return f"{self.climate_zone}_{self.archetype}_{self.year_bin}_FloorGround"

    @property
    def win(self) -> str:
        return f"{self.climate_zone}_{self.archetype}_{self.year_bin}_Win"


def set_geomeppy_idd(idd_path: str | os.PathLike) -> None:
    """
    geomeppy uses eppy under the hood and IDD can only be set once.
    This helper makes it idempotent.
    """
    from geomeppy import IDF as GIDF

    try:
        GIDF.setiddname(str(idd_path))
    except Exception:
        # eppy may raise IDDAlreadySetError; safe to ignore.
        return


def choose_wwr(usage: str, *, default: float = 0.35, residential: float = 0.30, industrial: float = 0.40) -> float:
    if usage.startswith("Residential"):
        return residential
    if usage.startswith("Industrial"):
        return industrial
    return default


def _copy_material_objects(dst: GIDF, src: GIDF) -> None:
    for obj_type in MATERIAL_COPY_OBJECTS:
        for seq, _obj in enumerate(src.idfobjects[obj_type]):
            dst.newidfobject(obj_type)
            dst.idfobjects[obj_type][seq] = src.idfobjects[obj_type][seq]


def apply_envelope_constructions(idf: GIDF, spec: EnvelopeSpec) -> None:
    for wall in idf.getsurfaces("wall"):
        if wall.Outside_Boundary_Condition == "surface":
            wall.Construction_Name = spec.int_wall
        elif wall.Outside_Boundary_Condition == "outdoors":
            wall.Construction_Name = spec.ext_wall

    for roof in idf.getsurfaces("roof"):
        roof.Construction_Name = spec.roof

    for floor in idf.getsurfaces("floor"):
        if floor.Outside_Boundary_Condition in {"ground", "outdoors"}:
            floor.Construction_Name = spec.floor_ground
        elif floor.Outside_Boundary_Condition == "surface":
            floor.Construction_Name = spec.floor_slab

    for ceiling in idf.getsurfaces("ceiling"):
        ceiling.Construction_Name = spec.floor_slab

    for window in idf.idfobjects["FENESTRATIONSURFACE:DETAILED"]:
        window.Construction_Name = spec.win


def capitalize_initial(text: str) -> str:
    return " ".join([w.capitalize() for w in str(text).split()])


def add_basic_simulation_objects(idf: GIDF, *, version: str = "23.2.0") -> None:
    idf.newidfobject("VERSION")
    idf.idfobjects["VERSION"][0].Version_Identifier = version

    idf.newidfobject("SIMULATIONCONTROL")
    sc = idf.idfobjects["SIMULATIONCONTROL"][0]
    sc.Do_Zone_Sizing_Calculation = "Yes"
    sc.Do_System_Sizing_Calculation = "Yes"
    sc.Do_Plant_Sizing_Calculation = "No"
    sc.Run_Simulation_for_Sizing_Periods = "No"
    sc.Run_Simulation_for_Weather_File_Run_Periods = "Yes"

    idf.newidfobject("BUILDING")
    b = idf.idfobjects["BUILDING"][0]
    b.North_Axis = 0
    b.Terrain = "City"

    idf.newidfobject("SHADOWCALCULATION")
    idf.newidfobject("HEATBALANCEALGORITHM")

    idf.newidfobject("TIMESTEP")
    idf.idfobjects["TIMESTEP"][0].Number_of_Timesteps_per_Hour = 1

    idf.newidfobject("CONVERGENCELIMITS")


def generate_mass_idfs(
    cfg: WorkflowConfig,
    buildings: BuildingPolygons,
    *,
    out_dir: str | os.PathLike,
) -> list[Path]:
    """
    Generate mass-model IDFs from building polygons (aligned with the notebook's `idf_generate`, but configurable).
    """
    out_dir = Path(out_dir)
    ensure_dirs(out_dir)

    set_geomeppy_idd(cfg.energyplus.idd_path)

    from geomeppy import IDF as GIDF

    idf_material_public = GIDF(str(cfg.templates.mass_public_industrial_idf))
    idf_material_dwell = GIDF(str(cfg.templates.mass_residential_idf))

    written: list[Path] = []

    for i, poly in buildings.polygons.items():
        usage = buildings.usage[i] if i < len(buildings.usage) else "Unknown"
        year_bin = buildings.year_bin[i] if i < len(buildings.year_bin) else "Unknown"
        poly_id = buildings.source_polygon_ids[i] if i < len(buildings.source_polygon_ids) else i

        file_name = f"{cfg.city_name}_{poly_id}_{usage}_{year_bin}.idf"
        dst = out_dir / file_name
        if dst.exists():
            continue

        height = float(buildings.heights[i]) if i < len(buildings.heights) else 0.0
        floors = int(buildings.floors[i]) if i < len(buildings.floors) else 0

        idf_new = GIDF()
        idf_new.new()

        coords = list(poly.exterior.coords)
        idf_new.add_block(name=f"Poly_{i}_{usage}", coordinates=coords, height=height, num_stories=floors)
        idf_new.intersect_match()

        idf_new.set_wwr(wwr=choose_wwr(usage))

        # Copy materials/constructions + set envelope constructions.
        if usage.startswith("Residential"):
            _copy_material_objects(idf_new, idf_material_dwell)
            spec = EnvelopeSpec(cfg.climate_zone, "Residential", year_bin)
        else:
            _copy_material_objects(idf_new, idf_material_public)
            spec = EnvelopeSpec(cfg.climate_zone, "Public&Industrial", year_bin)

        apply_envelope_constructions(idf_new, spec)

        # Capitalize to match the notebook behavior.
        for surface in idf_new.idfobjects["BUILDINGSURFACE:DETAILED"]:
            surface.Surface_Type = capitalize_initial(surface.Surface_Type)
            surface.Outside_Boundary_Condition = capitalize_initial(surface.Outside_Boundary_Condition)

        add_basic_simulation_objects(idf_new)
        idf_new.idfobjects["BUILDING"][0].Name = f"{cfg.city_name}_{usage}_{year_bin}_{poly_id}"

        idf_new.saveas(str(dst))
        written.append(dst)

    return written

