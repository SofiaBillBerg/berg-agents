# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.


"""This script generates Mermaid diagrams for berg_agents and its plugin packages.

It parses Python files to extract classes, functions, and their calls, then creates
flowcharts that illustrate internal and external dependencies of each submodule,
as well as a high-level overview of each package.
"""

import ast
import os

from ast import AST
from collections import defaultdict
from pathlib import Path
from typing import Any, TypedDict


MERMAID_THEME_FLOWCHART = """
    %% Plasma Pastel Theme Configuration %%
    classDef internalNode fill:#e8daff,stroke:#b594f0,stroke-width:2px,color:#4a2685,font-family:'Segoe UI',sans-serif;
    classDef externalNode fill:#ffd6f5,stroke:#936cd4,stroke-width:2px,color:#4a2685,font-family:'Segoe UI',sans-serif;
    classDef moduleNode fill:#d6f0ff,stroke:#936cd4,stroke-width:2px,color:#4a2685,font-family:'Segoe UI',sans-serif;

    linkStyle default stroke:#936cd4,stroke-width:2px;
"""

IGNORED_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    "tests",
    "docs"}


class PackageConfig(TypedDict):
    name: str
    path: Path


PACKAGES: list[PackageConfig] = [
    {"name": "berg_agents", "path": Path("./berg_agents")},
    {"name": "plugin_system", "path": Path("./plugin_system")},
    {"name": "shared_todo", "path": Path("./berg_plugins/shared-todo")}]


def sanitize_id(name: str) -> str:
    """Ersätt bindestreck och punkter med understreck för giltiga Mermaid-ID:n."""
    return name.replace("-", "_").replace(".", "_")


