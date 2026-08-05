"""База знаний проекта — повторение механики Langdock.

ЧТО ВЗЯТО ИЗ ДОКУМЕНТАЦИИ LANGDOCK (выгрузка в sandbox/reference/langdock-docs.txt,
раздел Knowledge Basics). Это утверждения платформы о себе, а не пересказ того,
что написано в промпте тренажёра:

  * ГЛАВНОЕ ПРАВИЛО — способ подачи зависит от ЧИСЛА документов, а не от их
    размера: «When the Agent has up to 20 documents in total, all are previewed
    in context. With more than 20, documents are retrieved through document
    search instead». Поиск по фрагментам включается только с 21-го документа;
  * «As much text of the document as possible is sent to the model as a preview.
    For small files, this can be the entire document»;
  * поиск по эмбеддингам применяется к Knowledge bases, синхронизированным
    папкам и к прямым файлам агента, когда их больше 20;
  * параметры поиска: фрагмент 2000 символов, вектор 1536 измерений,
    до 50 фрагментов на запрос.

Здесь воспроизведён тот же механизм. Вкладывать базу целиком было бы грубой
ошибкой: 464 КБ — это около 85 тысяч токенов в каждом запросе, и главное —
вход отличался бы от платформы, а значит тест ничего не мерил бы.

ЧЕГО МЫ НЕ ЗНАЕМ и где возможно расхождение с платформой:

  1. Есть ли предел у предпросмотра. «As much text as possible» подразумевает
     какой-то потолок, но он не опубликован. Мы вкладываем файл целиком.
  2. Какой моделью Langdock считает эмбеддинги (известна только размерность).
  3. Куда именно платформа кладёт содержимое в списке сообщений. В разбивке
     контекста «Attachments» — отдельная категория от «System prompt», поэтому
     мы кладём отдельным системным сообщением, а не подмешиваем в инструкции.
  4. Что именно Langdock добавляет от себя: в разбивке «System prompt» описан
     как «Instructions AND system context», плюс отдельная категория
     «System tools» с определениями инструментов. Ни того, ни другого у нас
     нет — и это расхождение, которое пока нечем закрыть.

Всё это пишется в лог прогона и помечается отклонением knowledge_retrieval,
чтобы разница была видна, а не подразумевалась. Закрыть пробелы можно
эмпирически: если Langdock показывает, на какие разделы он сослался,
сравните их с тем, что подняла песочница на том же вопросе, и подгоните
параметры выше.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import CONFIG, LOGS_DIR, REPO_ROOT

# По умолчанию — потолок, заявленный в документации Langdock.
# Значения — из документации Langdock (раздел Knowledge Basics, «Our Parameters»):
# вектор 1536 измерений, фрагмент 2000 символов, до 50 фрагментов на запрос.
DEFAULT_TOP_K = 50
DEFAULT_CHUNK_CHARS = 2000
DEFAULT_CHUNK_OVERLAP = 200
# Файлы мельче этого порога подаются целиком: у Langdock небольшие вложения
# тоже попадают в контекст полностью, а промпт тренажёра прямо требует
# выводить памятку из onboarding.md дословно — поиском фрагментов такое
# требование выполнить нельзя.
DEFAULT_FULL_TEXT_LIMIT = 4000

EMBEDDING_MODEL = "text-embedding-3-small"
# 1536 — размерность, заявленная Langdock. Какой моделью они считают вектор,
# не опубликовано; берём модель OpenAI той же размерности.
EMBEDDING_DIMENSIONS = 1536

_INDEX_PATH = LOGS_DIR / "knowledge_index.json"


@dataclass
class Chunk:
    """Один фрагмент базы знаний."""

    source: str
    heading: str
    text: str
    index: int
    embedding: list[float] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source}#{self.index}"

    def label(self) -> str:
        return f"{self.source} — {self.heading}" if self.heading else self.source


def split_markdown(text: str, source: str, chunk_chars: int, overlap: int) -> list[Chunk]:
    """Режет файл по заголовкам, длинные разделы дополнительно по размеру.

    Нарезка по заголовкам, а не вслепую по символам: в этих файлах раздел —
    смысловая единица (один аргумент, один портрет), и разрывать её посередине
    значит терять именно то, ради чего фрагмент ищется.
    """
    chunks: list[Chunk] = []
    parts = re.split(r"^(#{1,3} .+)$", text, flags=re.MULTILINE)

    blocks: list[tuple[str, str]] = []
    if parts and parts[0].strip():
        blocks.append(("", parts[0].strip()))
    for i in range(1, len(parts), 2):
        heading = parts[i].strip().lstrip("#").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append((heading, (parts[i] + body).strip()))

    def emit(heading: str, text: str) -> None:
        text = text.strip()
        if len(text) >= 40:  # огрызки вроде одиночного дефиса искать бессмысленно
            chunks.append(Chunk(source, heading, text, len(chunks)))

    for heading, body in blocks:
        if not body.strip():
            continue
        if len(body) <= chunk_chars:
            emit(heading, body)
            continue

        # Копим абзацы до предела размера. Накопление, а не скользящее окно:
        # окно с плавающим шагом легко схлопывается и режет файл на огрызки.
        paragraphs = re.split(r"\n{2,}", body)
        current: list[str] = []
        current_len = 0

        for paragraph in paragraphs:
            if len(paragraph) > chunk_chars:
                if current:
                    emit(heading, "\n\n".join(current))
                    current, current_len = [], 0
                for start in range(0, len(paragraph), chunk_chars):
                    emit(heading, paragraph[start : start + chunk_chars])
                continue

            if current_len + len(paragraph) > chunk_chars and current:
                emit(heading, "\n\n".join(current))
                # Небольшой хвост предыдущего фрагмента переносим в следующий,
                # чтобы мысль на стыке не терялась.
                tail: list[str] = []
                tail_len = 0
                for previous in reversed(current):
                    if tail_len >= overlap:
                        break
                    tail.insert(0, previous)
                    tail_len += len(previous)
                current, current_len = tail, tail_len

            current.append(paragraph)
            current_len += len(paragraph)

        if current:
            emit(heading, "\n\n".join(current))

    return chunks


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _headers() -> dict:
    headers = {"Authorization": f"Bearer {CONFIG.api_key}", "Content-Type": "application/json"}
    if CONFIG.organization:
        headers["OpenAI-Organization"] = CONFIG.organization
    return headers


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Векторы для списка текстов. Пустой список — если эмбеддинги недоступны."""
    if CONFIG.effective_mock or not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 96):  # батчами, чтобы не упереться в лимит запроса
        batch = texts[start : start + 96]
        body = {
            "model": EMBEDDING_MODEL,
            "input": batch,
            "dimensions": EMBEDDING_DIMENSIONS,
        }
        request = urllib.request.Request(
            f"{CONFIG.base_url}/embeddings",
            data=json.dumps(body).encode("utf-8"),
            headers=_headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=CONFIG.request_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        vectors.extend(item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"]))
    return vectors


def _load_index() -> dict:
    if _INDEX_PATH.exists():
        try:
            return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_index(index: dict) -> None:
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def build_index(
    files: list[str],
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    progress=None,
) -> tuple[list[Chunk], dict]:
    """Готовит фрагменты и их векторы. Переиндексирует только изменившиеся файлы."""
    index = _load_index()
    settings_key = f"{EMBEDDING_MODEL}:{EMBEDDING_DIMENSIONS}:{chunk_chars}:{overlap}"
    chunks: list[Chunk] = []
    stats = {"files": [], "embedded_now": 0, "from_cache": 0, "method": "embeddings"}

    for relative in files:
        path = (REPO_ROOT / relative).resolve()
        if not path.exists() or path.suffix.lower() == ".pdf":
            stats["files"].append({"source": relative, "missing": True})
            continue

        sha = _file_sha(path)
        cache_key = f"{relative}|{sha}|{settings_key}"
        cached = index.get(cache_key)

        file_chunks = split_markdown(path.read_text(encoding="utf-8"), relative, chunk_chars, overlap)

        if cached and len(cached.get("embeddings") or []) == len(file_chunks):
            for chunk, vector in zip(file_chunks, cached["embeddings"]):
                chunk.embedding = vector
            stats["from_cache"] += len(file_chunks)
        else:
            if progress:
                progress(f"индексирую {relative} ({len(file_chunks)} фрагментов)")
            vectors = embed_texts([chunk.text for chunk in file_chunks])
            if vectors:
                for chunk, vector in zip(file_chunks, vectors):
                    chunk.embedding = vector
                index[cache_key] = {"embeddings": vectors}
                stats["embedded_now"] += len(file_chunks)

        chunks.extend(file_chunks)
        stats["files"].append(
            {"source": relative, "sha": sha, "chunks": len(file_chunks), "chars": path.stat().st_size}
        )

    if stats["embedded_now"]:
        _save_index(index)
    if not any(chunk.embedding for chunk in chunks):
        stats["method"] = "лексический поиск (эмбеддинги недоступны)"
    return chunks, stats


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


_WORD = re.compile(r"[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z-]{3,}|\d+[,.]?\d*")


def _lexical_score(query: str, text: str) -> float:
    """Запасное ранжирование без эмбеддингов — только чтобы проверять песочницу.

    Это НЕ семантический поиск и с платформой не сопоставимо; такой прогон
    помечается в логе отдельно.
    """
    q = {w.lower() for w in _WORD.findall(query)}
    if not q:
        return 0.0
    t = {w.lower() for w in _WORD.findall(text)}
    return len(q & t) / len(q)


def retrieve(query: str, chunks: list[Chunk], top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Ищет наиболее релевантные фрагменты под запрос."""
    if not chunks:
        return []

    have_embeddings = any(chunk.embedding for chunk in chunks)
    if have_embeddings:
        query_vectors = embed_texts([query])
        if query_vectors:
            scored = [(_cosine(query_vectors[0], chunk.embedding), chunk) for chunk in chunks]
        else:
            scored = [(_lexical_score(query, chunk.text), chunk) for chunk in chunks]
    else:
        scored = [(_lexical_score(query, chunk.text), chunk) for chunk in chunks]

    scored.sort(key=lambda pair: pair[0], reverse=True)
    picked = [pair for pair in scored[:top_k] if pair[0] > 0]
    return [
        {
            "source": chunk.source,
            "heading": chunk.heading,
            "text": chunk.text,
            "score": round(score, 4),
            "key": chunk.key,
        }
        for score, chunk in picked
    ]


def render_context(found: list[dict]) -> str:
    """Собирает найденные фрагменты в текст для контекста.

    Каждый кусок подписан именем файла: промпт тренажёра требует ссылаться
    на источник, и без подписи выполнить это требование нельзя.
    """
    blocks = []
    for item in found:
        title = f"{item['source']}" + (f" — {item['heading']}" if item["heading"] else "")
        blocks.append(f"[{title}]\n{item['text']}")
    return "\n\n".join(blocks)


def contains_terms(terms: list[str], found: list[dict], chunks: list[Chunk]) -> dict:
    """Где термин вообще встречается: в найденном, в базе, или нигде.

    Ради этого разделения всё и затевалось. Ошибка в ответе объясняется
    по-разному: фрагмент не нашёлся поиском, в базе такого нет вовсе, или
    модель его получила и всё равно ошиблась. Три разные причины — три
    разных исправления.
    """
    retrieved_text = " ".join(item["text"] for item in found).lower()
    base_text = " ".join(chunk.text for chunk in chunks).lower()

    in_retrieved, in_base_only, missing = [], [], []
    for term in terms:
        lowered = term.lower()
        if lowered in retrieved_text:
            in_retrieved.append(term)
        elif lowered in base_text:
            in_base_only.append(term)
        else:
            missing.append(term)
    return {
        "in_retrieved": in_retrieved,
        "in_base_not_retrieved": in_base_only,
        "absent_from_base": missing,
    }
