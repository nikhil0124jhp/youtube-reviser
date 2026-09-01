YouTube Reviser

YouTube Reviser is a Retrieval-Augmented Generation (RAG) application for searching and revising long-form YouTube lecture playlists. It uses semantic retrieval to find the most relevant lecture segments and refines the result to an exact timestamp, so users can jump directly to where a topic was explained.

What It Does

Indexes YouTube lecture transcripts into a vector database.

Supports natural-language, technical, Hindi, English and Hinglish-style queries.

Searches within the currently selected playlist or across all indexed playlists.

Returns relevant videos with refined timestamps.

Generates timestamped YouTube links for quick revision.

Provides LLM-powered responses for supported chat queries.

Preserves playlist isolation so results from unrelated playlists do not leak into a scoped search.

Uses a transcript acquisition pipeline with captions / Transcript API and a Whisper fallback when captions are unavailable.

Core Architecture

YouTube Playlist / Videos
          |
          v
   Transcript Acquisition
          |
          v
   Transcript Chunking
   (75s chunks, 15s overlap)
          |
          v
 Multilingual Embeddings
 (multilingual-e5-small)
          |
          v
     Qdrant Vector DB
          |
          |
     User's Query
          |
          v
     Query Embedding
          |
          v
  Candidate Retrieval
       (up to 300)
          |
          v
  Relevance Filtering
          |
          v
 Timestamp Refinement
          |
          v
 Video + Exact Timestamp
          |
          v
   Optional LLM Answer

Tech Stack

Layer

Technology

Backend API

FastAPI

Vector Database

Qdrant

Embeddings

Sentence Transformers (intfloat/multilingual-e5-small)

LLM

Groq API

Transcript API

youtube-transcript-api

Caption / Media Handling

yt-dlp

Speech-to-Text Fallback

faster-whisper

Frontend

HTML, CSS, JavaScript

Language

Python

Retrieval Configuration

The current retrieval pipeline uses:

Embedding model: intfloat/multilingual-e5-small

Top results: 4

Candidate pool: 300

Minimum relevance score: 0.78

Chunk duration: 75 seconds

Chunk overlap: 15 seconds

Key Retrieval Features

Playlist-Scoped Search

The UI can restrict retrieval to the selected playlist. A separate Search all indexed playlists option enables global search.

Timestamp Refinement

The system first retrieves a relevant chunk and then refines the timestamp using the underlying transcript segments. This produces a more precise starting point than simply linking to the beginning of the retrieved chunk.

Multilingual / Hinglish Retrieval

The system is designed for lecture content where technical terms can appear in English, Hindi, Hinglish, or mixed representations. The embedding representation includes the transcript content used for semantic retrieval, while the original transcript data and timestamps are preserved for result refinement.

Qdrant Payload Optimization

Qdrant retrieval was optimized to transfer only the metadata required by the retrieval pipeline instead of downloading large transcript fields for all 300 candidates. Candidate text can then be hydrated from the existing local transcript JSON data when needed.

In testing, this optimization produced substantial latency improvements while preserving retrieval parity on the evaluation queries.

Performance Optimization

A before/after benchmark on seven representative queries showed:

Metric

Result

Candidate pool

300 (unchanged)

Maximum measured retrieval speedup

20.9×

Retrieval parity across test queries

100%

Embedding / vector data changes

None

Re-indexing for the optimization

None

Transcript re-fetch during the optimization

None

Observed post-optimization retrieval latency was approximately 230–870 ms for the tested locate queries, depending on the query and scope.

Project Structure

AIEngnear/
│
├── README.md
├── .gitignore
├── .env                         # Local secrets; never commit this
│
└── youtube_reviser/
    ├── web_app.py               # FastAPI application and API routes
    ├── fetch.py                 # Transcript acquisition and processing
    ├── index.py                 # Chunking, embeddings and Qdrant indexing
    ├── retrieval.py             # Semantic retrieval and timestamp refinement
    ├── chat.py                  # Query/chat orchestration
    ├── llm.py                   # Groq LLM integration
    ├── requirements.txt
    │
    ├── ui/
    │   ├── index.html
    │   ├── chat.html
    │   ├── chat.js
    │   ├── app.js
    │   ├── chat.css
    │   ├── style.css
    │   └── theme.js
    │
    └── <playlist folders>/      # Indexed transcript JSON files

Environment Variables

Create a .env file for local development:

GROQ_API_KEY=your_groq_api_key
QDRANT_URL=your_qdrant_url
QDRANT_API_KEY=your_qdrant_api_key

QDRANT_COLLECTION=youtube_transcripts
EMBEDDING_MODEL=intfloat/multilingual-e5-small
QDRANT_BATCH_SIZE=32
CHUNK_SECONDS=75
OVERLAP_SECONDS=15
TOP_K=4
RETRIEVAL_CANDIDATE_LIMIT=300
MIN_RELEVANCE_SCORE=0.78

Never commit .env or API keys to GitHub.

Local Setup

1. Clone the repository

git clone https://github.com/nikhil0124jhp/youtube-reviser.git
cd youtube-reviser

2. Create a virtual environment

Windows:

python -m venv .venv
.venv\Scripts\activate

macOS / Linux:

python -m venv .venv
source .venv/bin/activate

3. Install dependencies

pip install -r youtube_reviser/requirements.txt

4. Configure environment variables

Create .env in the project root and add the required Qdrant and Groq credentials.

5. Start the application

uvicorn youtube_reviser.web_app:app --host 0.0.0.0 --port 8000

Open:

http://127.0.0.1:8000

FastAPI documentation:

http://127.0.0.1:8000/docs

Indexing Workflow

The indexing pipeline follows this general flow:

YouTube URL
   ↓
Discover videos
   ↓
Acquire transcript
   ↓
Merge / chunk transcript
   ↓
Create multilingual embeddings
   ↓
Upsert vectors + metadata into Qdrant

Existing processed videos can be reused without unnecessarily downloading the same transcript again.

Search Workflow

User Query
   ↓
Query normalization / embedding
   ↓
Qdrant candidate retrieval
   ↓
Relevance filtering
   ↓
Timestamp refinement from local transcript data
   ↓
Top relevant timestamps
   ↓
Optional Groq-generated answer

Example Queries

Where is sliding window pattern explained?

Java mein constructor aur default constructor kaha samjhaya hai?

Where is ransom note solved?

10 sorted arrays ko merge karne ke liye kis data structure ka use hoga?

Stream of data mein minimum aur maximum kaise maintain karte hain?

Current Indexed Content

The repository currently includes transcript data for example lecture playlists such as:

DSA / problem-solving lectures

OOPs in Java lectures

Additional playlists can be indexed through the application workflow.

Deployment

The application is designed to run as a FastAPI web service with:

FastAPI / Uvicorn for the application server

Qdrant Cloud for the vector database

Groq API for LLM responses

Environment variables for secrets and configuration

A production deployment should keep API keys outside the repository and configure the same environment variables on the hosting platform.

Security Notes

.env is excluded from version control.

API keys should be stored as deployment environment variables.

Local virtual environments and generated backup files are excluded from Git.

Author

Nikhil

GitHub: @nikhil0124jhp

Repository: youtube-reviser
