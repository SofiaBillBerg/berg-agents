"""This script generates Mermaid diagrams for the berg_agents package, providing a visual representation of its structure and relationships.

It parses Python files to extract classes, functions, and their calls, then creates flowcharts that illustrate the internal and external dependencies of each submodule, as well as a high-level overview of the entire package. The diagrams are saved in the docs/visualizations directory for easy access and review.
"""

import ast
import os

from ast import AST
from collections import defaultdict
from pathlib import Path
from typing import Any


MERMAID_THEME_FLOWCHART = """
    %% Plasma Pastel Theme Configuration %%
    classDef internalNode fill:#e8daff,stroke:#b594f0,stroke-width:2px,color:#4a2685,font-family:'Segoe UI',sans-serif;
    classDef externalNode fill:#ffd6f5,stroke:#936cd4,stroke-width:2px,color:#4a2685,font-family:'Segoe UI',sans-serif;
    classDef moduleNode fill:#d6f0ff,stroke:#936cd4,stroke-width:2px,color:#4a2685,font-family:'Segoe UI',sans-serif;

    linkStyle default stroke:#936cd4,stroke-width:2px;
"""


def parse_python_components(
    file_path: Path, source_dir: Path
) -> list[dict[str, Any]]:  # ruff: ignore[complex-structure]
    """Parse a Python file and extract classes, functions, and their relationships.

    :param file_path: Path to the Python file to parse.
    :param source_dir: Directory containing the Python files.
    :return: List of parsed components.
    :rtype: list[dict[str, Any]]
    """
    with Path(file_path).open(encoding="utf-8") as f:
        try:
            node = ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            return []

    rel_path = file_path.relative_to(source_dir)
    submodule = rel_path.parts[0] if len(rel_path.parts) > 1 else "core"

    components = []

    def find_calls(code_node: ast.AST) -> list[str]:
        """A helper function to find all function calls within a given AST node.

        :param code_node: The AST node to analyze for function calls.
        :return: A list of function names called within the node.
        :rtype: list[str]
        """
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
                        "calls": method_calls,
                    })
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
                "bases": [ast.unparse(b) for b in child.bases],
            })

        elif isinstance(child, ast.FunctionDef):
            func_calls = find_calls(child)
            components.append({
                "type": "function",
                "name": child.name,
                "submodule": submodule,
                "calls": func_calls,
                "variables": [],
                "methods": [],
                "bases": [],
            })

    return components


def generate_mermaid() -> None:  # ruff: ignore[complex-structure]
    """Generate Mermaid diagrams for the berg_agents package, including detailed submodule maps and a high-level architectural overview.

    The diagrams are saved in the docs/visualizations directory.

    :return: None
    """
    output_dir = Path("./docs/visualizations")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_dir = Path("./berg_agents")
    all_components = []

    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".py") and not file.startswith("."):
                file_path = Path(root) / file
                comps = parse_python_components(file_path, source_dir)
                all_components.extend(comps)

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
            f"    %% Rich Component map focused on berg_agents.{mod_name} %%",
        ]

        external_dependencies = set()
        internal_nodes = []

        mmd_lines.append(
            f"    subgraph Internal_Structures [berg_agents.{mod_name} components]"
        )
        mmd_lines.append("        direction TB")

        for c in mod_comps:
            if c["type"] == "class":
                # FIX: We use clean Markdown lines (character-based layout) instead of breaking HTML tags
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

                # Double quotes and clean string compilation prevents rendering dropouts
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

        out_file = output_dir / f"packages_berg_agents.{mod_name}.mmd"
        out_file.write_text("\n".join(mmd_lines), encoding="utf-8")
        print(
            f"✓ Created text-safe rich perspective map for: berg_agents.{mod_name}"
        )

    # ====================================================================
    # B. GENERATE HIGH-LEVEL ARCHITECTURAL OVERVIEW
    # ====================================================================
    global_lines = [
        "flowchart LR",
        "    %% High-Level Subdirectory Overview %%",
    ]

    for mod_name in modules_map.keys():
        global_lines.append(f'    mod_{mod_name}["berg_agents.{mod_name}"]')

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
    for mod_name in modules_map.keys():
        global_lines.append(f"    class mod_{mod_name} moduleNode;")

    global_file = output_dir / "packages_berg_agents.mmd"
    global_file.write_text("\n".join(global_lines), encoding="utf-8")
    print("✓ Created global architectural overview map!")


if __name__ == "__main__":
    generate_mermaid()
