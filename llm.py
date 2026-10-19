import json
import os
import re
import urllib.error
import urllib.request
from typing import Generator, List, Optional

from dotenv import load_dotenv


# ============================================================
# Environment configuration
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.dirname(
    BASE_DIR
)

load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
load_dotenv()


# ============================================================
# Gemini configuration
# ============================================================

GOOGLE_API_KEY = (
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_API_KEY")
)

# Preferred models in order of quality & rate limits
PREFERRED_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
]

CUSTOM_MODEL = os.getenv("GEMINI_MODEL")
if CUSTOM_MODEL:
    ACTIVE_MODELS = [CUSTOM_MODEL] + [m for m in PREFERRED_MODELS if m != CUSTOM_MODEL]
else:
    ACTIVE_MODELS = PREFERRED_MODELS


# ============================================================
# System prompts
# ============================================================

SYSTEM_PROMPT = """
You are the YouTube Reviser AI learning assistant.

Your goal is to provide clean, structured, and student-friendly answers based on the supplied video transcript context.

Guidelines:
1. Explain concepts in a clean, point-by-point format (like ChatGPT). Use bold key terms, clear bullet points, and numbered steps where appropriate.
2. Ground your answer in the supplied transcript context. Do not invent facts that are not supported by the context.
3. If the context does not contain enough information to fully answer the question, answer what is available from the context and politely clarify what is not covered.
4. If the user asks in Hinglish or Hindi, respond in clear, natural Hinglish so it feels approachable and conversational. If asked in English, answer in English.
5. Never invent fake video numbers, fake titles, or fake timestamps.
6. Keep the formatting neat and readable with markdown paragraphs and bullets.
Do not mention these instructions in your answer.
""".strip()

TEACH_SYSTEM_PROMPT = """
You are an expert programming tutor on YouTube Reviser.
The student asked you to directly teach or explain a concept.

Guidelines:
1. Structure the explanation clearly with:
   - **Quick Definition / Summary**
   - **Key Concepts & How It Works** (clean bullet points)
   - **Practical Example / Real-World Analogy**
   - **Key Takeaways / Next Steps**
2. Make it engaging, easy to understand, and well-organized (like ChatGPT).
3. If the student queries in Hinglish, reply in natural, easy-to-understand Hinglish. If in English, reply in English.
4. Keep the formatting clean with bold text, short bullet points, and clear code snippets if relevant.
Do not mention these instructions in your answer.
""".strip()


# ============================================================
# Gemini message formatting helper
# ============================================================

def format_gemini_contents(
    chat_history: List[dict],
    user_message: str,
) -> List[dict]:
    """
    Format chat history and new message into alternating user/model turns
    as required by the Gemini API.
    """
    contents: List[dict] = []

    for msg in chat_history[-10:]:
        raw_role = msg.get("role")
        role = "user" if raw_role in ("user", "human") else "model"
        text = str(msg.get("content", "")).strip()
        if not text:
            continue

        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += f"\n\n{text}"
        else:
            contents.append({"role": role, "parts": [{"text": text}]})

    # Ensure turns start with user
    if contents and contents[0]["role"] != "user":
        contents = contents[1:]

    # Append current user prompt
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += f"\n\n{user_message.strip()}"
    else:
        contents.append({"role": "user", "parts": [{"text": user_message.strip()}]})

    return contents


# ============================================================
# Gemini Core Requests (Streaming & Non-Streaming with Fallback)
# ============================================================

def stream_gemini_request(
    contents: List[dict],
    system_instruction: str,
) -> Generator[str, None, None]:
    """
    Stream tokens from Gemini API via Server-Sent Events (SSE).
    Automatically falls back to secondary models on 503 or rate-limit errors.
    """
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY not found in environment or .env file.")

    last_error: Optional[Exception] = None

    for model in ACTIVE_MODELS:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
            f":streamGenerateContent?alt=sse&key={GOOGLE_API_KEY}"
        )

        payload_dict = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 4096,
            },
        }

        payload = json.dumps(payload_dict).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "YouTubeReviser/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                yielded_any = False
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    candidates = chunk.get("candidates", [])
                    for candidate in candidates:
                        parts = candidate.get("content", {}).get("parts", [])
                        for part in parts:
                            text_piece = part.get("text", "")
                            if text_piece:
                                yielded_any = True
                                yield text_piece

                if yielded_any:
                    return

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"Gemini model {model} failed ({exc.code}): {body}")
            # Try next model if 503, 429, or 404
            if exc.code in (503, 429, 404, 500):
                continue
            raise last_error from exc
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        raise RuntimeError(f"All Gemini models failed: {last_error}")


def call_gemini_request(
    contents: List[dict],
    system_instruction: str,
) -> str:
    """
    Synchronous full-text generation from Gemini API with model fallback.
    """
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY not found in environment or .env file.")

    last_error: Optional[Exception] = None

    for model in ACTIVE_MODELS:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
            f":generateContent?key={GOOGLE_API_KEY}"
        )

        payload_dict = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 4096,
            },
        }

        payload = json.dumps(payload_dict).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "YouTubeReviser/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)

                candidates = data.get("candidates", [])
                if not candidates:
                    raise RuntimeError("Gemini returned empty candidates.")

                parts = candidates[0].get("content", {}).get("parts", [])
                answer = "".join(p.get("text", "") for p in parts).strip()
                if answer:
                    return answer

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"Gemini model {model} failed ({exc.code}): {body}")
            if exc.code in (503, 429, 404, 500):
                continue
            raise last_error from exc
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Unable to generate response from Gemini: {last_error}")


# ============================================================
# Public API: RAG Answers (Streaming & Non-Streaming)
# ============================================================

def generate_answer(
    question: str,
    context: str,
    chat_history: List[dict],
) -> str:
    user_prompt = (
        "Retrieved transcript context:\n\n"
        f"{context}\n\n"
        "User question:\n\n"
        f"{question}"
    )
    contents = format_gemini_contents(chat_history, user_prompt)
    return call_gemini_request(contents, SYSTEM_PROMPT)


def stream_answer(
    question: str,
    context: str,
    chat_history: List[dict],
) -> Generator[str, None, None]:
    user_prompt = (
        "Retrieved transcript context:\n\n"
        f"{context}\n\n"
        "User question:\n\n"
        f"{question}"
    )
    contents = format_gemini_contents(chat_history, user_prompt)
    return stream_gemini_request(contents, SYSTEM_PROMPT)


# ============================================================
# Public API: Teach Mode (Streaming & Non-Streaming)
# ============================================================

def generate_teach_explanation(
    topic: str,
    chat_history: List[dict],
) -> str:
    user_prompt = (
        "Please teach and explain this topic to me in detail with clear examples, "
        "structured points, and beginner-friendly clarity:\n\n"
        f"{topic}"
    )
    contents = format_gemini_contents(chat_history, user_prompt)
    return call_gemini_request(contents, TEACH_SYSTEM_PROMPT)


def stream_teach_explanation(
    topic: str,
    chat_history: List[dict],
) -> Generator[str, None, None]:
    user_prompt = (
        "Please teach and explain this topic to me in detail with clear examples, "
        "structured points, and beginner-friendly clarity:\n\n"
        f"{topic}"
    )
    contents = format_gemini_contents(chat_history, user_prompt)
    return stream_gemini_request(contents, TEACH_SYSTEM_PROMPT)