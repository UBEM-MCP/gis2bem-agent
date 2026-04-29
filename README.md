## GIS2BEM Workflow Platform

**End-to-end climate-aware agentic workflow for urban building energy modelling.**

GIS2BEM Workflow Platform connects GIS building data with EnergyPlus model generation, weather-driven simulation, result analysis, and AI-assisted orchestration. It provides a Python workflow package, a Model Context Protocol (MCP) server, a Flask API, and a ReAct-style agent that can coordinate both built-in modelling tools and user-provided external APIs.

### Capabilities

- **GIS-to-EnergyPlus automation**: convert building footprint layers into model-ready geometry and attributes.
- **Urban building model generation**: produce EnergyPlus mass models and simulation-ready baseline/IdealLoads IDFs.
- **Climate-aware configuration**: manage climate zones, EPW weather data, EnergyPlus paths, template locations, and output folders through YAML configuration.
- **AI-assisted orchestration**: expose workflow operations through MCP, HTTP, Python functions, and a ReAct-style agent.
- **Extensible external services**: allow users to connect their own HTTP APIs for weather intelligence, geospatial enrichment, data services, or model-hosted reasoning.
- **Deployment-oriented asset management**: keep runtime-specific template assets on the deployment machine or a private service while publishing the workflow code.

### Architecture

- `gis2bem_workflow/`: main Python package
  - `config.py`: config dataclasses + YAML loader
  - `paths.py`: path resolution helpers
  - `gis/`: vector (shp/gpkg) → polygon CSV
  - `preprocess/`: building CSV cleaning (floors/year bins)
  - `geometry/`: CSV → shapely polygons + attributes
  - `idf/`: mass idf generation + baseline setup + ideal loads setup
  - `run/`: batch EnergyPlus execution (by EPW)
  - `results/`: summarize `*-meter.csv` + `*-table.htm(l)` to Excel
  - `agent/`: ReAct-style agent orchestration over the local workflow tools
- `gis2bem_workflow/assets/templates/`: private template mount point for deployment-specific IDF assets
- `examples/`: example configuration and workflow entry points

### Installation

```bash
git clone https://github.com/UBEM-MCP/<repository-name>.git
cd <repository-name>
pip install -e .
```

For the full GIS and EnergyPlus workflow, install the optional dependencies required by your platform:

```bash
pip install -r requirements.txt
```

GDAL/OGR is often best installed with Conda on Windows:

```bash
conda install -c conda-forge gdal
```

### Configuration

Copy the example configuration and update project-specific paths:

- `examples/config.example.yaml` → `config.yaml`

Key fields include:

- `project_root`: workflow root directory
- `city_name`: city or study-area identifier
- `climate_zone`: climate-zone label used by model templates
- `energyplus.energyplus_exe`: EnergyPlus executable path
- `energyplus.idd_path`: EnergyPlus IDD path
- `templates.*`: runtime template paths
- `buildings_csv_path`: processed building polygon CSV
- `weather_dir`: EPW weather directory
- `sim_output_root`: simulation output root

### Python Workflow

Run the configured workflow script:

```bash
python examples/run_pipeline.py --config config.yaml
```

Individual stages are also available as Python functions under:

- `gis2bem_workflow.gis`
- `gis2bem_workflow.preprocess`
- `gis2bem_workflow.geometry`
- `gis2bem_workflow.idf`
- `gis2bem_workflow.run`
- `gis2bem_workflow.results`

### ReAct Agent

The ReAct-style agent uses an LLM for planning and tool selection, while workflow execution is performed through structured Python tools and optional user-provided HTTP tools.

Configure an OpenAI-compatible model with:

- `GIS2BEM_LLM_BASE_URL` or `OPENAI_BASE_URL`
- `GIS2BEM_LLM_API_KEY` or `OPENAI_API_KEY`
- `GIS2BEM_LLM_MODEL` or `OPENAI_MODEL`

Run from CLI:

```bash
python -m gis2bem_workflow.agent.react_agent \
  --config config.yaml \
  --task "Inspect the project configuration and recommend the next modelling step"
```

#### External API tools

The agent can load user-provided HTTP tools from a JSON or YAML file. This enables integration with open-source or private services, such as weather intelligence, geospatial processing, metadata enrichment, city information services, or model-hosted reasoning endpoints. API endpoints and credentials are supplied by the user at runtime.

Example `external_tools.yaml`:

```yaml
tools:
  - name: weather_context
    description: "Retrieve climate or weather context from a user-provided service."
    method: POST
    url: "https://your-service.example.com/weather/context"
    headers:
      Authorization:
        env: WEATHER_API_KEY
        prefix: "Bearer "
    input_schema:
      city: "string, required"
      year: "integer, optional"
```

Run the agent with external tools:

```bash
python -m gis2bem_workflow.agent.react_agent \
  --config config.yaml \
  --external-tools external_tools.yaml \
  --task "Inspect the project and enrich it with weather context"
```

The same `external_tools_path` parameter is available through MCP (`run_react_agent`) and Flask (`POST /agent/run`).

### MCP server

Run the MCP server with stdio transport:

```bash
python -m gis2bem_workflow.server
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "gis2bem-workflow": {
      "command": "python",
      "args": ["-m", "gis2bem_workflow.server"]
    }
  }
}
```

### Flask API

Run the HTTP API:

```bash
python -m gis2bem_workflow.api
```

Default address:

- `http://127.0.0.1:8765`

You can override it with environment variables:

- `GIS2BEM_API_HOST`
- `GIS2BEM_API_PORT`

Useful endpoints:

- `GET /health`
- `POST /config/inspect`
- `POST /gis/vector-to-csv`
- `POST /csv/preprocess`
- `POST /idf/mass`
- `POST /idf/baseline`
- `POST /idf/idealload`
- `POST /simulate/idealload-batch`
- `POST /results/summarize`
- `POST /agent/run`

Example request:

```bash
curl -X POST http://127.0.0.1:8765/config/inspect \
  -H "Content-Type: application/json" \
  -d "{\"config_path\":\"D:/path/to/config.yaml\"}"
```

### Runtime Assets

EnergyPlus installations, IDD files, weather files, and template IDFs are configured at runtime. Template IDFs can be placed on the machine that runs the MCP/Flask API, or referenced from another private location through the YAML configuration. This supports public distribution of the workflow code while allowing deployment-specific modelling assets to remain under the control of the user or organisation.

### Licence

This project is released under the MIT Licence.

