# ModelCompatibilityCapabilities

Provider compatibility capability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider_family** | **str** |  | [optional] 
**responses_api** | **bool** |  | [optional] 
**responses_lite** | **bool** |  | [optional] [default to False]
**unsupported_media_policy** | [**UnsupportedMediaPolicy**](UnsupportedMediaPolicy.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.model_compatibility_capabilities import ModelCompatibilityCapabilities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCompatibilityCapabilities from a JSON string
model_compatibility_capabilities_instance = ModelCompatibilityCapabilities.from_json(json)
# print the JSON string representation of the object
print(ModelCompatibilityCapabilities.to_json())

# convert the object into a dict
model_compatibility_capabilities_dict = model_compatibility_capabilities_instance.to_dict()
# create an instance of ModelCompatibilityCapabilities from a dict
model_compatibility_capabilities_from_dict = ModelCompatibilityCapabilities.from_dict(model_compatibility_capabilities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


