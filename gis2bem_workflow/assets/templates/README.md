## Private Template Directory

This directory is intentionally excluded from Git for `*.idf` and `*.idf.bak` files.

The workflow can use private EnergyPlus template IDFs in two ways:

1. Place the private template files here on the machine that runs the API/MCP server.
2. Point `templates_dir`, `mass_residential_idf`, and `mass_public_industrial_idf`
   in your YAML config to another private location.

Do not commit proprietary or unpublished IDF templates to the public repository.

