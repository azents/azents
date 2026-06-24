# AgentModelSelection

Model selection snapshot stored on an Agent row.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**llm_provider_integration_id** | **str** | LLM provider integration ID |
**provider** | [**LLMProvider**](LLMProvider.md) | LLM hosting provider |
**model_identifier** | **str** | Provider model identifier |
**model_display_name** | **str** | Model display name |
**model_developer** | [**LLMModelDeveloper**](LLMModelDeveloper.md) | Model developer |
**model_family** | **str** |  | [optional]
**normalized_capabilities** | [**ModelCapabilities**](ModelCapabilities.md) | Runtime capability snapshot |
**model_snapshot** | **Dict[str, object]** | Normalized model snapshot |
**source_metadata** | **Dict[str, object]** |  | [optional]
**last_refreshed_at** | **datetime** |  | [optional]

## Example

```python
from azentspublicclient.models.agent_model_selection import AgentModelSelection

# TODO update the JSON string below
json = "{}"
# create an instance of AgentModelSelection from a JSON string
agent_model_selection_instance = AgentModelSelection.from_json(json)
# print the JSON string representation of the object
print(AgentModelSelection.to_json())

# convert the object into a dict
agent_model_selection_dict = agent_model_selection_instance.to_dict()
# create an instance of AgentModelSelection from a dict
agent_model_selection_from_dict = AgentModelSelection.from_dict(agent_model_selection_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
