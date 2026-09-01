import os
import re
import sys
from typing import Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .retrieval import (
    COLLECTION_NAME,
    MIN_KEYWORD_SCORE,
    MIN_RELEVANCE_SCORE,
    build_query_filter,
    deduplicate_by_time,
    extract_query_terms_and_phrases,
    get_qdrant_client,
    has_relevant_match,
    load_embedding_model,
    retrieve_candidates,
    rerank_chunks,
)


# ============================================================
# CONFIGURATION
# ============================================================

CHAT_HISTORY_TURNS = int(
    os.getenv(
        "CHAT_HISTORY_TURNS",
        "5",
    )
)

RETRIEVAL_K = int(
    os.getenv(
        "RETRIEVAL_K",
        "20",
    )
)

TOP_K = int(
    os.getenv(
        "TOP_K",
        "4",
    )
)

LOCATE_TOP_K = int(
    os.getenv(
        "LOCATE_TOP_K",
        "4",
    )
)

RETRIEVAL_CANDIDATE_LIMIT = int(
    os.getenv(
        "RETRIEVAL_CANDIDATE_LIMIT",
        "300",
    )
)

# For timestamp/location results we keep nearby but
# genuinely different explanations instead of collapsing
# a 45-second region into one result.
LOCATE_DEDUP_WINDOW_SECONDS = float(
    os.getenv(
        "LOCATE_DEDUP_WINDOW_SECONDS",
        "15",
    )
)

CHAT_DEDUP_WINDOW_SECONDS = float(
    os.getenv(
        "CHAT_DEDUP_WINDOW_SECONDS",
        "45",
    )
)


# ============================================================
# SCOPE-AWARE NOT-COVERED MESSAGES
# ============================================================

def get_not_covered_message(scope: str) -> str:
    """
    Return a scope-aware 'not covered' message.
    scope: "video" | "playlist" | "all"
    """
    if scope == "video":
        return (
            "Bhai, ye topic is video mein cover nahi hua hai. "
            "Agar chaho to main tumhe ye topic yahin padha sakta hoon."
        )
    if scope == "playlist":
        return (
            "Bhai, ye topic is playlist mein cover nahi hua hai. "
            "Agar chaho to main tumhe ye topic yahin padha sakta hoon."
        )
    # "all" — global search
    return (
        "Bhai, ye topic indexed videos mein cover nahi hua hai. "
        "Agar chaho to main tumhe ye topic yahin padha sakta hoon."
    )


# ============================================================
# TEACH MODE — PATTERNS AND TOPIC RECOVERY
# ============================================================

# Patterns that indicate the user wants a direct explanation
# after the assistant previously said the topic is not covered.
TEACH_PATTERNS = [
    r"\btum hi batao\b",
    r"\btum batao\b",
    r"\btum hi samjhao\b",
    r"\btum samjhao\b",
    r"\btheek hai tum\b",
    r"\bacha tum\b",
    r"\bok tum\b",
    r"\bokay tum\b",
    r"\bmujhe padha do\b",
    r"\bpadha do\b",
    r"\bteach me\b",
    r"\bthen explain\b",
    r"\bexplain it\b",
    r"\bokay explain\b",
    r"\bsamjha do\b",
    r"\bsikha do\b",
    r"\btoh padha do\b",
    r"\bfir padha do\b",
    r"\bchalo tum batao\b",
    r"\btum hi bata\b",
]

# Words that strongly indicate a "topic location" question
# (not content).  These are used to strip topic-location
# query words when recovering the actual topic.
_LOCATION_QUERY_WORDS = {
    "where", "kaha", "kahan", "kahaan", "knha",
    "padhaya", "padhayi", "padha", "padhi", "padhe",
    "sikhaya", "sikhayi", "sikhaya",
    "bataya", "batayi", "bataye", "batana",
    "taught", "teach", "teaching",
    "covered", "cover", "covering",
    "mentioned", "mention", "discussed", "discuss",
    "explained", "explain",
    "kaha", "kab", "kis", "konse", "kaunse",
    "lecture", "lesson", "part", "video", "videos",
    "topic", "topics", "jagah", "time", "timestamp",
    "padhaya", "gaya", "gayi", "gaye", "hua", "hui", "huye",
}


