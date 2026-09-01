import concurrent.futures
import json
import queue
import re
import shutil
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue

from . import fetch
from . import index
from .chat import handle_query

# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="YouTube Reviser",
)


# ============================================================
# STATIC FILES
# ============================================================

app.mount(
    "/static",
    StaticFiles(
        directory=UI_DIR
    ),
    name="static",
)


# ============================================================
# REQUEST MODELS
# ============================================================

class AnalyzeRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    video_ids: List[str]


class ChatRequest(BaseModel):
    question: str

    chat_history: List[Dict] = Field(
        default_factory=list
    )

    video_id: Optional[str] = None

    playlist_id: Optional[str] = None

    scope: str = "all"


# ============================================================
# YOUTUBE URL HELPERS
# ============================================================

def is_youtube_url(
    url: str,
) -> bool:

    try:
        parsed = urlparse(url)

        return parsed.hostname in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "www.youtu.be",
        }

    except Exception:
        return False


def is_playlist_url(
    url: str,
) -> bool:

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query
    )

    # Any URL containing list= is a playlist,
    # even when v= is also present.
    # e.g. /watch?v=XYZ&list=ABC is a playlist.
    return bool(
        query.get("list")
    )


def extract_video_id(
    url: str,
) -> str:

    parsed = urlparse(url)

    if parsed.hostname in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }:

        video_id = (
            parse_qs(
                parsed.query
            )
            .get(
                "v",
                [None],
            )[0]
        )

        if video_id:
            return video_id

    if parsed.hostname in {
        "youtu.be",
        "www.youtu.be",
    }:

        video_id = (
            parsed.path
            .strip("/")
            .split("/")[0]
        )

        if video_id:
            return video_id

    raise ValueError(
        "Invalid YouTube URL"
    )


def extract_playlist_id(
    url: str,
) -> Optional[str]:

    parsed = urlparse(url)

    return (
        parse_qs(
            parsed.query
        )
        .get(
            "list",
            [None],
        )[0]
    )


# ============================================================
# VIDEO INFORMATION
# ============================================================

def extract_video_info(
    video_id: str,
) -> Dict:

    command = [
        "yt-dlp",
        "--skip-download",
        "--print",
        "%(id)s",
        "--print",
        "%(title)s",
        (
            "https://www.youtube.com/"
            "watch?v="
            f"{video_id}"
        ),
    ]

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Unable to fetch video information."
        )

    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if len(lines) < 2:
        raise RuntimeError(
            "Unable to read video information."
        )

    return {
        "video_id": lines[0],
        "title": lines[1],
        "url": (
            "https://www.youtube.com/"
            "watch?v="
            f"{lines[0]}"
        ),
    }


# ============================================================
# PLAYLIST INFORMATION
# ============================================================

def extract_playlist_videos(
    url: str,
) -> Dict:

    command = [
        "yt-dlp",
        "--flat-playlist",
        "-J",
        url,
    ]

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Unable to read playlist."
        )

    try:
        data = json.loads(
            result.stdout
        )

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            "Invalid playlist response."
        ) from exc

    entries = data.get(
        "entries",
        [],
    )

    videos: List[Dict] = []

    for entry in entries:

        if not entry:
            continue

        video_id = entry.get(
            "id"
        )

        if not video_id:
            continue

        title = (
            entry.get("title")
            or "Untitled video"
        )

        videos.append(
            {
                "video_id": video_id,
                "title": title,
                "url": (
                    "https://www.youtube.com/"
                    "watch?v="
                    f"{video_id}"
                ),
            }
        )

    return {
        "title": data.get(
            "title",
            "YouTube Playlist",
        ),
        "videos": videos,
    }


# ============================================================
# QDRANT VIDEO CATALOG
# ============================================================

