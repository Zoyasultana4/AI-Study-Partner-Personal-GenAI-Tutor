import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Manually read .env file
def load_env_vars():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip()
                        print(f"Loaded env var: {key.strip()}")

load_env_vars()

# Try dotenv as fallback
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

DATA_FILE = os.path.join(BASE_DIR, "data.txt")
DATA_STORE = os.path.join(BASE_DIR, "data_store.json")
DB_PATH = os.path.join(BASE_DIR, "study_partner.db")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
NEXT_FRONTEND_OUT_DIR = os.path.join(BASE_DIR, "frontend-next", "out")
NEXT_FRONTEND_NEXT_DIR = os.path.join(NEXT_FRONTEND_OUT_DIR, "_next")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
REMINDER_POLL_SECONDS = 10

# Telegram configuration (load after env vars are set)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if TELEGRAM_BOT_TOKEN:
    print(f"[OK] Telegram Bot Token configured")
else:
    print(f"[ERROR] Telegram Bot Token: Not configured")

if TELEGRAM_CHAT_ID:
    print(f"[OK] Telegram Chat ID: {TELEGRAM_CHAT_ID}")
else:
    print(f"[ERROR] Telegram Chat ID: Not configured")

os.makedirs(UPLOADS_DIR, exist_ok=True)


def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score INTEGER,
            total_questions INTEGER,
            correct_answers INTEGER,
            created_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            duration_minutes INTEGER,
            created_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            remind_at TEXT,
            channel TEXT,
            chat_id TEXT,
            sent INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            original_name TEXT,
            uploaded_at TEXT,
            size INTEGER
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            achievement_id TEXT UNIQUE,
            name TEXT,
            unlocked_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            id INTEGER PRIMARY KEY,
            study_streak INTEGER DEFAULT 0,
            last_study_date TEXT,
            total_study_minutes INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("INSERT OR IGNORE INTO user_stats (id) VALUES (1)")
    
    conn.commit()
    conn.close()


init_database()

