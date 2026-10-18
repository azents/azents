# RoutineContent

Exactly comparable editable content with no implicit text rewriting.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** |  | 
**objective** | **str** |  | 
**sources** | [**List[ManualRoutineSource]**](ManualRoutineSource.md) |  | 

## Example

```python
from azentspublicclient.models.routine_content import RoutineContent

# TODO update the JSON string below
json = "{}"
# create an instance of RoutineContent from a JSON string
routine_content_instance = RoutineContent.from_json(json)
# print the JSON string representation of the object
print(RoutineContent.to_json())

# convert the object into a dict
routine_content_dict = routine_content_instance.to_dict()
# create an instance of RoutineContent from a dict
routine_content_from_dict = RoutineContent.from_dict(routine_content_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


