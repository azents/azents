# ExternalChannelFilesPatchRequest

Optimistic partial update for External Channel file limits.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**inbound_max_file_bytes** | **int** |  | [optional] 
**outbound_max_file_bytes** | **int** |  | [optional] 
**outbound_max_action_bytes** | **int** |  | [optional] 

## Example

```python
from azentsadminclient.models.external_channel_files_patch_request import ExternalChannelFilesPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelFilesPatchRequest from a JSON string
external_channel_files_patch_request_instance = ExternalChannelFilesPatchRequest.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelFilesPatchRequest.to_json())

# convert the object into a dict
external_channel_files_patch_request_dict = external_channel_files_patch_request_instance.to_dict()
# create an instance of ExternalChannelFilesPatchRequest from a dict
external_channel_files_patch_request_from_dict = ExternalChannelFilesPatchRequest.from_dict(external_channel_files_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


