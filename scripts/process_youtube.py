#!/usr/bin/env python3
"""
Process YouTube/YouTube Music export data for Second Brain knowledge graph.
Creates lightweight summary Artifacts with MENTIONS edges to known projects/concepts.
"""
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import cfg


def load_projects_config():
    config_path = Path(__file__).parent.parent / "projects.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"projects": {}, "concept_keywords": {}, "location_rules": {}, "notebook_mappings": {}}


_config = load_projects_config()

YOUTUBE_DIR = os.path.join(cfg.BRAIN_INBOX, "youtube")
EXTRACTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extractions", "youtube")
PROCESSED_DIR = os.path.join(cfg.BRAIN_INBOX, "processed", "youtube")
GRAPH_WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_writer.py")
PYTHON = sys.executable

# Build project list from config
KNOWN_PROJECTS = list(_config.get("projects", {}).keys())

# Build concept keyword -> canonical name mapping from config
KNOWN_CONCEPTS_KEYWORDS = {k: v for k, v in _config.get("concept_keywords", {}).items() if k != "_comment"}


def sanitize(s):
    """Remove apostrophes and clean string for SQL safety."""
    if s is None:
        return ""
    return str(s).replace("'", "").replace('"', "").replace("\\", "/").strip()


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def norm_path(p):
    """Normalize path to forward slashes for SQL safety."""
    return p.replace("\\", "/")


def detect_mentions(text_blob):
    """Scan text for known project/concept keywords, return MENTIONS edges."""
    edges = []
    seen = set()
    text_lower = text_blob.lower()

    for project in KNOWN_PROJECTS:
        if project.lower() in text_lower and project not in seen:
            seen.add(project)
            edges.append({
                "type": "MENTIONS",
                "from_type": "Artifact",
                "from_name": "__ARTIFACT__",
                "to_type": "Project",
                "to_name": project,
                "properties": {"context": "Referenced in YouTube export data"}
            })

    for keyword, concept in KNOWN_CONCEPTS_KEYWORDS.items():
        if keyword in text_lower and concept not in seen:
            seen.add(concept)
            edges.append({
                "type": "MENTIONS",
                "from_type": "Artifact",
                "from_name": "__ARTIFACT__",
                "to_type": "Concept",
                "to_name": concept,
                "properties": {"context": "Topic detected in YouTube export data"}
            })

    return edges


def process_subscriptions():
    """Read subscriptions.csv, create summary Artifact."""
    csv_path = os.path.join(YOUTUBE_DIR, "subscriptions", "subscriptions.csv")
    if not os.path.exists(csv_path):
        print("SKIP: subscriptions.csv not found")
        return None

    channels = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            channels.append(sanitize(row.get("Channel Title", "")))

    categories = {
        "Business / E-commerce": [],
        "Space / Science": [],
        "Digital Nomad / Expat / Travel": [],
        "Technology / AI": [],
        "Thai Culture / Music": [],
        "Side Hustle / Entrepreneurship": [],
        "Emergency / Disaster Comms": [],
        "Other": [],
    }

    for ch in channels:
        ch_lower = ch.lower()
        if any(kw in ch_lower for kw in ["ecommerce", "flip", "sourcing", "sell", "business"]):
            categories["Business / E-commerce"].append(ch)
        elif any(kw in ch_lower for kw in ["space", "astronaut", "spacex", "aviation"]):
            categories["Space / Science"].append(ch)
        elif any(kw in ch_lower for kw in ["nomad", "travel", "abroad", "expat"]):
            categories["Digital Nomad / Expat / Travel"].append(ch)
        elif any(kw in ch_lower for kw in ["tech", "ai", "prime", "saraev", "crypto"]):
            categories["Technology / AI"].append(ch)
        elif any(kw in ch_lower for kw in ["thai", "job 2 do"]):
            categories["Thai Culture / Music"].append(ch)
        elif any(kw in ch_lower for kw in ["hustle", "demand", "manning", "upflip"]):
            categories["Side Hustle / Entrepreneurship"].append(ch)
        elif any(kw in ch_lower for kw in ["disaster", "communication"]):
            categories["Emergency / Disaster Comms"].append(ch)
        else:
            categories["Other"].append(ch)

    summary_parts = [f"YouTube channel subscriptions: {len(channels)} total channels."]
    for cat, chs in categories.items():
        if chs:
            summary_parts.append(f"  {cat}: {', '.join(chs)}")

    summary = " | ".join(summary_parts)
    all_text = " ".join(channels)
    edges = detect_mentions(all_text)

    artifact_name = "YouTube Subscriptions Summary"
    for e in edges:
        e["from_name"] = artifact_name

    extraction = {
        "artifact": {
            "name": artifact_name,
            "source_type": "youtube-export",
            "source_path": norm_path(csv_path),
            "content_hash": content_hash("|".join(channels)),
            "summary": sanitize(summary),
            "metadata": {
                "channel_count": len(channels),
                "categories": {k: len(v) for k, v in categories.items() if v},
                "channel_names": [sanitize(c) for c in channels],
            }
        },
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }

    return extraction


