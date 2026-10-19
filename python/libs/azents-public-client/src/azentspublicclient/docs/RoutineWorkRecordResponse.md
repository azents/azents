# RoutineWorkRecordResponse

Objective outcome, recorded work and notification evidence stay distinct.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**routine_id** | **str** |  | 
**execution_id** | **str** |  | 
**started_at** | **datetime** |  | 
**completed_at** | **datetime** |  | 
**work** | [**RoutineWorkResult**](RoutineWorkResult.md) |  | 
**delivery_status** | [**RoutineDeliveryStatus**](RoutineDeliveryStatus.md) |  | 
**delivery_error** | **str** |  | 

## Example

```python
from azentspublicclient.models.routine_work_record_response import RoutineWorkRecordResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RoutineWorkRecordResponse from a JSON string
routine_work_record_response_instance = RoutineWorkRecordResponse.from_json(json)
# print the JSON string representation of the object
print(RoutineWorkRecordResponse.to_json())

# convert the object into a dict
routine_work_record_response_dict = routine_work_record_response_instance.to_dict()
# create an instance of RoutineWorkRecordResponse from a dict
routine_work_record_response_from_dict = RoutineWorkRecordResponse.from_dict(routine_work_record_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


