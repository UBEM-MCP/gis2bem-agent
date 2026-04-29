# Input Requirements

This document explains what users need to provide when running the GIS2BEM Workflow Platform with their own GIS, EnergyPlus, weather, and template files.

The workflow is designed to accept project-specific data at runtime. Public repositories should not include private IDF templates, licensed weather datasets, proprietary GIS layers, or local EnergyPlus installations.

## Required Inputs

| Input | Purpose | Typical Format | Config Field |
| --- | --- | --- | --- |
| Building footprint layer | Source building geometry and attributes | `.gpkg` or `.shp` | `input_vector_path` |
| Building layer name or index | Selects the layer inside a GeoPackage | string or integer | `input_vector_layer_name`, `input_vector_layer_index` |
| EnergyPlus executable | Runs EnergyPlus simulations | `energyplus.exe` or platform equivalent | `energyplus.energyplus_exe` |
| EnergyPlus IDD file | Defines the EnergyPlus object schema | `Energy+.idd` | `energyplus.idd_path` |
| Mass-model template IDFs | Provide constructions and materials for generated mass models | `.idf` | `templates.mass_residential_idf`, `templates.mass_public_industrial_idf` |
| Baseline template IDFs | Provide schedules, loads, output objects, and building-type assumptions | `.idf` | `templates.templates_dir` |
| Weather files | Drive EnergyPlus simulation scenarios | `.epw` | `weather_dir` |

## Building Footprint GPKG or SHP

The first stage reads polygon features from a GIS vector file and exports a vertex-level CSV used by later geometry and IDF generation stages.

### Supported File Types

- GeoPackage (`.gpkg`)
- ESRI Shapefile (`.shp`)

For GeoPackage inputs, provide either:

- `input_vector_layer_name`: the exact layer name to read, or
- `input_vector_layer_index`: the zero-based layer index, used when no layer name is provided.

For Shapefile inputs, the workflow reads the default layer.

### Geometry Requirements

The building layer should contain:

- Polygon or MultiPolygon geometries.
- One feature per building footprint, or one feature per modelling footprint.
- Valid exterior rings with at least three points.
- A valid coordinate reference system. If no CRS is present, the workflow assumes `EPSG:4326`.

The workflow automatically:

- reads exterior and interior rings,
- transforms coordinates to an inferred UTM CRS,
- shifts each polygon to local coordinates where the minimum x/y values start at zero,
- calculates polygon area in square metres,
- exports one CSV row per polygon vertex.

### Recommended Attribute Fields

The workflow can preserve any GIS attributes, but the downstream modelling stages expect the following fields by default:

| Field | Required For | Expected Type | Notes |
| --- | --- | --- | --- |
| `Height` | Mass IDF generation | number, metres | Used as the extrusion height for the building mass. |
| `Fnum` | Mass IDF generation | integer | Number of floors. If `Fnum` is zero and `Height` exists, the preprocessing stage can infer floors as `Height / 3 m`. |
| `Age` | Construction archetype selection | year-like number | Binned into `1980`, `1995`, `2005`, or `2015` and written as `Construction_year_modified`. |
| `usage` | Building type and envelope selection | string | Used in generated IDF filenames and in residential/non-residential envelope selection. |

Recommended `usage` values include:

- `Residential`
- `Residential_1`
- `Residential_2`
- `Residential_3`
- `Office`
- `Commercial`
- `Hotel`
- `Industrial`
- `Industry`
- `Administration`
- `Hospital`
- `School`
- `Transport`

Unknown or project-specific values may still be processed, but they can fall back to generic non-residential assumptions in later stages.

## Exported Building CSV

If users already have a prepared CSV, they can bypass the vector export stage and set `buildings_csv_path` directly.

The CSV should contain one row per polygon vertex.

### Required Geometry Columns

| Column | Description |
| --- | --- |
| `PolygonID` | Source building or footprint identifier. |
| `Type` | Ring type. Use `exterior` for outer rings. Interior rings may be present but are not currently used for mass geometry creation. |
| `RingID` | Ring identifier within the polygon. |
| `PointID` | Vertex order within the ring. |
| `X` | Local x coordinate in metres. |
| `Y` | Local y coordinate in metres. |
| `Area (sqm)` | Polygon area in square metres. |

### Required Modelling Columns

| Column | Description |
| --- | --- |
| `Height` | Building height in metres. |
| `Fnum` | Number of floors. |
| `usage` | Building usage/type label. |
| `Construction_year_modified` | Construction archetype year, normally one of `1980`, `1995`, `2005`, `2015`. |

If the CSV still contains raw `Age` instead of `Construction_year_modified`, run the preprocessing stage before IDF generation.

## EnergyPlus Installation

Users must provide a local EnergyPlus installation that is compatible with the IDF templates and generated models.

The configuration must include:

```yaml
energyplus:
  energyplus_exe: /path/to/EnergyPlus/energyplus.exe
  idd_path: /path/to/EnergyPlus/Energy+.idd
```

The current templates and generated model objects are intended for EnergyPlus `23.2.0` unless users adapt the templates and IDD path for another version.

## IDF Template Files

Template IDFs are runtime assets. They should be supplied by each user or organisation and referenced in `config.yaml`.

### Mass-Model Templates

Mass-model generation requires:

```yaml
templates:
  mass_residential_idf: /path/to/Template_Mass_Residential.idf
  mass_public_industrial_idf: /path/to/Template_Mass_Public&Industrial.idf
```

These templates must contain EnergyPlus material and construction objects used by generated building envelopes:

- `MATERIAL`
- `WINDOWMATERIAL:SIMPLEGLAZINGSYSTEM`
- `CONSTRUCTION`

The construction names should follow this pattern:

```text
<climate_zone>_<archetype>_<year_bin>_<element>
```

