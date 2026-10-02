# ParameterSupport

Independent support facts for the existing configurable parameters.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**temperature** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**max_output_tokens** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**top_p** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**top_k** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**stop_sequences** | [**CapabilitySupport**](CapabilitySupport.md) |  | 

## Example

```python
from azentspublicclient.models.parameter_support import ParameterSupport

# TODO update the JSON string below
json = "{}"
# create an instance of ParameterSupport from a JSON string
parameter_support_instance = ParameterSupport.from_json(json)
# print the JSON string representation of the object
print(ParameterSupport.to_json())

# convert the object into a dict
parameter_support_dict = parameter_support_instance.to_dict()
# create an instance of ParameterSupport from a dict
parameter_support_from_dict = ParameterSupport.from_dict(parameter_support_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


