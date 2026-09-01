import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
)
from sentence_transformers import SentenceTransformer


# ============================================================
# PATH / ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
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

# Number of closest vector matches to retrieve
TOP_K = int(
    os.getenv(
        "TOP_K",
        "4",
    )
)

RETRIEVAL_CANDIDATE_LIMIT = int(
    os.getenv(
        "RETRIEVAL_CANDIDATE_LIMIT",
        "300",
    )
)

RETRIEVAL_K = TOP_K
LOCATE_RETRIEVAL_K = TOP_K

# Relevance threshold for cosine similarity (calibrated for E5)
MIN_RELEVANCE_SCORE = float(
    os.getenv(
        "MIN_RELEVANCE_SCORE",
        "0.78",
    )
)

MIN_KEYWORD_SCORE = 0.0
SEMANTIC_WEIGHT = 1.0
KEYWORD_WEIGHT = 0.0

NO_MATCH_MESSAGE = (
    "This topic is not covered in this video or playlist."
)


# ============================================================
# QUERY FRAMING NORMALIZATION
#
# Removes conversational framing words (e.g. "ke bare me",
# "kon se video me bataya gaya hai", "where is") so that
# the vector embedding represents the core topical concept
# instead of matching conversational scaffolding.
# ============================================================

FRAMING_PATTERNS = [
    # Question wrappers (e.g. kya isme, kya ye)
    r"\b(kya\s+isme(in)?|kya\s+is\s+video\s+me(in)?|kya\s+yeh?)\b",
    
    # Video/location specifiers (e.g. kon se video me, kis video me, kisme)
    r"\b(ko[an]\s+se?|kis|which|what)\s+(video|lecture|episode|part|lesson)\s*(me(in)?|pe|par)?\b",
    r"\b(kis\s*me(in)?|kis\s*pe|kis\s*par)\b",
    
    # "About" phrasing (e.g. ke bare me, ke baare mein)
    r"\b(ke\s+|k\s+)?ba+re\s+me(in)?\b",
    r"\babout\b",
    
    # Location words (e.g. kaha, knha, kahan, kidhar)
    r"\b(ka+ha+n?|knha|kidhar)\s*(pe|par)?\b",
    r"\bwhere\s+(is|was|can\s+i\s+find|did|to\s+find)\b",
    
    # Action verbs (e.g. bataya, padhaya, sikhaya, explain kiya, cover kiya)
    r"\b(bata(ya|yi|ye|ana|o|iye|do)?|btya)\b",
    r"\b(padha(ya|yi|ye|ana|o|do|iye)?|pdhaya)\b",
    r"\b(sikha(ya|yi|ye|ana|o|do|iye)?)\b",
    r"\b(samjha(ya|yi|ye|ana|o|do|iye)?)\b",
    r"\b(explain|discuss(ed)?|mention(ed)?)\s*(kiya|kara|hua)?\b",
    r"\bcover(ed)?\s*(kiya|kara|hua)?\b",
    
    # Passive auxiliaries (e.g. gaya, gya, gaya hai, gya h)
    r"\b(ga?ya|ga?yi|ga?ye|hua|hue|hui)\b",
    
    # Trailing copulas in location questions (hai, h, hain, tha, thi, the)
    r"\b(hai|h|hain|tha|thi|the)\b",
    
    # English passive wrappers (e.g. is taught in, is explained in)
    r"\b(is|are|was|were)\s+(taught|explained|covered|mentioned|discussed)\s*(in)?\b",
]


def clean_query_text(query: str) -> str:
    """Strip conversational location framing from query before embedding."""
    text = query.strip()
    for pat in FRAMING_PATTERNS:
        text = re.sub(pat, " ", text, flags=re.IGNORECASE)
    cleaned = " ".join(text.split()).strip()
    return cleaned if cleaned else query.strip()


# ============================================================
# EMBEDDING MODEL
# ============================================================

