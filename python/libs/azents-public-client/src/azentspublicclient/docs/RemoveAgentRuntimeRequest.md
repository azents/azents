# RemoveAgentRuntimeRequest

Final irreversible Runtime removal request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_capability_version** | **int** |  | 
**expected_runtime_profile_selection_version** | **int** |  | 
**idempotency_key** | **str** |  | 
**confirmed** | **bool** | Explicit final destructive confirmation | 

## Example

```python
from azentspublicclient.models.remove_agent_runtime_request import RemoveAgentRuntimeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RemoveAgentRuntimeRequest from a JSON string
remove_agent_runtime_request_instance = RemoveAgentRuntimeRequest.from_json(json)
# print the JSON string representation of the object
print(RemoveAgentRuntimeRequest.to_json())

# convert the object into a dict
remove_agent_runtime_request_dict = remove_agent_runtime_request_instance.to_dict()
# create an instance of RemoveAgentRuntimeRequest from a dict
remove_agent_runtime_request_from_dict = RemoveAgentRuntimeRequest.from_dict(remove_agent_runtime_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


