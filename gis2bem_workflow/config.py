from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class EnergyPlusConfig:
    energyplus_exe: Path
    idd_path: Path


@dataclass(frozen=True)
class TemplatesConfig:
    templates_dir: Path
    mass_residential_idf: Path
    mass_public_industrial_idf: Path


@dataclass(frozen=True)
class WorkflowConfig:
    project_root: Path
    city_name: str
    climate_zone: str

    energyplus: EnergyPlusConfig
    templates: TemplatesConfig

    # Optional, stage-specific paths (defaults can be derived)
    input_vector_path: Optional[Path] = None
    input_vector_layer_name: Optional[str] = None
    input_vector_layer_index: int = 0

    buildings_csv_path: Optional[Path] = None
    mass_idf_out_dir: Optional[Path] = None
    baseline_out_dir: Optional[Path] = None
    idealload_out_dir: Optional[Path] = None

    weather_dir: Optional[Path] = None
    sim_output_root: Optional[Path] = None


def _as_path(p: Any, base: Path) -> Path:
    if p is None:
        raise ValueError("path is required but got None")
    path = Path(p)
    return path if path.is_absolute() else (base / path)


def load_config(config_path: str | Path) -> WorkflowConfig:
    """
    Load workflow configuration from YAML.

    Dependency: pyyaml (easy to swap to JSON if preferred).
    """
    config_path = Path(config_path)
    base = config_path.parent.resolve()

    try:
        import yaml  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Missing dependency 'pyyaml'. Install via: pip install pyyaml") from e

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"Invalid config format: {config_path}")

    project_root = _as_path(data.get("project_root", "."), base)
    city_name = str(data["city_name"])
    climate_zone = str(data.get("climate_zone", "HSWWZ"))

    eplus = data.get("energyplus", {})
    templates = data.get("templates", {})

    energyplus = EnergyPlusConfig(
        energyplus_exe=_as_path(eplus["energyplus_exe"], base),
        idd_path=_as_path(eplus["idd_path"], base),
    )

    templates_dir = _as_path(templates.get("templates_dir", "gis2bem_workflow/assets/templates"), base)
    templates_cfg = TemplatesConfig(
        templates_dir=templates_dir,
        mass_residential_idf=_as_path(
            templates.get("mass_residential_idf", templates_dir / "Template_Mass_Residential.idf"), base
        ),
        mass_public_industrial_idf=_as_path(
            templates.get(
                "mass_public_industrial_idf", templates_dir / "Template_Mass_Public&Industrial.idf"
            ),
            base,
        ),
    )

    def opt_path(key: str) -> Optional[Path]:
        v = data.get(key)
        return None if v in (None, "") else _as_path(v, base)

    return WorkflowConfig(
        project_root=project_root,
        city_name=city_name,
        climate_zone=climate_zone,
        energyplus=energyplus,
        templates=templates_cfg,
        input_vector_path=opt_path("input_vector_path"),
        input_vector_layer_name=data.get("input_vector_layer_name"),
        input_vector_layer_index=int(data.get("input_vector_layer_index", 0)),
        buildings_csv_path=opt_path("buildings_csv_path"),
        mass_idf_out_dir=opt_path("mass_idf_out_dir"),
        baseline_out_dir=opt_path("baseline_out_dir"),
        idealload_out_dir=opt_path("idealload_out_dir"),
        weather_dir=opt_path("weather_dir"),
        sim_output_root=opt_path("sim_output_root"),
    )


def as_dict(cfg: WorkflowConfig) -> dict[str, Any]:
    def p(x: Optional[Path]) -> Optional[str]:
        return None if x is None else str(x)

    return {
        "project_root": str(cfg.project_root),
        "city_name": cfg.city_name,
        "climate_zone": cfg.climate_zone,
        "energyplus": {"energyplus_exe": str(cfg.energyplus.energyplus_exe), "idd_path": str(cfg.energyplus.idd_path)},
        "templates": {
            "templates_dir": str(cfg.templates.templates_dir),
            "mass_residential_idf": str(cfg.templates.mass_residential_idf),
            "mass_public_industrial_idf": str(cfg.templates.mass_public_industrial_idf),
        },
        "input_vector_path": p(cfg.input_vector_path),
        "input_vector_layer_name": cfg.input_vector_layer_name,
        "input_vector_layer_index": cfg.input_vector_layer_index,
        "buildings_csv_path": p(cfg.buildings_csv_path),
        "mass_idf_out_dir": p(cfg.mass_idf_out_dir),
        "baseline_out_dir": p(cfg.baseline_out_dir),
        "idealload_out_dir": p(cfg.idealload_out_dir),
        "weather_dir": p(cfg.weather_dir),
        "sim_output_root": p(cfg.sim_output_root),
    }

