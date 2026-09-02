import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer


# ============================================================
# PATHS / ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

# Current structure:
#
# AIEngineer/
# ├── .env
# └── youtube_reviser/
#     └── index.py
#
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(
    PROJECT_ROOT / ".env"
)


# ============================================================
# CONFIGURATION
# ============================================================

COLLECTION_NAME = os.getenv(
    "QDRANT_COLLECTION",
    "youtube_transcripts",
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "intfloat/multilingual-e5-small",
)

BATCH_SIZE = int(
    os.getenv(
        "QDRANT_BATCH_SIZE",
        "32",
    )
)

# ============================================================
# TIME-BASED CHUNKING CONFIGURATION
#
# Raw caption segments are typically ~30s.
# We merge them into larger overlapping windows so that
# a single topic — which spans multiple raw captions —
# is represented in one chunk.
#
# CHUNK_SECONDS = target window length
# OVERLAP_SECONDS = how much consecutive windows overlap
# ============================================================

CHUNK_SECONDS = float(
    os.getenv(
        "CHUNK_SECONDS",
        "75",
    )
)

OVERLAP_SECONDS = float(
    os.getenv(
        "OVERLAP_SECONDS",
        "15",
    )
)


# ============================================================
# EXCLUDED FILES / DIRECTORIES
# ============================================================

EXCLUDED_JSON_NAMES = {
    "playlist_meta.json",
    "video_meta.json",
}

EXCLUDED_DIRS = {
    "qdrant_data",
    "ui",
    "__pycache__",
    ".venv",
    "venv",
    "backups",
}


# ============================================================
# EMBEDDING MODEL (SINGLETON)
# ============================================================

def load_embedding_model() -> SentenceTransformer:
    from .retrieval import load_embedding_model as _load_model
    return _load_model()


# ============================================================
# QDRANT CLIENT
# ============================================================

def get_qdrant_client() -> QdrantClient:
    qdrant_url = os.getenv(
        "QDRANT_URL"
    )

    qdrant_api_key = os.getenv(
        "QDRANT_API_KEY"
    )

    if not qdrant_url:
        raise RuntimeError(
            "QDRANT_URL was not found in .env"
        )

    if not qdrant_api_key:
        raise RuntimeError(
            "QDRANT_API_KEY was not found in .env"
        )

    print(
        f"QDRANT_URL loaded: "
        f"{bool(qdrant_url)}"
    )

    print(
        f"QDRANT_API_KEY loaded: "
        f"{bool(qdrant_api_key)}"
    )

    return QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key,
        timeout=120,
    )


# ============================================================
# TRANSCRIPT DISCOVERY
# ============================================================

def discover_transcript_files() -> List[Path]:
    files: List[Path] = []

    for entry in BASE_DIR.iterdir():

        # JSON directly inside youtube_reviser/
        if (
            entry.is_file()
            and entry.suffix.lower() == ".json"
        ):
            files.append(entry)
            continue

        # JSON inside playlist/video directories
        if (
            entry.is_dir()
            and entry.name not in EXCLUDED_DIRS
        ):
            for json_file in entry.rglob("*.json"):
                files.append(json_file)

    return sorted(
        set(files)
    )


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(
    value,
    default: float = 0.0,
) -> float:

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


# ============================================================
# SAFE INTEGER
# ============================================================

def safe_int(
    value,
) -> Optional[int]:

    if value is None:
        return None

    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


# ============================================================
# TIME-BASED CHUNKING
#
# Merges raw caption segments (each ~30s) into wider,
# overlapping windows of ~CHUNK_SECONDS duration.
#
# Rules:
#  - Never split a caption segment in the middle.
#  - Preserve exact start/end times from caption data.
#  - Overlap consecutive windows by OVERLAP_SECONDS.
#  - The window "steps forward" by (CHUNK_SECONDS - OVERLAP_SECONDS).
#
# Example with CHUNK_SECONDS=75, OVERLAP_SECONDS=15:
#   Window 1: t=0   → t~75
#   Window 2: t~60  → t~135
#   Window 3: t~120 → t~195
# ============================================================

