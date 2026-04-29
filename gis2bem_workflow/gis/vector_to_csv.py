from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import pyproj  # noqa: F401


@dataclass(frozen=True)
class RingPoint:
    x: float
    y: float
    fid: int
    ring_type: str  # "exterior" | "interior"
    ring_id: int
    point_id: int
    attributes: list


def open_vector_layer(input_path: str | os.PathLike, layer_name: str | None = None, layer_index: int = 0):
    from osgeo import ogr

    input_path = str(input_path)
    ext = os.path.splitext(input_path)[1].lower()

    driver_name = None
    if ext == ".shp":
        driver_name = "ESRI Shapefile"
    elif ext == ".gpkg":
        driver_name = "GPKG"

    if driver_name is not None:
        driver = ogr.GetDriverByName(driver_name)
        if driver is None:
            raise RuntimeError(f"OGR driver not available: {driver_name}")
        data_source = driver.Open(input_path, 0)
    else:
        data_source = ogr.Open(input_path, 0)

    if not data_source:
        raise RuntimeError(f"Failed to open vector file: {input_path}")

    if ext == ".gpkg":
        layer = data_source.GetLayerByName(layer_name) if layer_name else None
        if layer is None:
            layer = data_source.GetLayer(layer_index)
    else:
        layer = data_source.GetLayer()

    if layer is None:
        raise RuntimeError(
            f"Failed to get layer: {input_path} (layer_name={layer_name}, layer_index={layer_index})"
        )

    return data_source, layer


def layer_crs(layer) -> pyproj.CRS:
    import pyproj

    ogr_sr = layer.GetSpatialRef()
    if ogr_sr is None:
        return pyproj.CRS("EPSG:4326")
    return pyproj.CRS(ogr_sr.ExportToWkt())


def unique_field_names(layer) -> list[str]:
    layer_definition = layer.GetLayerDefn()
    field_names = [layer_definition.GetFieldDefn(i).GetName() for i in range(layer_definition.GetFieldCount())]

    counter: dict[str, int] = {}
    unique: list[str] = []
    for name in field_names:
        if name in counter:
            counter[name] += 1
            unique.append(f"{name}_{counter[name]-1}")
        else:
            counter[name] = 1
            unique.append(name)
    return unique