def load_embedding_model() -> SentenceTransformer:
    print(
        f"Loading embedding model: {EMBEDDING_MODEL}"
    )
    return SentenceTransformer(
        EMBEDDING_MODEL
    )


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
            "QDRANT_URL not found in .env"
        )

    if not qdrant_api_key:
        raise RuntimeError(
            "QDRANT_API_KEY not found in .env"
        )

    return QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key,
        timeout=120,
    )


# ============================================================
# TIMESTAMP & URL HELPERS
# ============================================================

def format_timestamp(
    seconds: float,
) -> str:
    total_seconds = max(
        0,
        int(seconds),
    )
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def create_timestamp_url(
    video_id: str,
    start_sec: float,
) -> str:
    seconds = max(
        0,
        int(start_sec),
    )
    return f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"


# ============================================================
# QUERY FILTER BUILDER
# ============================================================

def build_query_filter(
    video_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
) -> Optional[Filter]:
    conditions = []

    if video_id:
        conditions.append(
            FieldCondition(
                key="video_id",
                match=MatchValue(
                    value=video_id
                ),
            )
        )

    if playlist_id:
        conditions.append(
            FieldCondition(
                key="playlist_id",
                match=MatchValue(
                    value=playlist_id
                ),
            )
        )

    if not conditions:
        return None

    return Filter(
        must=conditions
    )


# ============================================================
# LIGHTWEIGHT PAYLOAD FIELDS & IN-MEMORY CHUNK HYDRATION
# ============================================================

LIGHTWEIGHT_PAYLOAD_FIELDS = [
    "video_id",
    "video_title",
    "video_number",
    "playlist_id",
    "playlist_title",
    "start_sec",
    "end_sec",
    "start_time",
    "end_time",
    "chunk_id",
    "source",
    "approximate",
]

_VIDEO_CHUNKS_MAP_CACHE: Dict[str, Dict[float, Dict[str, str]]] = {}


def get_video_chunks_map(video_id: str) -> Dict[float, Dict[str, str]]:
    """Return in-memory map of start_sec -> {text, english_text} for a video."""
    if video_id in _VIDEO_CHUNKS_MAP_CACHE:
        return _VIDEO_CHUNKS_MAP_CACHE[video_id]

    file_path = get_transcript_file_for_video(video_id)
    if not file_path or not file_path.exists():
        _VIDEO_CHUNKS_MAP_CACHE[video_id] = {}
        return {}

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        raw_chunks = data.get("chunks", [])
        if not raw_chunks:
            _VIDEO_CHUNKS_MAP_CACHE[video_id] = {}
            return {}

        sorted_chunks = sorted(
            raw_chunks,
            key=lambda c: float(c.get("start_time", 0.0)),
        )
        total_duration = float(sorted_chunks[-1].get("end_time", 0.0))
        step = 60.0  # 75.0 - 15.0
        t = float(sorted_chunks[0].get("start_time", 0.0))
        window_starts = []
        while t < total_duration:
            window_starts.append(t)
            t += step
        if not window_starts:
            window_starts = [0.0]

        chunked = []
        for win_start in window_starts:
            win_end = win_start + 75.0
            window_segs = [
                seg for seg in sorted_chunks
                if float(seg.get("start_time", 0.0)) < win_end
                and float(seg.get("end_time", 0.0)) > win_start
            ]
            if not window_segs:
                continue

            actual_start = float(window_segs[0].get("start_time", win_start))
            actual_end = float(window_segs[-1].get("end_time", win_end))
            text = " ".join(
                str(seg.get("text", "")).strip()
                for seg in window_segs
                if str(seg.get("text", "")).strip()
            )
            english_text = " ".join(
                str(seg.get("english_text", seg.get("text", ""))).strip()
                for seg in window_segs
                if str(seg.get("english_text", seg.get("text", ""))).strip()
            )
            chunked.append({
                "start_sec": actual_start,
                "end_sec": actual_end,
                "text": text,
                "english_text": english_text,
            })

        mapping = {}
        for c in chunked:
            st = round(float(c.get("start_sec", 0.0)), 2)
            mapping[st] = {
                "text": c.get("text", ""),
                "english_text": c.get("english_text", c.get("text", "")),
            }
        _VIDEO_CHUNKS_MAP_CACHE[video_id] = mapping
        return mapping
    except Exception:
        _VIDEO_CHUNKS_MAP_CACHE[video_id] = {}
        return {}


