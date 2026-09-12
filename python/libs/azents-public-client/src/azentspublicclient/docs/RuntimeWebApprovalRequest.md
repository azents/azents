# RuntimeWebApprovalRequest

Revision- and displayed-duration-bound approval mutation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**duration_seconds** | **int** |  | 
**duration_configuration_revision** | **int** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_approval_request import RuntimeWebApprovalRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebApprovalRequest from a JSON string
runtime_web_approval_request_instance = RuntimeWebApprovalRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebApprovalRequest.to_json())

# convert the object into a dict
runtime_web_approval_request_dict = runtime_web_approval_request_instance.to_dict()
# create an instance of RuntimeWebApprovalRequest from a dict
runtime_web_approval_request_from_dict = RuntimeWebApprovalRequest.from_dict(runtime_web_approval_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


