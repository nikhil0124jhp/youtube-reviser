import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from faster_whisper import WhisperModel
from youtube_transcript_api import YouTubeTranscriptApi


# ============================================================
# TYPES
# ============================================================

Chunk = Tuple[float, float, str]


# ============================================================
# PATHS / CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

OUTPUT_DIR = BASE_DIR
DATA_DIR = BASE_DIR

VIDEO_DIR_NAME = "videos"

EXCLUDED_DIRS = {
    "qdrant_data",
    "ui",
    "__pycache__",
    ".venv",
    "venv",
    "backups",
}


# ============================================================
# CONCURRENCY CONFIGURATION
# ============================================================

MAX_CONCURRENT_VIDEOS = int(
    os.getenv("MAX_CONCURRENT_VIDEOS", "4")
)

MAX_CONCURRENT_WHISPER = int(
    os.getenv("MAX_CONCURRENT_WHISPER", "1")
)


# ============================================================
# CHUNK CONFIGURATION
# ============================================================

TARGET_CHUNK_DURATION = 25.0
MAX_CHUNK_DURATION = 35.0


# ============================================================
# YT-DLP HELPER
# ============================================================

def get_ytdlp_cmd() -> List[str]:
    return [sys.executable, "-m", "yt_dlp"]


# ============================================================
# WHISPER MODEL (LAZY SINGLETON & THREAD-SAFE CONCURRENCY)
# ============================================================

_WHISPER_MODEL: Optional[WhisperModel] = None
_WHISPER_INIT_LOCK = threading.Lock()
_WHISPER_TRANSCRIBE_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_WHISPER)


