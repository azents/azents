# SessionContextSystemPromptFragmentResponse

Session context system prompt fragment response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Prompt fragment ID | 
**source** | **str** | Prompt fragment source | 
**label** | **str** | Display label | 
**content** | **str** | Full prompt content | 
**preview** | **str** | Prompt preview | 
**length** | **int** | Prompt content length | 
**metadata** | **Dict[str, str]** | Source metadata | 

## Example

```python
from azentspublicclient.models.session_context_system_prompt_fragment_response import SessionContextSystemPromptFragmentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextSystemPromptFragmentResponse from a JSON string
session_context_system_prompt_fragment_response_instance = SessionContextSystemPromptFragmentResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextSystemPromptFragmentResponse.to_json())

# convert the object into a dict
session_context_system_prompt_fragment_response_dict = session_context_system_prompt_fragment_response_instance.to_dict()
# create an instance of SessionContextSystemPromptFragmentResponse from a dict
session_context_system_prompt_fragment_response_from_dict = SessionContextSystemPromptFragmentResponse.from_dict(session_context_system_prompt_fragment_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


