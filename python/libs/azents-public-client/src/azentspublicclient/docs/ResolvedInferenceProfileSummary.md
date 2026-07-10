# ResolvedInferenceProfileSummary

Allowlisted resolved model identity safe for public projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**LLMProvider**](LLMProvider.md) | Resolved hosting provider | 
**model_identifier** | **str** | Resolved provider model identifier | 
**model_display_name** | **str** | Resolved model display name | 
**model_developer** | [**LLMModelDeveloper**](LLMModelDeveloper.md) | Resolved model developer | 

## Example

```python
from azentspublicclient.models.resolved_inference_profile_summary import ResolvedInferenceProfileSummary

# TODO update the JSON string below
json = "{}"
# create an instance of ResolvedInferenceProfileSummary from a JSON string
resolved_inference_profile_summary_instance = ResolvedInferenceProfileSummary.from_json(json)
# print the JSON string representation of the object
print(ResolvedInferenceProfileSummary.to_json())

# convert the object into a dict
resolved_inference_profile_summary_dict = resolved_inference_profile_summary_instance.to_dict()
# create an instance of ResolvedInferenceProfileSummary from a dict
resolved_inference_profile_summary_from_dict = ResolvedInferenceProfileSummary.from_dict(resolved_inference_profile_summary_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


