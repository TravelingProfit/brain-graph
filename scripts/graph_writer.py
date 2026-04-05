#!/usr/bin/env python3
"""
Write extracted entities to ArcadeDB via MCP API.
Reads JSON extraction files and creates nodes + edges.

Usage: python graph_writer.py <extraction.json> [extraction2.json ...]
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg


def execute(sql):
    result = cfg.arcadedb_execute(sql)
    is_error = result.get("result", {}).get("content", [{}])[0].get("type") == "text" and result.get("result", {}).get("isError", False)
    if is_error:
        error_text = result["result"]["content"][0]["text"]
        return {"error": error_text}
    return result


def query(sql):
    try:
        return {"records": cfg.arcadedb_query(sql)}
    except Exception as e:
        return {"error": str(e)}


def escape_sql(s):
    """Escape single quotes for SQL strings."""
    if s is None:
        return ""
    return str(s).replace("'", "\\'").replace("\\", "\\\\") if "'" in str(s) else str(s)


def sql_str(s):
    """Wrap in SQL quotes with escaping."""
    return f"'{escape_sql(s)}'"


def check_exists(node_type, name):
    """Check if a node exists by name."""
    result = query(f"SELECT count(*) as cnt FROM {node_type} WHERE name = {sql_str(name)}")
    try:
        return result["records"][0]["cnt"] > 0
    except Exception:
        return False


def create_artifact(a):
    if not a:
        return
    result = query(f"SELECT count(*) as cnt FROM Artifact WHERE content_hash = {sql_str(a['content_hash'])}")
    try:
        if result["records"][0]["cnt"] > 0:
            print(f"  SKIP artifact (exists): {a['name']}")
            return
    except Exception:
        pass

    ts = a.get("source_timestamp", "")
    ts_clause = f", source_timestamp = '{ts}'" if ts else ""
    sql = (f"INSERT INTO Artifact SET name = {sql_str(a['name'])}, "
           f"source_type = {sql_str(a.get('source_type', 'project-doc'))}, "
           f"source_path = {sql_str(a.get('source_path', ''))}, "
           f"content_hash = {sql_str(a['content_hash'])}, "
           f"summary = {sql_str(a.get('summary', ''))}, "
           f"created_at = sysdate(){ts_clause}, "
           f"metadata = {json.dumps(a.get('metadata', {}))}")
    result = execute(sql)
    if "error" in result:
        print(f"  ERROR creating artifact {a['name']}: {result['error']}")
    else:
        print(f"  + Artifact: {a['name']}")


def create_nodes(node_type, nodes):
    created = 0
    skipped = 0
    for n in (nodes or []):
        name = n["name"]
        if check_exists(node_type, name):
            execute(f"UPDATE {node_type} SET updated_at = sysdate() WHERE name = {sql_str(name)}")
            skipped += 1
            continue

        if node_type == "Concept":
            aliases_str = json.dumps(n.get("aliases", []))
            sql = (f"INSERT INTO Concept SET name = {sql_str(name)}, "
                   f"description = {sql_str(n.get('description', ''))}, "
                   f"created_at = sysdate(), updated_at = sysdate(), "
                   f"source = {sql_str(n.get('source', 'project-doc'))}, "
                   f"aliases = {aliases_str}, metadata = {json.dumps(n.get('metadata', {}))}")
        elif node_type == "Decision":
            alts = json.dumps(n.get("alternatives", []))
            valid = "true" if n.get("still_valid", True) else "false"
            sql = (f"INSERT INTO Decision SET name = {sql_str(name)}, "
                   f"what = {sql_str(n.get('what', ''))}, "
                   f"alternatives = {alts}, "
                   f"reasoning = {sql_str(n.get('reasoning', ''))}, "
                   f"confidence = {sql_str(n.get('confidence', 'medium'))}, "
                   f"still_valid = {valid}, "
                   f"created_at = sysdate(), metadata = {json.dumps(n.get('metadata', {}))}")
        elif node_type == "Person":
            sql = (f"INSERT INTO Person SET name = {sql_str(name)}, "
                   f"context = {sql_str(n.get('context', ''))}, "
                   f"relationship = {sql_str(n.get('relationship', ''))}, "
                   f"created_at = sysdate(), metadata = {json.dumps(n.get('metadata', {}))}")
        elif node_type == "Project":
            sql = (f"INSERT INTO Project SET name = {sql_str(name)}, "
                   f"description = {sql_str(n.get('description', ''))}, "
                   f"status = {sql_str(n.get('status', 'active'))}, "
                   f"created_at = sysdate(), metadata = {json.dumps(n.get('metadata', {}))}")
        else:
            continue

        result = execute(sql)
        if "error" in result:
            print(f"  ERROR creating {node_type} '{name}': {result.get('error', result)}")
        else:
            created += 1

    print(f"  + {node_type}: {created} created, {skipped} existing (updated)")


def create_edges(edges):
    created = 0
    errors = 0
    for e in (edges or []):
        edge_type = e["type"]
        from_type = e["from_type"]
        from_name = e["from_name"]
        to_type = e["to_type"]
        to_name = e["to_name"]
        props = e.get("properties", {})

        prop_clauses = ", ".join(
            f"{k} = {sql_str(v)}" if isinstance(v, str) else f"{k} = {v}"
            for k, v in props.items()
        )
        if prop_clauses:
            prop_clauses = f", {prop_clauses}"

        sql = (f"CREATE EDGE {edge_type} FROM "
               f"(SELECT FROM {from_type} WHERE name = {sql_str(from_name)}) TO "
               f"(SELECT FROM {to_type} WHERE name = {sql_str(to_name)}) "
               f"SET created_at = sysdate(){prop_clauses}")

        result = execute(sql)
        if "error" in result:
            errors += 1
        else:
            created += 1

    print(f"  + Edges: {created} created, {errors} errors")


def process_extraction(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\nProcessing: {filepath}")
    print(f"{'='*60}")

    create_artifact(data.get("artifact"))
    create_nodes("Project", data.get("projects"))
    create_nodes("Person", data.get("persons"))
    create_nodes("Concept", data.get("concepts"))
    create_nodes("Decision", data.get("decisions"))
    create_edges(data.get("edges"))

    print(f"{'='*60}")
    print("Done.\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python graph_writer.py <extraction.json> [extraction2.json ...]")
        sys.exit(1)
    for fp in sys.argv[1:]:
        process_extraction(fp)