def is_teach_intent(question: str) -> bool:
    """Return True if the question is a teach follow-up."""
    text = question.lower().strip()
    return any(
        re.search(pattern, text)
        for pattern in TEACH_PATTERNS
    )


def recover_topic_from_history(
    chat_history: List[Dict],
    current_question: str,
) -> str:
    """
    Walk backwards through chat_history to find the last
    meaningful user query that contained a topic term.
    Returns the best topic string found, or the current
    question as a fallback.
    """
    # Collect all user messages from recent history
    user_messages = [
        msg.get("content", "")
        for msg in reversed(chat_history)
        if msg.get("role") == "user"
        and msg.get("content", "").strip()
    ]

    for msg in user_messages:
        # Skip the current teach follow-up message itself
        if is_teach_intent(msg):
            continue

        # Extract content tokens (ignoring location query words)
        words = re.findall(
            r"[\w\u0900-\u097F]+",
            msg.lower(),
        )
        topic_words = [
            w for w in words
            if w not in _LOCATION_QUERY_WORDS
            and len(w) > 2
        ]

        if topic_words:
            # Return the original (unprocessed) message as topic
            # so the LLM gets the full natural-language context.
            return msg.strip()

    # Fallback: use current question stripped of teach patterns
    return current_question.strip()


# ============================================================
# DISPLAY VIDEO NUMBER HELPER
#
# Extracts the intended episode / video number from the title
# (e.g. "Ep 10", "Episode 02", "Ep:05", "Ep. 03", "#14", "15 | Quadrant")
# so that non-episode playlist insertions do not shift the numbers.
# Falls back to playlist position if no episode tag is found.
# ============================================================

def extract_display_video_number(
    title: Optional[str],
    fallback_number: Optional[int] = None,
) -> Optional[int]:
    if not title:
        return fallback_number

    # Match patterns like "Ep 10", "Episode 02", "Ep:05", "Ep. 03", "#14"
    match = re.search(
        r"\b(?:ep(?:isode)?\.?[:\s]*|#\s*)(\d+)\b",
        title,
        re.IGNORECASE,
    )
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            pass

    # Match starting number pattern like "15 | Quadrant" or "12. What is RAG"
    match_start = re.match(
        r"^\s*(\d+)\s*[\|\-\.:]",
        title,
    )
    if match_start:
        try:
            return int(match_start.group(1))
        except (TypeError, ValueError):
            pass

    return fallback_number


def is_preceded_by_not_covered(
    chat_history: Optional[List[Dict]],
) -> bool:
    """Return True only if the last assistant message was a 'not covered' response."""
    if not chat_history:
        return False
    for msg in reversed(chat_history):
        if msg.get("role") in ("assistant", "bot"):
            content = msg.get("content", "").lower()
            return (
                "cover nahi hua" in content
                or "not covered in this" in content
                or "yahin padha sakta hoon" in content
                or "topic is not covered" in content
            )
    return False


# ============================================================
# INTENT DETECTION
# ============================================================

def detect_intent(
    question: str,
    chat_history: Optional[List[Dict]] = None,
) -> str:
    """
    Returns: "summary" | "teach" | "locate" | "chat"
    """
    text = question.lower().strip()

    # 1. Teach follow-up intent
    #    Must be checked BEFORE locate because some teach
    #    phrases ("samjha do") overlap with locate patterns,
    #    BUT ONLY when the immediately preceding assistant turn
    #    was a 'not covered' response.
    if is_teach_intent(question) and is_preceded_by_not_covered(chat_history):
        return "teach"

    # 2. Summary intent check
    summary_patterns = [
        r"\bsummary\b",
        r"\bsummarize\b",
        r"\bsummarise\b",
        r"\boverview\b",
        r"\bsaransh\b",
        r"\bkhulasa\b",
        r"\bgist\b",
        r"\brecap\b",
        r"\bbrief\b",
    ]

    if any(
        re.search(
            pattern,
            text,
        )
        for pattern in summary_patterns
    ):
        return "summary"

    # 3. Location / timestamp intent check
    locate_patterns = [
        r"\bwhere\b",
        r"\bwhere is\b",
        r"\bwhere was\b",
        r"\bwhich video\b",
        r"\bwhat video\b",
        r"\bcovered\b",
        r"\bcover(ed)?\b",
        r"\btaught\b",
        r"\bmentioned\b",
        r"\btimestamp\b",
        r"\btimestamps\b",
        r"\btime stamp\b",
        r"\btime-stamp\b",
        r"\bminute\b",
        r"\bkis video\b",
        r"\bkis video me\b",
        r"\bkis video mein\b",
        r"\bkonse video\b",
        r"\bkaunse video\b",
        r"\bkahan\b",
        r"\bkahaan\b",
        r"\bkaha\b",
        r"\bknha\b",
        r"\bkis time\b",
        r"\bkis jagah\b",
        r"\bwhere did\b",
        r"\bwhere can i find\b",
        r"\bwhich lecture\b",
        r"\bwhich lesson\b",
        r"\bwhich part\b",
        r"\bshow me where\b",
        r"\bbataya\b",
        r"\bbatayi\b",
        r"\bbataye\b",
        r"\bbatana\b",
        r"\bpadhaya\b",
        r"\bpadhayi\b",
        r"\bpadha\b",
        r"\bsikhaya\b",
        r"\bsikhayi\b",
        r"\bcover kiya\b",
        r"\bcover hua\b",
        r"\bcover hai\b",
        r"\bcovers\b",
        r"\bkya isme\b",
        r"\bkya is\b",
        r"\bkya yeh\b",
        r"\bkya ye\b",
    ]

    if any(
        re.search(
            pattern,
            text,
        )
        for pattern in locate_patterns
    ):
        return "locate"

    return "chat"


