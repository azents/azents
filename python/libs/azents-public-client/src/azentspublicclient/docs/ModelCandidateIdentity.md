# ModelCandidateIdentity

Public-safe exact physical candidate identity.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**llm_provider_integration_id** | **str** |  | 
**model_identifier** | **str** |  | 

## Example

```python
from azentspublicclient.models.model_candidate_identity import ModelCandidateIdentity

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCandidateIdentity from a JSON string
model_candidate_identity_instance = ModelCandidateIdentity.from_json(json)
# print the JSON string representation of the object
print(ModelCandidateIdentity.to_json())

# convert the object into a dict
model_candidate_identity_dict = model_candidate_identity_instance.to_dict()
# create an instance of ModelCandidateIdentity from a dict
model_candidate_identity_from_dict = ModelCandidateIdentity.from_dict(model_candidate_identity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


