# AgentRuntimePublicActionsResponse

Complete public Runtime action availability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**add** | **bool** |  | 
**remove** | **bool** |  | 
**start** | **bool** |  | 
**stop** | **bool** |  | 
**restart** | **bool** |  | 
**reset** | **bool** |  | 
**observe** | **bool** |  | 
**use_runner** | **bool** |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_public_actions_response import AgentRuntimePublicActionsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimePublicActionsResponse from a JSON string
agent_runtime_public_actions_response_instance = AgentRuntimePublicActionsResponse.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimePublicActionsResponse.to_json())

# convert the object into a dict
agent_runtime_public_actions_response_dict = agent_runtime_public_actions_response_instance.to_dict()
# create an instance of AgentRuntimePublicActionsResponse from a dict
agent_runtime_public_actions_response_from_dict = AgentRuntimePublicActionsResponse.from_dict(agent_runtime_public_actions_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


