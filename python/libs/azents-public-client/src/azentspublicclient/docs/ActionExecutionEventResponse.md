# ActionExecutionEventResponse

Action execution event response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Action execution event ID | 
**action_execution_id** | **str** | Action execution ID | 
**sequence** | **int** | Monotonic event sequence | 
**kind** | **str** | Event kind | 
**step_key** | **str** |  | [optional] 
**command_argv** | **List[str]** |  | [optional] 
**content** | **str** |  | [optional] 
**exit_code** | **int** |  | [optional] 
**created_at** | **datetime** | Created time | 

## Example

```python
from azentspublicclient.models.action_execution_event_response import ActionExecutionEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ActionExecutionEventResponse from a JSON string
action_execution_event_response_instance = ActionExecutionEventResponse.from_json(json)
# print the JSON string representation of the object
print(ActionExecutionEventResponse.to_json())

# convert the object into a dict
action_execution_event_response_dict = action_execution_event_response_instance.to_dict()
# create an instance of ActionExecutionEventResponse from a dict
action_execution_event_response_from_dict = ActionExecutionEventResponse.from_dict(action_execution_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


