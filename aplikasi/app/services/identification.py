import re
from dataclasses import dataclass


CASE_NUMBER_RE = re.compile(
    r"\b(?P<number>\d{1,6})\s*/\s*(?P<class>Pdt\.\s*(?:G|P|Gugatan|Permohonan)|Pdt\.G|Pdt\.P)\s*/\s*"
    r"(?P<year>20\d{2})\s*/\s*(?P<court>PA\.\s*[A-Za-z]{2,10})\b",
    re.IGNORECASE,
)

DOCUMENT_RULES = {
    "Penetapan Majelis Hakim": [
        (r"\bpenetapan\s+majelis\s+hakim\b", 30),
        (r"\bmenetapkan\s+(majelis\s+)?hakim\b", 25),
        (r"\bsusunan\s+majelis\s+hakim\b", 20),
        (r"\bditetapkan\s+hakim\s+yang\s+menangani\s+perkara\s+ini\b", 20),
        (r"\bhakim\s+yang\s+menangani\s+perkara\s+ini\b", 18),
        (r"\bizin\s+sidang\s+dengan\s+hakim\s+tunggal\b", 14),
        (r"\bhakim\s+tunggal\b", 10),
    ],
    "Penunjukan Panitera": [
        (r"\bpenunjukan\s+panitera\s+pengganti\b", 30),
        (r"\bmenunjuk\s+panitera\s+pengganti\b", 25),
        (r"\bpanitera\s+pengganti\b", 12),
    ],
    "Penunjukan Jurusita": [
        (r"\bpenunjukan\s+jurusita\b", 30),
        (r"\bmenunjuk\s+jurusita\b", 25),
        (r"\bjurusita\s+pengganti\b", 12),
    ],
    "Penetapan Hari Sidang": [
        (r"\bpenetapan\s+hari\s+sidang\b", 30),
        (r"\bmenetapkan\s+hari\s+sidang\b", 25),
        (r"\bditetapkan\s+hari\s+sidang\b", 18),
        (r"\bhari\s+sidang\s+pertama\b", 12),
        (r"\bhari\s+sidang\b", 4),
    ],
}


@dataclass
class IdentificationResult:
    case_number: str | None
    document_type: str | None
    confidence: str


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_case_number(match: re.Match) -> str:
    case_class = match.group("class").replace(" ", "")
    if case_class.lower() in {"pdt.gugatan", "pdt.g"}:
        case_class = "Pdt.G"
    elif case_class.lower() in {"pdt.permohonan", "pdt.p"}:
        case_class = "Pdt.P"
    court = match.group("court").replace(" ", "")
    court = court[:3].upper() + court[3:]
    return f"{int(match.group('number'))}/{case_class}/{match.group('year')}/{court}"


def extract_case_number(text: str) -> str | None:
    normalized = normalize_whitespace(text)
    match = CASE_NUMBER_RE.search(normalized)
    return normalize_case_number(match) if match else None


def identify_document_type(text: str) -> str | None:
    haystack = normalize_whitespace(text).lower()
    scores: dict[str, int] = {}
    for doc_type, rules in DOCUMENT_RULES.items():
        score = 0
        for pattern, weight in rules:
            if re.search(pattern, haystack, re.IGNORECASE):
                score += weight
        scores[doc_type] = score

    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    return best_type if best_score >= 10 else None


def identify_document_type_from_filename(filename: str | None) -> str | None:
    value = normalize_whitespace((filename or "").replace("_", " ").replace("-", " ")).lower()
    if "penetapan hari sidang" in value:
        return "Penetapan Hari Sidang"
    if "penetapan majelis hakim" in value or "penetapan hakim" in value:
        return "Penetapan Majelis Hakim"
    if "penunjukan panitera" in value:
        return "Penunjukan Panitera"
    if "penunjukan jurusita" in value:
        return "Penunjukan Jurusita"
    return None


def identify_document(text: str) -> IdentificationResult:
    case_number = extract_case_number(text)
    document_type = identify_document_type(text)

    if case_number and document_type:
        confidence = "tinggi"
    elif case_number or document_type:
        confidence = "sedang"
    else:
        confidence = "rendah"

    return IdentificationResult(case_number, document_type, confidence)
