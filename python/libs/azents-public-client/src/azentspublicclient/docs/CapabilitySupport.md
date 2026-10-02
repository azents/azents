# CapabilitySupport

One justified support state, independent of source or runtime libraries.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**state** | [**SupportState**](SupportState.md) |  | 
**origin** | [**EvidenceOrigin**](EvidenceOrigin.md) |  | 
**predicate** | [**SupportPredicate**](SupportPredicate.md) |  | 

## Example

```python
from azentspublicclient.models.capability_support import CapabilitySupport

# TODO update the JSON string below
json = "{}"
# create an instance of CapabilitySupport from a JSON string
capability_support_instance = CapabilitySupport.from_json(json)
# print the JSON string representation of the object
print(CapabilitySupport.to_json())

# convert the object into a dict
capability_support_dict = capability_support_instance.to_dict()
# create an instance of CapabilitySupport from a dict
capability_support_from_dict = CapabilitySupport.from_dict(capability_support_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


