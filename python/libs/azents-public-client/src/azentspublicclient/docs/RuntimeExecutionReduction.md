# RuntimeExecutionReduction

One effective value reduced by a governing policy layer.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**path** | **str** |  | 
**previous** | **object** |  | 
**current** | **object** |  | 
**governing_layer** | [**RuntimeExecutionPolicyLayer**](RuntimeExecutionPolicyLayer.md) |  | 
**reason** | [**RuntimeExecutionReductionReason**](RuntimeExecutionReductionReason.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_reduction import RuntimeExecutionReduction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionReduction from a JSON string
runtime_execution_reduction_instance = RuntimeExecutionReduction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionReduction.to_json())

# convert the object into a dict
runtime_execution_reduction_dict = runtime_execution_reduction_instance.to_dict()
# create an instance of RuntimeExecutionReduction from a dict
runtime_execution_reduction_from_dict = RuntimeExecutionReduction.from_dict(runtime_execution_reduction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


