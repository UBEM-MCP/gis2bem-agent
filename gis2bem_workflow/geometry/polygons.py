from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from shapely.geometry import Polygon


@dataclass(frozen=True)
class BuildingPolygons:
    polygons: Dict[int, Polygon]
    heights: List[float]
    floors: List[int]
    usage: List[str]
    year_bin: List[str]
    source_polygon_ids: List[int]


def _to_year_str(series: pd.Series) -> list[str]:
    s = pd.to_numeric(series, errors="coerce").round(0).astype("Int64").astype(str)
    return s.tolist()


def load_building_polygons_from_csv(
    csv_path: str | Path,
    *,
    polygon_id_col: str = "PolygonID",
    ring_type_col: str = "Type",
    x_col: str = "X",
    y_col: str = "Y",
    height_col: str = "Height",
    floors_col: str = "Fnum",
    usage_col: str = "usage",
    year_col: str = "Construction_year_modified",
) -> BuildingPolygons:
    """
    Load exterior rings from a CSV produced by `vector_polygons_to_csv()` and build shapely polygons.
    Only `Type == 'exterior'` points are used; one polygon per PolygonID.
    """
    df = pd.read_csv(csv_path, low_memory=False)
    if polygon_id_col not in df.columns:
        raise ValueError(f"Missing required column '{polygon_id_col}': {csv_path}")

    polygons: Dict[int, Polygon] = {}

    polygon_ids = df[polygon_id_col].unique().tolist()
    for new_id, poly_id in enumerate(polygon_ids):
        pts = df[df[polygon_id_col] == poly_id]
        ext = pts[pts[ring_type_col] == "exterior"]
        coords = [(float(r[x_col]), float(r[y_col])) for _, r in ext.iterrows()]
        if len(coords) >= 3:
            polygons[new_id] = Polygon(shell=coords)

    by_poly = df.drop_duplicates(subset=polygon_id_col)

    heights = by_poly[height_col].astype(float, errors="ignore").tolist() if height_col in by_poly.columns else []
    floors = (
        pd.to_numeric(by_poly[floors_col], errors="coerce").fillna(0).astype(int).tolist()
        if floors_col in by_poly.columns
        else []
    )
    usage = by_poly[usage_col].astype(str).tolist() if usage_col in by_poly.columns else []
    year_bin = _to_year_str(by_poly[year_col]) if year_col in by_poly.columns else []
    source_polygon_ids = pd.to_numeric(by_poly[polygon_id_col], errors="coerce").fillna(-1).astype(int).tolist()

    return BuildingPolygons(
        polygons=polygons,
        heights=heights,
        floors=floors,
        usage=usage,
        year_bin=year_bin,
        source_polygon_ids=source_polygon_ids,
    )

