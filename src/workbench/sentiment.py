"""Optional locally installed FinBERT inference with versioned in-run reuse."""
import re


class FinBertScorer:
    def __init__(self, revision):
        if not re.fullmatch(r"[a-fA-F0-9]{40}", revision):
            raise ValueError("Provide the exact 40-character FinBERT model revision.")
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
        except ImportError as exc:
            raise ValueError("Install the optional sentiment dependencies to use FinBERT.") from exc
        self.version = f"ProsusAI/finbert@{revision}"
        try:
            tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert", revision=revision,
                                                      local_files_only=True, trust_remote_code=False)
            model = AutoModelForSequenceClassification.from_pretrained(
                "ProsusAI/finbert", revision=revision, local_files_only=True,
                trust_remote_code=False, use_safetensors=True,
            )
            self.pipeline = pipeline("text-classification", model=model, tokenizer=tokenizer, device=-1)
        except (ValueError, OSError) as exc:
            raise ValueError("The pinned FinBERT safetensors checkpoint was not available in the local model cache.") from exc
        self.cache = {}

    def __call__(self, headlines):
        pending = list(dict.fromkeys(text for text in headlines if text not in self.cache))
        for start in range(0, len(pending), 16):
            batch = pending[start:start + 16]
            predictions = self.pipeline(batch, top_k=None, truncation=True, max_length=128, batch_size=16)
            for text, labels in zip(batch, predictions, strict=True):
                values = {item["label"].lower(): item["score"] for item in labels}
                self.cache[text] = values["positive"] - values["negative"]
        return [self.cache[text] for text in headlines]
