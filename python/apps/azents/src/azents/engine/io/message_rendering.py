"""Runtime-agnostic message rendering helpers."""


def render_message(
    content: str,
    headers: list[tuple[str, str]],
    metadata: dict[str, str],
) -> str:
    """Render a message as model-visible text.

    :param content: Original content
    :param headers: Important metadata
    :param metadata: Technical metadata
    :return: Rendered content
    """
    parts: list[str] = []

    if headers:
        for key, value in headers:
            parts.append(f"{key}: {value}" if key else value)
        parts.append("")

    parts.append(content)

    if metadata:
        meta_str = ", ".join(f"{k}={v}" for k, v in sorted(metadata.items()))
        parts.append(f"<metadata>{meta_str}</metadata>")

    return "\n".join(parts)
