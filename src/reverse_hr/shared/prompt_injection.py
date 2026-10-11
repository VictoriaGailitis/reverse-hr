"""Explainable suspicion signals, not a proof of cheating or an LLM firewall."""

import re
import unicodedata

RULE_VERSION = "prompt-risk-v1"
RULES = {
    "instruction_override": (
        r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?"
        r"(?:previous|prior|system|developer)\s+(?:instructions?|prompts?|rules?)\b|"
        r"\b(?:игнорируй|забудь|отмени)\s+(?:все\s+)?"
        r"(?:предыдущие|системные|прежние)\s+(?:инструкции|правила|указания)\b"
    ),
    "role_spoofing": (
        r"<\|(?:im_start|start_header_id)\|>\s*(?:system|developer)|"
        r"</?(?:system|developer)>|\[INST\]\s*<<SYS>>"
    ),
    "system_exfiltration": (
        r"\b(?:reveal|print|show|output)\s+(?:(?:your|the|entire|full)\s+)*"
        r"(?:system|developer)\s+prompt\b|"
        r"\b(?:покажи|выведи|раскрой)\s+(?:свой\s+)?системный\s+промпт\b"
    ),
    "grade_manipulation": (
        r"\b(?:give|assign|return|set)\s+(?:me\s+)?(?:a\s+)?(?:score|grade)"
        r"\s*(?:(?:of|to|=|:)\s*)?(?:100|senior|lead)\b|"
        r"\b(?:поставь|выставь|присвой)\s+(?:мне\s+)?(?:оценку|грейд)\s*(?:100|senior|lead)\b"
    ),
}
COMPILED = {code: re.compile(pattern, re.I) for code, pattern in RULES.items()}


def detect(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    # Mere mentions of the concept do not match; explicit instructions can still
    # be a legitimate security example. A human must resolve that ambiguity.
    return sorted(code for code, pattern in COMPILED.items() if pattern.search(normalized))


def scan_source(value) -> list[str]:
    codes = set()

    def visit(item):
        if isinstance(item, str):
            codes.update(detect(item))
        elif isinstance(item, dict):
            for key, child in item.items():
                if key in {"content", "text", "transcript"} or isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(codes)
