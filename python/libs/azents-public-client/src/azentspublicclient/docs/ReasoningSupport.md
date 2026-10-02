# ReasoningSupport

Reasoning support and an explicitly complete, partial, or unknown effort set.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**support** | [**CapabilitySupport**](CapabilitySupport.md) |  | 
**completeness** | [**EffortCompleteness**](EffortCompleteness.md) |  | 
**efforts** | [**List[EffortDeclaration]**](EffortDeclaration.md) |  | 
**default_effort** | [**DefaultEffortEvidence**](DefaultEffortEvidence.md) |  | 

## Example

```python
from azentspublicclient.models.reasoning_support import ReasoningSupport

# TODO update the JSON string below
json = "{}"
# create an instance of ReasoningSupport from a JSON string
reasoning_support_instance = ReasoningSupport.from_json(json)
# print the JSON string representation of the object
print(ReasoningSupport.to_json())

# convert the object into a dict
reasoning_support_dict = reasoning_support_instance.to_dict()
# create an instance of ReasoningSupport from a dict
reasoning_support_from_dict = ReasoningSupport.from_dict(reasoning_support_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


