# SessionContextSystemPromptResponse

Session context system prompt analysis response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_prompt** | [**SessionContextSystemPromptFragmentResponse**](SessionContextSystemPromptFragmentResponse.md) |  | [optional]
**toolkit_prompts** | [**List[SessionContextSystemPromptFragmentResponse]**](SessionContextSystemPromptFragmentResponse.md) | Toolkit prompt fragments |
**injected_prompts** | [**List[SessionContextSystemPromptFragmentResponse]**](SessionContextSystemPromptFragmentResponse.md) | Turn injected prompt fragments |
**final_prompt** | [**SessionContextSystemPromptFragmentResponse**](SessionContextSystemPromptFragmentResponse.md) |  | [optional]

## Example

```python
from azentspublicclient.models.session_context_system_prompt_response import SessionContextSystemPromptResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextSystemPromptResponse from a JSON string
session_context_system_prompt_response_instance = SessionContextSystemPromptResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextSystemPromptResponse.to_json())

# convert the object into a dict
session_context_system_prompt_response_dict = session_context_system_prompt_response_instance.to_dict()
# create an instance of SessionContextSystemPromptResponse from a dict
session_context_system_prompt_response_from_dict = SessionContextSystemPromptResponse.from_dict(session_context_system_prompt_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
