# RoutineExecutionResponse

Most recent occurrence timing and status, not execution authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**execution_id** | **str** |  | 
**phase** | **str** |  | 
**admitted_at** | **datetime** |  | 
**started_at** | **datetime** |  | 
**completed_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.routine_execution_response import RoutineExecutionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RoutineExecutionResponse from a JSON string
routine_execution_response_instance = RoutineExecutionResponse.from_json(json)
# print the JSON string representation of the object
print(RoutineExecutionResponse.to_json())

# convert the object into a dict
routine_execution_response_dict = routine_execution_response_instance.to_dict()
# create an instance of RoutineExecutionResponse from a dict
routine_execution_response_from_dict = RoutineExecutionResponse.from_dict(routine_execution_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


