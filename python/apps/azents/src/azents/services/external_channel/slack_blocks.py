"""Bounded Slack Block Kit and rich-text normalization."""

from dataclasses import dataclass

_MAX_BLOCKS = 32
_MAX_ELEMENTS = 512
_MAX_DEPTH = 8
_MAX_TEXT_BYTES = 32 * 1024


@dataclass
class _TraversalBudget:
    remaining_elements: int = _MAX_ELEMENTS


def slack_blocks_text(value: object) -> str:
    """Return bounded readable text from supported Slack blocks."""
    if not isinstance(value, list):
        return ""
    budget = _TraversalBudget()
    parts = [
        _block_text(block, budget)
        for block in value[:_MAX_BLOCKS]
        if isinstance(block, dict)
    ]
    return _bounded("\n".join(part for part in parts if part).strip())


def projected_slack_blocks(value: object) -> list[dict[str, str]]:
    """Project Slack blocks into bounded type and normalized-text fields."""
    if not isinstance(value, list):
        return []
    projected: list[dict[str, str]] = []
    for block in value[:_MAX_BLOCKS]:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if not isinstance(block_type, str) or not block_type:
            continue
        normalized_text = slack_blocks_text([block])
        projected.append(
            {
                "type": block_type,
                **({"normalized_text": normalized_text} if normalized_text else {}),
            }
        )
    return projected


def _block_text(block: dict[str, object], budget: _TraversalBudget) -> str:
    projected = block.get("normalized_text")
    if isinstance(projected, str):
        return projected
    block_type = block.get("type")
    if block_type == "rich_text":
        return _container_text(block.get("elements"), budget, depth=0)
    if block_type in {"section", "header"}:
        parts = [_text_object(block.get("text"), budget)]
        fields = block.get("fields")
        if isinstance(fields, list):
            parts.extend(_text_object(field, budget) for field in fields)
        return "\n".join(part for part in parts if part)
    if block_type == "context":
        elements = block.get("elements")
        if isinstance(elements, list):
            return " ".join(
                part for element in elements if (part := _text_object(element, budget))
            )
    return ""


def _container_text(
    value: object,
    budget: _TraversalBudget,
    *,
    depth: int,
) -> str:
    if depth >= _MAX_DEPTH or not isinstance(value, list):
        return ""
    parts: list[str] = []
    for element in value:
        if budget.remaining_elements <= 0:
            break
        if not isinstance(element, dict):
            continue
        budget.remaining_elements -= 1
        element_type = element.get("type")
        if element_type in {
            "rich_text_section",
            "rich_text_quote",
            "rich_text_preformatted",
        }:
            text = _container_text(
                element.get("elements"),
                budget,
                depth=depth + 1,
            )
            if text:
                parts.append(text)
        elif element_type == "rich_text_list":
            nested = element.get("elements")
            if isinstance(nested, list):
                ordered = element.get("style") == "ordered"
                for index, item in enumerate(nested, start=1):
                    text = _container_text([item], budget, depth=depth + 1)
                    if text:
                        marker = f"{index}." if ordered else "•"
                        parts.append(f"{marker} {text}")
        else:
            text = _rich_element_text(element, budget)
            if text:
                parts.append(text)
    separator = (
        "\n"
        if any(
            isinstance(element, dict)
            and element.get("type")
            in {
                "rich_text_list",
                "rich_text_quote",
                "rich_text_preformatted",
            }
            for element in value
        )
        else ""
    )
    return separator.join(parts)


def _rich_element_text(
    element: dict[str, object],
    budget: _TraversalBudget,
) -> str:
    element_type = element.get("type")
    if element_type == "text":
        return _string(element.get("text"))
    if element_type == "link":
        return _string(element.get("text")) or _string(element.get("url"))
    if element_type == "emoji":
        name = _string(element.get("name"))
        return f":{name}:" if name else ""
    if element_type == "user":
        user_id = _string(element.get("user_id"))
        return f"<@{user_id}>" if user_id else ""
    if element_type == "channel":
        channel_id = _string(element.get("channel_id"))
        return f"<#{channel_id}>" if channel_id else ""
    if element_type == "broadcast":
        broadcast = _string(element.get("range"))
        return f"@{broadcast}" if broadcast else ""
    if element_type == "usergroup":
        usergroup_id = _string(element.get("usergroup_id"))
        return f"<!subteam^{usergroup_id}>" if usergroup_id else ""
    if element_type == "date":
        return (
            _string(element.get("fallback"))
            or _string(element.get("format"))
            or _string(element.get("timestamp"))
        )
    if element_type in {
        "rich_text_section",
        "rich_text_quote",
        "rich_text_preformatted",
        "rich_text_list",
    }:
        return _container_text([element], budget, depth=1)
    return ""


def _text_object(value: object, budget: _TraversalBudget) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict) or budget.remaining_elements <= 0:
        return ""
    budget.remaining_elements -= 1
    return _string(value.get("text"))


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _bounded(value: str) -> str:
    encoded = value.encode()
    if len(encoded) <= _MAX_TEXT_BYTES:
        return value
    return encoded[:_MAX_TEXT_BYTES].decode(errors="ignore")