def parse_python_components(
    file_path: Path, source_dir: Path, pkg_name: str
) -> list[dict[str, Any]]:  # ruff: ignore[complex-structure]
    """Parse a Python file and extract classes, functions, and their relationships."""
    with Path(file_path).open(encoding="utf-8") as f:
        try:
            node = ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            return []

    rel_path = file_path.relative_to(source_dir)
    parts = list(rel_path.parts)

    # If the file is in a subdirectory with the same name as the package (t.ex. plugin_system/plugin_system/fil.py), remove the first part
    if len(parts) > 1 and sanitize_id(parts[0]) == pkg_name:
        parts = parts[1:]

    # Determine the submodule name based on the file's relative path
    if len(parts) > 1:
        raw_submodule = parts[0]
    else:
        raw_submodule = (
            file_path.stem if file_path.stem != "__init__" else "core"
        )

    submodule = sanitize_id(raw_submodule)
    components = []

    def find_calls(code_node: ast.AST) -> list[str]:
        """Find all function calls within a given AST node."""
        calls = []
        child: AST
        for child in ast.walk(code_node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
        return list(set(calls))

    for child in node.body:
        if isinstance(child, ast.ClassDef):
            class_methods = []
            class_vars = []
            class_calls = []

            for item in child.body:
                if isinstance(item, ast.FunctionDef):
                    method_calls = find_calls(item)
                    class_methods.append({
                        "name": item.name,
                        "calls": method_calls})
                    class_calls.extend(method_calls)
                elif isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    class_vars.append(item.target.id)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            class_vars.append(t.id)

            components.append({
                "type": "class",
                "name": child.name,
                "submodule": submodule,
                "variables": class_vars,
                "methods": class_methods,
                "calls": list(set(class_calls)),
                "bases": [ast.unparse(b) for b in child.bases]})

        elif isinstance(child, ast.FunctionDef):
            func_calls = find_calls(child)
            components.append({
                "type": "function",
                "name": child.name,
                "submodule": submodule,
                "calls": func_calls,
                "variables": [],
                "methods": [],
                "bases": []})

    return components


def process_package(pkg_name: str, source_dir: Path, output_dir: Path) -> None:  # ruff: ignore[complex-structure]
    """Generate Mermaid diagrams for a specific package directory."""
    if not source_dir.exists():
        print(f"⚠️ Skipping '{pkg_name}': directory not found at {source_dir}")
        return
    all_components = []
    for root, dirs, files in os.walk(source_dir):
        # Filter out ignored directories and hidden directories
        dirs[:] = [
            d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")
        ]

        for file in files:
            if file.endswith(".py") and not file.startswith("."):
                file_path = Path(root) / file
                comps = parse_python_components(file_path, source_dir, pkg_name)
                all_components.extend(comps)

    if not all_components:
        print(f"ℹ️ No Python components found in '{pkg_name}'.")
        return

    known_entities = {c["name"]: c["submodule"] for c in all_components}
    for c in all_components:
        if c["type"] == "class":
            for m in c["methods"]:
                known_entities[m["name"]] = c["submodule"]

    modules_map = defaultdict(list)
    for c in all_components:
        modules_map[c["submodule"]].append(c)

    # ====================================================================
    # A. GENERATE RENDER-SAFE PERSPECTIVE MAPS PER SUBDIRECTORY
    # ====================================================================
    for mod_name, mod_comps in modules_map.items():
        mmd_lines = [
            "flowchart LR",
            f"    %% Rich Component map focused on {pkg_name}.{mod_name} %%"]

        external_dependencies = set()
        internal_nodes = []

        mmd_lines.extend((
            f"    subgraph Internal_Structures [{pkg_name}.{mod_name} components]",
            "        direction TB",
        ))

        for c in mod_comps:
            if c["type"] == "class":
                header = f"class {c['name']}"
                if c["bases"]:
                    header += f" ({', '.join(c['bases'])})"

                body_parts = [header, "===================="]
                if c["variables"]:
                    body_parts.append("Attributes:")
                    body_parts.extend([f"  - {v}" for v in c["variables"][:5]])
                if c["methods"]:
                    body_parts.append("Methods:")
                    body_parts.extend([
                        f"  + {m['name']}()" for m in c["methods"][:6]
                    ])

                full_label = "\\n".join(body_parts)
                mmd_lines.append(f'        {c["name"]}["{full_label}"]')
                internal_nodes.append(c["name"])
            else:
                mmd_lines.append(
                    f'        {c["name"]}["function {c["name"]}()"]'
                )
                internal_nodes.append(c["name"])
        mmd_lines.append("    end")

        # Execution flow linkages
        for c in mod_comps:
            for call in c["calls"]:
                if call in known_entities:
                    if known_entities[call] != mod_name:
                        external_dependencies.add(call)
                    mmd_lines.append(f"    {c['name']} --> {call}")

        # External dependencies layout box
        if external_dependencies:
            mmd_lines.append(
                "    subgraph External_Connections [External Components Called]"
            )
            for ext in external_dependencies:
                ext_mod = known_entities[ext]
                mmd_lines.append(
                    f'        {ext}["{ext}() \\n (from {ext_mod})"]'
                )
            mmd_lines.append("    end")

        # Styles injection
        mmd_lines.append(MERMAID_THEME_FLOWCHART)
        for name in internal_nodes:
            mmd_lines.append(f"    class {name} internalNode;")
        for name in external_dependencies:
            mmd_lines.append(f"    class {name} externalNode;")

        out_file = output_dir / f"packages_{pkg_name}.{mod_name}.mmd"
        out_file.write_text("\n".join(mmd_lines), encoding="utf-8")
        print(
            f"✓ Created text-safe rich perspective map for: {pkg_name}.{mod_name}"
        )

    # ====================================================================
    # B. GENERATE HIGH-LEVEL ARCHITECTURAL OVERVIEW
    # ====================================================================
    global_lines = [
        "flowchart LR",
        f"    %% High-Level Subdirectory Overview for {pkg_name} %%"]

    for mod_name in modules_map:
        global_lines.append(f'    mod_{mod_name}["{pkg_name}.{mod_name}"]')

    cross_module_edges = set()
    for c in all_components:
        for call in c["calls"]:
            if call in known_entities:
                target_mod = known_entities[call]
                if c["submodule"] != target_mod:
                    cross_module_edges.add((c["submodule"], target_mod))

    for source_mod, target_mod in cross_module_edges:
        global_lines.append(f"    mod_{source_mod} --> mod_{target_mod}")

    global_lines.append(MERMAID_THEME_FLOWCHART)
    for mod_name in modules_map:
        global_lines.append(f"    class mod_{mod_name} moduleNode;")

    global_file = output_dir / f"packages_{pkg_name}.mmd"
    global_file.write_text("\n".join(global_lines), encoding="utf-8")
    print(f"✓ Created global architectural overview map for {pkg_name}!")


def generate_mermaid() -> None:
    """Generate Mermaid diagrams for all configured packages."""
    output_dir = Path("./docs/visualizations")
    output_dir.mkdir(parents=True, exist_ok=True)

    for pkg in PACKAGES:
        print(f"\n--- Processing package: {pkg['name']} ---")
        process_package(pkg["name"], pkg["path"], output_dir)


if __name__ == "__main__":
    generate_mermaid()
