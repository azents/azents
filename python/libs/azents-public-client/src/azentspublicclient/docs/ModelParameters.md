# ModelParameters

LLM model parameters.  Every field is optional; unset fields use model defaults.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**temperature** | **float** |  | [optional]
**max_tokens** | **int** |  | [optional]
**top_p** | **float** |  | [optional]
**top_k** | **int** |  | [optional]
**stop_sequences** | **List[str]** |  | [optional]
**reasoning_effort** | **str** |  | [optional]
**builtin_tools** | [**List[BuiltinToolConfig]**](BuiltinToolConfig.md) | Built-in tool list to enable | [optional]

## Example

```python
from azentspublicclient.models.model_parameters import ModelParameters

# TODO update the JSON string below
json = "{}"
# create an instance of ModelParameters from a JSON string
model_parameters_instance = ModelParameters.from_json(json)
# print the JSON string representation of the object
print(ModelParameters.to_json())

# convert the object into a dict
model_parameters_dict = model_parameters_instance.to_dict()
# create an instance of ModelParameters from a dict
model_parameters_from_dict = ModelParameters.from_dict(model_parameters_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
