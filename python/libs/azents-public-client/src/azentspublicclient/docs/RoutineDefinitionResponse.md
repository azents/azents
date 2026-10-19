# RoutineDefinitionResponse

Current definition content for read-only Session inspection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**slug** | **str** |  | 
**content** | [**RoutineContent**](RoutineContent.md) |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.routine_definition_response import RoutineDefinitionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RoutineDefinitionResponse from a JSON string
routine_definition_response_instance = RoutineDefinitionResponse.from_json(json)
# print the JSON string representation of the object
print(RoutineDefinitionResponse.to_json())

# convert the object into a dict
routine_definition_response_dict = routine_definition_response_instance.to_dict()
# create an instance of RoutineDefinitionResponse from a dict
routine_definition_response_from_dict = RoutineDefinitionResponse.from_dict(routine_definition_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