def time_based_chunking(
    raw_chunks: List[Dict],
    chunk_seconds: float = CHUNK_SECONDS,
    overlap_seconds: float = OVERLAP_SECONDS,
) -> List[Dict]:
    """
    Merge raw caption segments into overlapping time-based windows.

    Each returned dict has:
        start_sec   – earliest segment start in this window
        end_sec     – latest segment end in this window
        text        – joined transcript text
        source      – "caption" (or "whisper" if any segment is whisper)
    """

    if not raw_chunks:
        return []

    # Sort by start time (defensive; input is usually sorted)
    sorted_chunks = sorted(
        raw_chunks,
        key=lambda c: safe_float(c.get("start_time", 0)),
    )

    step = max(
        1.0,
        chunk_seconds - overlap_seconds,
    )

    # Determine window start positions
    total_duration = safe_float(
        sorted_chunks[-1].get("end_time", 0)
    )

    window_starts: List[float] = []
    t = safe_float(sorted_chunks[0].get("start_time", 0))

    while t < total_duration:
        window_starts.append(t)
        t += step

    # If no windows generated, create one covering everything
    if not window_starts:
        window_starts = [0.0]

    merged: List[Dict] = []

    for win_start in window_starts:
        win_end = win_start + chunk_seconds

        # Collect all segments that overlap this window.
        # A segment overlaps the window if it starts before
        # win_end AND ends after win_start.
        window_segs = [
            seg for seg in sorted_chunks
            if (
                safe_float(seg.get("start_time", 0)) < win_end
                and safe_float(seg.get("end_time", 0)) > win_start
            )
        ]

        if not window_segs:
            continue

        actual_start = safe_float(
            window_segs[0].get("start_time", win_start)
        )
        actual_end = safe_float(
            window_segs[-1].get("end_time", win_end)
        )

        # Join text, preserving order
        text = " ".join(
            str(seg.get("text", "")).strip()
            for seg in window_segs
            if str(seg.get("text", "")).strip()
        ).strip()

        english_text = " ".join(
            str(seg.get("english_text", seg.get("text", ""))).strip()
            for seg in window_segs
            if str(seg.get("english_text", seg.get("text", ""))).strip()
        ).strip()

        if not text and not english_text:
            continue

        # Source is "whisper" if any segment is whisper
        sources = {
            str(seg.get("source", "caption")).lower()
            for seg in window_segs
        }
        source = (
            "whisper" if "whisper" in sources else "caption"
        )

        merged.append({
            "start_sec": actual_start,
            "end_sec": actual_end,
            "text": text,
            "english_text": english_text or text,
            "source": source,
        })

    return merged


# ============================================================
# LOAD TRANSCRIPTS
#
# Reads transcript JSON files and applies time-based chunking.
# Returns a flat list of document dicts — one per chunk.
# ============================================================

def load_transcript_files(
    video_ids: Optional[List[str]] = None,
) -> List[Dict]:
    transcript_files = (
        discover_transcript_files()
    )
    if video_ids:
        target_ids = {vid.strip() for vid in video_ids if vid.strip()}
        transcript_files = [
            f for f in transcript_files
            if f.stem in target_ids
        ]

    if not transcript_files:
        print(
            "No transcript JSON files found."
        )
        return []

    print(
        f"Found {len(transcript_files)} "
        f"JSON files."
    )

    documents: List[Dict] = []

    for file_path in transcript_files:

        if (
            file_path.name
            in EXCLUDED_JSON_NAMES
        ):
            continue

        try:
            data = json.loads(
                file_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
        ) as exc:

            print(
                f"Skipping "
                f"{file_path.name}: "
                f"{exc}"
            )

            continue

        if not isinstance(
            data,
            dict,
        ):
            print(
                f"Skipping "
                f"{file_path.name}: "
                f"root is not an object."
            )
            continue

        video_id = data.get(
            "video_id"
        )

        if not video_id:
            print(
                f"Skipping "
                f"{file_path.name}: "
                f"video_id missing."
            )
            continue

        video_id = str(
            video_id
        ).strip()

        video_title = (
            data.get(
                "video_title"
            )
            or data.get(
                "title"
            )
            or video_id
        )

        playlist_id = data.get(
            "playlist_id"
        )

        playlist_title = data.get(
            "playlist_title"
        )

        video_number = safe_int(
            data.get(
                "video_number"
            )
        )

        raw_chunks = data.get(
            "chunks",
            [],
        )

        if not isinstance(
            raw_chunks,
            list,
        ):
            print(
                f"Skipping chunks in "
                f"{file_path.name}: "
                f"chunks is not a list."
            )
            continue

        # Apply time-based chunking
        timed_chunks = time_based_chunking(
            raw_chunks=raw_chunks,
            chunk_seconds=CHUNK_SECONDS,
            overlap_seconds=OVERLAP_SECONDS,
        )

        if not timed_chunks:
            print(
                f"Warning: "
                f"{file_path.name} "
                f"produced no time-based chunks."
            )
            continue

        video_title_str = str(video_title).strip()
        playlist_id_str = (
            str(playlist_id).strip()
            if playlist_id
            else None
        )
        playlist_title_str = (
            str(playlist_title).strip()
            if playlist_title
            else None
        )

        for chunk in timed_chunks:

            start_sec = chunk["start_sec"]
            end_sec = chunk["end_sec"]
            text = chunk["text"]
            english_text = chunk.get("english_text") or text

            # Stable chunk identifier
            chunk_id = (
                f"{video_id}:{int(start_sec)}"
            )

            # Embedding text: title + original text + english representation (when different)
            # ONE UNIFORM RULE FOR ALL VIDEOS:
            if english_text and english_text.strip() and english_text.strip() != text.strip():
                embed_text = (
                    f"{video_title_str}\n\n{text}\n\n{english_text}"
                )
            else:
                embed_text = (
                    f"{video_title_str}\n\n{text}"
                )

            document = {
                "chunk_id": chunk_id,
                "video_id": video_id,
                "video_title": video_title_str,
                "video_number": video_number,
                "playlist_id": playlist_id_str,
                "playlist_title": playlist_title_str,
                "start_time": start_sec,
                "end_time": end_sec,
                "text": text,
                "english_text": english_text,
                "embed_text": embed_text,
                "source": chunk.get("source", "caption"),
                "approximate": False,
            }

            documents.append(document)

        print(
            f"  {file_path.name}: "
            f"{len(raw_chunks)} raw segments -> "
            f"{len(timed_chunks)} timed chunks "
            f"({CHUNK_SECONDS}s / {OVERLAP_SECONDS}s overlap)"
        )

    return documents


