# AddAgentRuntimeRequest

Dedicated Runtime addition request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_runtime_profile_id** | **str** | Explicit available Workspace Runtime Profile ID | 
**expected_capability_version** | **int** |  | 
**expected_runtime_profile_selection_version** | **int** |  | 
**idempotency_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.add_agent_runtime_request import AddAgentRuntimeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AddAgentRuntimeRequest from a JSON string
add_agent_runtime_request_instance = AddAgentRuntimeRequest.from_json(json)
# print the JSON string representation of the object
print(AddAgentRuntimeRequest.to_json())

# convert the object into a dict
add_agent_runtime_request_dict = add_agent_runtime_request_instance.to_dict()
# create an instance of AddAgentRuntimeRequest from a dict
add_agent_runtime_request_from_dict = AddAgentRuntimeRequest.from_dict(add_agent_runtime_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