# ============================================================
# NORMALIZE CANDIDATE FROM QDRANT PAYLOAD
# ============================================================

def normalize_candidate(
    payload: Dict,
    score: float = 0.0,
) -> Optional[Dict]:
    video_id = str(
        payload.get(
            "video_id",
            "",
        )
    ).strip()

    if not video_id:
        return None

    try:
        start_sec = float(
            payload.get(
                "start_sec",
                payload.get("start_time", 0.0),
            )
        )
    except (TypeError, ValueError):
        start_sec = 0.0

    try:
        end_sec = float(
            payload.get(
                "end_sec",
                payload.get("end_time", 0.0),
            )
        )
    except (TypeError, ValueError):
        end_sec = 0.0

    text = str(
        payload.get(
            "text",
            "",
        )
    ).strip()

    english_text = str(
        payload.get(
            "english_text",
            "",
        )
    ).strip()

    # Hydrate from local chunk cache if text was omitted from Qdrant payload transfer
    if not text:
        cmap = get_video_chunks_map(video_id)
        st_key = round(start_sec, 2)
        matched = cmap.get(st_key)
        if not matched:
            for k, v in cmap.items():
                if abs(k - st_key) <= 0.1:
                    matched = v
                    break
        if matched:
            text = matched.get("text", "")
            english_text = matched.get("english_text", text)

    if not text:
        return None

    if not english_text:
        english_text = text

    video_title = (
        payload.get("video_title")
        or video_id
    )

    video_number = payload.get("video_number")
    if video_number is not None:
        try:
            video_number = int(video_number)
        except (TypeError, ValueError):
            video_number = None

    chunk_id = (
        payload.get("chunk_id")
        or f"{video_id}:{int(start_sec)}"
    )

    norm_score = round(float(score), 4)

    return {
        "video_id": video_id,
        "video_title": str(video_title),
        "video_number": video_number,
        "playlist_id": payload.get("playlist_id"),
        "playlist_title": payload.get("playlist_title"),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "start_time": start_sec,
        "end_time": end_sec,
        "text": text,
        "english_text": english_text,
        "chunk_id": chunk_id,
        "url": create_timestamp_url(video_id, start_sec),
        "score": norm_score,
        "qdrant_score": norm_score,
        "keyword_score": 0.0,
        "combined_score": norm_score,
        "reranker_score": norm_score,
        "source": payload.get("source", "caption"),
        "approximate": bool(payload.get("approximate", False)),
    }


# ============================================================
# VECTOR-BASED SEMANTIC SEARCH
# ============================================================

def semantic_search(
    question: str,
    model: SentenceTransformer,
    client: QdrantClient,
    limit: int = 4,
    query_filter: Optional[Filter] = None,
) -> List[Dict]:
    if not question.strip():
        return []

    # Clean conversational location framing for accurate topical vector embedding
    cleaned_query = clean_query_text(question)

    # Prepend 'query: ' for E5 model compatibility
    model_name_str = str(getattr(model, "model_card_data", "") or "") + str(EMBEDDING_MODEL).lower()
    if "e5" in model_name_str.lower():
        query_input = f"query: {cleaned_query}"
    else:
        query_input = cleaned_query

    query_vector = model.encode(
        query_input,
        normalize_embeddings=True,
    ).tolist()

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=LIGHTWEIGHT_PAYLOAD_FIELDS,
    )

    candidates: List[Dict] = []

    for point in response.points:
        cand = normalize_candidate(
            payload=point.payload or {},
            score=point.score or 0.0,
        )
        if cand:
            candidates.append(cand)

    # Order from best match to worst match (descending cosine similarity)
    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return candidates


# ============================================================
# GENERIC SECOND-STAGE RELEVANCE & EXACT VIDEO SELECTION
# ============================================================

