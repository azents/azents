# AgentResponse

Agent response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**name** | **str** |  | 
**description** | **str** |  | 
**model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | 
**lightweight_model_selection** | [**AgentModelSelection**](AgentModelSelection.md) |  | 
**effective_context_window_tokens** | **int** |  | 
**effective_auto_compaction_threshold_tokens** | **int** |  | 
**model_parameters** | [**ModelParameters**](ModelParameters.md) |  | 
**system_prompt** | **str** |  | 
**enabled** | **bool** |  | 
**type** | [**AgentType**](AgentType.md) |  | 
**runtime_provider_id** | **str** |  | 
**shell_enabled** | **bool** |  | 
**memory_enabled** | **bool** |  | 
**max_turns** | **int** |  | 
**avatar** | [**UploadedImage**](UploadedImage.md) |  | [optional] 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.agent_response import AgentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentResponse from a JSON string
agent_response_instance = AgentResponse.from_json(json)
# print the JSON string representation of the object
print(AgentResponse.to_json())

# convert the object into a dict
agent_response_dict = agent_response_instance.to_dict()
# create an instance of AgentResponse from a dict
agent_response_from_dict = AgentResponse.from_dict(agent_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