# ============================================================
# COLLECTION
# ============================================================

def ensure_collection(
    client: QdrantClient,
    vector_size: int,
) -> None:
    existing_collections = {
        collection.name
        for collection
        in client.get_collections().collections
    }

    if COLLECTION_NAME not in existing_collections:
        print(
            f"Collection {COLLECTION_NAME} not found. Creating..."
        )
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )

        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="video_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="playlist_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="video_title",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print(
            f"Created collection and payload indexes: {COLLECTION_NAME}"
        )
    else:
        print(
            f"Collection {COLLECTION_NAME} already exists. Using incremental indexing."
        )


def create_collection(
    client: QdrantClient,
    vector_size: int,
) -> None:

    existing_collections = {
        collection.name
        for collection
        in client.get_collections().collections
    }

    if COLLECTION_NAME in existing_collections:

        print(
            f"Deleting existing collection: "
            f"{COLLECTION_NAME}"
        )

        client.delete_collection(
            collection_name=COLLECTION_NAME
        )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=vector_size,
            distance=Distance.COSINE,
        ),
    )

    # --------------------------------------------------------
    # Payload indexes
    # --------------------------------------------------------

    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="video_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )

    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="playlist_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )

    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="video_title",
        field_schema=PayloadSchemaType.KEYWORD,
    )

    print(
        "Created payload indexes: "
        "video_id, playlist_id, video_title"
    )

    print(
        f"Created collection: "
        f"{COLLECTION_NAME}"
    )


# ============================================================
# POINT ID
#
# Deterministic integer ID based on video_id + start_sec.
# This means re-indexing the same chunk produces the same ID,
# so Qdrant upsert is idempotent (no duplicates).
# ============================================================

def create_point_id(
    video_id: str,
    start_sec: float,
) -> int:
    """
    Stable, collision-resistant integer ID from video_id + start time.
    Uses only video_id + int(start_sec) so that minor float differences
    in the same logical chunk always produce the same ID.
    """
    raw_id = f"{video_id}:{int(start_sec)}"

    digest = hashlib.sha256(
        raw_id.encode("utf-8")
    ).digest()

    # Qdrant accepts integer point IDs.
    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    )


# ============================================================
# EMBEDDINGS
#
# Embeds the enriched "embed_text" field (title + transcript)
# instead of raw transcript text only.
# This improves cross-script semantic retrieval.
# ============================================================

