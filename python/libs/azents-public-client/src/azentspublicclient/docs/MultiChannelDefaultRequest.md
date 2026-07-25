# MultiChannelDefaultRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_generation** | **datetime** |  | 
**route_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.multi_channel_default_request import MultiChannelDefaultRequest

# TODO update the JSON string below
json = "{}"
# create an instance of MultiChannelDefaultRequest from a JSON string
multi_channel_default_request_instance = MultiChannelDefaultRequest.from_json(json)
# print the JSON string representation of the object
print(MultiChannelDefaultRequest.to_json())

# convert the object into a dict
multi_channel_default_request_dict = multi_channel_default_request_instance.to_dict()
# create an instance of MultiChannelDefaultRequest from a dict
multi_channel_default_request_from_dict = MultiChannelDefaultRequest.from_dict(multi_channel_default_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


