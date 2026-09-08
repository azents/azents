# ModelExecutionOptionDefinition

Public metadata for one model execution option.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | [**ModelExecutionOptionId**](ModelExecutionOptionId.md) |  | 
**label** | **str** |  | 
**description** | **str** |  | 
**cost_hint** | **str** |  | 
**control** | **str** |  | 

## Example

```python
from azentspublicclient.models.model_execution_option_definition import ModelExecutionOptionDefinition

# TODO update the JSON string below
json = "{}"
# create an instance of ModelExecutionOptionDefinition from a JSON string
model_execution_option_definition_instance = ModelExecutionOptionDefinition.from_json(json)
# print the JSON string representation of the object
print(ModelExecutionOptionDefinition.to_json())

# convert the object into a dict
model_execution_option_definition_dict = model_execution_option_definition_instance.to_dict()
# create an instance of ModelExecutionOptionDefinition from a dict
model_execution_option_definition_from_dict = ModelExecutionOptionDefinition.from_dict(model_execution_option_definition_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


