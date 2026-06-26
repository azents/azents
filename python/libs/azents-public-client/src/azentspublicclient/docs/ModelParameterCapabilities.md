# ModelParameterCapabilities

Configurable generation parameters supported by the model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**temperature** | **bool** |  | [optional] [default to False]
**max_tokens** | **bool** |  | [optional] [default to False]
**top_p** | **bool** |  | [optional] [default to False]
**top_k** | **bool** |  | [optional] [default to False]
**stop_sequences** | **bool** |  | [optional] [default to False]

## Example

```python
from azentspublicclient.models.model_parameter_capabilities import ModelParameterCapabilities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelParameterCapabilities from a JSON string
model_parameter_capabilities_instance = ModelParameterCapabilities.from_json(json)
# print the JSON string representation of the object
print(ModelParameterCapabilities.to_json())

# convert the object into a dict
model_parameter_capabilities_dict = model_parameter_capabilities_instance.to_dict()
# create an instance of ModelParameterCapabilities from a dict
model_parameter_capabilities_from_dict = ModelParameterCapabilities.from_dict(model_parameter_capabilities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


