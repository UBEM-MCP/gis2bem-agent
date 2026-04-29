from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd  # noqa: F401


def parse_floorage_from_table_html(table_path: str | Path) -> float:
    """
    Notebook-aligned parser: find the first "Total" area value within the PERFORMANCE section.
    """
    table_path = Path(table_path)
    from lxml import etree

    table_html = etree.parse(str(table_path), etree.HTMLParser())
    table_str = etree.tostring(table_html, encoding="unicode", method="html")

    pos_perf = table_str.find("PERFORMANCE")
    if pos_perf == -1:
        raise ValueError(f"PERFORMANCE section not found: {table_path}")

    seg = table_str[pos_perf:]
    pos_total = seg.find("Total</td>")
    if pos_total == -1:
        raise ValueError(f"Total</td> not found within PERFORMANCE section: {table_path}")

    seg2 = seg[pos_total:]
    m = re.search(r"<td align=\\\"right\\\">\\s*([0-9.]+)\\s*</td>", seg2)
    if not m:
        raise ValueError(f"Failed to parse floor area value: {table_path}")
    return float(m.group(1))


def parse_building_type_from_idf_stem(idf_stem: str) -> str:
    parts = idf_stem.split("_")
    if len(parts) < 3:
        return "Unknown"
    bt = parts[2]
    if bt == "Residential" and len(parts) >= 4 and parts[3].isdigit():
        return f"Residential_{parts[3]}"
    return bt


def summarize_sim_results(results_root: str | Path, output_excel_path: str | Path):
    """
    Traverse `results_root` for `*-meter.csv` files, parse matching `*-table.htm(l)`, and write a summary Excel.
    Expected layout: `<results_root>/<scenario>/<idf_stem>/...`
    """
    import pandas as pd

    results_root = Path(results_root)
    output_excel_path = Path(output_excel_path)

    meter_files = sorted(results_root.rglob("*-meter.csv"))
    if not meter_files:
        raise FileNotFoundError(f"No *-meter.csv found under: {results_root}")

    rows: list[dict] = []

    for meter_path in meter_files:
        idf_stem = meter_path.name[: -len("-meter.csv")]
        table_path = meter_path.with_name(idf_stem + "-table.htm")
        if not table_path.exists():
            alt = meter_path.with_name(idf_stem + "-table.html")
            if alt.exists():
                table_path = alt
            else:
                continue

        try:
            rel = meter_path.relative_to(results_root).parts
            scenario = rel[0] if len(rel) >= 3 else "Unknown"
        except Exception:
            scenario = "Unknown"

        try:
            floorage = parse_floorage_from_table_html(table_path)
        except Exception:
            floorage = float("nan")

        df = pd.read_csv(meter_path, low_memory=False)
        if df.shape[1] <= 1:
            continue

        value_cols = [c for c in df.columns if c.strip().lower() != "date/time"]
        values_J = df[value_cols].apply(pd.to_numeric, errors="coerce")
        values_W = values_J / 3600.0

        max_load_W = values_W.max(axis=0)
        energy_kWh = values_W.sum(axis=0) / 1000.0

        row: dict[str, object] = {
            "scenario": scenario,
            "idf_stem": idf_stem,
            "building_type": parse_building_type_from_idf_stem(idf_stem),
            "floorage_m2": floorage,
        }

        for col in value_cols:
            base = col
            if "[J](Hourly)" in base:
                base = base[: base.index("[J](Hourly)")].strip()

            if pd.notna(floorage) and floorage > 0:
                row[f"{base} (PLI, W/sqm)"] = float(max_load_W[col] / floorage)
                row[f"{base} (EUI, kWh/sqm)"] = float(energy_kWh[col] / floorage)
            else:
                row[f"{base} (PLI, W/sqm)"] = float("nan")
                row[f"{base} (EUI, kWh/sqm)"] = float("nan")

        rows.append(row)

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.sort_values(["scenario", "idf_stem"], inplace=True, ignore_index=True)

    output_excel_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_excel_path) as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)

    return summary_df

