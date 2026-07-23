# ExternalChannelFilesDetailResponse

Effective External Channel file policy without internal generation data.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**section** | **str** |  | 
**schema_version** | **int** |  | 
**admin_version** | **int** |  | 
**inbound_max_file_bytes** | **int** |  | 
**outbound_max_file_bytes** | **int** |  | 
**outbound_max_action_bytes** | **int** |  | 

## Example

```python
from azentsadminclient.models.external_channel_files_detail_response import ExternalChannelFilesDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelFilesDetailResponse from a JSON string
external_channel_files_detail_response_instance = ExternalChannelFilesDetailResponse.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelFilesDetailResponse.to_json())

# convert the object into a dict
external_channel_files_detail_response_dict = external_channel_files_detail_response_instance.to_dict()
# create an instance of ExternalChannelFilesDetailResponse from a dict
external_channel_files_detail_response_from_dict = ExternalChannelFilesDetailResponse.from_dict(external_channel_files_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


