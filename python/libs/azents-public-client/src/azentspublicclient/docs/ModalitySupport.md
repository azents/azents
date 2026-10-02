# ModalitySupport

One supported, denied, unknown, or conditional content form.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**modality** | [**ModalityValue**](ModalityValue.md) |  | 
**support** | [**CapabilitySupport**](CapabilitySupport.md) |  | 

## Example

```python
from azentspublicclient.models.modality_support import ModalitySupport

# TODO update the JSON string below
json = "{}"
# create an instance of ModalitySupport from a JSON string
modality_support_instance = ModalitySupport.from_json(json)
# print the JSON string representation of the object
print(ModalitySupport.to_json())

# convert the object into a dict
modality_support_dict = modality_support_instance.to_dict()
# create an instance of ModalitySupport from a dict
modality_support_from_dict = ModalitySupport.from_dict(modality_support_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


