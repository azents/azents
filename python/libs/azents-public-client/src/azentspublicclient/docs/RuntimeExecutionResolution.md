# RuntimeExecutionResolution

Complete hierarchical resolution and explanation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**available** | **bool** |  | 
**effective_policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 
**digest** | **str** |  | 
**source_versions** | [**RuntimeExecutionSourceVersions**](RuntimeExecutionSourceVersions.md) |  | 
**governing_layers** | [**Dict[str, RuntimeExecutionPolicyLayer]**](RuntimeExecutionPolicyLayer.md) |  | 
**reductions** | [**List[RuntimeExecutionReduction]**](RuntimeExecutionReduction.md) |  | 
**change** | [**RuntimeExecutionChangeSummary**](RuntimeExecutionChangeSummary.md) |  | 
**availability_reason** | [**RuntimeExecutionAvailabilityReason**](RuntimeExecutionAvailabilityReason.md) |  | 
**availability_detail** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_resolution import RuntimeExecutionResolution

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionResolution from a JSON string
runtime_execution_resolution_instance = RuntimeExecutionResolution.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionResolution.to_json())

# convert the object into a dict
runtime_execution_resolution_dict = runtime_execution_resolution_instance.to_dict()
# create an instance of RuntimeExecutionResolution from a dict
runtime_execution_resolution_from_dict = RuntimeExecutionResolution.from_dict(runtime_execution_resolution_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


