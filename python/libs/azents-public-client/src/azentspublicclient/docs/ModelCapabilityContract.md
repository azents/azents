# ModelCapabilityContract

Version-two semantic authority carried by a newly projected selection.  Existing boolean/list capability fields are conservative derived views of this object. Raw source records and collection provenance are stored outside this bounded dispatch contract. No field triggers source or profile lookup.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**version** | **int** |  | 
**reasoning** | [**ReasoningSupport**](ReasoningSupport.md) |  | 
**reasoning_summaries** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**function_calling** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**parallel_function_calls** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**strict_function_schema** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**structured_response** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**parameters** | [**ParameterSupport**](ParameterSupport.md) |  | 
**input_modalities** | [**List[ModalitySupport]**](ModalitySupport.md) |  | 
**output_modalities** | [**List[ModalitySupport]**](ModalitySupport.md) |  | 
**built_in_tools** | [**List[BuiltinToolSupport]**](BuiltinToolSupport.md) |  | 

## Example

```python
from azentspublicclient.models.model_capability_contract import ModelCapabilityContract

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCapabilityContract from a JSON string
model_capability_contract_instance = ModelCapabilityContract.from_json(json)
# print the JSON string representation of the object
print(ModelCapabilityContract.to_json())

# convert the object into a dict
model_capability_contract_dict = model_capability_contract_instance.to_dict()
# create an instance of ModelCapabilityContract from a dict
model_capability_contract_from_dict = ModelCapabilityContract.from_dict(model_capability_contract_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


