# RuntimeExecutionPolicyDocument

Complete versioned execution-policy document.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**schema_version** | **int** |  | 
**image_build** | [**RuntimeExecutionBooleanModule**](RuntimeExecutionBooleanModule.md) |  | 
**container_run** | [**RuntimeExecutionBooleanModule**](RuntimeExecutionBooleanModule.md) |  | 
**compose** | [**RuntimeExecutionBooleanModule**](RuntimeExecutionBooleanModule.md) |  | 
**resources** | [**RuntimeExecutionResourceModule**](RuntimeExecutionResourceModule.md) |  | 
**engine_storage** | [**RuntimeExecutionStorageModule**](RuntimeExecutionStorageModule.md) |  | 
**network_egress** | [**RuntimeExecutionNetworkModule**](RuntimeExecutionNetworkModule.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_policy_document import RuntimeExecutionPolicyDocument

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionPolicyDocument from a JSON string
runtime_execution_policy_document_instance = RuntimeExecutionPolicyDocument.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionPolicyDocument.to_json())

# convert the object into a dict
runtime_execution_policy_document_dict = runtime_execution_policy_document_instance.to_dict()
# create an instance of RuntimeExecutionPolicyDocument from a dict
runtime_execution_policy_document_from_dict = RuntimeExecutionPolicyDocument.from_dict(runtime_execution_policy_document_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


