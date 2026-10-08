"""Pure exact hosting-resource protocol identity shared by compiler and codecs."""

from typing import Literal


def vertex_model_family(model: str) -> Literal["google", "anthropic"]:
    """Interpret the existing Vertex protocol route without borrowing model facts."""
    parts = model.split("/")
    if "publishers" in parts:
        index = parts.index("publishers")
        if len(parts) <= index + 3 or parts[index + 2] != "models":
            raise ValueError("The Vertex publisher resource is malformed.")
        publisher = parts[index + 1]
        if publisher in {"google", "anthropic"}:
            return publisher
        raise ValueError("The Vertex publisher is not an authorized model family.")
    return "anthropic" if model.startswith("claude-") else "google"
