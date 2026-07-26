# RuntimeExecutionChangeSummary

Aggregate and field-level security direction.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**direction** | [**RuntimeExecutionChangeDirection**](RuntimeExecutionChangeDirection.md) |  | 
**fields** | [**List[RuntimeExecutionFieldChange]**](RuntimeExecutionFieldChange.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_change_summary import RuntimeExecutionChangeSummary

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionChangeSummary from a JSON string
runtime_execution_change_summary_instance = RuntimeExecutionChangeSummary.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionChangeSummary.to_json())

# convert the object into a dict
runtime_execution_change_summary_dict = runtime_execution_change_summary_instance.to_dict()
# create an instance of RuntimeExecutionChangeSummary from a dict
runtime_execution_change_summary_from_dict = RuntimeExecutionChangeSummary.from_dict(runtime_execution_change_summary_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


