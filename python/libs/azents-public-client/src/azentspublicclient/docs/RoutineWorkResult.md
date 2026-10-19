# RoutineWorkResult

One completed objective and independently chosen user notification.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**objective_outcome** | [**RoutineObjectiveOutcome**](RoutineObjectiveOutcome.md) |  | 
**result** | **str** |  | 
**next_hint** | **str** |  | 
**notify** | **bool** |  | 
**message** | **str** |  | 

## Example

```python
from azentspublicclient.models.routine_work_result import RoutineWorkResult

# TODO update the JSON string below
json = "{}"
# create an instance of RoutineWorkResult from a JSON string
routine_work_result_instance = RoutineWorkResult.from_json(json)
# print the JSON string representation of the object
print(RoutineWorkResult.to_json())

# convert the object into a dict
routine_work_result_dict = routine_work_result_instance.to_dict()
# create an instance of RoutineWorkResult from a dict
routine_work_result_from_dict = RoutineWorkResult.from_dict(routine_work_result_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


