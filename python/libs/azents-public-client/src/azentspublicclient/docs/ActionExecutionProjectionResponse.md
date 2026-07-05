# ActionExecutionProjectionResponse

Action execution state plus durable progress events.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**execution** | [**ActionExecutionResponse**](ActionExecutionResponse.md) | Action execution state | 
**events** | [**List[ActionExecutionEventResponse]**](ActionExecutionEventResponse.md) | Action execution event list | 

## Example

```python
from azentspublicclient.models.action_execution_projection_response import ActionExecutionProjectionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ActionExecutionProjectionResponse from a JSON string
action_execution_projection_response_instance = ActionExecutionProjectionResponse.from_json(json)
# print the JSON string representation of the object
print(ActionExecutionProjectionResponse.to_json())

# convert the object into a dict
action_execution_projection_response_dict = action_execution_projection_response_instance.to_dict()
# create an instance of ActionExecutionProjectionResponse from a dict
action_execution_projection_response_from_dict = ActionExecutionProjectionResponse.from_dict(action_execution_projection_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