Examples:

```text
HSWWZ_Residential_2005_Roof
HSWWZ_Residential_2005_ExtWall
HSWWZ_Residential_2005_IntWall
HSWWZ_Residential_2005_FloorSlab
HSWWZ_Residential_2005_FloorGround
HSWWZ_Residential_2005_Win
HSWWZ_Public&Industrial_2005_Roof
HSWWZ_Public&Industrial_2005_ExtWall
```

Supported envelope elements are:

- `Roof`
- `ExtWall`
- `IntWall`
- `FloorSlab`
- `FloorGround`
- `Win`

The `climate_zone` value must match the value in `config.yaml`, and `year_bin` must match the binned construction year in the building CSV.

### Baseline Templates

Baseline setup reads building-type-specific files from `templates.templates_dir`.

Expected filenames are:

```text
Template_Residential.idf
Template_Commercial.idf
Template_Industrial.idf
Template_Administration.idf
Template_Office.idf
Template_Transport.idf
```

Additional templates can be used if the workflow is extended with additional building-type mappings.

Baseline templates should provide the EnergyPlus objects that the workflow copies into each generated model, including:

- `SimulationControl`
- `Timestep`
- `ConvergenceLimits`
- `RunPeriod`
- `ScheduleTypeLimits`
- `Schedule:Compact`
- `People`
- `Lights`
- `ElectricEquipment`
- `ZoneInfiltration:DesignFlowRate`
- `DesignSpecification:OutdoorAir`
- `Sizing:Parameters`
- `Sizing:Zone`
- `ZoneControl:Thermostat`
- `ThermostatSetpoint:DualSetpoint`
- output reporting objects such as `Output:Variable`, `Output:Meter`, and `Output:Table:SummaryReports`

The IdealLoads stage expects zones in the generated model to include building-type tokens such as `Residential`, `Commercial`, `Industrial`, `Administration`, `Office`, or `Transport`.

## User-Provided IDFs as Workflow Inputs

Users may also provide their own IDF files for later workflow stages instead of generating every IDF from GIS.

### Existing Mass IDFs for Baseline Setup

To use an existing mass IDF as input to the baseline setup stage, the file should:

- be readable by the configured EnergyPlus IDD,
- contain valid geometry objects and zones,
- use a filename that includes the building type between the second and third underscores.

Recommended filename pattern:

```text
<city_name>_<polygon_id>_<building_type>_<year_bin>.idf
```

Example:

```text
ExampleCity_102_Office_2005.idf
ExampleCity_205_Residential_1995.idf
```

The workflow uses the `building_type` token to select `Template_<building_type>.idf` from `templates.templates_dir`.

### Existing Baseline IDFs for IdealLoads Setup

To use an existing baseline IDF as input to the IdealLoads stage, the file should:

- contain `Zone` objects,
- contain `Sizing:Zone` objects if sizing settings need to be adjusted,
- use zone names that include recognisable building-type tokens such as `Office`, `Commercial`, `Industrial`, `Administration`, `Residential`, or `Transport`,
- use the same filename pattern as the mass IDF where possible, so the building type can be inferred consistently.

### Existing IdealLoads IDFs for Simulation

To use existing IdealLoads IDFs directly in the EnergyPlus simulation stage:

- place them in the directory configured as `idealload_out_dir`, or pass that directory to the relevant API/tool call,
- use the suffix `*_Idealload.idf`,
- ensure each file is compatible with the configured `Energy+.idd`,
- ensure the weather-independent simulation objects are already present in the model.

Example:

```text
ExampleCity_102_Office_2005_Idealload.idf
```

## Weather Files

Weather files should be placed in the configured `weather_dir`.

Requirements:

- File extension: `.epw`
- One EPW file per simulation scenario
- Compatible with the location and intended climate assumptions of the study

The workflow derives a scenario name from each EPW filename. If the filename contains underscores, the final underscore-separated token is used as the scenario name.

Example:

```text
Xiamen_TMY.epw        -> TMY
Xiamen_Heatwave.epw   -> Heatwave
```

## Example Configuration

```yaml
project_root: .
city_name: ExampleCity
climate_zone: HSWWZ

energyplus:
  energyplus_exe: /path/to/EnergyPlus/energyplus.exe
  idd_path: /path/to/EnergyPlus/Energy+.idd

templates:
  templates_dir: /path/to/private/templates
  mass_residential_idf: /path/to/private/templates/Template_Mass_Residential.idf
  mass_public_industrial_idf: /path/to/private/templates/Template_Mass_Public&Industrial.idf

input_vector_path: /path/to/buildings.gpkg
input_vector_layer_name: buildings
input_vector_layer_index: 0

buildings_csv_path: /path/to/output/buildings.csv
mass_idf_out_dir: /path/to/output/Mass
baseline_out_dir: /path/to/output/Baseline
idealload_out_dir: /path/to/output/Idealload

weather_dir: /path/to/weather
sim_output_root: /path/to/output/SimResults
```

## Pre-Run Checklist

Before running the workflow, confirm that:

- The GPKG/SHP opens successfully in QGIS, GDAL, or another GIS tool.
- The selected layer contains polygon or multipolygon features.
- `Height`, `Fnum`, `Age`, and `usage` fields are present or intentionally remapped in code.
- EnergyPlus executable and `Energy+.idd` paths point to the same EnergyPlus installation.
- Mass-model template IDFs contain the required construction names for the configured climate zone and year bins.
- Baseline template filenames match the building type names used by the workflow.
- EPW files are present in `weather_dir`.
- Output directories are writable.

## Data Privacy and Licensing

Users are responsible for ensuring that GIS files, IDF templates, weather files, and any third-party data can be used and redistributed under their own project requirements. Private project assets should be referenced through configuration rather than committed to a public repository.
