from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class YearBinning:
    bins: tuple[int, int, int, int] = (1980, 1995, 2005, 2015)

    def bin_year(self, year: float | int | None) -> int:
        if year is None:
            return self.bins[0]
        try:
            y = int(float(year))
        except Exception:
            return self.bins[0]

        if y < self.bins[1]:
            return self.bins[0]
        if self.bins[1] <= y < self.bins[2]:
            return self.bins[1]
        if self.bins[2] <= y < self.bins[3]:
            return self.bins[2]
        return self.bins[3]


def infer_floors_from_height(height_m: float, floor_height_m: float = 3.0) -> int:
    if height_m is None:
        return 0
    try:
        return int(round(float(height_m) / float(floor_height_m)))
    except Exception:
        return 0


def preprocess_buildings_csv_inplace(
    csv_path: str | Path,
    *,
    year_col: str = "Age",
    floors_col: str = "Fnum",
    height_col: str = "Height",
    floor_height_m: float = 3.0,
    out_year_col: str = "Construction_year_modified",
    year_binning: Optional[YearBinning] = None,
) -> Path:
    """
    Minimal cleaning for a buildings CSV exported from GIS:
    - if `Fnum==0` and `Height` exists, infer floors by Height / 3m
    - bin `Age` (or `year_col`) into {1980, 1995, 2005, 2015}
    - write back to the same file (inplace)
    """
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path, low_memory=False)

    if year_binning is None:
        year_binning = YearBinning()

    if floors_col in df.columns and height_col in df.columns:
        def _fix_fnum(row):
            try:
                f = float(row[floors_col])
            except Exception:
                f = 0.0
            if f != 0:
                return int(round(f))
            return infer_floors_from_height(row.get(height_col), floor_height_m=floor_height_m)

        df[floors_col] = df.apply(_fix_fnum, axis=1)

    if year_col in df.columns:
        df[out_year_col] = df[year_col].apply(year_binning.bin_year)
    else:
        df[out_year_col] = year_binning.bins[0]

    df.to_csv(csv_path, index=False)
    return csv_path