def get_indexed_video_catalog() -> List[Dict]:
    """
    Build a unique video catalog from Qdrant.
    """

    client = (
        index.get_qdrant_client()
    )

    videos: Dict[str, Dict] = {}

    next_offset = None

    while True:

        points, next_offset = (
            client.scroll(
                collection_name=(
                    index.COLLECTION_NAME
                ),
                limit=1000,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
        )

        for point in points:

            payload = (
                point.payload or {}
            )

            video_id = payload.get(
                "video_id"
            )

            if not video_id:
                continue

            video_id = str(
                video_id
            )

            video_title = (
                payload.get(
                    "video_title"
                )
                or video_id
            )

            videos[video_id] = {
                "video_id": video_id,

                "title": str(
                    video_title
                ),

                "url": (
                    "https://www.youtube.com/"
                    "watch?v="
                    f"{video_id}"
                ),

                "video_number": (
                    payload.get(
                        "video_number"
                    )
                ),

                "playlist_id": (
                    payload.get(
                        "playlist_id"
                    )
                ),

                "playlist_title": (
                    payload.get(
                        "playlist_title"
                    )
                ),
            }

        if next_offset is None:
            break

    return sorted(
        videos.values(),
        key=lambda item: (
            item.get("video_number")
            if item.get("video_number")
            is not None
            else 999999,
            item["title"].lower(),
        ),
    )


# ============================================================
# SAVED VIDEO IDS
# ============================================================

def get_saved_video_ids() -> set[str]:

    try:

        catalog = (
            get_indexed_video_catalog()
        )

        return {
            video["video_id"]
            for video in catalog
            if video.get("video_id")
        }

    except Exception as exc:

        print(
            "Unable to read indexed videos "
            f"from Qdrant: {exc}"
        )

        return set()


# ============================================================
# HOME
# ============================================================

@app.get("/")
def serve_index():

    return FileResponse(
        UI_DIR / "index.html"
    )


# ============================================================
# ANALYZE
# ============================================================

@app.post("/api/analyze")
def analyze_url(
    request: AnalyzeRequest,
):

    url = request.url.strip()

    if not url:

        raise HTTPException(
            status_code=400,
            detail=(
                "YouTube URL is required."
            ),
        )

    if not is_youtube_url(url):

        raise HTTPException(
            status_code=400,
            detail=(
                "Please enter a valid YouTube URL."
            ),
        )

    try:

        saved_ids = (
            get_saved_video_ids()
        )

        # ====================================================
        # PLAYLIST
        # ====================================================

        if is_playlist_url(url):

            playlist = (
                extract_playlist_videos(
                    url
                )
            )

            playlist_id = (
                extract_playlist_id(
                    url
                )
            )

            videos = []

            for video_number, video in enumerate(
                playlist["videos"],
                start=1,
            ):

                video_id = video[
                    "video_id"
                ]

                videos.append(
                    {
                        **video,
                        "video_number": (
                            video_number
                        ),
                        "already_saved": (
                            video_id
                            in saved_ids
                        ),
                    }
                )

            saved_count = sum(
                1
                for video in videos
                if video["already_saved"]
            )

            new_count = (
                len(videos)
                - saved_count
            )

            return {
                "type": "playlist",

                "playlist_id": (
                    playlist_id
                ),

                "title": (
                    playlist["title"]
                ),

                "url": url,

                "total_videos": len(
                    videos
                ),

                "saved_videos": (
                    saved_count
                ),

                "new_videos": (
                    new_count
                ),

                "videos": videos,
            }

        # ====================================================
        # SINGLE VIDEO
        # ====================================================

        video_id = (
            extract_video_id(
                url
            )
        )

        video = (
            extract_video_info(
                video_id
            )
        )

        already_saved = (
            video_id
            in saved_ids
        )

        return {
            "type": "video",

            "playlist_id": None,

            "title": video[
                "title"
            ],

            "url": url,

            "total_videos": 1,

            "saved_videos": (
                1
                if already_saved
                else 0
            ),

            "new_videos": (
                0
                if already_saved
                else 1
            ),

            "videos": [
                {
                    **video,

                    "video_number": 1,

                    "already_saved": (
                        already_saved
                    ),
                }
            ],
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to analyze URL: "
                f"{exc}"
            ),
        ) from exc


# ============================================================
# PROCESS VIDEOS
# ============================================================

