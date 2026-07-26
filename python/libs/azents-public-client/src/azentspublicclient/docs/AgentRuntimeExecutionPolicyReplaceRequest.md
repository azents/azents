# AgentRuntimeExecutionPolicyReplaceRequest

Complete optimistic Agent intent replacement.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**profile_id** | **str** |  | 
**restriction** | [**RuntimeExecutionPolicyRestriction**](RuntimeExecutionPolicyRestriction.md) |  | 

## Example

```python
from azentspublicclient.models.agent_runtime_execution_policy_replace_request import AgentRuntimeExecutionPolicyReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRuntimeExecutionPolicyReplaceRequest from a JSON string
agent_runtime_execution_policy_replace_request_instance = AgentRuntimeExecutionPolicyReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(AgentRuntimeExecutionPolicyReplaceRequest.to_json())

# convert the object into a dict
agent_runtime_execution_policy_replace_request_dict = agent_runtime_execution_policy_replace_request_instance.to_dict()
# create an instance of AgentRuntimeExecutionPolicyReplaceRequest from a dict
agent_runtime_execution_policy_replace_request_from_dict = AgentRuntimeExecutionPolicyReplaceRequest.from_dict(agent_runtime_execution_policy_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