STOP_WORDS = {
    "kaha", "knha", "kahan", "kidhar", "bataya", "btya", "padhaya", "pdhaya",
    "sikhaya", "samjhaya", "hua", "hue", "hui", "hai", "hain", "h", "mein", "me",
    "pe", "par", "ko", "se", "ka", "ke", "ki", "kya", "isme", "is", "ye", "yeh",
    "wo", "woh", "kis", "kon", "video", "lecture", "episode", "part", "explain",
    "explained", "solve", "solved", "discussion", "covered", "where", "in",
    "which", "what", "how", "to", "the", "a", "an", "of", "for", "on", "and", "or",
    "bare", "baare", "about", "kare", "karna", "karein", "dekh", "dekhe", "dekhein",
}


def extract_core_terms(query_text: str) -> Tuple[str, List[str]]:
    cleaned = clean_query_text(query_text).lower()
    tokens = re.findall(r"[\w\u0900-\u097F]+", cleaned)
    core = [t for t in tokens if t not in STOP_WORDS and len(t) > 1]
    return cleaned, core


def evaluate_second_stage_relevance(
    question: str,
    candidates: List[Dict],
    min_score: float = MIN_RELEVANCE_SCORE,
    limit: int = TOP_K,
    window_seconds: float = 15.0,
) -> List[Dict]:
    """
    Generic Second-Stage Relevance Evaluation:
    Evaluates exact phrase matches, token coverage, and chunk topical density
    across video title, english_text, and original text without domain-specific rules.
    """
    if not candidates:
        return []

    cleaned_q, core_terms = extract_core_terms(question)

    top_dense = candidates[0].get("score", 0.0)
    if top_dense < min_score:
        return []

    # Build n-grams from core query terms (2-grams, 3-grams)
    ngrams = []
    if len(core_terms) >= 2:
        for i in range(len(core_terms) - 1):
            ngrams.append(f"{core_terms[i]} {core_terms[i+1]}")
    if len(core_terms) >= 3:
        for i in range(len(core_terms) - 2):
            ngrams.append(f"{core_terms[i]} {core_terms[i+1]} {core_terms[i+2]}")

    scored_candidates = []
    for c in candidates:
        dense_score = float(c.get("score", 0.0))
        title = str(c.get("video_title", "")).lower()
        en_text = str(c.get("english_text", "")).lower()
        hi_text = str(c.get("text", "")).lower()
        chunk_text = f"{en_text} {hi_text}"
        doc_text = f"{title} {chunk_text}"

        phrase_in_title = bool(cleaned_q and cleaned_q in title)
        phrase_in_chunk = bool(cleaned_q and cleaned_q in chunk_text)

        if core_terms:
            title_hits = sum(1 for t in core_terms if t in title)
            chunk_hits = sum(1 for t in core_terms if t in chunk_text)
            doc_hits = sum(1 for t in core_terms if t in doc_text)

            title_cov = title_hits / len(core_terms)
            chunk_cov = chunk_hits / len(core_terms)
            doc_cov = doc_hits / len(core_terms)
        else:
            title_cov = chunk_cov = doc_cov = 1.0

        ngram_hits = sum(1 for ng in ngrams if ng in doc_text)
        ngram_score = min(1.0, ngram_hits / len(ngrams)) if ngrams else 0.0

        topical_boost = (
            0.12 * doc_cov +
            0.08 * title_cov +
            0.06 * chunk_cov +
            (0.12 if phrase_in_title else 0.0) +
            (0.08 if phrase_in_chunk else 0.0) +
            0.04 * ngram_score
        )

        s2_score = round(dense_score + topical_boost, 4)
        scored_candidates.append({
            **c,
            "dense_score": dense_score,
            "stage2_score": s2_score,
            "combined_score": s2_score,
            "score": s2_score,
            "doc_cov": doc_cov,
        })

    # Not-Covered Gate: Check if candidate pool contains true subject evidence
    has_subject_evidence = False
    if not core_terms:
        has_subject_evidence = max(sc["dense_score"] for sc in scored_candidates) >= 0.82
    else:
        for sc in scored_candidates:
            title = str(sc.get("video_title", "")).lower()
            en_text = str(sc.get("english_text", "")).lower()
            hi_text = str(sc.get("text", "")).lower()
            doc_text = f"{title} {en_text} {hi_text}"

            if cleaned_q and cleaned_q in doc_text:
                has_subject_evidence = True
                break

            if len(core_terms) >= 2:
                t0, t1 = core_terms[0], core_terms[1]
                if (t0 in doc_text and t1 in doc_text) or f"{t0} {t1}" in doc_text:
                    has_subject_evidence = True
                    break
            else:
                if core_terms[0] in doc_text:
                    has_subject_evidence = True
                    break

    if not has_subject_evidence:
        return []

    # Group candidates by video_id
    video_groups: Dict[str, List[Dict]] = {}
    for sc in scored_candidates:
        vid = sc["video_id"]
        video_groups.setdefault(vid, []).append(sc)

    ranked_videos = []
    for vid, v_chunks in video_groups.items():
        v_chunks.sort(key=lambda x: x["stage2_score"], reverse=True)
        # Deduplicate near-duplicate timestamps within video (~15s)
        deduped = []
        for chk in v_chunks:
            t = chk["start_time"]
            if not any(abs(t - prev["start_time"]) <= window_seconds for prev in deduped):
                deduped.append(chk)
        if deduped:
            best_chunk = deduped[0]
            ranked_videos.append({
                "video_id": vid,
                "video_title": best_chunk["video_title"],
                "best_score": best_chunk["stage2_score"],
                "chunks": deduped,
            })

    ranked_videos.sort(key=lambda v: v["best_score"], reverse=True)

    final_results: List[Dict] = []
    for v in ranked_videos:
        for chk in v["chunks"][:2]:
            final_results.append(chk)
            if len(final_results) >= limit:
                break
        if len(final_results) >= limit:
            break

    return final_results