app = FastAPI(title="AI Study Partner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)

if os.path.isdir(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

if os.path.isdir(NEXT_FRONTEND_NEXT_DIR):
    app.mount("/_next", StaticFiles(directory=NEXT_FRONTEND_NEXT_DIR), name="next-assets")


def _load_store() -> dict:
    if os.path.exists(DATA_STORE):
        with open(DATA_STORE, "r", encoding="utf-8") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return {}
    return {}


def _save_store(store: dict) -> None:
    with open(DATA_STORE, "w", encoding="utf-8") as file:
        json.dump(store, file, ensure_ascii=False, indent=2)


def _get_store() -> dict:
    store = _load_store()
    store.setdefault("reminders", [])
    store.setdefault("quizAttempts", [])
    store.setdefault("studyPlans", [])
    store.setdefault("sessions", {})
    store.setdefault("lastStudyDate", None)
    store.setdefault("studyStreak", 0)
    store.setdefault("achievements", [])
    store.setdefault("totalStudyMinutes", 0)
    store.setdefault("documents", [])
    return store


def _read_syllabus() -> str:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return _clean_extracted_text(file.read().strip())
    return ""


def _write_syllabus(content: str) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        file.write(_clean_extracted_text(content).strip())


def _normalize_line_for_match(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip().lower()
    line = re.sub(r"\bpage\s*\d+(\s*(of|/)\s*\d+)?\b", "", line)
    line = re.sub(r"\d+", "#", line)
    return line


def _clean_extracted_text(text: str) -> str:
    """Clean noisy OCR/PDF text by removing repeated headers/footers and junk lines."""
    if not text:
        return ""

    # Normalize line breaks first
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [ln.strip() for ln in text.split("\n")]

    # Remove obvious junk lines
    filtered_lines = []
    for ln in raw_lines:
        if not ln:
            continue
        low = ln.lower()
        if "www." in low or "http" in low:
            continue
        if "copyright" in low or "all rights reserved" in low:
            continue
        if re.fullmatch(r"page\s*\d+(\s*(of|/)\s*\d+)?", low):
            continue
        if re.fullmatch(r"\d+", ln):
            continue
        filtered_lines.append(ln)

    if not filtered_lines:
        return ""

    # Remove repeated boilerplate lines (common headers/footers)
    normalized = [_normalize_line_for_match(ln) for ln in filtered_lines]
    counts = Counter(normalized)
    noisy_norm = {k for k, v in counts.items() if k and v >= 3}

    cleaned_lines = []
    for ln in filtered_lines:
        norm = _normalize_line_for_match(ln)
        if norm in noisy_norm:
            continue
        # remove broken citation-like tokens and figure refs
        ln = re.sub(r"\[\d+(\.\d+)?\]", "", ln)
        ln = re.sub(r"\bfigure\s*\d+(\.\d+)?\b", "", ln, flags=re.IGNORECASE)
        ln = re.sub(r"\s+", " ", ln).strip()
        if len(ln) < 3:
            continue
        cleaned_lines.append(ln)

    # Join and normalize paragraph spacing
    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
    return cleaned_text


def _split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


LOW_SIGNAL_TERMS = {
    "as", "the", "this", "that", "these", "those", "it", "its", "they", "them", "we", "our",
    "you", "your", "he", "she", "his", "her", "their", "there", "here", "in", "on", "at",
    "for", "from", "to", "of", "and", "or", "but", "with", "without", "by", "an", "a",
}


def _is_valid_concept_term(term: str) -> bool:
    cleaned = re.sub(r"\s+", " ", term).strip(" ,;:-")
    if not cleaned:
        return False

    low = cleaned.lower()
    if low in LOW_SIGNAL_TERMS:
        return False
    if re.fullmatch(r"(chapter|section|figure|table)\s*\d*", low):
        return False
    if re.fullmatch(r"\d+(\.\d+)?", low):
        return False

    tokens = [t for t in re.split(r"\s+", low) if t]
    if not tokens:
        return False
    if len(tokens) == 1 and (tokens[0] in LOW_SIGNAL_TERMS or len(tokens[0]) < 3):
        return False
    if all(t in LOW_SIGNAL_TERMS for t in tokens):
        return False

    return True


def _extract_key_concepts(text: str) -> List[tuple]:
    """Extract key concepts and their definitions/context from text."""
    concepts = []
    sentences = _split_sentences(text)

    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).strip()
        match = re.match(
            r"^([A-Za-z][A-Za-z0-9\-(),/&\s]{1,80}?)\s+(is|are|means|refers to|stands for)\s+(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        term = re.sub(r"^[Tt]he\s+", "", match.group(1)).strip(" ,;:-")
        definition = match.group(3).strip(" ,;:-")

        # reject overlong / low-signal terms
        if len(term) < 2 or len(term.split()) > 8:
            continue
        if len(definition) < 15:
            continue
        if not _is_valid_concept_term(term):
            continue

        concepts.append((term, definition, normalized))
    
    # Remove duplicates, keep first occurrence
    seen = set()
    unique = []
    for term, defn, sent in concepts:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append((term, defn, sent))
    
    return unique[:8]


def _generate_smart_summary(text: str, max_sentences: int = 5) -> str:
    """Generate a meaningful summary by extracting key information."""
    sentences = _split_sentences(text)
    if not sentences:
        return "No content available."
    
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    
    # Score sentences by:
    # 1. Length (more info = higher score)
    # 2. Presence of key terms (capitalized words, numbers)
    # 3. Early position in text (likely important)
    
    scored = []
    for i, sent in enumerate(sentences):
        # Base score from position (earlier sentences more important)
        pos_score = max(0, (len(sentences) - i) / len(sentences))
        
        # Length score (longer sentences have more info)
        length_score = min(len(sent) / 100, 1.0)
        
        # Key term score (count capitalized words, numbers)
        key_count = len([w for w in sent.split() if w[0].isupper() or w[0].isdigit()])
        term_score = min(key_count / 3, 1.0)
        
        final_score = (pos_score * 0.4 + length_score * 0.35 + term_score * 0.25)
        scored.append((final_score, i, sent))
    
    # Get top sentences and maintain original order
    top_sents = sorted(scored, key=lambda x: x[0], reverse=True)[:max_sentences]
    top_sents = sorted(top_sents, key=lambda x: x[1])  # Re-order by position
    
    summary = " ".join([s[2] for s in top_sents])
    return summary


def _generate_quality_flashcards(text: str, count: int = 6) -> List[dict]:
    """Generate high-quality flashcards with real definitions and examples."""
    concepts = _extract_key_concepts(text)
    
    if not concepts:
        # Fallback: use important sentences
        sentences = _split_sentences(text)
        concepts = []
        for sent in sentences[:count]:
            if len(sent) > 30:
                words = [w.strip('.,;:') for w in sent.split() if len(w) > 4]
                if words:
                    concepts.append((words[0], sent, sent))
    
    flashcards = []
    for term, definition, full_context in concepts[:count]:
        flashcards.append({
            "front": term,
            "back": definition if len(definition) < 150 else definition[:150] + "...",
            "context": full_context
        })
    
    return flashcards


def _generate_quality_quiz(text: str, count: int = 5) -> List[dict]:
    """Generate meaningful quiz questions with proper answers."""
    sentences = _split_sentences(text)
    if not sentences:
        return []
    
    # Filter for meaningful sentences
    meaningful = [s for s in sentences if 20 < len(s) < 250]
    
    if not meaningful:
        meaningful = sentences
    
    quiz = []
    
    for sentence in meaningful[:count * 2]:  # Process more to get better ones
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue
        
        words = sentence.split()
        
        # Try to extract a clean main concept
        key_words = [w.strip('.,;:()') for w in words 
                     if len(w) > 4 and w[0].isupper()]
        
        if not key_words:
            key_words = [w.strip('.,;:()') for w in words if len(w) > 5]
        
        if not key_words:
            continue
        
        concept = key_words[0]
        
        # Create appropriate question type
        if ' is ' in sentence.lower() or ' are ' in sentence.lower():
            # Definition question
            question = f"What is {concept.lower()}?"
        elif any(verb in sentence.lower() for verb in ['shows', 'demonstrates', 'indicates', 'suggests', 'explains']):
            # Comprehension question
            question = f"What does {concept} demonstrate?"
        else:
            # Explanation question
            question = f"Explain {concept}"
        
        # Find distractor (different sentence with key term)
        distractors = []
        for other in meaningful:
            if other != sentence and len(distractors) < 2:
                if concept.lower() not in other.lower():
                    # Use first part of other sentence as wrong answer
                    distractor = other.split('.')[0][:80].strip()
                    if distractor and len(distractor) > 20:
                        distractors.append(distractor)
        
        quiz_item = {
            "question": question,
            "answer": sentence,
            "options": [sentence] + distractors,
            "explanation": f"According to the material: {sentence}"
        }
        
        quiz.append(quiz_item)
        
        if len(quiz) >= count:
            break
    
    if not quiz:
        return [{
            "question": "What is the main topic?",
            "answer": meaningful[0] if meaningful else "Content",
            "options": [meaningful[0] if meaningful else "Content"],
            "explanation": "Review the uploaded document for more details."
        }]
    
    return quiz


def _context_excerpt(text: str, max_chars: int = 12000) -> str:
    cleaned = _clean_extracted_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    head = cleaned[: int(max_chars * 0.75)]
    tail = cleaned[-int(max_chars * 0.25):]
    return f"{head}\n\n...\n\n{tail}"


def _extract_json_array(text: str) -> Optional[List[dict]]:
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, list):
            return value
    except Exception:
        pass

    match = re.search(r"\[(.|\n|\r)*\]", text)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        if isinstance(value, list):
            return value
    except Exception:
        return None
    return None


def _summary_with_openai(text: str, max_sentences: int = 4) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not (OPENAI_AVAILABLE and api_key):
        return None

    try:
        openai.api_key = api_key
        excerpt = _context_excerpt(text)
        prompt = (
            f"Create a faithful, student-friendly summary in exactly {max_sentences} numbered points. "
            "Do not copy long passages verbatim. Keep each point concise and meaningful. "
            "If content is noisy, infer the core learning points only from valid academic text.\n\n"
            f"Document:\n{excerpt}"
        )
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "You produce high-quality study summaries grounded in source text."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response["choices"][0]["message"]["content"].strip()
        return content or None
    except Exception:
        return None


def _quiz_with_openai(text: str, count: int = 5) -> Optional[List[dict]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not (OPENAI_AVAILABLE and api_key):
        return None

    try:
        openai.api_key = api_key
        excerpt = _context_excerpt(text)
        prompt = (
            f"Generate {count} high-quality MCQ quiz items from the document. "
            "Return ONLY a valid JSON array. Each item must have: question (string), options (array of 4), "
            "answer (string, must be one option), explanation (string). "
            "Questions must test understanding, not trivial copy-paste.\n\n"
            f"Document:\n{excerpt}"
        )
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {"role": "system", "content": "You create accurate educational quizzes from source material."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response["choices"][0]["message"]["content"].strip()
        items = _extract_json_array(content)
        if not items:
            return None

        normalized = []
        for item in items[:count]:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question", "")).strip()
            options = item.get("options", [])
            ans = str(item.get("answer", "")).strip()
            exp = str(item.get("explanation", "")).strip()
            if not q:
                continue
            if not isinstance(options, list):
                options = []
            options = [str(o).strip() for o in options if str(o).strip()]
            if ans and ans not in options:
                options = [ans, *options]
            options = options[:4]
            if len(options) < 2:
                continue
            if not ans:
                ans = options[0]
            normalized.append({
                "question": q,
                "options": options,
                "answer": ans,
                "explanation": exp or "Based on the uploaded content.",
            })

        return normalized or None
    except Exception:
        return None


def _fallback_quiz_from_terms(text: str, count: int = 5) -> List[dict]:
    sentences = [s for s in _split_sentences(_clean_extracted_text(text)) if 30 <= len(s) <= 240]
    concepts = [c for c in _extract_key_concepts(text) if _is_valid_concept_term(c[0])]
    terms = [t for t, _, _ in concepts]
    unique_terms = []
    seen_terms = set()
    for t in terms:
        key = t.lower().strip()
        if key and key not in seen_terms:
            seen_terms.add(key)
            unique_terms.append(t)

    quiz = []
    for term, definition, context in concepts:
        sentence = context if context else definition
        if not sentence:
            continue

        distractors = [t for t in unique_terms if t.lower() != term.lower()][:3]
        options = [term, *distractors]
        if len(options) < 2:
            continue

        quiz.append({
            "question": f"Which term best matches this description? {definition[:140]}",
            "options": options,
            "answer": term,
            "explanation": sentence,
        })
        if len(quiz) >= count:
            break

    if quiz:
        return quiz

    # Last fallback: comprehension from meaningful sentences
    for s in sentences[:count]:
        lead = re.sub(r"\s+", " ", s.split(",")[0]).strip()[:120]
        if not lead or lead.lower() in LOW_SIGNAL_TERMS:
            continue
        quiz.append({
            "question": f"According to the document, which statement is correct about: {lead}?",
            "options": [
                s,
                "The document does not discuss this topic.",
                "It is defined as unrelated to the course.",
                "It is only a historical note with no application.",
            ],
            "answer": s,
            "explanation": s,
        })
        if len(quiz) >= count:
            break

    if quiz:
        return quiz

    return [{
        "question": "What is the main idea of the uploaded content?",
        "options": [
            "It presents key concepts and explanations from the uploaded material.",
            "It contains no meaningful educational information.",
            "It is exclusively code and configuration output.",
            "It is only a bibliography with no content.",
        ],
        "answer": "It presents key concepts and explanations from the uploaded material.",
        "explanation": "The system extracts learning points from your document for study use.",
    }]


def _summary_from_text(text: str, max_sentences: int = 4) -> str:
    """Generate a high-quality summary (OpenAI first, deterministic fallback)."""
    ai_summary = _summary_with_openai(text, max_sentences)
    if ai_summary:
        return ai_summary

    concepts = [c for c in _extract_key_concepts(text) if _is_valid_concept_term(c[0])]
    if concepts:
        lines = []
        for i, (term, definition, _) in enumerate(concepts[:max_sentences], start=1):
            clean_def = re.sub(r"\s+", " ", definition).strip()
            lines.append(f"{i}. {term}: {clean_def}")
        if len(lines) >= 2:
            return "\n".join(lines)

    return _generate_smart_summary(text, max_sentences)


def _extract_key_terms(text: str) -> List[str]:
    """Extract key technical terms and concepts from text."""
    concepts = _extract_key_concepts(text)
    return [term for term, _, _ in concepts]


def _generate_flashcards(text: str, count: int = 5) -> List[dict]:
    """Generate high-quality flashcards using quality function."""
    return _generate_quality_flashcards(text, count)


def _generate_quiz(text: str, count: int = 5) -> List[dict]:
    """Generate high-quality quiz (OpenAI first, deterministic fallback)."""
    ai_quiz = _quiz_with_openai(text, count)
    if ai_quiz:
        return ai_quiz

    fallback = _fallback_quiz_from_terms(text, count)
    if fallback:
        return fallback
    return _generate_quality_quiz(text, count)


def _generate_study_plan(text: str, days: int = 7) -> List[dict]:
    cleaned = _clean_extracted_text(text)
    sentences = _split_sentences(cleaned)
    if not sentences or days < 1:
        return []

    # Keep concise, meaningful sentences only (avoid dumping full notes)
    candidates = []
    seen = set()
    for s in sentences:
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) < 35 or len(s) > 180:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(s)

    if not candidates:
        candidates = [s[:150].strip() for s in sentences[: max(days * 2, 7)]]

    chunks = [candidates[i::days] for i in range(days)]
    plan = []
    for day in range(days):
        topics = chunks[day] if day < len(chunks) else []
        plan.append({
            "day": day + 1,
            "focus": topics[:3],
        })
    return plan


@app.get("/", response_class=HTMLResponse)
def root():
    next_index_path = os.path.join(NEXT_FRONTEND_OUT_DIR, "index.html")
    if os.path.exists(next_index_path):
        return FileResponse(next_index_path)

    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h2>AI Study Partner Backend is running 🚀</h2>")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "db": "sqlite",
        "uploads_dir": UPLOADS_DIR,
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "telegram_bot_token_set": bool(TELEGRAM_BOT_TOKEN),
        "telegram_chat_id_set": bool(TELEGRAM_CHAT_ID),
    }


@app.get("/api/test-upload")
def test_upload():
    try:
        test_file = os.path.join(UPLOADS_DIR, "test.txt")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return {"status": "ok", "uploads_writable": True, "path": UPLOADS_DIR}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class Syllabus(BaseModel):
    content: str = Field(..., min_length=1)


@app.post("/api/syllabus")
def upload_syllabus(syllabus: Syllabus):
    _write_syllabus(syllabus.content)
    return {"message": "Syllabus uploaded successfully!", "length": len(syllabus.content)}


@app.get("/api/syllabus")
def get_syllabus():
    content = _read_syllabus()
    return {
        "length": len(content),
        "preview": content[:300],
        "hasContent": bool(content),
    }


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    sessionId: Optional[str] = None


class SummaryRequest(BaseModel):
    maxSentences: int = Field(4, ge=1, le=10)


class QuizRequest(BaseModel):
    count: int = Field(5, ge=1, le=10)


class StudyPlanRequest(BaseModel):
    days: int = Field(7, ge=1, le=30)


class ReminderRequest(BaseModel):
    title: str = Field(..., min_length=1)
    remindAt: str = Field(..., min_length=1)
    channel: str = Field("local")
    chatId: Optional[str] = None


class QuizAttemptRequest(BaseModel):
    score: int = Field(..., ge=0, le=100)
    totalQuestions: int = Field(..., ge=1, le=50)
    correctAnswers: int = Field(..., ge=0, le=50)


class StudySessionRequest(BaseModel):
    durationMinutes: int = Field(..., ge=1, le=480)
    topicCovered: str = Field(..., min_length=1)


try:
    import openai  # type: ignore

    OPENAI_AVAILABLE = True
except Exception:
    openai = None  # type: ignore
    OPENAI_AVAILABLE = False


def _chat_with_openai(question: str, context: str, history: List[dict]) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not (OPENAI_AVAILABLE and api_key):
        return None

    openai.api_key = api_key
    prompt = (
        "You are a helpful study partner. Use the syllabus context if relevant.\n\n"
        f"Syllabus:\n{context}\n\nQuestion: {question}"
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful study partner."},
                *history,
                {"role": "user", "content": prompt},
            ],
        )
        return response["choices"][0]["message"]["content"]
    except Exception:
        return None


@app.post("/api/chat")
def chat(request: ChatRequest):
    syllabus = _read_syllabus()
    store = _get_store()
    session_id = request.sessionId or "default"
    history = store.get("sessions", {}).get(session_id, [])
    answer = _chat_with_openai(request.question, syllabus, history)
    if answer:
        history.append({"role": "user", "content": request.question})
        history.append({"role": "assistant", "content": answer})
        store["sessions"][session_id] = history[-10:]
        _save_store(store)
        return {"answer": answer, "source": "openai"}

    if not syllabus:
        return {
            "answer": "No syllabus content is available. Upload a syllabus to get better answers.",
            "source": "fallback",
        }

    summary = _summary_from_text(syllabus, max_sentences=3)
    response = (
        f"I couldn't reach the AI service. Based on your syllabus, here is a quick summary:\n{summary}\n\n"
        f"Question: {request.question}\n"
        "Try asking a more specific question tied to the summary above."
    )
    return {"answer": response, "source": "fallback"}


@app.post("/api/summary")
def summarize(request: SummaryRequest):
    content = _read_syllabus()
    return {"summary": _summary_from_text(content, request.maxSentences)}


@app.post("/api/study-plan")
def study_plan(request: StudyPlanRequest):
    content = _read_syllabus()
    plan = _generate_study_plan(content, request.days)
    store = _get_store()
    store["studyPlans"].append({
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "days": request.days,
        "plan": plan,
    })
    _save_store(store)
    return {"plan": plan}


@app.post("/api/flashcards")
def flashcards(request: QuizRequest):
    content = _read_syllabus()
    return {"cards": _generate_flashcards(content, request.count)}


@app.post("/api/quiz")
def quiz(request: QuizRequest):
    content = _read_syllabus()
    return {"quiz": _generate_quiz(content, request.count)}


def _send_telegram_message(message: str, chat_id: Optional[str]) -> bool:
    """Backward-compatible wrapper that returns success as a boolean."""
    success, _ = _send_telegram_message_with_error(message, chat_id)
    return success


def _send_telegram_message_with_error(message: str, chat_id: Optional[str]) -> Tuple[bool, str]:
    """Send message to Telegram using bot token and chat ID with detailed error."""
    bot_token = TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID
    
    if not (bot_token and target_chat):
        error_message = f"Telegram not configured. Bot: {bool(bot_token)}, Chat: {bool(target_chat)}"
        print(error_message)
        return False, error_message

    import urllib.parse
    import urllib.request

    payload = urllib.parse.urlencode({
        "chat_id": target_chat,
        "text": message,
    }).encode()
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as response:
            response_data = response.read().decode()
            success = response.status == 200
            print(f"Telegram API Response ({response.status}): {response_data[:200]}")
            if success:
                return True, "Telegram message sent successfully"
            return False, f"Telegram API returned status {response.status}"
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode() if e.fp else str(e)
        print(f"Telegram HTTP Error {e.code}: {error_msg[:200]}")
        return False, f"Telegram HTTP Error {e.code}: {error_msg[:200]}"
    except Exception as e:
        print(f"Telegram error: {type(e).__name__}: {str(e)[:200]}")
        return False, f"Telegram error: {type(e).__name__}: {str(e)[:200]}"


def _persist_telegram_chat_id(chat_id: str) -> None:
    """Persist discovered Telegram chat ID in memory and .env for future runs."""
    global TELEGRAM_CHAT_ID

    chat_id = str(chat_id).strip()
    if not chat_id:
        return

    TELEGRAM_CHAT_ID = chat_id
    os.environ["TELEGRAM_CHAT_ID"] = chat_id

    env_path = os.path.join(BASE_DIR, ".env")
    lines: List[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("TELEGRAM_CHAT_ID="):
            lines[idx] = f"TELEGRAM_CHAT_ID={chat_id}\n"
            updated = True
            break

    if not updated:
        lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


@app.post("/api/reminders")
def create_reminder(request: ReminderRequest):
    if request.channel == "telegram" and not (request.chatId or TELEGRAM_CHAT_ID):
        raise HTTPException(
            status_code=400,
            detail="Telegram chat ID not configured. Click 'Get Chat ID from Telegram' first.",
        )

    store = _get_store()
    reminder = {
        "id": f"rem_{int(time.time())}",
        "title": request.title,
        "remindAt": request.remindAt,
        "channel": request.channel,
        "chatId": request.chatId or TELEGRAM_CHAT_ID,
        "sent": False,
    }
    store["reminders"].append(reminder)
    _save_store(store)
    return {"reminder": reminder}


@app.get("/api/reminders")
def list_reminders():
    store = _get_store()
    return {"reminders": store["reminders"]}


@app.get("/api/analytics")
def analytics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM quiz_attempts ORDER BY created_at DESC LIMIT 5")
    recent = cursor.fetchall()
    
    cursor.execute("SELECT AVG(score), COUNT(*) FROM quiz_attempts")
    avg_score, total = cursor.fetchone()
    
    cursor.execute("SELECT study_streak, total_study_minutes FROM user_stats WHERE id = 1")
    stats = cursor.fetchone()
    
    cursor.execute("SELECT * FROM documents ORDER BY uploaded_at DESC")
    docs = cursor.fetchall()
    
    cursor.execute("SELECT * FROM achievements")
    achievements = cursor.fetchall()
    
    conn.close()
    
    return {
        "totalAttempts": total or 0,
        "averageScore": round(avg_score, 2) if avg_score else 0,
        "recentAttempts": [{"score": r[1], "correct": r[3]} for r in recent],
        "studyStreak": stats[0] if stats else 0,
        "totalStudyMinutes": stats[1] if stats else 0,
        "achievements": [{"id": a[1], "name": a[2]} for a in achievements],
        "documents": [{"name": d[2], "size": d[4]} for d in docs],
    }


@app.post("/api/quiz-attempt")
def quiz_attempt(request: QuizAttemptRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO quiz_attempts (score, total_questions, correct_answers, created_at) VALUES (?, ?, ?, ?)",
        (request.score, request.totalQuestions, request.correctAnswers, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    _update_study_streak()
    return {"attempt": {"score": request.score, "totalQuestions": request.totalQuestions}}


@app.post("/api/telegram/get-chat-id")
def get_telegram_chat_id():
    """Get the latest chat ID from Telegram bot updates."""
    bot_token = TELEGRAM_BOT_TOKEN
    if not bot_token:
        return {"success": False, "message": "Bot token not configured"}
    
    import urllib.parse
    import urllib.request
    import json as json_lib
    
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json_lib.loads(response.read().decode())
            if data.get("ok") and data.get("result"):
                # Get the latest message
                latest_update = data["result"][-1]
                chat_id = str(latest_update.get("message", {}).get("chat", {}).get("id"))
                if chat_id:
                    _persist_telegram_chat_id(chat_id)
                    return {
                        "success": True,
                        "chat_id": chat_id,
                        "message": f"Found and saved chat ID: {chat_id}",
                    }
            return {"success": False, "message": "No messages found. Please send a message to your bot first."}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)[:100]}"}


@app.post("/api/telegram/test")
def telegram_test():
    success, message = _send_telegram_message_with_error("📚 You have a study reminder: Live study message", None)
    return {"success": success, "message": message}


def _reminder_worker():
    while True:
        try:
            store = _get_store()
            updated = False
            now = datetime.now(timezone.utc)
            for reminder in store.get("reminders", []):
                if reminder.get("sent"):
                    continue
                try:
                    remind_at = datetime.fromisoformat(reminder["remindAt"])
                except Exception:
                    continue
                if remind_at <= now:
                    message = f"📚 You have a study reminder: {reminder['title']}"
                    if reminder.get("channel") == "telegram":
                        _send_telegram_message(message, reminder.get("chatId"))
                    reminder["sent"] = True
                    updated = True
            if updated:
                _save_store(store)
            time.sleep(REMINDER_POLL_SECONDS)
        except Exception:
            time.sleep(REMINDER_POLL_SECONDS)


def _update_study_streak():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT study_streak, last_study_date FROM user_stats WHERE id = 1")
        result = cursor.fetchone()
        
        today = datetime.now(timezone.utc).date()
        streak = result[0] if result else 0
        last_study = result[1] if result else None
        
        if last_study:
            try:
                last_date = datetime.fromisoformat(last_study).date()
                if (today - last_date).days == 1:
                    streak += 1
                elif today > last_date:
                    streak = 1
            except Exception:
                streak = 1
        else:
            streak = 1
        
        cursor.execute(
            "UPDATE user_stats SET study_streak = ?, last_study_date = ? WHERE id = 1",
            (streak, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()
        _check_achievements()
    except Exception as e:
        print(f"Error updating study streak: {e}")


def _check_achievements() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM quiz_attempts")
    total_quizzes = cursor.fetchone()[0]
    
    cursor.execute("SELECT study_streak FROM user_stats WHERE id = 1")
    streak = cursor.fetchone()[0]
    
    cursor.execute("SELECT AVG(score) FROM quiz_attempts")
    avg_score = cursor.fetchone()[0] or 0
    
    achievements = []
    if total_quizzes >= 5:
        achievements.append(("5_quizzes", "Quiz Master"))
    if total_quizzes >= 10:
        achievements.append(("10_quizzes", "Study Legend"))
    if streak >= 7:
        achievements.append(("7_day_streak", "Week Warrior"))
    if avg_score >= 90:
        achievements.append(("high_scorer", "Top Scorer"))
    
    for ach_id, name in achievements:
        cursor.execute(
            "INSERT OR IGNORE INTO achievements (achievement_id, name, unlocked_at) VALUES (?, ?, ?)",
            (ach_id, name, datetime.now(timezone.utc).isoformat())
        )
    
    conn.commit()
    conn.close()


def _extract_text_from_file(filepath: str, filename: str) -> str:
    """Extract text from PDF, DOCX, or TXT files."""
    try:
        if filename.endswith(".pdf"):
            import PyPDF2
            pages_text = []
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        pages_text.append(extracted)

            text = "\n".join(pages_text)
            text = _clean_extracted_text(text)
            if text.strip():
                return text
            return ""
            
        elif filename.endswith(".txt"):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = _clean_extracted_text(f.read().strip())
                return text if text else ""
                
        elif filename.endswith(".docx"):
            from docx import Document
            doc = Document(filepath)
            text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            text = _clean_extracted_text(text)
            return text if text.strip() else ""
            
    except ImportError as e:
        print(f"Missing library: {e}")
        return ""
    except Exception as e:
        print(f"Error extracting text from {filename}: {e}")
        import traceback
        traceback.print_exc()
        return ""
    
    return ""


@app.post("/api/upload-document")
async def upload_document(file: UploadFile = File(...)):
    try:
        if not file.filename:
            return {"success": False, "error": "No filename provided"}
        
        content = await file.read()
        if not content:
            return {"success": False, "error": "Empty file"}
        
        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}_{file.filename}"
        filepath = os.path.join(UPLOADS_DIR, filename)
        
        # Save file to disk
        with open(filepath, "wb") as f:
            f.write(content)
        
        # Save to database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO documents (filename, original_name, uploaded_at, size) VALUES (?, ?, ?, ?)",
            (filename, file.filename, datetime.now(timezone.utc).isoformat(), len(content))
        )
        conn.commit()
        conn.close()
        
        _update_study_streak()
        
        # Extract text from file
        print(f"Extracting text from {file.filename}...")
        extracted_text = _extract_text_from_file(filepath, file.filename)
        
        if extracted_text and len(extracted_text.strip()) > 10:
            _write_syllabus(extracted_text)
            word_count = len(extracted_text.split())
            return {
                "success": True,
                "filename": filename,
                "message": f"✅ Document uploaded and parsed. {word_count} words extracted.",
                "wordCount": word_count,
            }
        else:
            print(f"Text extraction returned empty or too short for {file.filename}")
            return {
                "success": True,
                "filename": filename,
                "message": "✅ Document uploaded but text extraction failed. Trying text-based formats...",
                "charCount": 0,
            }
    except Exception as e:
        import traceback
        print(f"Upload error: {e}")
        traceback.print_exc()
        return {"success": False, "error": f"Upload failed: {str(e)}"}



@app.post("/api/study-session")
def log_study_session(request: StudySessionRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO study_sessions (topic, duration_minutes, created_at) VALUES (?, ?, ?)",
        (request.topicCovered, request.durationMinutes, datetime.now(timezone.utc).isoformat())
    )
    
    cursor.execute("SELECT total_study_minutes FROM user_stats WHERE id = 1")
    current_total = cursor.fetchone()[0] or 0
    new_total = current_total + request.durationMinutes
    
    cursor.execute("UPDATE user_stats SET total_study_minutes = ? WHERE id = 1", (new_total,))
    
    conn.commit()
    conn.close()
    
    _update_study_streak()
    return {"message": "Study session logged", "totalMinutes": new_total}


@app.get("/{asset_path:path}")
def serve_frontend_asset(asset_path: str):
    if not asset_path:
        return root()

    next_index_path = os.path.join(NEXT_FRONTEND_OUT_DIR, "index.html")
    if os.path.exists(next_index_path):
        normalized = os.path.normpath(asset_path).replace("\\", "/")
        if normalized.startswith("../") or normalized == "..":
            raise HTTPException(status_code=404, detail="Not found")

        candidate = os.path.normpath(os.path.join(NEXT_FRONTEND_OUT_DIR, normalized))
        next_base = os.path.normpath(NEXT_FRONTEND_OUT_DIR)

        if candidate.startswith(next_base) and os.path.isfile(candidate):
            return FileResponse(candidate)

        if "." not in os.path.basename(normalized):
            html_candidate = os.path.normpath(os.path.join(NEXT_FRONTEND_OUT_DIR, normalized, "index.html"))
            if html_candidate.startswith(next_base) and os.path.isfile(html_candidate):
                return FileResponse(html_candidate)

            return FileResponse(next_index_path)

    legacy_asset = os.path.normpath(os.path.join(FRONTEND_DIR, asset_path))
    legacy_base = os.path.normpath(FRONTEND_DIR)
    if legacy_asset.startswith(legacy_base) and os.path.isfile(legacy_asset):
        return FileResponse(legacy_asset)

    raise HTTPException(status_code=404, detail="Not found")


threading.Thread(target=_reminder_worker, daemon=True).start()