@app.post("/api/process")
def process_videos(
    request: ProcessRequest,
):

    if not request.video_ids:

        raise HTTPException(
            status_code=400,
            detail="No video IDs provided.",
        )

    results: List[Dict] = []

    playlist_id: Optional[str] = None
    playlist_title: Optional[str] = None

    playlist_video_map: Dict[
        str,
        Dict,
    ] = {}

    # ========================================================
    # READ PLAYLIST METADATA
    # ========================================================

    if is_playlist_url(
        request.url
    ):

        playlist_id = (
            extract_playlist_id(
                request.url
            )
        )

        if playlist_id:

            try:

                playlist = (
                    extract_playlist_videos(
                        request.url
                    )
                )

                playlist_title = (
                    playlist["title"]
                )

                for video_number, video in enumerate(
                    playlist["videos"],
                    start=1,
                ):

                    playlist_video_map[
                        video["video_id"]
                    ] = {
                        "title": video[
                            "title"
                        ],

                        "video_number": (
                            video_number
                        ),
                    }

            except Exception as exc:

                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Unable to read "
                        f"playlist metadata: {exc}"
                    ),
                ) from exc

    # ========================================================
    # PROCESS SELECTED VIDEOS (CONCURRENT BATCH)
    # ========================================================

    video_items: List[Dict] = []

    for video_id in request.video_ids:
        video_id = video_id.strip()
        if not video_id:
            results.append(
                {
                    "video_id": "",
                    "title": "Untitled video",
                    "success": False,
                    "error": "Video ID is required.",
                }
            )
            continue

        metadata = playlist_video_map.get(video_id, {})
        title = metadata.get("title")
        video_number = metadata.get("video_number")

        if not title and not playlist_id:
            try:
                title = extract_video_info(video_id)["title"]
            except Exception:
                title = video_id

        video_items.append(
            {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": title,
                "video_number": video_number,
            }
        )

    if video_items:
        batch_results = fetch.process_videos_batch(
            videos=video_items,
            playlist_id=playlist_id,
            playlist_title=playlist_title,
        )

        for res in batch_results:
            results.append(
                {
                    "video_id": res["video_id"],
                    "title": res.get("video_title") or res["video_id"],
                    "success": res["success"],
                    "video_number": res.get("video_number"),
                    "playlist_id": playlist_id,
                    "error": res.get("error"),
                }
            )

    # ========================================================
    # INDEX
    # ========================================================

    successful_videos = [
        result
        for result in results
        if result["success"] is True
    ]

    if successful_videos:

        try:

            indexing_success = (
                index.main(
                    video_ids=[
                        result["video_id"]
                        for result in successful_videos
                    ],
                    recreate=False,
                )
            )

            if indexing_success is False:

                raise RuntimeError(
                    "Indexing did not complete successfully."
                )

            # Clear cached Qdrant/model resources
            get_chat_resources.cache_clear()

        except Exception as exc:

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Indexing failed: {exc}"
                ),
            ) from exc

    return {
        "results": results,

        "processed_count": len(
            successful_videos
        ),

        "failed_count": (
            len(results)
            - len(successful_videos)
        ),
    }


# ============================================================
# PROCESS VIDEOS (STREAMING PROGRESS)
# ============================================================

