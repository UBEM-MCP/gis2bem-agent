from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import WorkflowConfig


@dataclass(frozen=True)
class ResolvedPaths:
    project_root: Path

    buildings_csv_path: Path
    mass_idf_out_dir: Path
    baseline_out_dir: Path
    idealload_out_dir: Path

    weather_dir: Optional[Path]
    sim_output_root: Path


def resolve_paths(cfg: WorkflowConfig) -> ResolvedPaths:
    root = cfg.project_root.resolve()

    buildings_csv_path = cfg.buildings_csv_path or (root / f"{cfg.city_name}.csv")
    mass_idf_out_dir = cfg.mass_idf_out_dir or (root / cfg.city_name)
    baseline_out_dir = cfg.baseline_out_dir or (mass_idf_out_dir / "Baseline")
    idealload_out_dir = cfg.idealload_out_dir or (mass_idf_out_dir / "Idealload")

    weather_dir = cfg.weather_dir
    sim_output_root = cfg.sim_output_root or (idealload_out_dir / "SimResults")

    return ResolvedPaths(
        project_root=root,
        buildings_csv_path=Path(buildings_csv_path),
        mass_idf_out_dir=Path(mass_idf_out_dir),
        baseline_out_dir=Path(baseline_out_dir),
        idealload_out_dir=Path(idealload_out_dir),
        weather_dir=None if weather_dir is None else Path(weather_dir),
        sim_output_root=Path(sim_output_root),
    )


def ensure_dirs(*dirs: Path) -> None:
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