# ============================================================
# TIMESTAMP
# ============================================================

def format_timestamp(
    seconds: float,
) -> str:

    total_seconds = max(
        0,
        int(seconds),
    )

    hours = (
        total_seconds // 3600
    )

    minutes = (
        total_seconds % 3600
    ) // 60

    secs = (
        total_seconds % 60
    )

    if hours:
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{secs:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{secs:02d}"
    )


# ============================================================
# SNIPPET
# ============================================================

def create_snippet(
    text: str,
    max_length: int = 180,
) -> str:

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if len(text) <= max_length:
        return text

    snippet = (
        text[:max_length]
        .rsplit(" ", 1)[0]
    )

    return f"{snippet}..."


# ============================================================
# CHAT HISTORY
# ============================================================

def trim_chat_history(
    chat_history: List[Dict],
) -> List[Dict]:

    max_messages = (
        CHAT_HISTORY_TURNS * 2
    )

    return chat_history[
        -max_messages:
    ]


# ============================================================
# YOUTUBE URL
# ============================================================

def build_youtube_url(
    video_id: str,
    start_time: float,
) -> str:

    seconds = max(
        0,
        int(start_time),
    )

    return f"https://www.youtube.com/watch?v={video_id}&t={seconds}s" 


# ============================================================
# CONTEXT
# ============================================================

def build_context(
    results: List[Dict],
) -> str:

    context_parts = []

    for index, result in enumerate(
        results,
        start=1,
    ):
        video_title = (
            result.get("video_title")
            or result["video_id"]
        )

        video_number = extract_display_video_number(
            video_title,
            result.get("video_number"),
        )

        if video_number is not None:
            video_label = (
                f"Video {video_number} - "
                f"{video_title}"
            )
        else:
            video_label = video_title

        context_parts.append(
            (
                f"Source {index}\n"
                f"Video: {video_label}\n"
                f"Video ID: {result['video_id']}\n"
                f"Timestamp: "
                f"{format_timestamp(result['start_time'])}\n"
                f"End: "
                f"{format_timestamp(result['end_time'])}\n"
                f"URL: "
                f"{build_youtube_url(result['video_id'], result['start_time'])}\n"
                f"Transcript:\n"
                f"{result['text']}"
            )
        )

    return "\n\n".join(
        context_parts
    )

# ============================================================
# LOCATE RESULTS
# ============================================================

def sort_results_by_video_chronological(
    results: List[Dict],
) -> List[Dict]:
    """
    Preserve inter-video ordering by relevance (highest scoring video first),
    while sorting chunks WITHIN the same video chronologically by start_sec ascending.
    """
    video_groups: Dict[str, List[Dict]] = {}
    video_order: List[str] = []

    for item in results:
        vid = item["video_id"]
        if vid not in video_groups:
            video_groups[vid] = []
            video_order.append(vid)
        video_groups[vid].append(item)

    sorted_results: List[Dict] = []
    for vid in video_order:
        chunks = video_groups[vid]
        chunks.sort(
            key=lambda c: float(
                c.get("start_sec", c.get("start_time", 0.0))
            )
        )
        sorted_results.extend(chunks)

    return sorted_results


