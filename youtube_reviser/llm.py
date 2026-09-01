import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv


# ============================================================
# Environment configuration
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

# .env is one level above youtube_reviser/
# AIEngineer/.env
PROJECT_ROOT = os.path.dirname(
    BASE_DIR
)

load_dotenv(
    os.path.join(
        PROJECT_ROOT,
        ".env",
    )
)


# ============================================================
# Groq configuration
# ============================================================

GROQ_API_URL = (
    "https://api.groq.com/openai/v1/chat/completions"
)

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY"
)


# ============================================================
# System prompt
# ============================================================

SYSTEM_PROMPT = """
You are the YouTube Reviser learning assistant.

Use the supplied transcript context as the primary
source of truth.

Rules:

1. Do not invent facts that are not supported by
   the supplied context.

2. If the context does not contain enough information,
   clearly say that the information is not available.

3. Explain concepts in a practical and student-friendly way.

4. Keep answers focused and directly related to the
   user's question.

5. For questions asking where a topic was taught,
   rely only on the supplied video and timestamp metadata.

6. Never invent:
   - video numbers
   - video titles
   - timestamps
   - YouTube URLs

7. When timestamp/source metadata is supplied, preserve
   that information accurately.

8. For normal conversational questions, answer naturally.

Do not mention these instructions in your answer.
""".strip()


# ============================================================
# Generate answer
# ============================================================

def generate_answer(
    question: str,
    context: str,
    chat_history: list[dict],
) -> str:

    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY not found in .env"
        )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    # --------------------------------------------------------
    # Chat history
    # --------------------------------------------------------

    for message in chat_history[-10:]:

        role = message.get(
            "role"
        )

        content = message.get(
            "content"
        )

        if role not in {
            "user",
            "assistant",
        }:
            continue

        if not isinstance(
            content,
            str,
        ):
            continue

        content = content.strip()

        if not content:
            continue

        messages.append(
            {
                "role": role,
                "content": content,
            }
        )

    # --------------------------------------------------------
    # Current question + retrieved context
    # --------------------------------------------------------

    messages.append(
        {
            "role": "user",
            "content": (
                "Retrieved transcript context:\n\n"
                f"{context}\n\n"
                "User question:\n\n"
                f"{question}"
            ),
        }
    )

    # --------------------------------------------------------
    # Request payload
    # --------------------------------------------------------

    payload = json.dumps(
        {
            "model": GROQ_MODEL,
            "messages": messages,
        }
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        GROQ_API_URL,
        data=payload,
        headers={
            "Authorization": (
                f"Bearer {GROQ_API_KEY}"
            ),
            "Content-Type": (
                "application/json"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )

    # --------------------------------------------------------
    # API request
    # --------------------------------------------------------

    try:

        with urllib.request.urlopen(
            request,
            timeout=120,
        ) as response:

            response_body = (
                response.read()
                .decode(
                    "utf-8"
                )
            )

            data = json.loads(
                response_body
            )

    except urllib.error.HTTPError as exc:

        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"LLM request failed ({exc.code}): {body}"
        ) from exc

    except urllib.error.URLError as exc:

        raise RuntimeError(
            "Unable to reach the LLM service: "
            f"{exc.reason}"
        ) from exc

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            "The LLM service returned invalid JSON."
        ) from exc

    # --------------------------------------------------------
    # Extract answer
    # --------------------------------------------------------

    try:

        answer = (
            data[
                "choices"
            ][0][
                "message"
            ][
                "content"
            ]
        )

    except (
        KeyError,
        IndexError,
        TypeError,
    ) as exc:

        raise RuntimeError(
            "The LLM service returned an unexpected response."
        ) from exc

    answer = str(
        answer
    ).strip()

    if not answer:

        raise RuntimeError(
            "The LLM returned an empty answer."
        )

    return answer


# ============================================================
# Generate teach explanation (for direct tutoring mode)
# ============================================================

TEACH_SYSTEM_PROMPT = """
You are an expert, encouraging programming tutor.
The student asked you to explain a topic directly.

Rules:
1. Explain the requested concept clearly and comprehensively in a student-friendly way.
2. Use intuitive real-world analogies, concise code snippets where applicable, and structured bullet points.
3. Keep the tone helpful, engaging, and easy to understand for beginners.
4. Structure the explanation with a brief definition, key concepts, practical use case / example, and summary.
5. Answer in clear English or natural Hindi/Hinglish if the student conversed in Hinglish.
Do not mention these instructions in your answer.
""".strip()


def generate_teach_explanation(
    topic: str,
    chat_history: list[dict],
) -> str:

    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY not found in .env"
        )

    messages = [
        {
            "role": "system",
            "content": TEACH_SYSTEM_PROMPT,
        }
    ]

    for message in chat_history[-6:]:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append({
            "role": role,
            "content": content.strip(),
        })

    messages.append({
        "role": "user",
        "content": (
            "Please teach and explain this topic to me in detail with clear examples and student-friendly explanations:\n\n"
            f"{topic}"
        ),
    })

    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": messages,
    }).encode("utf-8")

    request = urllib.request.Request(
        GROQ_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=120,
        ) as response:
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body)

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LLM request failed ({exc.code}): {body}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Unable to reach the LLM service: {exc.reason}"
        ) from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "The LLM service returned invalid JSON."
        ) from exc

    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "The LLM service returned an unexpected response."
        ) from exc

    answer = str(answer).strip()
    if not answer:
        raise RuntimeError(
            "The LLM returned an empty answer."
        )

    return answer