def get_whisper_model() -> WhisperModel:
    """Lazy-load the Whisper model once and reuse across calls."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        with _WHISPER_INIT_LOCK:
            if _WHISPER_MODEL is None:
                print("\n[ASR] Loading faster-whisper model (lazy singleton)...")
                try:
                    _WHISPER_MODEL = WhisperModel(
                        "small",
                        device="auto",
                        compute_type="auto",
                    )
                except Exception as exc:
                    print(f"[ASR] Device 'auto' failed ({exc}), falling back to CPU...")
                    _WHISPER_MODEL = WhisperModel(
                        "small",
                        device="cpu",
                        compute_type="int8",
                    )
    return _WHISPER_MODEL


def set_whisper_cpu_model() -> WhisperModel:
    """Explicitly switch the global singleton to CPU model on failure and cache it."""
    global _WHISPER_MODEL
    with _WHISPER_INIT_LOCK:
        print("[ASR] Initializing/updating global Whisper model on CPU (int8)...")
        _WHISPER_MODEL = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8",
        )
    return _WHISPER_MODEL


# ============================================================
# PLAYLIST DIRECTORY
# ============================================================

def sanitize_folder_name(
    name: str,
) -> str:
    name = re.sub(
        r"[^\w\s-]",
        "",
        name,
    ).strip()

    name = re.sub(
        r"\s+",
        "_",
        name,
    )

    return (
        name[:60]
        or "playlist"
    )


def get_playlist_dir(
    playlist_id: str,
    playlist_title: str,
) -> Path:

    folder_name = (
        f"{sanitize_folder_name(playlist_title)}"
        f"_{playlist_id}"
    )

    playlist_dir = (
        DATA_DIR / folder_name
    )

    playlist_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return playlist_dir


def find_playlist_dir(
    playlist_id: str,
) -> Optional[Path]:

    for folder in DATA_DIR.iterdir():

        if (
            folder.is_dir()
            and folder.name not in EXCLUDED_DIRS
            and folder.name.endswith(
                f"_{playlist_id}"
            )
        ):
            return folder

    return None


# ============================================================
# SINGLE VIDEO DIRECTORY
# ============================================================

def get_video_dir() -> Path:

    video_dir = (
        DATA_DIR / VIDEO_DIR_NAME
    )

    video_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return video_dir


# ============================================================
# SAVED VIDEO IDS
# ============================================================

def list_all_saved_video_ids() -> Set[str]:

    saved_ids: Set[str] = set()

    for entry in DATA_DIR.iterdir():

        if (
            entry.is_file()
            and entry.suffix == ".json"
        ):
            json_files = [entry]

        elif (
            entry.is_dir()
            and entry.name not in EXCLUDED_DIRS
        ):
            json_files = list(
                entry.rglob("*.json")
            )

        else:
            continue

        for json_file in json_files:

            if json_file.name in {
                "playlist_meta.json",
                "video_meta.json",
            }:
                continue

            try:

                data = json.loads(
                    json_file.read_text(
                        encoding="utf-8"
                    )
                )

                video_id = data.get(
                    "video_id"
                )

                if video_id:
                    saved_ids.add(
                        str(video_id)
                    )

            except (
                OSError,
                json.JSONDecodeError,
            ):
                continue

    return saved_ids


# ============================================================
# PLAYLIST METADATA
# ============================================================

def save_playlist_meta(
    playlist_dir: Path,
    playlist_id: str,
    title: str,
    url: str,
    video_count: int,
) -> None:

    meta_path = (
        playlist_dir / "playlist_meta.json"
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    created_at = now

    if meta_path.exists():

        try:

            existing = json.loads(
                meta_path.read_text(
                    encoding="utf-8"
                )
            )

            created_at = existing.get(
                "created_at",
                now,
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):
            pass

    meta = {
        "playlist_id": playlist_id,
        "title": title,
        "url": url,
        "video_count": video_count,
        "created_at": created_at,
        "updated_at": now,
    }

    meta_path.write_text(
        json.dumps(
            meta,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# YOUTUBE URL HELPERS
# ============================================================

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
            ).get(
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


# ============================================================
# VIDEO TITLE
# ============================================================

def extract_video_title(
    video_url: str,
) -> Optional[str]:

    command = get_ytdlp_cmd() + [
        "--skip-download",
        "--print",
        "%(title)s",
        video_url,
    ]

    try:

        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            return None

        title = (
            result.stdout.strip()
        )

        return (
            title
            if title
            else None
        )

    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None


# ============================================================
# PLAYLIST DETECTION
# ============================================================

def is_playlist_url(
    url: str,
) -> bool:

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query
    )

    return bool(
        query.get("list")
    )


# ============================================================
# EXTRACT PLAYLIST VIDEOS
# ============================================================

def extract_playlist_videos(
    url: str,
) -> List[str]:

    command = get_ytdlp_cmd() + [
        "--flat-playlist",
        "-J",
        url,
    ]

    try:

        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            return []

        data = json.loads(
            result.stdout
        )

        videos: List[str] = []

        for entry in data.get(
            "entries",
            [],
        ):

            if not entry:
                continue

            video_id = entry.get(
                "id"
            )

            if not video_id:
                continue

            videos.append(
                (
                    "https://www.youtube.com/"
                    "watch?v="
                    f"{video_id}"
                )
            )

        return videos

    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ):
        return []


def extract_playlist_info(
    url: str,
) -> Dict:
    """
    Extract playlist metadata and detailed video items (id, title, url)
    in a single yt-dlp call to avoid redundant individual title lookups.
    """
    command = get_ytdlp_cmd() + [
        "--flat-playlist",
        "-J",
        url,
    ]

    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return {"title": "Playlist", "playlist_id": None, "videos": []}

        data = json.loads(result.stdout)
        parsed_id = parse_qs(urlparse(url).query).get("list", [None])[0]
        playlist_id = data.get("id") or parsed_id
        playlist_title = data.get("title") or f"Playlist_{playlist_id}"

        videos: List[Dict] = []
        for idx, entry in enumerate(data.get("entries", []) or [], start=1):
            if not entry:
                continue
            vid = entry.get("id")
            if not vid:
                continue
            vtitle = entry.get("title") or f"Video {idx}"
            videos.append({
                "video_id": vid,
                "title": vtitle,
                "video_number": idx,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })

        return {
            "title": playlist_title,
            "playlist_id": playlist_id,
            "videos": videos,
        }
    except Exception:
        return {"title": "Playlist", "playlist_id": None, "videos": []}


# ============================================================
# FETCH CAPTIONS (PARALLEL LANGUAGE FETCH IN SINGLE YT-DLP CALL)
# ============================================================

def fetch_captions(
    video_url: str,
    temp_dir: Path,
    languages: str = "hi,en",
) -> Optional[Tuple[Path, str]]:
    """
    Fetches captions attempting Hindi and English in a single yt-dlp call.
    Returns (vtt_path, selected_language) preferring Hindi over English.
    """
    output_template = temp_dir / "%(id)s.%(lang)s"

    command = get_ytdlp_cmd() + [
        "--write-auto-sub",
        "--write-sub",
        "--sub-lang",
        languages,
        "--skip-download",
        "--sub-format",
        "vtt",
        "-o",
        str(output_template),
        video_url,
    ]

    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        # Check for Hindi first (priority order)
        hi_files = list(temp_dir.glob("*.hi*.vtt"))
        if hi_files:
            return hi_files[0], "hi"

        # Fallback to English
        en_files = list(temp_dir.glob("*.en*.vtt"))
        if en_files:
            return en_files[0], "en"

        # Any other vtt file
        any_vtt = list(temp_dir.glob("*.vtt"))
        if any_vtt:
            return any_vtt[0], "other"

        return None

    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None


# ============================================================
# TIMESTAMP
# ============================================================

def timestamp_to_seconds(
    timestamp: str,
) -> float:

    parts = (
        timestamp
        .strip()
        .split(":")
    )

    if len(parts) != 3:

        raise ValueError(
            "Invalid VTT timestamp: "
            f"{timestamp}"
        )

    hours, minutes, seconds = parts

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + float(
            seconds.replace(
                ",",
                ".",
            )
        )
    )


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_caption_text(
    text: str,
) -> str:

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = text.replace(
        "&nbsp;",
        " ",
    )

    text = text.replace(
        "\u200b",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_for_comparison(
    text: str,
) -> str:

    text = clean_caption_text(
        text
    ).lower()

    text = re.sub(
        r"[^\w\s\u0900-\u097F]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# REMOVE CAPTION OVERLAP
# ============================================================

def remove_overlap(
    previous: str,
    current: str,
) -> str:

    previous_words = (
        previous.split()
    )

    current_words = (
        current.split()
    )

    if (
        not previous_words
        or not current_words
    ):
        return current

    previous_norm = [
        normalize_for_comparison(
            word
        )
        for word in previous_words
    ]

    current_norm = [
        normalize_for_comparison(
            word
        )
        for word in current_words
    ]

    max_overlap = min(
        len(previous_words),
        len(current_words),
        40,
    )

    best_overlap = 0

    for size in range(
        1,
        max_overlap + 1,
    ):

        if (
            previous_norm[-size:]
            == current_norm[:size]
        ):
            best_overlap = size

    if best_overlap:

        remaining = (
            current_words[
                best_overlap:
            ]
        )

        return " ".join(
            remaining
        ).strip()

    return current


# ============================================================
# ============================================================
# DEDUPLICATE CAPTION FRAGMENTS
# ============================================================

def deduplicate_fragments(
    fragments: List[Tuple],
) -> List[Tuple]:

    if not fragments:
        return []

    cleaned: List[Tuple] = []

    previous_text = ""

    for item in fragments:
        start = item[0]
        end = item[1]
        text = item[2]
        en_text = item[3] if len(item) > 3 else None

        text = clean_caption_text(text)
        if not text:
            continue

        normalized = normalize_for_comparison(text)

        if (
            previous_text
            and normalized
            == normalize_for_comparison(previous_text)
        ):
            continue

        new_text = remove_overlap(
            previous_text,
            text,
        )

        if not new_text:
            continue

        if en_text is not None:
            cleaned.append((start, end, new_text, en_text))
        else:
            cleaned.append((start, end, new_text))

        previous_text = text

    return cleaned


# ============================================================
# PARSE VTT
# ============================================================

def parse_vtt(
    vtt_path: Path,
) -> List[Chunk]:

    if not vtt_path.exists():
        return []

    content = vtt_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    chunks: List[Chunk] = []

    blocks = re.split(
        r"\n\s*\n",
        content.strip(),
    )

    for block in blocks:

        lines = [
            l.strip()
            for l in block.split("\n")
            if l.strip()
        ]

        if not lines:
            continue

        timestamp_line = None

        text_lines = []

        for line in lines:

            if "-->" in line:
                timestamp_line = line
            elif (
                timestamp_line
                and not line.startswith("WEBVTT")
                and not line.startswith("NOTE")
            ):
                text_lines.append(line)

        if not timestamp_line or not text_lines:
            continue

        match = re.match(
            r"(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})",
            timestamp_line,
        )

        if not match:
            continue

        start_str, end_str = (
            match.groups()
        )

        start = (
            timestamp_to_seconds(
                start_str
            )
        )

        end = (
            timestamp_to_seconds(
                end_str
            )
        )

        raw_text = " ".join(
            text_lines
        )

        text = clean_caption_text(
            raw_text
        )

        if text:
            chunks.append(
                (
                    start,
                    end,
                    text,
                )
            )

    return deduplicate_fragments(
        chunks
    )


# ============================================================
# SENTENCE BOUNDARY DETECTION
# ============================================================

def is_sentence_boundary(
    text: str,
) -> bool:

    text = text.strip()

    if not text:
        return False

    return bool(
        re.search(
            r"[।!?.]\s*$",
            text,
        )
    )


# ============================================================
# MERGE CHUNKS
# ============================================================

def merge_chunks(
    chunks: List[Tuple],
    target_duration: float = TARGET_CHUNK_DURATION,
    max_duration: float = MAX_CHUNK_DURATION,
) -> List[Dict]:

    if not chunks:
        return []

    merged: List[Dict] = []

    current_start = chunks[0][0]
    current_end = chunks[0][1]
    current_text = chunks[0][2]
    current_en_text = chunks[0][3] if len(chunks[0]) > 3 and chunks[0][3] else None

    for item in chunks[1:]:
        start = item[0]
        end = item[1]
        text = item[2]
        en_text = item[3] if len(item) > 3 and item[3] else None

        current_duration = current_end - current_start
        next_duration = end - current_start
        reached_target = current_duration >= target_duration
        sentence_boundary = is_sentence_boundary(current_text)
        would_exceed_max = next_duration > max_duration

        if would_exceed_max or (reached_target and sentence_boundary):
            chunk_dict = {
                "start_time": round(current_start, 3),
                "end_time": round(current_end, 3),
                "text": current_text.strip(),
            }
            if current_en_text:
                chunk_dict["english_text"] = current_en_text.strip()
            merged.append(chunk_dict)

            current_start = start
            current_end = end
            current_text = text
            current_en_text = en_text

        else:
            current_end = end
            current_text = f"{current_text} {text}".strip()
            if en_text:
                current_en_text = f"{current_en_text} {en_text}".strip() if current_en_text else en_text.strip()

    if current_text:
        chunk_dict = {
            "start_time": round(current_start, 3),
            "end_time": round(current_end, 3),
            "text": current_text.strip(),
        }
        if current_en_text:
            chunk_dict["english_text"] = current_en_text.strip()
        merged.append(chunk_dict)

    return merged


# ============================================================
# YOUTUBE TRANSCRIPT API (TIERED ACQUISITION: DIRECT EN -> NATIVE TRANSLATION -> SOURCE ONLY)
# ============================================================

def fetch_transcript_api(
    video_id: str,
) -> Optional[Tuple[List[Tuple], str, str]]:
    """
    Tiered YouTube Transcript API fetching:
    STEP 1: Check for direct English transcript.
            If found -> fetch English transcript (and source transcript if available).
            Preserves "text" = source, "english_text" = English.
            acquisition_path = "direct_english"
            
    STEP 2: If direct English is unavailable, check if source transcript is translatable by YouTube.
            If translatable -> fetch source & source.translate("en").fetch().
            Preserves "text" = source, "english_text" = YouTube native English translation.
            acquisition_path = "youtube_native"
            
    STEP 3: If not translatable by YouTube, fetch source transcript only.
            acquisition_path = "source_only"
            
    Returns (fragments, selected_language, acquisition_path) if successful, or None.
    """
    api = YouTubeTranscriptApi()

    try:
        transcript_list = api.list(video_id)
        transcripts = list(transcript_list)
        if not transcripts:
            return None

        en_transcripts = [t for t in transcripts if t.language_code.startswith("en")]
        non_en_transcripts = [t for t in transcripts if not t.language_code.startswith("en")]

        # ----------------------------------------------------
        # STEP 1: Direct English Transcript Available
        # ----------------------------------------------------
        if en_transcripts:
            best_en = en_transcripts[0]
            try:
                en_items = best_en.fetch()
                # If there is also a non-English source transcript track, try to pair them
                if non_en_transcripts:
                    best_src = non_en_transcripts[0]
                    try:
                        src_items = best_src.fetch()
                        if len(src_items) == len(en_items):
                            fragments: List[Tuple] = []
                            for s_item, e_item in zip(src_items, en_items):
                                st = float(s_item.start)
                                dur = float(s_item.duration)
                                s_txt = clean_caption_text(s_item.text)
                                e_txt = clean_caption_text(e_item.text)
                                if s_txt or e_txt:
                                    fragments.append((st, st + dur, s_txt or e_txt, e_txt or s_txt))
                            fragments = deduplicate_fragments(fragments)
                            if fragments:
                                return fragments, best_src.language_code, "direct_english"
                    except Exception:
                        pass

                # Direct English only
                fragments = []
                for item in en_items:
                    st = float(item.start)
                    dur = float(item.duration)
                    txt = clean_caption_text(item.text)
                    if txt:
                        fragments.append((st, st + dur, txt, txt))
                fragments = deduplicate_fragments(fragments)
                if fragments:
                    return fragments, best_en.language_code, "direct_english"
            except Exception as exc:
                print(f"[{video_id}] Direct English fetch failed ({exc})")

        # ----------------------------------------------------
        # STEP 2: YouTube Native English Translation
        # ----------------------------------------------------
        if non_en_transcripts:
            best_src = non_en_transcripts[0]
            if best_src.is_translatable:
                try:
                    src_items = best_src.fetch()
                    en_items = best_src.translate("en").fetch()
                    fragments = []
                    for s_item, e_item in zip(src_items, en_items):
                        st = float(s_item.start)
                        dur = float(s_item.duration)
                        s_txt = clean_caption_text(s_item.text)
                        e_txt = clean_caption_text(e_item.text)
                        if s_txt or e_txt:
                            fragments.append((st, st + dur, s_txt or e_txt, e_txt or s_txt))
                    fragments = deduplicate_fragments(fragments)
                    if fragments:
                        return fragments, best_src.language_code, "youtube_native"
                except Exception as exc:
                    print(f"[{video_id}] YouTube native translation fetch failed ({exc}), falling back to source-only")

            # ----------------------------------------------------
            # STEP 3: Source-only via API (will use fallback translator)
            # ----------------------------------------------------
            try:
                src_items = best_src.fetch()
                fragments = []
                for item in src_items:
                    st = float(item.start)
                    dur = float(item.duration)
                    txt = clean_caption_text(item.text)
                    if txt:
                        fragments.append((st, st + dur, txt, None))
                fragments = deduplicate_fragments(fragments)
                if fragments:
                    return fragments, best_src.language_code, "source_only"
            except Exception as exc:
                print(f"[{video_id}] Source transcript fetch failed: {exc}")

    except Exception as exc:
        print(f"[{video_id}] YouTubeTranscriptApi listing failed ({exc})")

    return None


# ============================================================
# WHISPER FALLBACK (REUSES SINGLETON & BOUNDED CONCURRENCY)
# ============================================================

def fallback_transcribe(
    video_url: str,
    temp_dir: Path,
) -> Optional[List[Chunk]]:
    """
    Downloads audio temporarily and transcribes with the lazy-singleton WhisperModel.
    Thread-safe execution guarded by _WHISPER_TRANSCRIBE_SEMAPHORE.
    """
    audio_path = temp_dir / "audio.%(ext)s"

    download_command = get_ytdlp_cmd() + [
        "-f",
        "ba/b",
        "-o",
        str(audio_path),
        video_url,
    ]

    try:
        subprocess.run(
            download_command,
            text=True,
            capture_output=True,
            check=False,
        )

        audio_files = list(temp_dir.glob("audio.*"))
        if not audio_files:
            return None

        audio_file = audio_files[0]

        # Use thread-safe semaphore and lazy singleton
        with _WHISPER_TRANSCRIBE_SEMAPHORE:
            try:
                model = get_whisper_model()
                segments, _ = model.transcribe(
                    str(audio_file),
                    vad_filter=True,
                )
                segment_list = list(segments)
            except Exception as exc:
                print(f"[ASR] Transcribe failed on initial device ({exc}), switching global singleton to CPU...")
                model = set_whisper_cpu_model()
                segments, _ = model.transcribe(
                    str(audio_file),
                    vad_filter=True,
                )
                segment_list = list(segments)

            chunks: List[Chunk] = []
            for segment in segment_list:
                text = clean_caption_text(segment.text)
                if text:
                    chunks.append((
                        float(segment.start),
                        float(segment.end),
                        text,
                    ))

            return chunks or None

    except Exception as exc:
        print(f"[ASR Error] Whisper transcription error: {exc}")
        return None


# ============================================================
# SAVE JSON TO PLAYLIST DIRECTORY
# ============================================================

def save_json(
    video_id: str,
    chunks: List[Dict],
    output_dir: Path,
    playlist_id: Optional[str] = None,
    playlist_title: Optional[str] = None,
    video_title: Optional[str] = None,
    video_number: Optional[int] = None,
) -> Path:

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{video_id}.json"
    )

    data = {
        "video_id": video_id,
        "video_title": video_title,
        "video_number": video_number,
        "chunks": chunks,
    }

    if playlist_id:
        data["playlist_id"] = playlist_id
    if playlist_title:
        data["playlist_title"] = playlist_title

    output_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# TRANSLATION / ENRICHMENT HELPERS
# ============================================================

def is_predominantly_english(chunks: List[Dict]) -> bool:
    """Returns True if the chunks are predominantly ASCII/Latin (English)."""
    sample_text = " ".join(c.get("text", "") for c in chunks[:10])
    if not sample_text:
        return True
    devanagari_count = len(re.findall(r"[\u0900-\u097F]", sample_text))
    if devanagari_count > len(sample_text) * 0.15:
        return False
    return True


def translate_chunks_batch(chunks: List[Dict], target_lang: str = "en") -> None:
    """
    Enriches chunks in-place with 'english_text' using fast batch HTTP translation.
    Generic fallback across all domains without hardcoded rules.
    """
    missing_indices = [i for i, c in enumerate(chunks) if not c.get("english_text")]
    if not missing_indices:
        return

    texts = [chunks[i].get("text", "") for i in missing_indices]
    batch_size = 25
    translated_results: List[str] = []

    import urllib.parse
    import urllib.request

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        delimiter = "\n---DELIM---\n"
        combined = delimiter.join(batch)

        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": target_lang,
            "dt": "t",
            "q": combined,
        }
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            full_text = "".join(item[0] for item in data[0] if item and item[0])
            items = full_text.split("---DELIM---")
            if len(items) == len(batch):
                translated_results.extend([t.strip() for t in items])
            else:
                for item in batch:
                    p = {"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": item}
                    enc = urllib.parse.urlencode(p).encode("utf-8")
                    r = urllib.request.Request(url, data=enc, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(r, timeout=10) as s_resp:
                        s_data = json.loads(s_resp.read().decode("utf-8"))
                        s_text = "".join(x[0] for x in s_data[0] if x and x[0])
                        translated_results.append(s_text.strip())
        except Exception as e:
            print(f"[Translation] Batch error ({e}), preserving original text as fallback")
            translated_results.extend(batch)

    for idx, en_txt in zip(missing_indices, translated_results):
        chunks[idx]["english_text"] = en_txt


# ============================================================
# PROCESS SINGLE VIDEO (TIERED ACQUISITION & ENRICHMENT)
# ============================================================

def process_single_video_detailed(
    video_url: str,
    playlist_id: Optional[str] = None,
    playlist_title: Optional[str] = None,
    video_title: Optional[str] = None,
    video_number: Optional[int] = None,
) -> Dict:
    """
    Processes a single video:
    1. Checks if already exists. If english_text is present -> skips completely.
       If english_text is missing -> enriches in-place without re-fetching.
    2. For new videos:
       Step 1: Direct English transcript via YouTubeTranscriptApi.
       Step 2: YouTube Native English translation via translate("en").fetch().
       Step 3: Source captions / Whisper + fallback batch translation.
    3. Saves single JSON file per video.
    """
    try:
        video_id = extract_video_id(video_url)
    except ValueError as exc:
        return {
            "video_id": "",
            "video_title": video_title or "Untitled",
            "video_number": video_number,
            "success": False,
            "source": None,
            "error": str(exc),
            "skipped": False,
            "json_path": None,
        }

    output_dir = (
        get_playlist_dir(
            playlist_id,
            playlist_title or "Playlist",
        )
        if playlist_id
        else get_video_dir()
    )

    existing_path = output_dir / f"{video_id}.json"

    # --------------------------------------------------------
    # Check if already processed
    # --------------------------------------------------------
    if existing_path.exists():
        try:
            with open(existing_path, "r", encoding="utf-8") as fp:
                existing_data = json.load(fp)
            chunks = existing_data.get("chunks", [])
            missing_en = any(not c.get("english_text") for c in chunks)
            if not missing_en:
                print(f"[Skip] Transcript already fully processed with english_text: {existing_path}")
                return {
                    "video_id": video_id,
                    "video_title": existing_data.get("video_title") or video_title or video_id,
                    "video_number": existing_data.get("video_number") or video_number,
                    "success": True,
                    "source": "existing",
                    "error": None,
                    "skipped": True,
                    "json_path": str(existing_path),
                }
            else:
                print(f"[Enrich] Adding missing english_text to existing JSON: {existing_path.name}")
                if is_predominantly_english(chunks):
                    for c in chunks:
                        if not c.get("english_text"):
                            c["english_text"] = c.get("text", "")
                else:
                    translate_chunks_batch(chunks)
                existing_data["chunks"] = chunks
                with open(existing_path, "w", encoding="utf-8") as fp:
                    json.dump(existing_data, fp, indent=2, ensure_ascii=False)
                return {
                    "video_id": video_id,
                    "video_title": existing_data.get("video_title") or video_title or video_id,
                    "video_number": existing_data.get("video_number") or video_number,
                    "success": True,
                    "source": "existing_enriched",
                    "error": None,
                    "skipped": True,
                    "json_path": str(existing_path),
                }
        except Exception as e:
            print(f"[Warning] Failed reading existing JSON ({e}), proceeding with fetch")

    # --------------------------------------------------------
    # Determine video title (only query yt-dlp if not provided)
    # --------------------------------------------------------
    if not video_title:
        video_title = extract_video_title(video_url) or video_id

    # --------------------------------------------------------
    # Fetch transcript inside isolated temporary directory
    # --------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix=f"yt_fetch_{video_id}_") as temp:
        temp_dir = Path(temp)
        raw_chunks: Optional[List[Tuple]] = None
        source: Optional[str] = None
        acq_path: Optional[str] = None

        # 1. Try YouTube Transcript API first (Tiered: Direct EN -> Native YT translation -> Source-only)
        api_result = fetch_transcript_api(video_id)
        if api_result:
            raw_chunks, lang, acq_path = api_result
            source = "transcript_api"
            print(f"[{video_id}] Transcript found via Transcript API ({lang}, path={acq_path}).")

        # 2. Try yt-dlp captions (hi, en in single call) if Transcript API didn't return
        if not raw_chunks:
            caption_result = fetch_captions(video_url, temp_dir, languages="hi,en")
            if caption_result:
                caption_file, lang = caption_result
                try:
                    parsed_vtt = parse_vtt(caption_file)
                    if parsed_vtt:
                        source = "caption"
                        print(f"[{video_id}] Captions found via yt-dlp ({lang}).")
                        if lang == "en":
                            raw_chunks = [(c[0], c[1], c[2], c[2]) for c in parsed_vtt]
                            acq_path = "direct_english"
                        else:
                            raw_chunks = parsed_vtt
                            acq_path = "source_only"
                except Exception as exc:
                    print(f"[{video_id}] Failed to parse VTT: {exc}")

        # 3. Whisper Fallback (only when no captions exist)
        if not raw_chunks:
            print(f"[{video_id}] No captions found. Falling back to faster-whisper...")
            raw_chunks = fallback_transcribe(video_url, temp_dir)
            if raw_chunks:
                source = "whisper"
                acq_path = "whisper"
                print(f"[{video_id}] Whisper transcription completed.")

        # 4. Validate
        if not raw_chunks or not source:
            print(f"[{video_id}] Error: Unable to obtain transcript.")
            return {
                "video_id": video_id,
                "video_title": video_title,
                "video_number": video_number,
                "success": False,
                "source": None,
                "error": "Unable to obtain transcript or audio transcription.",
                "skipped": False,
                "json_path": None,
            }

        # 5. Merge chunks (preserve exact start_time, end_time, original text, and english_text if present)
        merged_chunks = merge_chunks(raw_chunks)
        if not merged_chunks:
            return {
                "video_id": video_id,
                "video_title": video_title,
                "video_number": video_number,
                "success": False,
                "source": source,
                "error": "Transcript contains no usable chunks.",
                "skipped": False,
                "json_path": None,
            }

        for chunk in merged_chunks:
            chunk["source"] = source
            if source == "whisper":
                chunk["approximate"] = True

        # 6. English Transcript Enrichment
        # Only translate if english_text is missing from chunks
        missing_en = any(not c.get("english_text") for c in merged_chunks)
        if missing_en:
            if is_predominantly_english(merged_chunks):
                for c in merged_chunks:
                    if not c.get("english_text"):
                        c["english_text"] = c.get("text", "")
            else:
                # Step 3 Fallback Translation
                print(f"[{video_id}] Direct English & YouTube translation unavailable. Using fallback translation...")
                translate_chunks_batch(merged_chunks)
                for c in merged_chunks:
                    if not c.get("english_text"):
                        c["english_text"] = c.get("text", "")

        # 7. Save JSON (Single JSON per video)
        try:
            output_path = save_json(
                video_id=video_id,
                chunks=merged_chunks,
                output_dir=output_dir,
                playlist_id=playlist_id,
                playlist_title=playlist_title,
                video_title=video_title,
                video_number=video_number,
            )

            print(f"[{video_id}] Saved {len(merged_chunks)} chunks to {output_path.name}")
            return {
                "video_id": video_id,
                "video_title": video_title,
                "video_number": video_number,
                "success": True,
                "source": source,
                "error": None,
                "skipped": False,
                "json_path": str(output_path),
            }

        except OSError as exc:
            return {
                "video_id": video_id,
                "video_title": video_title,
                "video_number": video_number,
                "success": False,
                "source": source,
                "error": f"Failed to save JSON: {exc}",
                "skipped": False,
                "json_path": None,
            }


def process_single_video(
    video_url: str,
    playlist_id: Optional[str] = None,
    playlist_title: Optional[str] = None,
    video_title: Optional[str] = None,
    video_number: Optional[int] = None,
) -> bool:
    """Backward-compatible boolean wrapper for process_single_video_detailed."""
    res = process_single_video_detailed(
        video_url=video_url,
        playlist_id=playlist_id,
        playlist_title=playlist_title,
        video_title=video_title,
        video_number=video_number,
    )
    return bool(res.get("success", False))


# ============================================================
# CONCURRENT BATCH VIDEO PROCESSING
# ============================================================

def process_videos_batch(
    videos: List[Dict],
    playlist_id: Optional[str] = None,
    playlist_title: Optional[str] = None,
    max_workers: int = MAX_CONCURRENT_VIDEOS,
) -> List[Dict]:
    """
    Processes a list of video items concurrently with bounded ThreadPoolExecutor.
    - videos: list of dicts with keys 'video_id' or 'url', optional 'title', 'video_number'.
    - Deduplicates input video IDs while preserving original order.
    - Preserves deterministic original playlist order in return results.
    """
    if not videos:
        return []

    # 1. Deduplicate videos preserving first-seen order
    seen_ids = set()
    deduped_videos: List[Dict] = []
    for item in videos:
        vid = item.get("video_id")
        if not vid and item.get("url"):
            try:
                vid = extract_video_id(item["url"])
            except Exception:
                continue
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            deduped_videos.append({
                **item,
                "video_id": vid,
                "url": item.get("url") or f"https://www.youtube.com/watch?v={vid}",
            })

    total = len(deduped_videos)
    print(f"\n[Batch] Processing {total} videos with concurrency limit = {max_workers}...")

    # Dictionary to store results keyed by video_id to preserve original ordering
    results_map: Dict[str, Dict] = {}

    def _worker(item: Dict) -> Dict:
        vid = item["video_id"]
        url = item["url"]
        vtitle = item.get("title")
        vnum = item.get("video_number")
        try:
            return process_single_video_detailed(
                video_url=url,
                playlist_id=playlist_id,
                playlist_title=playlist_title,
                video_title=vtitle,
                video_number=vnum,
            )
        except Exception as exc:
            return {
                "video_id": vid,
                "video_title": vtitle or vid,
                "video_number": vnum,
                "success": False,
                "source": None,
                "error": f"Unhandled worker exception: {exc}",
                "skipped": False,
                "json_path": None,
            }

    # Execute concurrent tasks with bounded ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_vid = {
            executor.submit(_worker, item): item["video_id"]
            for item in deduped_videos
        }

        for future in concurrent.futures.as_completed(future_to_vid):
            vid = future_to_vid[future]
            try:
                res = future.result()
                results_map[vid] = res
            except Exception as exc:
                results_map[vid] = {
                    "video_id": vid,
                    "video_title": vid,
                    "video_number": None,
                    "success": False,
                    "source": None,
                    "error": str(exc),
                    "skipped": False,
                    "json_path": None,
                }

    # Reconstruct final results in the exact original playlist order
    ordered_results: List[Dict] = [
        results_map.get(item["video_id"], {
            "video_id": item["video_id"],
            "video_title": item.get("title", item["video_id"]),
            "video_number": item.get("video_number"),
            "success": False,
            "source": None,
            "error": "Result missing",
            "skipped": False,
            "json_path": None,
        })
        for item in deduped_videos
    ]

    return ordered_results


# ============================================================
# PROCESS PLAYLIST (CONCURRENT)
# ============================================================

def process_playlist(
    video_url: str,
    max_workers: int = MAX_CONCURRENT_VIDEOS,
) -> bool:
    """
    Discovers playlist videos and processes them concurrently with bounded workers.
    Preserves exact playlist order in saved metadata.
    """
    print("\n[Playlist] Discovering playlist videos and metadata...")
    playlist_info = extract_playlist_info(video_url)
    videos = playlist_info.get("videos", [])

    if not videos:
        # Fallback to simple extraction
        raw_urls = extract_playlist_videos(video_url)
        if not raw_urls:
            print("Error: Unable to extract videos from playlist.")
            return False
        videos = [
            {
                "video_id": extract_video_id(u),
                "url": u,
                "video_number": idx,
                "title": None,
            }
            for idx, u in enumerate(raw_urls, start=1)
        ]

    total = len(videos)
    playlist_id = (
        playlist_info.get("playlist_id")
        or parse_qs(urlparse(video_url).query).get("list", [None])[0]
    )
    playlist_title = playlist_info.get("title") or f"Playlist_{playlist_id}"

    print(f"[Playlist] Found {total} videos for '{playlist_title}' ({playlist_id}).")

    # Run bounded concurrent processing
    results = process_videos_batch(
        videos=videos,
        playlist_id=playlist_id,
        playlist_title=playlist_title,
        max_workers=max_workers,
    )

    successful = sum(1 for r in results if r.get("success"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = total - successful

    if playlist_id:
        save_playlist_meta(
            get_playlist_dir(playlist_id, playlist_title),
            playlist_id,
            playlist_title,
            video_url,
            total,
        )

    print("\n" + "=" * 60)
    print(f"[Playlist] Processing Completed: {playlist_title}")
    print(f"  Total: {total} | Succeeded: {successful} | Skipped: {skipped} | Failed: {failed}")
    print("=" * 60)

    return successful > 0


# ============================================================
# CLI
# ============================================================

def main() -> None:
    video_url = input(
        "Enter YouTube video/playlist URL: "
    ).strip()

    if not video_url:
        print("Error: YouTube URL is required.")
        return

    if is_playlist_url(video_url):
        process_playlist(video_url)
        return

    process_single_video(video_url)


if __name__ == "__main__":
    main()