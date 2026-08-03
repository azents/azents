# PrepareSessionWorkingFolderRequest

Request an explicit retry of canonical Session-folder preparation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**client_request_id** | **str** | Client-generated idempotency key | 

## Example

```python
from azentspublicclient.models.prepare_session_working_folder_request import PrepareSessionWorkingFolderRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PrepareSessionWorkingFolderRequest from a JSON string
prepare_session_working_folder_request_instance = PrepareSessionWorkingFolderRequest.from_json(json)
# print the JSON string representation of the object
print(PrepareSessionWorkingFolderRequest.to_json())

# convert the object into a dict
prepare_session_working_folder_request_dict = prepare_session_working_folder_request_instance.to_dict()
# create an instance of PrepareSessionWorkingFolderRequest from a dict
prepare_session_working_folder_request_from_dict = PrepareSessionWorkingFolderRequest.from_dict(prepare_session_working_folder_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


