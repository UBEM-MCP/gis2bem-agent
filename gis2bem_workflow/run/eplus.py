from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

from ..config import WorkflowConfig
from ..paths import ensure_dirs


@dataclass(frozen=True)
class EnergyPlusRunOptions:
    annual: bool = True
    readvars: bool = True
    output_suffix: str = "D"
    expandobjects: bool = True


def scenario_name_from_epw(epw_path: Path) -> str:
    stem = epw_path.stem
    return stem.split("_")[-1] if "_" in stem else stem


def run_energyplus(
    cfg: WorkflowConfig,
    *,
    idf_path: str | Path,
    epw_path: str | Path,
    output_dir: str | Path,
    output_prefix: Optional[str] = None,
    options: Optional[EnergyPlusRunOptions] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    idf_path = Path(idf_path)
    epw_path = Path(epw_path)
    output_dir = Path(output_dir)
    ensure_dirs(output_dir)

    if options is None:
        options = EnergyPlusRunOptions()

    cmd: list[str] = [str(cfg.energyplus.energyplus_exe)]
    cmd += ["--weather", str(epw_path)]
    cmd += ["--output-directory", str(output_dir)]
    if options.annual:
        cmd += ["--annual"]
    cmd += ["--idd", str(cfg.energyplus.idd_path)]
    if options.expandobjects:
        cmd += ["--expandobjects"]
    if options.readvars:
        cmd += ["--readvars"]
    cmd += ["--output-prefix", output_prefix or idf_path.stem]
    cmd += ["--output-suffix", options.output_suffix]
    cmd += [str(idf_path)]

    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def cleanup_energyplus_outputs(out_dir: Path, idf_stem: str, suffixes: Iterable[str]) -> None:
    for suf in suffixes:
        f = out_dir / f"{idf_stem}{suf}"
        if f.exists():
            f.unlink()


def run_idealload_idfs_by_epw(
    cfg: WorkflowConfig,
    *,
    idealload_idf_dir: str | Path,
    weather_dir: str | Path,
    output_root: Optional[str | Path] = None,
    options: Optional[EnergyPlusRunOptions] = None,
    cleanup_outputs: bool = True,
) -> Dict[str, Dict[str, str]]:
    """
    Batch run: for each EPW, run all `*_Idealload.idf` in a directory.
    Returns: `{scenario_name: {idf_stem: output_dir}}`
    """
    idealload_idf_dir = Path(idealload_idf_dir)
    weather_dir = Path(weather_dir)

    idf_paths = sorted(idealload_idf_dir.glob("*_Idealload.idf"))
    if not idf_paths:
        raise FileNotFoundError(f"No *_Idealload.idf found in: {idealload_idf_dir}")

    epw_files = sorted(weather_dir.glob("*.epw"))
    if not epw_files:
        raise FileNotFoundError(f"No .epw files found in: {weather_dir}")

    output_root = Path(output_root) if output_root is not None else (idealload_idf_dir / "SimResults")
    ensure_dirs(output_root)

    unused_files_suffix = [
        ".sql",
        ".eso",
        ".csv",
        ".bnd",
        ".end",
        ".mtd",
        ".mdd",
        ".rdd",
        ".mtr",
        ".rvaudit",
        ".shd",
        ".audit",
    ]

    results: Dict[str, Dict[str, str]] = {}

    for epw_path in epw_files:
        scenario = scenario_name_from_epw(epw_path)
        scenario_root = output_root / scenario
        ensure_dirs(scenario_root)
        results[scenario] = {}

        for idf_path in idf_paths:
            idf_stem = idf_path.stem
            out_dir = scenario_root / idf_stem
            ensure_dirs(out_dir)

            run_energyplus(cfg, idf_path=idf_path, epw_path=epw_path, output_dir=out_dir, output_prefix=idf_stem, options=options)

            if cleanup_outputs:
                cleanup_energyplus_outputs(out_dir, idf_stem, unused_files_suffix)

            results[scenario][idf_stem] = str(out_dir)

    return results

