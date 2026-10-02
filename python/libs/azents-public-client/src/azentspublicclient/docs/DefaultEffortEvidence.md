# DefaultEffortEvidence

A saved known default; absence of this object means the default is unknown.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**level** | [**ReasoningEffortValue**](ReasoningEffortValue.md) |  | 
**origin** | [**EvidenceOrigin**](EvidenceOrigin.md) |  | 

## Example

```python
from azentspublicclient.models.default_effort_evidence import DefaultEffortEvidence

# TODO update the JSON string below
json = "{}"
# create an instance of DefaultEffortEvidence from a JSON string
default_effort_evidence_instance = DefaultEffortEvidence.from_json(json)
# print the JSON string representation of the object
print(DefaultEffortEvidence.to_json())

# convert the object into a dict
default_effort_evidence_dict = default_effort_evidence_instance.to_dict()
# create an instance of DefaultEffortEvidence from a dict
default_effort_evidence_from_dict = DefaultEffortEvidence.from_dict(default_effort_evidence_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