# ============================================================
# RAW TRANSCRIPT SEGMENT TIMESTAMP REFINEMENT
#
# Inspects the original raw transcript segments for the selected
# 75s chunk and pinpoints the earliest segment that introduces
# or contains direct topical evidence for the user query.
# ============================================================

_TRANSCRIPT_FILE_INDEX: Dict[str, Path] = {}
_TRANSCRIPT_RAW_SEGMENTS_CACHE: Dict[str, List[Dict]] = {}


def get_transcript_file_for_video(video_id: str) -> Optional[Path]:
    """Index and resolve transcript JSON path by video_id."""
    if not _TRANSCRIPT_FILE_INDEX:
        base_dir = Path(__file__).resolve().parent
        for path in base_dir.rglob("*.json"):
            if path.name not in {"playlist_meta.json", "video_meta.json"} and "backups" not in path.parts:
                _TRANSCRIPT_FILE_INDEX[path.stem] = path
    return _TRANSCRIPT_FILE_INDEX.get(video_id)


def get_raw_segments_for_video(video_id: str) -> List[Dict]:
    """Retrieve raw transcript segments for a video from existing JSON files."""
    if video_id in _TRANSCRIPT_RAW_SEGMENTS_CACHE:
        return _TRANSCRIPT_RAW_SEGMENTS_CACHE[video_id]

    file_path = get_transcript_file_for_video(video_id)
    if file_path and file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            chunks = data.get("chunks", [])
            if isinstance(chunks, list):
                _TRANSCRIPT_RAW_SEGMENTS_CACHE[video_id] = chunks
                return chunks
        except Exception:
            pass
    return []


