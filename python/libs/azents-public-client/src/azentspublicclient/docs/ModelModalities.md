# ModelModalities

Input/output modalities supported by the model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**input** | [**List[ModelModality]**](ModelModality.md) |  | [optional]
**output** | [**List[ModelModality]**](ModelModality.md) |  | [optional]

## Example

```python
from azentspublicclient.models.model_modalities import ModelModalities

# TODO update the JSON string below
json = "{}"
# create an instance of ModelModalities from a JSON string
model_modalities_instance = ModelModalities.from_json(json)
# print the JSON string representation of the object
print(ModelModalities.to_json())

# convert the object into a dict
model_modalities_dict = model_modalities_instance.to_dict()
# create an instance of ModelModalities from a dict
model_modalities_from_dict = ModelModalities.from_dict(model_modalities_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