def process_playlists():
    """Read playlists.csv, create summary Artifact."""
    csv_path = os.path.join(YOUTUBE_DIR, "playlists", "playlists.csv")
    if not os.path.exists(csv_path):
        print("SKIP: playlists.csv not found")
        return None

    playlists = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            playlists.append({
                "title": sanitize(row.get("Playlist Title (Original)", "")),
                "visibility": sanitize(row.get("Playlist Visibility", "")),
                "created": sanitize(row.get("Playlist Create Timestamp", "")),
                "updated": sanitize(row.get("Playlist Update Timestamp", "")),
            })

    wl_path = os.path.join(YOUTUBE_DIR, "playlists", "Watch later-videos.csv")
    wl_count = 0
    if os.path.exists(wl_path):
        with open(wl_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            wl_count = sum(1 for _ in reader)

    titles = [p["title"] for p in playlists]
    summary = (
        f"YouTube playlists: {len(playlists)} playlists found. "
        f"Titles: {', '.join(titles)}. "
        f"Watch Later queue: {wl_count} videos."
    )

    all_text = " ".join(titles)
    edges = detect_mentions(all_text)

    artifact_name = "YouTube Playlists Summary"
    for e in edges:
        e["from_name"] = artifact_name

    extraction = {
        "artifact": {
            "name": artifact_name,
            "source_type": "youtube-export",
            "source_path": norm_path(csv_path),
            "content_hash": content_hash("|".join(titles) + str(wl_count)),
            "summary": sanitize(summary),
            "metadata": {
                "playlist_count": len(playlists),
                "watch_later_count": wl_count,
                "playlists": playlists,
            }
        },
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }

    return extraction


def process_watch_history():
    """Parse watch-history.html for summary stats only."""
    html_path = os.path.join(YOUTUBE_DIR, "history", "watch-history.html")
    if not os.path.exists(html_path):
        print("SKIP: watch-history.html not found")
        return None

    file_size = os.path.getsize(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    watched_count = content.count("Watched\xa0<a href=") + content.count("Watched <a href=")

    date_pattern = r'(\w{3} \d{1,2}, \d{4}), \d{1,2}:\d{2}:\d{2}'
    dates = re.findall(date_pattern, content)

    date_range_start = dates[-1] if dates else "unknown"
    date_range_end = dates[0] if dates else "unknown"

    channel_pattern = r'youtube\.com/channel/[^"]+"[^>]*>([^<]+)</a>'
    channels_found = re.findall(channel_pattern, content[:200000])
    unique_channels = list(set(channels_found))

    summary = (
        f"YouTube watch history: {watched_count} videos watched. "
        f"Date range: {date_range_start} to {date_range_end}. "
        f"File size: {file_size / 1024:.0f} KB. "
        f"Unique channels in sample: {len(unique_channels)}."
    )

    all_text = " ".join(unique_channels)
    edges = detect_mentions(all_text)

    artifact_name = "YouTube Watch History Summary"
    for e in edges:
        e["from_name"] = artifact_name

    extraction = {
        "artifact": {
            "name": artifact_name,
            "source_type": "youtube-export",
            "source_path": norm_path(html_path),
            "content_hash": content_hash(f"watch-{watched_count}-{date_range_start}-{date_range_end}"),
            "summary": sanitize(summary),
            "metadata": {
                "video_count": watched_count,
                "date_range_start": sanitize(date_range_start),
                "date_range_end": sanitize(date_range_end),
                "file_size_kb": round(file_size / 1024),
                "unique_channels_sampled": len(unique_channels),
            }
        },
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }

    return extraction


def process_search_history():
    """Parse search-history.html for summary stats only."""
    html_path = os.path.join(YOUTUBE_DIR, "history", "search-history.html")
    if not os.path.exists(html_path):
        print("SKIP: search-history.html not found")
        return None

    file_size = os.path.getsize(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    search_count = content.count("Searched for\xa0<a href=") + content.count("Searched for <a href=")

    date_pattern = r'(\w{3} \d{1,2}, \d{4}), \d{1,2}:\d{2}:\d{2}'
    dates = re.findall(date_pattern, content)

    date_range_start = dates[-1] if dates else "unknown"
    date_range_end = dates[0] if dates else "unknown"

    search_term_pattern = r'search_query=[^"]*"[^>]*>([^<]+)</a>'
    terms_found = re.findall(search_term_pattern, content[:200000])
    unique_terms = list(set(terms_found))

    summary = (
        f"YouTube search history: {search_count} searches. "
        f"Date range: {date_range_start} to {date_range_end}. "
        f"File size: {file_size / 1024:.0f} KB. "
        f"Sample search terms: {', '.join(unique_terms[:20])}."
    )

    all_text = " ".join(unique_terms)
    edges = detect_mentions(all_text)

    artifact_name = "YouTube Search History Summary"
    for e in edges:
        e["from_name"] = artifact_name

    extraction = {
        "artifact": {
            "name": artifact_name,
            "source_type": "youtube-export",
            "source_path": norm_path(html_path),
            "content_hash": content_hash(f"search-{search_count}-{date_range_start}-{date_range_end}"),
            "summary": sanitize(summary),
            "metadata": {
                "search_count": search_count,
                "date_range_start": sanitize(date_range_start),
                "date_range_end": sanitize(date_range_end),
                "file_size_kb": round(file_size / 1024),
                "sample_terms": [sanitize(t) for t in unique_terms[:30]],
            }
        },
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }

    return extraction


def process_music_library():
    """Read music library songs.csv, create summary Artifact."""
    csv_path = os.path.join(YOUTUBE_DIR, "music (library and uploads)", "music library songs.csv")
    if not os.path.exists(csv_path):
        print("SKIP: music library songs.csv not found")
        return None

    songs = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            songs.append({
                "title": sanitize(row.get("Song Title", "")),
                "album": sanitize(row.get("Album Title", "")),
                "artist": sanitize(row.get("Artist Name 1", "")),
            })

    artists = list(set(s["artist"] for s in songs if s["artist"]))
    albums = list(set(s["album"] for s in songs if s["album"]))

    summary = (
        f"YouTube Music library: {len(songs)} songs. "
        f"Artists: {', '.join(artists)}. "
        f"Albums: {', '.join(albums)}."
    )

    all_text = " ".join(artists) + " " + " ".join([s["title"] for s in songs])
    edges = detect_mentions(all_text)

    artifact_name = "YouTube Music Library Summary"
    for e in edges:
        e["from_name"] = artifact_name

    extraction = {
        "artifact": {
            "name": artifact_name,
            "source_type": "youtube-export",
            "source_path": norm_path(csv_path),
            "content_hash": content_hash("|".join(s["title"] for s in songs)),
            "summary": sanitize(summary),
            "metadata": {
                "song_count": len(songs),
                "artists": artists,
                "albums": albums,
                "songs": songs,
            }
        },
        "projects": [],
        "concepts": [],
        "decisions": [],
        "persons": [],
        "edges": edges,
    }

    return extraction


def move_to_processed():
    """Move source files to processed directory, preserving folder structure."""
    for root, dirs, files in os.walk(YOUTUBE_DIR):
        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, YOUTUBE_DIR)
            dst = os.path.join(PROCESSED_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            print(f"  Moved: {rel}")

    for root, dirs, files in os.walk(YOUTUBE_DIR, topdown=False):
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                os.rmdir(dp)
            except OSError:
                pass
    try:
        os.rmdir(YOUTUBE_DIR)
    except OSError:
        pass


def main():
    os.makedirs(EXTRACTIONS_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    processors = [
        ("subscriptions", process_subscriptions),
        ("playlists", process_playlists),
        ("watch-history", process_watch_history),
        ("search-history", process_search_history),
        ("music-library", process_music_library),
    ]

    extraction_files = []
    total_edges = 0
    errors = 0

    for name, processor in processors:
        print(f"\n--- Processing: {name} ---")
        try:
            extraction = processor()
            if extraction is None:
                errors += 1
                continue

            out_path = os.path.join(EXTRACTIONS_DIR, f"youtube-{name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(extraction, f, indent=2, ensure_ascii=False)

            edge_count = len(extraction.get("edges", []))
            total_edges += edge_count
            extraction_files.append(out_path)
            print(f"  Wrote: {out_path}")
            print(f"  Artifact: {extraction['artifact']['name']}")
            print(f"  Summary: {extraction['artifact']['summary'][:120]}...")
            print(f"  Edges: {edge_count}")
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

    print(f"\n{'='*60}")
    print("Writing to graph...")
    print(f"{'='*60}")

    for fp in extraction_files:
        print(f"\n  graph_writer.py {os.path.basename(fp)}")
        result = subprocess.run(
            [PYTHON, GRAPH_WRITER, fp],
            capture_output=True, text=True, encoding="utf-8"
        )
        print(result.stdout)
        if result.stderr:
            print(f"  STDERR: {result.stderr}")

    print(f"\n{'='*60}")
    print("Moving files to processed...")
    print(f"{'='*60}")
    move_to_processed()

    print(f"\n{'='*60}")
    print("REPORT")
    print(f"{'='*60}")
    print(f"Artifacts created: {len(extraction_files)}")
    print(f"Total MENTIONS edges: {total_edges}")
    print(f"Errors: {errors}")
    print(f"Extraction files: {EXTRACTIONS_DIR}")
    for fp in extraction_files:
        print(f"  - {os.path.basename(fp)}")


if __name__ == "__main__":
    main()