def refine_candidate_timestamp(candidate: Dict, query: str) -> Dict:
    """
    Refines the candidate's timestamp to the earliest raw transcript segment
    inside the 75-second retrieval window that contains direct evidence for the query.
    """
    video_id = candidate.get("video_id")
    if not video_id:
        return candidate

    chunk_start = float(candidate.get("start_sec", candidate.get("start_time", 0.0)))
    chunk_end = float(candidate.get("end_sec", candidate.get("end_time", chunk_start + 75.0)))

    raw_segs = get_raw_segments_for_video(video_id)
    if not raw_segs:
        return candidate

    overlapping_segs = [
        seg for seg in raw_segs
        if float(seg.get("end_time", 0.0)) > chunk_start - 0.5
        and float(seg.get("start_time", 0.0)) < chunk_end + 0.5
    ]

    if not overlapping_segs:
        return candidate

    cleaned_q, core_terms = extract_core_terms(query)
    ngrams = []
    if len(core_terms) >= 2:
        for i in range(len(core_terms) - 1):
            ngrams.append(f"{core_terms[i]} {core_terms[i+1]}")
    if len(core_terms) >= 3:
        for i in range(len(core_terms) - 2):
            ngrams.append(f"{core_terms[i]} {core_terms[i+1]} {core_terms[i+2]}")

    scored_segs = []
    for seg in overlapping_segs:
        s_start = float(seg.get("start_time", 0.0))
        s_end = float(seg.get("end_time", s_start))
        en_text = str(seg.get("english_text", "")).lower()
        hi_text = str(seg.get("text", "")).lower()
        seg_text = f"{en_text} {hi_text}"

        phrase_hit = bool(cleaned_q and cleaned_q in seg_text)
        if core_terms:
            terms_hit = sum(1 for t in core_terms if t in seg_text)
            cov = terms_hit / len(core_terms)
        else:
            terms_hit = 0
            cov = 0.0

        ngram_hits = sum(1 for ng in ngrams if ng in seg_text)
        ngram_score = (ngram_hits / len(ngrams)) if ngrams else 0.0

        seg_score = (
            (1.0 if phrase_hit else 0.0) +
            cov * 0.8 +
            ngram_score * 0.5 +
            (0.1 if terms_hit > 0 else 0.0)
        )

        scored_segs.append({
            "start_time": s_start,
            "end_time": s_end,
            "seg_score": seg_score,
            "terms_hit": terms_hit,
            "phrase_hit": phrase_hit,
            "text": seg.get("text", ""),
            "english_text": seg.get("english_text", ""),
        })

    max_seg_score = max(s["seg_score"] for s in scored_segs) if scored_segs else 0.0
    if max_seg_score > 0.15:
        threshold = max(0.35, max_seg_score * 0.75)
        strong_segs = [s for s in scored_segs if s["seg_score"] >= threshold]
        if strong_segs:
            refined_seg = strong_segs[0]
            new_start = refined_seg["start_time"]
            if new_start >= chunk_start:
                updated = dict(candidate)
                updated["start_time"] = new_start
                updated["start_sec"] = new_start
                updated["url"] = create_timestamp_url(video_id, new_start)
                return updated

    return candidate


# ============================================================
# RETRIEVE CANDIDATES (CORE API - TWO-STAGE VECTOR & LEXICAL)
# ============================================================

def retrieve_candidates(
    question: str,
    model: SentenceTransformer,
    client: QdrantClient,
    limit: int = TOP_K,
    candidate_pool_limit: int = RETRIEVAL_CANDIDATE_LIMIT,
    video_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    window_seconds: float = 15.0,
) -> List[Dict]:
    """
    Two-Stage Candidate Retrieval with Timestamp Precision Refinement:
    1. Broad Dense Vector Search in Qdrant (300 candidates).
    2. Generic Second-Stage Relevance Evaluation (lexical/semantic evidence).
    3. Exact video ranking & timestamp deduplication (~15s).
    4. Exact raw-segment timestamp precision refinement.
    """
    query_filter = build_query_filter(
        video_id=video_id,
        playlist_id=playlist_id,
    )

    # Stage 1: Broad Vector Search across Qdrant
    raw_candidates = semantic_search(
        question=question,
        model=model,
        client=client,
        limit=candidate_pool_limit,
        query_filter=query_filter,
    )

    if not raw_candidates:
        return []

    # Stage 2: Generic Second-Stage Relevance Evaluation & Video Ranking
    stage2_results = evaluate_second_stage_relevance(
        question=question,
        candidates=raw_candidates,
        min_score=MIN_RELEVANCE_SCORE,
        limit=limit * 2,
        window_seconds=window_seconds,
    )

    # Stage 3: Timestamp Precision Refinement to exact raw segment
    refined_results = [
        refine_candidate_timestamp(cand, question)
        for cand in stage2_results
    ]

    # Re-deduplicate by refined timestamps (~15s) within same video
    seen_times: Dict[str, List[float]] = {}
    deduped_results: List[Dict] = []
    for cand in refined_results:
        vid = cand["video_id"]
        t = float(cand["start_sec"])
        if vid in seen_times:
            if any(abs(t - prev_t) <= window_seconds for prev_t in seen_times[vid]):
                continue
        seen_times.setdefault(vid, []).append(t)
        deduped_results.append(cand)
        if len(deduped_results) >= limit:
            break

    return deduped_results