def format_locate_results(
    results: List[Dict],
) -> Dict:

    # First take the top-K by relevance, then sort same-video chunks chronologically
    top_candidates = results[:LOCATE_TOP_K]
    ordered_results = sort_results_by_video_chronological(top_candidates)

    formatted_results = []

    for result in ordered_results:

        video_title = result.get("video_title") or result["video_id"]
        video_number = extract_display_video_number(
            video_title,
            result.get("video_number"),
        )
        start_sec = float(result.get("start_sec", result.get("start_time", 0.0)))
        end_sec = float(result.get("end_sec", result.get("end_time", start_sec)))
        score = float(result.get("score", result.get("qdrant_score", 0.0)))
        text = str(result.get("text", "")).strip()

        formatted_results.append(
            {
                "video_number": video_number,
                "video_id": result["video_id"],
                "video_title": video_title,
                "timestamp": format_timestamp(start_sec),
                "start_time": start_sec,
                "start_sec": start_sec,
                "end_time": end_sec,
                "end_sec": end_sec,
                "text": text,
                "chunk_id": result.get("chunk_id") or f"{result['video_id']}:{int(start_sec)}",
                "snippet": create_snippet(text),
                "url": build_youtube_url(result["video_id"], start_sec),
                "score": round(score, 4),
                "playlist_id": result.get("playlist_id"),
            }
        )

    return {
        "mode": "locate",
        "results": formatted_results,
    }


# ============================================================
# CHAT SOURCES
# ============================================================

def build_chat_sources(
    results: List[Dict],
) -> List[Dict]:

    sources = []

    seen = set()

    for result in results:

        key = (
            result["video_id"],
            int(
                result["start_time"]
            ),
        )

        if key in seen:
            continue

        seen.add(key)

        sources.append(
            {
                "video_id": (
                    result["video_id"]
                ),

                "video_title": (
                    result.get(
                        "video_title"
                    )
                    or result["video_id"]
                ),

                "video_number": extract_display_video_number(
                    result.get("video_title"),
                    result.get("video_number"),
                ),

                "timestamp": (
                    format_timestamp(
                        result["start_time"]
                    )
                ),

                "url": (
                    build_youtube_url(
                        result["video_id"],
                        result["start_time"],
                    )
                ),
            }
        )

    return sources


# ============================================================
# LLM
# ============================================================

def generate_llm_answer(
    question: str,
    context: str,
    chat_history: List[Dict],
) -> str:

    from .llm import generate_answer

    return generate_answer(
        question=question,
        context=context,
        chat_history=chat_history,
    )


# ============================================================
# TEACH QUERY
#
# Invoked when the user says "ok tum hi batao" (or similar)
# after a "not covered" response.  Recovers the previous
# topic and generates a direct educational explanation.
# ============================================================

def handle_teach_query(
    question: str,
    chat_history: List[Dict],
) -> Dict:

    from .llm import generate_teach_explanation

    # Recover the actual topic from history
    topic = recover_topic_from_history(
        chat_history=chat_history,
        current_question=question,
    )

    try:
        explanation = generate_teach_explanation(
            topic=topic,
            chat_history=chat_history,
        )
    except Exception as err:
        explanation = (
            f"Sorry, I couldn't generate an explanation right now ({err}). "
            "Please check your API key and connection."
        )

    return {
        "mode": "teach",
        "answer": explanation,
        "sources": [],
    }


# ============================================================
# LOCATE QUERY
# ============================================================

def handle_locate_query(
    question: str,
    embedding_model,
    client,
    video_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    scope: str = "all",
) -> Dict:

    not_covered = get_not_covered_message(scope)

    # Retrieve top results using Two-Stage Vector Retrieval
    final_results = retrieve_candidates(
        question=question,
        model=embedding_model,
        client=client,
        limit=LOCATE_TOP_K,
        candidate_pool_limit=RETRIEVAL_CANDIDATE_LIMIT,
        video_id=video_id,
        playlist_id=playlist_id,
        window_seconds=LOCATE_DEDUP_WINDOW_SECONDS,
    )

    # Relevance gate: Real Qdrant cosine similarity threshold check
    if not final_results or not has_relevant_match(final_results, question=question):
        return {
            "mode": "locate",
            "results": [],
            "message": not_covered,
        }

    return format_locate_results(final_results)