def utm_crs_from_first_point(source: pyproj.CRS, x: float, y: float) -> pyproj.CRS:
    import pyproj

    wgs84 = pyproj.CRS("EPSG:4326")
    to_wgs84 = pyproj.Transformer.from_crs(source, wgs84, always_xy=True)
    lon, lat = to_wgs84.transform(x, y)

    utm_zone = int((lon + 180) // 6) + 1
    is_northern = lat >= 0
    return pyproj.CRS(f"EPSG:{32600 + utm_zone}" if is_northern else f"EPSG:{32700 + utm_zone}")


def iter_polygon_ring_points(layer, field_names: Sequence[str]) -> list[list[RingPoint]]:
    from osgeo import ogr

    coords: list[list[RingPoint]] = []
    layer.ResetReading()

    for feature in layer:
        geom = feature.GetGeometryRef()
        if geom is None:
            continue

        attributes = [feature.GetField(i) for i in range(len(field_names))]

        if geom.GetGeometryType() == ogr.wkbMultiPolygon:
            polygons = geom
        else:
            polygons = [geom]

        for polygon in polygons:
            polygon_coords: list[RingPoint] = []

            exterior_ring = polygon.GetGeometryRef(0)
            if exterior_ring is None:
                continue

            ext_points: list[RingPoint] = []
            for point_id in range(exterior_ring.GetPointCount()):
                x, y, *_ = exterior_ring.GetPoint(point_id)
                ext_points.append(
                    RingPoint(
                        x=float(x),
                        y=float(y),
                        fid=int(feature.GetFID()),
                        ring_type="exterior",
                        ring_id=0,
                        point_id=int(point_id),
                        attributes=list(attributes),
                    )
                )

            # Reverse exterior ring order to match the notebook behavior.
            ext_points.reverse()
            polygon_coords.extend(ext_points)

            for ring_id in range(1, polygon.GetGeometryCount()):
                interior_ring = polygon.GetGeometryRef(ring_id)
                if interior_ring is None:
                    continue
                for point_id in range(interior_ring.GetPointCount()):
                    x, y, *_ = interior_ring.GetPoint(point_id)
                    polygon_coords.append(
                        RingPoint(
                            x=float(x),
                            y=float(y),
                            fid=int(feature.GetFID()),
                            ring_type="interior",
                            ring_id=int(ring_id),
                            point_id=int(point_id),
                            attributes=list(attributes),
                        )
                    )

            coords.append(polygon_coords)

    return coords


def polygon_area_utm(points_xy: Sequence[tuple[float, float]]) -> float:
    from osgeo import ogr

    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in points_xy:
        ring.AddPoint(float(x), float(y))
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(ring)
    return float(polygon.GetArea())


def write_polygon_csv(
    out_csv: str | os.PathLike,
    field_names: Sequence[str],
    transformed: Sequence[Sequence[tuple[tuple[float, float], RingPoint]]],
    area_by_polygon: Sequence[float],
) -> None:
    header = ["PolygonID", "Type", "RingID", "PointID", "X", "Y", "Area (sqm)"] + list(field_names)
    out_csv = str(out_csv)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)

        for polygon_i, polygon_points in enumerate(transformed):
            area = area_by_polygon[polygon_i]
            min_x = min(pt_xy[0][0] for pt_xy in polygon_points)
            min_y = min(pt_xy[0][1] for pt_xy in polygon_points)

            for (x, y), rp in polygon_points:
                w.writerow(
                    [
                        rp.fid,
                        rp.ring_type,
                        rp.ring_id,
                        rp.point_id,
                        float(x - min_x),
                        float(y - min_y),
                        area,
                        *rp.attributes,
                    ]
                )


def vector_polygons_to_csv(
    input_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    layer_name: Optional[str] = None,
    layer_index: int = 0,
    output_csv_name: Optional[str] = None,
) -> Path:
    """
    Read polygon features from shp/gpkg and write a CSV:
    - one row per vertex (exterior/interior rings), including attribute fields
    - coordinates are transformed to an inferred UTM zone and shifted to local coordinates (min x/y -> 0)
    - polygon area is computed in sqm (UTM)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(input_path)
    stem = output_csv_name or input_path.stem
    out_csv = output_dir / f"{stem}.csv"

    data_source, layer = open_vector_layer(str(input_path), layer_name=layer_name, layer_index=layer_index)
    try:
        import pyproj

        src_crs = layer_crs(layer)
        fields = unique_field_names(layer)
        coords = iter_polygon_ring_points(layer, fields)
        if not coords:
            raise ValueError(f"No polygons were read from: {input_path}")

        first = coords[0][0]
        utm = utm_crs_from_first_point(src_crs, first.x, first.y)
        transformer = pyproj.Transformer.from_crs(src_crs, utm, always_xy=True)

        transformed: list[list[tuple[tuple[float, float], RingPoint]]] = []
        areas: list[float] = []

        for polygon_coords in coords:
            tpoly: list[tuple[tuple[float, float], RingPoint]] = []
            for rp in polygon_coords:
                x2, y2 = transformer.transform(rp.x, rp.y)
                tpoly.append(((float(x2), float(y2)), rp))

            # Area uses the same approach as the notebook: all points are added into a LinearRing.
            areas.append(polygon_area_utm([xy for xy, _ in tpoly]))
            transformed.append(tpoly)

        write_polygon_csv(out_csv, fields, transformed, areas)
        return out_csv
    finally:
        # Release OGR resources
        data_source = None