def generate_embeddings(
    documents: List[Dict],
    model: SentenceTransformer,
    progress_callback: Optional[Callable[[Dict], None]] = None,
):
    # Use the enriched embed_text field when available,
    # falling back to raw text.
    texts = [
        document.get("embed_text") or document["text"]
        for document in documents
    ]

    if not texts:
        return []

    # E5 models require 'passage: ' prefix for document embeddings
    model_name_str = str(getattr(model, "model_card_data", "") or "") + str(EMBEDDING_MODEL).lower()
    if "e5" in model_name_str.lower():
        texts = [f"passage: {t}" for t in texts]

    total_chunks = len(texts)
    total_batches = math.ceil(total_chunks / BATCH_SIZE)

    print(
        f"Creating embeddings for "
        f"{total_chunks} chunks "
        f"({total_batches} batches)..."
    )

    if progress_callback:
        progress_callback({
            "stage": "embedding",
            "status": "processing",
            "completed": 0,
            "total": total_batches,
            "chunks_completed": 0,
            "total_chunks": total_chunks,
            "message": f"Generating embeddings (0/{total_batches})...",
        })

    all_embeddings = []
    for i in range(0, total_chunks, BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_emb = model.encode(
            batch_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        all_embeddings.append(batch_emb)
        batch_num = (i // BATCH_SIZE) + 1
        if progress_callback:
            progress_callback({
                "stage": "embedding",
                "status": "processing" if batch_num < total_batches else "success",
                "completed": batch_num,
                "total": total_batches,
                "chunks_completed": min(i + BATCH_SIZE, total_chunks),
                "total_chunks": total_chunks,
                "message": f"Generating embeddings ({batch_num}/{total_batches})...",
            })

    import numpy as np
    return np.vstack(all_embeddings) if all_embeddings else []


# ============================================================
# CREATE QDRANT POINTS
# ============================================================

def create_points(
    documents: List[Dict],
    embeddings,
) -> List[PointStruct]:

    points: List[PointStruct] = []

    used_ids = set()

    for document, embedding in zip(
        documents,
        embeddings,
    ):

        point_id = create_point_id(
            video_id=document["video_id"],
            start_sec=document["start_time"],
        )

        if point_id in used_ids:
            continue

        used_ids.add(
            point_id
        )

        payload = {
            # ------------------------------------------------
            # Chunk identifier
            # ------------------------------------------------
            "chunk_id": document["chunk_id"],

            # ------------------------------------------------
            # Video metadata
            # ------------------------------------------------
            "video_id": document[
                "video_id"
            ],

            "video_title": document.get(
                "video_title"
            ),

            "video_number": document.get(
                "video_number"
            ),

            # ------------------------------------------------
            # Playlist metadata
            # ------------------------------------------------
            "playlist_id": document.get(
                "playlist_id"
            ),

            "playlist_title": document.get(
                "playlist_title"
            ),

            # ------------------------------------------------
            # Timestamp metadata
            # The timestamp travels with the chunk.
            # It is NEVER reconstructed from the transcript.
            # ------------------------------------------------
            "start_time": document[
                "start_time"
            ],

            "end_time": document[
                "end_time"
            ],

            "start_sec": document[
                "start_time"
            ],

            "end_sec": document[
                "end_time"
            ],

            # ------------------------------------------------
            # Transcript
            # ------------------------------------------------
            "text": document[
                "text"
            ],

            "english_text": document.get(
                "english_text",
                document["text"],
            ),

            "source": document[
                "source"
            ],

            "approximate": document[
                "approximate"
            ],
        }

        points.append(
            PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload=payload,
            )
        )

    return points


# ============================================================
# INDEX DOCUMENTS
# ============================================================

def index_documents(
    client: QdrantClient,
    points: List[PointStruct],
    progress_callback: Optional[Callable[[Dict], None]] = None,
) -> None:

    total = len(points)

    if total == 0:
        print(
            "No points to upload."
        )
        return

    total_batches = math.ceil(total / BATCH_SIZE)

    if progress_callback:
        progress_callback({
            "stage": "indexing",
            "status": "processing",
            "completed": 0,
            "total": total_batches,
            "points_completed": 0,
            "total_points": total,
            "message": f"Saving to knowledge base (0/{total_batches})...",
        })

    for i, start in enumerate(
        range(
            0,
            total,
            BATCH_SIZE,
        )
    ):

        batch = points[
            start:start + BATCH_SIZE
        ]

        end = min(
            start + BATCH_SIZE,
            total,
        )

        print(
            f"Uploading points "
            f"{start + 1}-{end}/{total}..."
        )

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=batch,
            wait=True,
        )

        batch_num = i + 1
        if progress_callback:
            progress_callback({
                "stage": "indexing",
                "status": "processing" if batch_num < total_batches else "success",
                "completed": batch_num,
                "total": total_batches,
                "points_completed": end,
                "total_points": total,
                "message": f"Saving to knowledge base ({batch_num}/{total_batches})...",
            })


# ============================================================
# MAIN
# ============================================================

def main(
    video_ids: Optional[List[str]] = None,
    recreate: bool = False,
    progress_callback: Optional[Callable[[Dict], None]] = None,
) -> bool:

    print(
        "\n"
        "========================================"
    )

    print(
        "YouTube Transcript Indexing"
    )

    print(
        f"  Chunk size:  {CHUNK_SECONDS}s"
    )

    print(
        f"  Overlap:     {OVERLAP_SECONDS}s"
    )

    print(
        f"  Incremental: {not recreate}"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Load documents (applies time-based chunking)
    # --------------------------------------------------------

    print(
        "\nLoading and chunking transcript files..."
    )

    if progress_callback:
        progress_callback({
            "stage": "chunking",
            "status": "processing",
            "completed": 0,
            "total": 1,
            "message": "Creating searchable chunks...",
        })

    documents = (
        load_transcript_files(
            video_ids=video_ids,
        )
    )

    if not documents:

        print(
            "No valid transcript chunks found."
        )

        if progress_callback:
            progress_callback({
                "stage": "chunking",
                "status": "failed",
                "message": "No valid transcript chunks found.",
            })

        return False

    print(
        f"\nLoaded {len(documents)} "
        f"timed chunks total."
    )

    if progress_callback:
        progress_callback({
            "stage": "chunking",
            "status": "success",
            "chunks_count": len(documents),
            "completed": len(documents),
            "total": len(documents),
            "message": f"Created {len(documents)} chunks",
        })

    # --------------------------------------------------------
    # Initialize model and Qdrant
    # --------------------------------------------------------

    try:

        model = load_embedding_model()

        vector_size = (
            model.get_sentence_embedding_dimension()
        )

        if not vector_size:
            raise RuntimeError(
                "Unable to determine embedding dimension."
            )

        print(
            f"Embedding dimension: "
            f"{vector_size}"
        )

        client = get_qdrant_client()

    except Exception as exc:

        print(
            "\nInitialization failed: "
            f"{exc}"
        )

        return False

    # --------------------------------------------------------
    # Generate embeddings BEFORE deleting collection
    #
    # This protects the existing collection from being
    # deleted if embedding generation fails.
    # --------------------------------------------------------

    try:

        embeddings = generate_embeddings(
            documents,
            model,
            progress_callback=progress_callback,
        )

        if len(embeddings) != len(
            documents
        ):
            raise RuntimeError(
                "Embedding count does not match "
                "document count."
            )

        points = create_points(
            documents,
            embeddings,
        )

        if not points:
            raise RuntimeError(
                "No Qdrant points were created."
            )

    except Exception as exc:

        print(
            "\nEmbedding generation failed: "
            f"{exc}"
        )

        return False

    # --------------------------------------------------------
    # Ensure or Recreate collection
    # --------------------------------------------------------

    try:

        if recreate:
            create_collection(
                client=client,
                vector_size=vector_size,
            )
        else:
            ensure_collection(
                client=client,
                vector_size=vector_size,
            )

    except Exception as exc:

        print(
            "\nCollection creation failed: "
            f"{exc}"
        )

        return False

    # --------------------------------------------------------
    # Upload points
    # --------------------------------------------------------

    try:

        print(
            f"\nIndexing {len(points)} "
            f"chunks into Qdrant..."
        )

        index_documents(
            client=client,
            points=points,
            progress_callback=progress_callback,
        )

    except Exception as exc:

        print(
            "\nIndexing failed: "
            f"{exc}"
        )

        return False

    # --------------------------------------------------------
    # Success
    # --------------------------------------------------------

    print(
        "\nSuccessfully indexed "
        f"{len(points)} chunks."
    )

    print(
        f"Collection: "
        f"{COLLECTION_NAME}"
    )

    print(
        "Payload per point:"
    )

    print("  - chunk_id     (e.g. 7yd5qO2TPr0:2496)")
    print("  - video_id")
    print("  - video_title")
    print("  - video_number")
    print("  - playlist_id")
    print("  - playlist_title")
    print("  - start_time   (exact seconds)")
    print("  - end_time     (exact seconds)")
    print("  - text         (transcript only, not embedding text)")
    print()
    print("Re-run this command anytime to reindex without re-downloading.")
    print("Duplicate runs produce identical point IDs → no duplicates.")

    return True


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    recreate_flag = "--recreate" in sys.argv or "-r" in sys.argv
    success = main(recreate=recreate_flag)

    if not success:
        raise SystemExit(1)
    