@app.post("/api/process/stream")
def process_videos_stream(
    request: ProcessRequest,
):
    if not request.video_ids:
        raise HTTPException(
            status_code=400,
            detail="No video IDs provided.",
        )

    def event_stream():
        playlist_id: Optional[str] = None
        playlist_title: Optional[str] = None
        playlist_video_map: Dict[str, Dict] = {}

        if is_playlist_url(request.url):
            playlist_id = extract_playlist_id(request.url)
            if playlist_id:
                try:
                    playlist = extract_playlist_videos(request.url)
                    playlist_title = playlist["title"]
                    for video_number, video in enumerate(
                        playlist["videos"],
                        start=1,
                    ):
                        playlist_video_map[video["video_id"]] = {
                            "title": video["title"],
                            "video_number": video_number,
                        }
                except Exception as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Unable to read playlist metadata: {exc}'})}\n\n"
                    return

        video_items = []
        for video_id in request.video_ids:
            video_id = video_id.strip()
            if not video_id:
                continue

            metadata = playlist_video_map.get(video_id, {})
            title = metadata.get("title")
            video_number = metadata.get("video_number")

            if not title and not playlist_id:
                try:
                    title = extract_video_info(video_id)["title"]
                except Exception:
                    title = video_id

            video_items.append(
                {
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": title,
                    "video_number": video_number,
                }
            )

        total = len(video_items)
        yield f"data: {json.dumps({'type': 'step', 'step': 'Fetching video transcripts...', 'total': total, 'completed': 0})}\n\n"
        yield f"data: {json.dumps({'type': 'stage_progress', 'stage': 'fetching', 'status': 'processing', 'completed': 0, 'total': total, 'message': 'Fetching video transcripts...'})}\n\n"

        # Emit initial waiting state for all videos
        for item in video_items:
            yield f"data: {json.dumps({'type': 'video_status', 'video_id': item['video_id'], 'title': item['title'], 'video_number': item['video_number'], 'status': 'waiting', 'message': 'Waiting'})}\n\n"

        results = []
        completed_count = 0
        failed_count = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=fetch.MAX_CONCURRENT_VIDEOS) as executor:
            future_to_item = {}
            for item in video_items:
                future = executor.submit(
                    fetch.process_single_video_detailed,
                    video_url=item["url"],
                    playlist_id=playlist_id,
                    playlist_title=playlist_title,
                    video_title=item["title"],
                    video_number=item["video_number"],
                )
                future_to_item[future] = item
                yield f"data: {json.dumps({'type': 'video_status', 'video_id': item['video_id'], 'title': item['title'], 'video_number': item['video_number'], 'status': 'processing', 'message': 'Fetching transcript...'})}\n\n"

            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    res = future.result()
                except Exception as exc:
                    res = {
                        "video_id": item["video_id"],
                        "video_title": item["title"],
                        "video_number": item["video_number"],
                        "success": False,
                        "error": str(exc),
                    }
                results.append(res)
                if res.get("success"):
                    completed_count += 1
                    status_text = "Completed"
                    yield f"data: {json.dumps({'type': 'video_status', 'video_id': item['video_id'], 'title': item['title'], 'video_number': item['video_number'], 'status': 'success', 'message': status_text, 'completed': completed_count, 'failed': failed_count, 'total': total})}\n\n"
                else:
                    failed_count += 1
                    err_msg = res.get("error") or "Failed to fetch transcript"
                    yield f"data: {json.dumps({'type': 'video_status', 'video_id': item['video_id'], 'title': item['title'], 'video_number': item['video_number'], 'status': 'failed', 'message': err_msg, 'completed': completed_count, 'failed': failed_count, 'total': total})}\n\n"

                yield f"data: {json.dumps({'type': 'stage_progress', 'stage': 'fetching', 'status': 'processing' if (completed_count + failed_count) < total else 'success', 'completed': completed_count, 'failed': failed_count, 'total': total, 'message': f'Fetching video transcripts ({completed_count}/{total})...'})}\n\n"

        yield f"data: {json.dumps({'type': 'stage_progress', 'stage': 'fetching', 'status': 'success', 'completed': completed_count, 'failed': failed_count, 'total': total, 'message': f'Fetched {completed_count}/{total} transcripts'})}\n\n"

        successful_videos = [r for r in results if r.get("success")]
        if successful_videos:
            event_queue = queue.Queue()

            def run_indexer():
                try:
                    def progress_cb(evt):
                        event_queue.put({"type": "stage_progress", **evt})

                    indexing_success = index.main(
                        video_ids=[r["video_id"] for r in successful_videos],
                        recreate=False,
                        progress_callback=progress_cb,
                    )
                    if indexing_success is False:
                        event_queue.put({"type": "error", "message": "Indexing did not complete successfully."})
                    else:
                        event_queue.put({"type": "indexer_done"})
                except Exception as exc:
                    event_queue.put({"type": "error", "message": f"Indexing failed: {exc}"})

            indexer_thread = threading.Thread(target=run_indexer, daemon=True)
            indexer_thread.start()

            while True:
                try:
                    evt = event_queue.get(timeout=0.2)
                    if evt.get("type") == "indexer_done":
                        break
                    elif evt.get("type") == "error":
                        yield f"data: {json.dumps(evt)}\n\n"
                        return
                    else:
                        step_msg = evt.get("message") or ""
                        if step_msg:
                            yield f"data: {json.dumps({'type': 'step', 'step': step_msg})}\n\n"
                        yield f"data: {json.dumps(evt)}\n\n"
                except queue.Empty:
                    if not indexer_thread.is_alive():
                        break

            get_chat_resources.cache_clear()

        yield f"data: {json.dumps({'type': 'stage_progress', 'stage': 'complete', 'status': 'success', 'message': 'Processing complete'})}\n\n"
        yield f"data: {json.dumps({'type': 'complete', 'step': 'Completed', 'total': total, 'succeeded': len(successful_videos), 'failed': failed_count, 'results': results})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ============================================================
