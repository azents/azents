# ActionExecutionResponse

Action execution live projection response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Action execution ID | 
**input_buffer_id** | **str** | Durable source input buffer ID | 
**action_type** | **str** | Action discriminator | 
**action** | [**Action**](Action.md) |  | 
**status** | **str** | Execution status | 
**failure_summary** | **str** |  | [optional] 
**started_at** | **datetime** |  | [optional] 
**completed_at** | **datetime** |  | [optional] 
**failed_at** | **datetime** |  | [optional] 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentspublicclient.models.action_execution_response import ActionExecutionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ActionExecutionResponse from a JSON string
action_execution_response_instance = ActionExecutionResponse.from_json(json)
# print the JSON string representation of the object
print(ActionExecutionResponse.to_json())

# convert the object into a dict
action_execution_response_dict = action_execution_response_instance.to_dict()
# create an instance of ActionExecutionResponse from a dict
action_execution_response_from_dict = ActionExecutionResponse.from_dict(action_execution_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


