"""
app/memory/memory_manager.py — Long-term memory for DIMO.

Ported from Mark-XXXIX-OR-main/memory/memory_manager.py.
LLM backend: Gemini Flash Lite (primary, fast + cheap) with Ollama fallback.
Storage: JSON at app/memory/long_term.json.

API surface (identical to Mark):
    load_memory()                                  → dict
    save_memory(memory)                            → None
    update_memory(memory_update)                   → dict
    should_extract_memory(user_text, jarvis_text)  → bool
    extract_memory(user_text, jarvis_text)         → dict
    format_memory_for_prompt(memory)               → str
    remember(key, value, category)                 → str
    forget(key, category)                          → str
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

load_dotenv()

import logging
logger = logging.getLogger("dimo.memory")

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE        = Path(__file__).resolve().parent
MEMORY_PATH  = _HERE / "long_term.json"

# ── Limits (same as Mark) ─────────────────────────────────────────────────────
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200

# ── Thread safety ─────────────────────────────────────────────────────────────
_lock = Lock()

# ── Ollama settings ───────────────────────────────────────────────────────────
OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MEMORY_MODEL   = os.getenv("ROUTER_MODEL", "llama3.2:3b")   # fast model for memory checks

# ── Gemini settings (primary for memory extraction) ────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MEMORY_MODEL = "gemini-2.0-flash-lite"  # fast + cheap for YES/NO and JSON


# ══════════════════════════════════════════════════════════════════════════════
# EMPTY / LOAD / SAVE
# ══════════════════════════════════════════════════════════════════════════════

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }


def load_memory() -> dict:
    """Load memory from JSON file. Returns empty structure if file missing or corrupt."""
    if not MEMORY_PATH.exists():
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            logger.warning("[Memory] ⚠️ Load error: %s", e)
            return _empty_memory()


def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    """Remove oldest entries until JSON serialisation fits within MEMORY_MAX_CHARS."""
    serialized = json.dumps(memory, ensure_ascii=False)
    if len(serialized) <= MEMORY_MAX_CHARS:
        return memory

    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))

    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        logger.debug("[Memory] 🗑️ Trimmed %s/%s", cat, key)

    return memory


def save_memory(memory: dict) -> None:
    """Trim memory to limit then persist to JSON."""
    if not isinstance(memory, dict):
        return

    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ══════════════════════════════════════════════════════════════════════════════
# UPDATE (recursive merge)
# ══════════════════════════════════════════════════════════════════════════════

def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    """Recursively merge updates into target. Returns True if anything changed."""
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                new_val = _truncate_value(str(value["value"]))
            else:
                new_val = _truncate_value(str(value))

            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    """Merge a partial update dict into the persisted memory and save."""
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        logger.info("[Memory] 💾 Saved: %s", list(memory_update.keys()))
    return memory


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY EXTRACTION PIPELINE  (two-stage, mirroring Mark exactly)
# ══════════════════════════════════════════════════════════════════════════════

def _gemini_chat(prompt: str, system: str, max_tokens: int = 10) -> str:
    """Call Gemini Flash Lite for memory ops (fast + cheap)."""
    if not GEMINI_API_KEY:
        return ""
    try:
        import google.generativeai as genai  # noqa: PLC0415
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=GEMINI_MEMORY_MODEL,
            system_instruction=system,
        )
        resp = model.generate_content(
            prompt,
            generation_config={"max_output_tokens": max_tokens, "temperature": 0.0},
        )
        return (resp.text or "").strip()
    except Exception as e:
        logger.debug("[Memory] Gemini call failed: %s", e)
        return ""


def _ollama_chat(prompt: str, system: str, max_tokens: int = 10) -> str:
    """Fallback: call Ollama generate with a system + user prompt."""
    try:
        from ollama import Client  # type: ignore  # noqa: PLC0415
        client = Client(host=OLLAMA_HOST)
        full_prompt = f"{system}\n\n{prompt}"
        resp = client.generate(
            model=MEMORY_MODEL,
            prompt=full_prompt,
            stream=False,
            options={"num_predict": max_tokens, "temperature": 0.0},
        )
        return (resp.response or "").strip()
    except Exception as e:
        logger.warning("[Memory] Ollama call failed: %s", e)
        return ""


def _llm_chat(prompt: str, system: str, max_tokens: int = 10) -> str:
    """Try Gemini first; fall back to Ollama."""
    result = _gemini_chat(prompt, system, max_tokens)
    if result:
        return result
    return _ollama_chat(prompt, system, max_tokens)


def should_extract_memory(user_text: str, assistant_text: str) -> bool:
    """
    Strict two-gate policy for deciding whether to extract memory.

    Gate 1 (fast path): user explicitly asked to remember something.
    Gate 2 (LLM gate): conversation contains a genuine long-term fact.

    Defaults to NO in all ambiguous cases.
    """
    user_lower = user_text.lower()

    # ── Gate 1: explicit save signal ──────────────────────────────────────────
    _EXPLICIT_SIGNALS = (
        "remember this", "save this", "store this", "don't forget",
        "add to memory", "keep this in mind", "note this", "memorize this",
    )
    if any(sig in user_lower for sig in _EXPLICIT_SIGNALS):
        logger.info("[Memory] Gate 1 PASS — explicit save signal detected")
        return True

    # ── Gate 1b: skip fast if clearly a one-time task ─────────────────────────
    _ONE_TIME_SIGNALS = (
        "send a message", "send whatsapp", "send telegram", "send email",
        "search for", "look up", "open the", "play ", "remind me",
        "what is", "what's the weather", "show me", "find a flight",
        "compose a message", "draft a message", "write a message",
    )
    if any(sig in user_lower for sig in _ONE_TIME_SIGNALS):
        logger.info("[Memory] Skipped: Temporary task (one-time command detected)")
        return False

    # ── Gate 2: LLM strict check ──────────────────────────────────────────────
    combined = f"User: {user_text[:400]}\nAssistant: {assistant_text[:400]}"
    result = _llm_chat(
        prompt=(
            "Does this conversation contain ANY of these SPECIFIC long-term facts?\n"
            "1. A long-term personal preference (diet, lifestyle, recurring behavior)\n"
            "2. A long-term interest or hobby the user regularly engages in\n"
            "3. A long-term goal or aspiration (career, health, life goal)\n"
            "4. An active project the user is building or working on regularly\n"
            "5. A persistent recurring workflow or schedule\n\n"
            "Answer YES only if at least one of the above is CLEARLY present.\n"
            "Answer NO for: one-time tasks, messages sent, commands, casual chat, "
            "tool outputs, search results, people mentioned once, generated text, "
            "execution summaries, or anything temporary.\n\n"
            "When in doubt → NO.\n\n"
            f"Conversation:\n{combined}\n\n"
            "Reply ONLY: YES or NO"
        ),
        system="You are a strict memory filter. Reply only YES or NO. Default to NO.",
        max_tokens=5,
    )
    decision = "YES" in result.upper()
    if decision:
        logger.info("[Memory] Gate 2 PASS — long-term fact detected by LLM")
    else:
        logger.info("[Memory] Skipped: LLM gate returned NO (no durable long-term fact)")
    return decision


def _score_and_filter_memory(extracted: dict) -> tuple[dict, str]:
    """
    Post-extraction filter: removes entries that look like temporary/tool content.
    Returns (filtered_dict, reason_string).
    """
    import re as _re  # noqa: PLC0415

    # Patterns that indicate temporary/tool output content
    _SKIP_PATTERNS = [
        r"sent a message", r"search result", r"step \d+",
        r"task completed", r"tool output", r"execution",
        r"\[result", r"whatsapp message", r"compose",
        r"I sent", r"message was sent", r"successfully sent",
    ]

    filtered = {}
    reasons = []

    for category, items in extracted.items():
        if not isinstance(items, dict):
            continue
        kept = {}
        for key, entry in items.items():
            val = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            is_temp = any(_re.search(p, val.lower()) for p in _SKIP_PATTERNS)
            if is_temp:
                logger.info("[Memory] Skipped entry '%s/%s': looks like temporary content", category, key)
            else:
                kept[key] = entry
        if kept:
            filtered[category] = kept
            reasons.append(f"{category}({len(kept)})")

    reason = "Long-term facts: " + ", ".join(reasons) if reasons else "nothing durable"
    return filtered, reason


def extract_memory(user_text: str, assistant_text: str) -> dict:
    """
    Stage 2: Extract structured memory facts conservatively.
    Only extracts long-term, durable facts. Discards temporary content.
    """
    combined = f"User: {user_text[:600]}\nAssistant: {assistant_text[:300]}"
    raw = _llm_chat(
        prompt=(
            "Extract ONLY long-term, durable personal facts from this conversation.\n"
            "Return ONLY valid JSON. Use {} if nothing qualifies.\n\n"
            "ONLY include:\n"
            "  identity    → name, age, city, job, language (only if stated directly)\n"
            "  preferences → long-term favorites: diet, music, color, hobbies, sport (NOT one-time mentions)\n"
            "  projects    → actively built projects, ongoing goals the user works on regularly\n"
            "  wishes      → long-term aspirations, plans, things they want to achieve\n"
            "  notes       → persistent habits, recurring schedule, lifestyle facts\n\n"
            "DO NOT include:\n"
            "  - relationships (people mentioned once)\n"
            "  - tool outputs, sent messages, search results\n"
            "  - one-time tasks, commands, temporary requests\n"
            "  - casual conversation or small talk\n"
            "  - anything that won't be useful in a future conversation\n\n"
            "Be CONSERVATIVE. If unsure whether something is long-term → omit it.\n\n"
            f"Conversation:\n{combined}\n\nJSON:"
        ),
        system="Return ONLY valid JSON. Be very conservative. Omit anything temporary.",
        max_tokens=512,
    )

    clean = raw.strip()
    clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

    if not clean or clean == "{}":
        logger.info("[Memory] Skipped: extraction returned empty")
        return {}

    try:
        extracted = json.loads(clean)
    except json.JSONDecodeError:
        logger.debug("[Memory] JSON parse failed for extraction result")
        return {}

    # Post-filter: remove temporary/tool content
    filtered, reason = _score_and_filter_memory(extracted)

    if filtered:
        logger.info("[Memory] Saved because: %s", reason)
    else:
        logger.info("[Memory] Skipped: all extracted entries were temporary content")

    return filtered


# ══════════════════════════════════════════════════════════════════════════════
# FORMAT FOR PROMPT  (identical to Mark's format_memory_for_prompt)
# ══════════════════════════════════════════════════════════════════════════════

def format_memory_for_prompt(memory: dict | None) -> str:
    """
    Convert the memory dict into a human-readable block for injection into the
    LLM system prompt.  Mirrors Mark's format_memory_for_prompt() exactly.
    """
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"

    return result + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def remember(key: str, value: str, category: str = "notes") -> str:
    """Save a single key/value fact to memory."""
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    """Delete a single key from memory."""
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget  # alias for Mark compatibility