# CHAT RESOURCES
# ============================================================

@lru_cache(maxsize=1)
def get_chat_resources():

    embedding_model = (
        index.load_embedding_model()
    )

    client = (
        index.get_qdrant_client()
    )

    return (
        embedding_model,
        client,
    )


# ============================================================
# CHAT PAGE
# ============================================================

@app.get("/chat")
def serve_chat():

    return FileResponse(
        UI_DIR / "chat.html"
    )


# ============================================================
# INDEXED VIDEOS
# ============================================================

@app.get("/api/videos")
def get_videos():

    try:

        videos = (
            get_indexed_video_catalog()
        )

        return {
            "videos": videos
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to load indexed videos: "
                f"{exc}"
            ),
        ) from exc


# ============================================================
# REMOVE PLAYLIST
# ============================================================

@app.delete("/api/playlist/{playlist_id}")
def delete_playlist(
    playlist_id: str,
):
    playlist_id = playlist_id.strip()

    if not playlist_id:
        raise HTTPException(
            status_code=400,
            detail="Playlist ID is required.",
        )

    if not re.match(r"^[\w-]+$", playlist_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid Playlist ID format.",
        )

    try:
        # 1. Delete Qdrant points belonging ONLY to this playlist
        client = index.get_qdrant_client()
        delete_filter = Filter(
            must=[
                FieldCondition(
                    key="playlist_id",
                    match=MatchValue(value=playlist_id),
                )
            ]
        )

        client.delete(
            collection_name=index.COLLECTION_NAME,
            points_selector=delete_filter,
            wait=True,
        )

        # 2. Delete transcript directory belonging ONLY to this playlist
        deleted_dir = False
        playlist_dir = fetch.find_playlist_dir(playlist_id)

        if playlist_dir and playlist_dir.is_dir():
            resolved_dir = playlist_dir.resolve()
            resolved_data_dir = fetch.DATA_DIR.resolve()

            # Extra security verification:
            # - directory must be directly inside DATA_DIR
            # - folder name must end with _{playlist_id}
            # - folder name must not be in EXCLUDED_DIRS
            if (
                resolved_dir.parent == resolved_data_dir
                and playlist_dir.name not in fetch.EXCLUDED_DIRS
                and playlist_dir.name.endswith(f"_{playlist_id}")
            ):
                shutil.rmtree(resolved_dir)
                deleted_dir = True

        # Clear cached chat resources
        get_chat_resources.cache_clear()

        return {
            "success": True,
            "playlist_id": playlist_id,
            "deleted_directory": deleted_dir,
            "message": f"Playlist {playlist_id} has been removed from knowledge base.",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete playlist: {exc}",
        ) from exc


# ============================================================
# CHAT API
# ============================================================

@app.post("/api/chat")
def chat(
    request: ChatRequest,
):

    question = request.question.strip()

    if not question:

        raise HTTPException(
            status_code=400,
            detail=(
                "Please enter a question."
            ),
        )

    if request.scope not in {
        "all",
        "video",
        "playlist",
    }:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid chat scope."
            ),
        )

    if (
        request.scope == "video"
        and not request.video_id
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "A video ID is required "
                "for video scope."
            ),
        )

    if (
        request.scope == "all"
        and not request.playlist_id
    ):

        # Allow general chat even when
        # playlist ID is not available.
        pass

    try:

        (
            embedding_model,
            client,
        ) = get_chat_resources()

        return handle_query(
            question=question,

            chat_history=(
                request.chat_history
            ),

            embedding_model=(
                embedding_model
            ),

            client=client,

            video_id=request.video_id,

            playlist_id=request.playlist_id,

            scope=request.scope,
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Chat processing failed: "
                f"{exc}"
            ),
        ) from exc