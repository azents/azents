# RoutineDetailResponse

Current content, most recent occurrence and retained execution records.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**routine** | [**RoutineDefinitionResponse**](RoutineDefinitionResponse.md) |  | 
**execution** | [**RoutineExecutionResponse**](RoutineExecutionResponse.md) |  | 
**records** | [**List[RoutineWorkRecordResponse]**](RoutineWorkRecordResponse.md) |  | 

## Example

```python
from azentspublicclient.models.routine_detail_response import RoutineDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RoutineDetailResponse from a JSON string
routine_detail_response_instance = RoutineDetailResponse.from_json(json)
# print the JSON string representation of the object
print(RoutineDetailResponse.to_json())

# convert the object into a dict
routine_detail_response_dict = routine_detail_response_instance.to_dict()
# create an instance of RoutineDetailResponse from a dict
routine_detail_response_from_dict = RoutineDetailResponse.from_dict(routine_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


