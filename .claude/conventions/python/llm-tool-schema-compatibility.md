---
title: "Keep LLM function-tool schemas provider-compatible: use one top-level object, avoid root unions and provider-specific conditionals, and enforce cross-field rules at runtime."
---

# Keep LLM Tool Schemas Provider-Compatible

Tool declarations cross provider boundaries, so prefer the conservative JSON Schema subset shared by supported models.

- ALWAYS expose tool parameters as one top-level `type: object` with explicit properties.
- AVOID root `RootModel`, `oneOf`, `anyOf`, primitive branches, discriminators, and conditional keywords; use a normal action or mode field instead.
- Keep conditional required fields, mutual exclusion, and other cross-field rules in runtime model validation, with concise field descriptions guiding the model.
- Keep the declared schema aligned with the handler's accepted JSON shape. Test both the Tool spec and lowered native declaration for a top-level object without root combinators.
- Use nested combinators only when unavoidable and covered across every supported lowerer/provider profile.

## Bad

```python
class ToolInput(RootModel[FinishInput | ContinueInput]):
    pass
```

## Good

```python
class ToolInput(BaseModel):
    mode: Literal["finish", "continue"]
    message: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "ToolInput":
        if self.mode == "finish" and self.message is None:
            raise ValueError("Finish requires a message.")
        return self
```
