# RuntimeExecutionProfileResponse

One stable named Runtime execution Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeExecutionProfileLifecycle**](RuntimeExecutionProfileLifecycle.md) |  | 
**version** | **int** |  | 
**policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 
**digest** | **str** |  | 
**reserved** | **bool** |  | 
**system_key** | **str** |  | 
**updated_by_user_id** | **str** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_profile_response import RuntimeExecutionProfileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionProfileResponse from a JSON string
runtime_execution_profile_response_instance = RuntimeExecutionProfileResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionProfileResponse.to_json())

# convert the object into a dict
runtime_execution_profile_response_dict = runtime_execution_profile_response_instance.to_dict()
# create an instance of RuntimeExecutionProfileResponse from a dict
runtime_execution_profile_response_from_dict = RuntimeExecutionProfileResponse.from_dict(runtime_execution_profile_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


