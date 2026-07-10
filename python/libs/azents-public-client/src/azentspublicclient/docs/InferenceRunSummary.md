# InferenceRunSummary

Compact allowlisted inference provenance for a user message.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**run_id** | **str** | Associated AgentRun ID | 
**run_index** | **int** | Session-local AgentRun index | 
**status** | [**AgentRunStatus**](AgentRunStatus.md) | Latest associated run status | 
**requested_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | 
**source** | [**InferenceProfileSource**](InferenceProfileSource.md) |  | 
**resolved_profile** | [**ResolvedInferenceProfileSummary**](ResolvedInferenceProfileSummary.md) |  | 
**resolved_reasoning_effort** | [**ModelReasoningEffort**](ModelReasoningEffort.md) |  | 
**effective_context_window_tokens** | **int** |  | 
**effective_auto_compaction_threshold_tokens** | **int** |  | 
**failure_code** | [**InferenceProfileFailureCode**](InferenceProfileFailureCode.md) |  | 
**failure_message** | **str** |  | 

## Example

```python
from azentspublicclient.models.inference_run_summary import InferenceRunSummary

# TODO update the JSON string below
json = "{}"
# create an instance of InferenceRunSummary from a JSON string
inference_run_summary_instance = InferenceRunSummary.from_json(json)
# print the JSON string representation of the object
print(InferenceRunSummary.to_json())

# convert the object into a dict
inference_run_summary_dict = inference_run_summary_instance.to_dict()
# create an instance of InferenceRunSummary from a dict
inference_run_summary_from_dict = InferenceRunSummary.from_dict(inference_run_summary_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


