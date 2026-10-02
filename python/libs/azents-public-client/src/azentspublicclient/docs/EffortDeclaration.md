# EffortDeclaration

An individual effort fact and whether it was explicit or derived.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**level** | [**ReasoningEffortValue**](ReasoningEffortValue.md) |  | 
**state** | **str** |  | 
**origin** | [**EvidenceOrigin**](EvidenceOrigin.md) |  | 

## Example

```python
from azentspublicclient.models.effort_declaration import EffortDeclaration

# TODO update the JSON string below
json = "{}"
# create an instance of EffortDeclaration from a JSON string
effort_declaration_instance = EffortDeclaration.from_json(json)
# print the JSON string representation of the object
print(EffortDeclaration.to_json())

# convert the object into a dict
effort_declaration_dict = effort_declaration_instance.to_dict()
# create an instance of EffortDeclaration from a dict
effort_declaration_from_dict = EffortDeclaration.from_dict(effort_declaration_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


