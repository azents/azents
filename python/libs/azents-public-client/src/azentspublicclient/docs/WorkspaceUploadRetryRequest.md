# WorkspaceUploadRetryRequest

Runtime delivery retry request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** | Exact upload revision observed by the caller | 
**current_delivery_number** | **int** | Exact current delivery attempt number | 
**overwrite** | **bool** | Whether to explicitly replace the conflicted destination | 
**conflict_precondition** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.workspace_upload_retry_request import WorkspaceUploadRetryRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUploadRetryRequest from a JSON string
workspace_upload_retry_request_instance = WorkspaceUploadRetryRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUploadRetryRequest.to_json())

# convert the object into a dict
workspace_upload_retry_request_dict = workspace_upload_retry_request_instance.to_dict()
# create an instance of WorkspaceUploadRetryRequest from a dict
workspace_upload_retry_request_from_dict = WorkspaceUploadRetryRequest.from_dict(workspace_upload_retry_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