# ============================================================
# RELEVANCE & DEDUPLICATION HELPERS
# ============================================================

def has_relevant_match(
    candidates: List[Dict],
    min_score: float = MIN_RELEVANCE_SCORE,
    question: Optional[str] = None,
) -> bool:
    """Return True if the top candidate meets the empirical similarity threshold."""
    if not candidates:
        return False
    return float(candidates[0].get("score", 0.0)) >= min_score


def rerank_chunks(
    question: str,
    candidates: List[Dict],
    top_k: int = 4,
) -> List[Dict]:
    if not candidates:
        return []
    sorted_cands = sorted(
        candidates,
        key=lambda item: item.get("score", 0.0),
        reverse=True,
    )
    return sorted_cands[:top_k]


def deduplicate_by_time(
    candidates: List[Dict],
    window_seconds: float = 15.0,
) -> List[Dict]:
    """
    Collapse near-duplicate timestamps (~15s) within the same video,
    while allowing genuinely different moments from the same video.
    """
    if not candidates:
        return []

    seen: Dict[str, List[float]] = {}
    deduped: List[Dict] = []

    for item in candidates:
        vid = item["video_id"]
        t = float(item["start_sec"])
        if vid in seen:
            if any(abs(t - prev_t) <= window_seconds for prev_t in seen[vid]):
                continue
            seen[vid].append(t)
        else:
            seen[vid] = [t]
        deduped.append(item)

    return deduped


def extract_query_terms_and_phrases(
    question: str,
) -> Tuple[List[str], List[str]]:
    tokens = [w for w in question.lower().split() if w]
    return tokens, []


# ============================================================
# PRINT RESULTS (CLI)
# ============================================================

def print_results(
    question: str,
    results: List[Dict],
) -> None:
    print("\n" + "=" * 80)
    print(f"Question: {question}")
    print("=" * 80)

    if not results:
        print(f"\n{NO_MATCH_MESSAGE}")
        return

    for index, result in enumerate(results, start=1):
        start = format_timestamp(result["start_sec"])
        end = format_timestamp(result["end_sec"])
        video_number = result.get("video_number")
        video_title = result.get("video_title") or result["video_id"]

        if video_number is not None:
            video_label = f"Video {video_number} - {video_title}"
        else:
            video_label = video_title

        print(f"\n{index}. {video_label}")
        print(f"   Time: {start} - {end}")
        print(f"   Score: {result.get('score', 0.0)}")
        print(f"   URL: {result['url']}")
        print(f"   Text: {result['text'][:120]}...")

    print("\n" + "=" * 80)


def main() -> None:
    model = load_embedding_model()
    client = get_qdrant_client()

    print("\nReady. Vector retrieval initialized. Ask questions repeatedly.")
    print("Type 'exit', 'quit', or 'q' to stop.\n")

    while True:
        try:
            question = input("Enter your question: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if not question:
            continue

        if question.lower() in {"exit", "quit", "q"}:
            break

        results = retrieve_candidates(
            question=question,
            model=model,
            client=client,
            limit=4,
        )

        print_results(
            question=question,
            results=results,
        )


if __name__ == "__main__":
    main()
