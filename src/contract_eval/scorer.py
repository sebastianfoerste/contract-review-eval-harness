"""Pure scoring functions. Each measures one dimension of contract-review quality."""

from dataclasses import dataclass

from contract_eval.models import Citation


@dataclass
class ClauseScore:
    precision: float
    recall: float
    f1: float


@dataclass
class CitationScore:
    grounded: int
    total: int
    grounding_rate: float


def clause_scores(expected: list[str], predicted: list[str]) -> ClauseScore:
    exp, pred = set(expected), set(predicted)
    tp = len(exp & pred)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(exp) if exp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return ClauseScore(precision, recall, f1)


def risk_flag_accuracy(expected: dict[str, str], predicted: dict[str, str]) -> float:
    if not expected:
        return 0.0
    matched = sum(1 for clause_type, severity in expected.items() if predicted.get(clause_type) == severity)
    return matched / len(expected)


import string

def normalize_text(text: str) -> str:
    t = text.lower()
    for p in string.punctuation + "“”‘’–—":
        t = t.replace(p, " ")
    return " ".join(t.split())


def _is_grounded(source_text: str, quote: str, threshold: float = 0.85) -> bool:
    norm_source = normalize_text(source_text)
    norm_quote = normalize_text(quote)
    
    if not norm_quote:
        return False
        
    if norm_quote in norm_source:
        return True
        
    source_words = norm_source.split()
    quote_words = norm_quote.split()
    q_len = len(quote_words)
    
    if q_len <= 3:
        return norm_quote in norm_source
        
    quote_set = set(quote_words)
    
    for i in range(len(source_words) - q_len + 1):
        window = set(source_words[i:i + q_len])
        overlap = len(quote_set & window) / len(quote_set)
        if overlap >= threshold:
            return True
            
    return False


def citation_grounding(source_text: str, citations: list[Citation]) -> CitationScore:
    total = len(citations)
    grounded = sum(1 for c in citations if _is_grounded(source_text, c.quote))
    rate = grounded / total if total else 0.0
    return CitationScore(grounded, total, rate)


def count_hallucinations(source_text: str, citations: list[Citation]) -> int:
    return sum(1 for c in citations if not _is_grounded(source_text, c.quote))