# ============================================================
# SUMMARIZATION QUERY
# ============================================================

def handle_summary_query(
    question: str,
    client,
    video_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
) -> Dict:

    is_playlist = bool(
        re.search(r"\bplaylist\b", question.lower()) or
        re.search(r"\ball videos\b", question.lower()) or
        re.search(r"\bsaare videos\b", question.lower()) or
        re.search(r"\bentire series\b", question.lower()) or
        re.search(r"\bwhole playlist\b", question.lower())
    )

    if not is_playlist and not video_id and playlist_id:
        is_playlist = True

    # --------------------------------------------------------
    # 1. PLAYLIST SUMMARY
    # --------------------------------------------------------
    if is_playlist:
        query_filter = build_query_filter(playlist_id=playlist_id)
        points = []
        offset = None

        while len(points) < 500:
            page, offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=query_filter,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not page:
                break
            points.extend(page)
            if offset is None:
                break

        if not points:
            return {
                "mode": "chat",
                "answer": (
                    "Bhai, is playlist ka transcript indexed nahi hai. "
                    "Pehle is playlist ke videos process kar lijiye."
                ),
                "sources": [],
            }

        videos_data: Dict[str, Dict] = {}
        for pt in points:
            payload = pt.payload or {}
            vid = str(payload.get("video_id", "")).strip()
            if not vid:
                continue
            if vid not in videos_data:
                videos_data[vid] = {
                    "video_id": vid,
                    "video_title": payload.get("video_title") or vid,
                    "video_number": payload.get("video_number"),
                    "chunks": [],
                }
            videos_data[vid]["chunks"].append({
                "start_time": float(payload.get("start_time", 0)),
                "end_time": float(payload.get("end_time", 0)),
                "text": str(payload.get("text", "")).strip(),
            })

        sorted_videos = sorted(
            videos_data.values(),
            key=lambda v: (
                v.get("video_number") if v.get("video_number") is not None else 999999,
                v["video_title"].lower(),
            ),
        )

        context_lines = []
        sources = []

        for v in sorted_videos:
            v_num = f"Video {v['video_number']} — " if v.get("video_number") is not None else ""
            v_title = f"{v_num}{v['video_title']}"
            context_lines.append(f"\n=== {v_title} ===")

            v["chunks"].sort(key=lambda c: c["start_time"])
            if v["chunks"]:
                sources.append({
                    "video_id": v["video_id"],
                    "video_title": v["video_title"],
                    "video_number": v.get("video_number"),
                    "timestamp": format_timestamp(v["chunks"][0]["start_time"]),
                    "url": build_youtube_url(v["video_id"], v["chunks"][0]["start_time"]),
                })

            for c in v["chunks"][:25]:
                context_lines.append(
                    f"[{format_timestamp(c['start_time'])}] {c['text']}"
                )

        full_context = "\n".join(context_lines)
        prompt = (
            f"Provide a clear, well-structured, and comprehensive summary of this entire playlist.\n\n"
            f"User request: {question}\n\n"
            f"Structure:\n"
            f"1. **Playlist Overview & Objective**\n"
            f"2. **Breakdown of Major Topics Covered across Videos**\n"
            f"3. **Key Concepts, Architecture & Takeaways**\n\n"
            f"Stay strictly grounded in the transcript context. Do not invent any details not present in the transcripts."
        )

        answer = generate_llm_answer(
            question=prompt,
            context=full_context,
            chat_history=[],
        )

        return {
            "mode": "chat",
            "answer": answer,
            "sources": sources[:5],
        }

    # --------------------------------------------------------
    # 2. SINGLE VIDEO SUMMARY
    # --------------------------------------------------------
    if not video_id:
        return {
            "mode": "chat",
            "answer": "Bhai, pehle right panel se ek video select kar lijiye jiska summary chahiye.",
            "sources": [],
        }

    query_filter = build_query_filter(video_id=video_id)
    points = []
    offset = None

    while len(points) < 300:
        page, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not page:
            break
        points.extend(page)
        if offset is None:
            break

    if not points:
        return {
            "mode": "chat",
            "answer": (
                "Bhai, is video ka transcript indexed nahi hai. "
                "Pehle is video ko process kar lijiye."
            ),
            "sources": [],
        }

    chunks = []
    video_title = video_id
    video_number = None

    for pt in points:
        payload = pt.payload or {}
        if payload.get("video_title"):
            video_title = payload.get("video_title")
        if payload.get("video_number") is not None:
            video_number = payload.get("video_number")
        chunks.append({
            "start_time": float(payload.get("start_time", 0)),
            "end_time": float(payload.get("end_time", 0)),
            "text": str(payload.get("text", "")).strip(),
        })

    chunks.sort(key=lambda c: c["start_time"])
    v_num_str = f"Video {video_number} — " if video_number is not None else ""

    sources = []
    step = max(1, len(chunks) // 5)
    for i in range(0, min(len(chunks), step * 5), step):
        c = chunks[i]
        sources.append({
            "video_id": video_id,
            "video_title": video_title,
            "video_number": video_number,
            "timestamp": format_timestamp(c["start_time"]),
            "url": build_youtube_url(video_id, c["start_time"]),
        })

    context_lines = [f"Transcript for {v_num_str}{video_title}:\n"]
    for c in chunks:
        context_lines.append(
            f"[{format_timestamp(c['start_time'])}] {c['text']}"
        )

    full_context = "\n".join(context_lines)
    prompt = (
        f"Provide a structured, detailed summary of this video ({v_num_str}{video_title}).\n\n"
        f"User request: {question}\n\n"
        f"Structure:\n"
        f"1. **Video Overview & Key Objective**\n"
        f"2. **Detailed Topics & Timeline Highlights**\n"
        f"3. **Key Learnings & Summary**\n\n"
        f"Stay strictly grounded in the transcript context."
    )

    answer = generate_llm_answer(
        question=prompt,
        context=full_context,
        chat_history=[],
    )

    return {
        "mode": "chat",
        "answer": answer,
        "sources": sources[:5],
    }


# ============================================================
# NORMAL CHAT QUERY
# ============================================================

def handle_chat_query(
    question: str,
    chat_history: List[Dict],
    embedding_model,
    client,
    video_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    scope: str = "all",
) -> Dict:

    not_covered = get_not_covered_message(scope)

    final_results = retrieve_candidates(
        question=question,
        model=embedding_model,
        client=client,
        limit=TOP_K,
        candidate_pool_limit=RETRIEVAL_CANDIDATE_LIMIT,
        video_id=video_id,
        playlist_id=playlist_id,
        window_seconds=CHAT_DEDUP_WINDOW_SECONDS,
    )

    # Relevance gate: Real Qdrant cosine similarity threshold check
    if not final_results or not has_relevant_match(final_results, question=question):
        return {
            "mode": "chat",
            "answer": not_covered,
            "sources": [],
        }

    # --------------------------------------------------------
    # Build context
    # --------------------------------------------------------

    context = build_context(
        final_results
    )

    history = trim_chat_history(
        chat_history
    )

    # --------------------------------------------------------
    # Generate answer
    # --------------------------------------------------------

    try:
        answer = generate_llm_answer(
            question=question,
            context=context,
            chat_history=history,
        )
    except Exception as err:
        answer = (
            f"Unable to generate response right now ({err}). "
            "Please check your API key and connection."
        )

    return {
        "mode": "chat",
        "answer": answer,
        "sources": build_chat_sources(
            final_results
        ),
    }


# ============================================================
# MAIN QUERY HANDLER
# ============================================================

def handle_query(
    question: str,
    chat_history: List[Dict],
    embedding_model,
    client,
    video_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    scope: str = "all",
) -> Dict:

    question = question.strip()

    if not question:

        return {
            "mode": "chat",
            "answer": (
                "Please enter a question."
            ),
            "sources": [],
        }

    intent = detect_intent(
        question=question,
        chat_history=chat_history,
    )

    # --------------------------------------------------------
    # Summary query
    # --------------------------------------------------------

    if intent == "summary":

        return handle_summary_query(
            question=question,
            client=client,
            video_id=video_id,
            playlist_id=playlist_id,
        )

    # --------------------------------------------------------
    # Teach / direct explanation query
    # --------------------------------------------------------

    if intent == "teach":

        return handle_teach_query(
            question=question,
            chat_history=chat_history,
        )

    # --------------------------------------------------------
    # Scope routing
    #
    # "video"    → search strictly within video_id
    # "playlist" → search all videos in playlist_id
    # "all"      → global search (no filter)
    # --------------------------------------------------------

    if scope == "video":
        search_video_id = video_id
        search_playlist_id = None
    elif scope == "playlist":
        search_video_id = None
        search_playlist_id = playlist_id
    else:  # "all" or any unrecognised value
        search_video_id = None
        search_playlist_id = None

    # --------------------------------------------------------
    # Location / timestamp query
    # --------------------------------------------------------

    if intent == "locate":

        return handle_locate_query(
            question=question,
            embedding_model=(
                embedding_model
            ),
            client=client,
            video_id=search_video_id,
            playlist_id=search_playlist_id,
            scope=scope,
        )

    # --------------------------------------------------------
    # Normal RAG chat
    # --------------------------------------------------------

    return handle_chat_query(
        question=question,
        chat_history=chat_history,
        embedding_model=(
            embedding_model
        ),
        client=client,
        video_id=search_video_id,
        playlist_id=search_playlist_id,
        scope=scope,
    )


# ============================================================
# CLI
# ============================================================

def main() -> None:

    print(
        "Loading embedding model..."
    )

    embedding_model = (
        load_embedding_model()
    )

    print(
        "Connecting to Qdrant..."
    )

    client = (
        get_qdrant_client()
    )

    print(
        "\nChat ready."
    )

    print(
        "Type 'exit', 'quit', or "
        "'q' to stop.\n"
    )

    chat_history: List[Dict] = []

    while True:

        try:

            question = input(
                "You: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):

            print(
                "\nExiting..."
            )

            break

        if not question:
            continue

        if question.lower() in {
            "exit",
            "quit",
            "q",
        }:

            print(
                "Exiting..."
            )

            break

        try:

            response = handle_query(
                question=question,
                chat_history=(
                    chat_history
                ),
                embedding_model=(
                    embedding_model
                ),
                client=client,
            )

            print(
                "\nAssistant:"
            )

            # =================================================
            # TEACH OR NORMAL CHAT
            # =================================================

            if response[
                "mode"
            ] in ("chat", "teach"):

                print(
                    response["answer"]
                )

                chat_history.append(
                    {
                        "role": "user",
                        "content": question,
                    }
                )

                chat_history.append(
                    {
                        "role": "assistant",
                        "content": (
                            response[
                                "answer"
                            ]
                        ),
                    }
                )

                if response[
                    "sources"
                ]:

                    print(
                        "\nSources:"
                    )

                    for source in (
                        response[
                            "sources"
                        ]
                    ):

                        video_number = (
                            source.get(
                                "video_number"
                            )
                        )

                        video_title = (
                            source.get(
                                "video_title"
                            )
                            or source[
                                "video_id"
                            ]
                        )

                        if video_number is not None:

                            label = (
                                f"Video "
                                f"{video_number} - "
                                f"{video_title}"
                            )

                        else:

                            label = (
                                video_title
                            )

                        print(
                            f"- {label} "
                            f"@ "
                            f"{source['timestamp']}"
                        )

                        print(
                            f"  {source['url']}"
                        )

            # =================================================
            # LOCATE
            # =================================================

            else:

                if not response[
                    "results"
                ]:

                    print(
                        response.get(
                            "message",
                            get_not_covered_message("all"),
                        )
                    )

                    continue

                print(
                    "Here are the most "
                    "relevant locations:\n"
                )

                for index, result in enumerate(
                    response[
                        "results"
                    ],
                    start=1,
                ):

                    video_number = (
                        result.get(
                            "video_number"
                        )
                    )

                    if video_number is not None:

                        video_label = (
                            f"Video "
                            f"{video_number} - "
                            f"{result['video_title']}"
                        )

                    else:

                        video_label = (
                            result[
                                "video_title"
                            ]
                        )

                    print(
                        f"{index}. "
                        f"{video_label}"
                    )

                    print(
                        f"   ▶ "
                        f"{result['timestamp']}"
                    )

                    print(
                        f"   "
                        f"{result['snippet']}"
                    )

                    print(
                        f"   "
                        f"{result['url']}"
                    )

            print()

        except Exception as exc:

            print(
                f"\nError: {exc}\n"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
    