# ManualRoutineSource

Candidate input at eligible checks without a manual user action.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 

## Example

```python
from azentspublicclient.models.manual_routine_source import ManualRoutineSource

# TODO update the JSON string below
json = "{}"
# create an instance of ManualRoutineSource from a JSON string
manual_routine_source_instance = ManualRoutineSource.from_json(json)
# print the JSON string representation of the object
print(ManualRoutineSource.to_json())

# convert the object into a dict
manual_routine_source_dict = manual_routine_source_instance.to_dict()
# create an instance of ManualRoutineSource from a dict
manual_routine_source_from_dict = ManualRoutineSource.from_dict(manual_routine_source_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


