# ResetAgentRuntimeRequest

Agent Runtime reset request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**final_desired_state** | [**RuntimeDesiredState**](RuntimeDesiredState.md) | Desired state after reset completes |

## Example

```python
from azentspublicclient.models.reset_agent_runtime_request import ResetAgentRuntimeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ResetAgentRuntimeRequest from a JSON string
reset_agent_runtime_request_instance = ResetAgentRuntimeRequest.from_json(json)
# print the JSON string representation of the object
print(ResetAgentRuntimeRequest.to_json())

# convert the object into a dict
reset_agent_runtime_request_dict = reset_agent_runtime_request_instance.to_dict()
# create an instance of ResetAgentRuntimeRequest from a dict
reset_agent_runtime_request_from_dict = ResetAgentRuntimeRequest.from_dict(reset_agent_runtime_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
