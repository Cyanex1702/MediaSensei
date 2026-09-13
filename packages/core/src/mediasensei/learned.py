"""Bounded, JSON-serializable fitted lexical and supervised language adapters."""

from __future__ import annotations

import math
import re
from collections import Counter

WORDS = re.compile(r"\w+", re.UNICODE)


def tokens(text):
    return WORDS.findall(text.casefold())


def fit_model(texts, kind, labels):
    if not texts or len(texts) > 1000 or sum(len(t.encode()) for t in texts) > 2 * 1024**2:
        raise ValueError("Training requires 1–1000 chunks totaling at most 2 MiB.")
    counts = Counter(word for text in texts for word in set(tokens(text)))
    vocabulary = sorted(sorted(counts, key=lambda word: (-counts[word], word))[:512])
    if not vocabulary:
        raise ValueError("Training text contains no words.")
    if kind == "tfidf":
        return {
            "kind": kind,
            "vocabulary": vocabulary,
            "idf": [math.log((1 + len(texts)) / (1 + counts[word])) + 1 for word in vocabulary],
        }
    if kind != "language" or len(labels) != len(texts):
        raise ValueError("Choose tfidf or supply one language label per training chunk.")
    classes = sorted(set(labels))
    if not 2 <= len(classes) <= 32 or any(
        not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", label) for label in classes
    ):
        raise ValueError("Language models need 2–32 valid language labels, for example en and ur.")
    weights, priors = [], []
    for label in classes:
        subset = [text for text, assigned in zip(texts, labels) if assigned == label]
        totals = Counter(word for text in subset for word in tokens(text))
        denominator = sum(totals[word] for word in vocabulary) + len(vocabulary)
        weights.append([math.log((totals[word] + 1) / denominator) for word in vocabulary])
        priors.append(math.log(len(subset) / len(texts)))
    return {
        "kind": kind,
        "vocabulary": vocabulary,
        "classes": classes,
        "weights": weights,
        "priors": priors,
    }


def validate_model(model):
    if not isinstance(model, dict):
        raise ValueError("Model must be a JSON object.")  # noqa: TRY004 - API input validation
    vocabulary = model.get("vocabulary")
    if not isinstance(vocabulary, list) or not 1 <= len(vocabulary) <= 512:
        raise ValueError("Invalid model vocabulary.")
    if any(not isinstance(word, str) or not 1 <= len(word) <= 512 for word in vocabulary) or len(
        set(vocabulary)
    ) != len(vocabulary):
        raise ValueError("Invalid or duplicate model words.")
    size = len(vocabulary)

    def vector(values, expected):
        return (
            isinstance(values, list)
            and len(values) == expected
            and all(
                type(v) in (int, float) and math.isfinite(v) and abs(v) <= 10000 for v in values
            )
        )

    if model.get("kind") == "tfidf":
        if not vector(model.get("idf"), size) or any(v <= 0 for v in model["idf"]):
            raise ValueError("Invalid fitted IDF weights.")
    elif model.get("kind") == "language":
        classes = model.get("classes", [])
        weights = model.get("weights", [])
        if (
            not isinstance(classes, list)
            or not 2 <= len(classes) <= 32
            or any(not isinstance(label, str) for label in classes)
            or len(set(classes)) != len(classes)
        ):
            raise ValueError("Invalid language classes.")
        if any(
            not isinstance(label, str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", label)
            for label in classes
        ):
            raise ValueError("Invalid language labels.")
        if (
            not vector(model.get("priors"), len(classes))
            or not isinstance(weights, list)
            or len(weights) != len(classes)
            or not all(vector(row, size) for row in weights)
        ):
            raise ValueError("Invalid language weights.")
    else:
        raise ValueError("Unsupported learned model kind.")
    return model


class FittedEmbeddingProvider:
    provider_id = "learned-tfidf"

    def __init__(self, model, revision):
        self.model = validate_model(model)
        if model["kind"] != "tfidf":
            raise ValueError("This revision is not an embedding model.")
        self.model_revision = revision
        self.dimensions = len(model["vocabulary"])

    def embed(self, texts):
        result = []
        for text in texts:
            if len(text) > 200000:
                raise ValueError("Embedding input exceeds 200,000 characters.")
            counts = Counter(tokens(text))
            values = [
                (1 + math.log(counts[word])) * weight if counts[word] else 0.0
                for word, weight in zip(self.model["vocabulary"], self.model["idf"])
            ]
            norm = math.sqrt(sum(value * value for value in values)) or 1
            result.append(tuple(value / norm for value in values))
        return result


def classify_language(model, text):
    validate_model(model)
    if model["kind"] != "language" or not text.strip() or len(text) > 200000:
        raise ValueError("Supply text and a language-classifier revision.")
    counts = Counter(tokens(text))
    known = sum(counts[word] for word in model["vocabulary"])
    scores = [
        prior + sum(counts[word] * weight for word, weight in zip(model["vocabulary"], weights))
        for prior, weights in zip(model["priors"], model["weights"])
    ]
    exp = [math.exp(score - max(scores)) for score in scores]
    probabilities = [value / sum(exp) for value in exp]
    best = max(range(len(scores)), key=probabilities.__getitem__)
    return {
        "language": model["classes"][best] if known >= 2 and probabilities[best] >= 0.6 else "und",
        "scores": dict(zip(model["classes"], probabilities)),
        "known_words": known,
        "method": "supervised multinomial Naive Bayes; scores are not calibrated confidence",
    }
