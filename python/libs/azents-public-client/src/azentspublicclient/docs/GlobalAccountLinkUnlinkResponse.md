# GlobalAccountLinkUnlinkResponse

Terminal result for disconnecting one global provider identity.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**state** | [**ExternalAccountLinkState**](ExternalAccountLinkState.md) |  | 

## Example

```python
from azentspublicclient.models.global_account_link_unlink_response import GlobalAccountLinkUnlinkResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GlobalAccountLinkUnlinkResponse from a JSON string
global_account_link_unlink_response_instance = GlobalAccountLinkUnlinkResponse.from_json(json)
# print the JSON string representation of the object
print(GlobalAccountLinkUnlinkResponse.to_json())

# convert the object into a dict
global_account_link_unlink_response_dict = global_account_link_unlink_response_instance.to_dict()
# create an instance of GlobalAccountLinkUnlinkResponse from a dict
global_account_link_unlink_response_from_dict = GlobalAccountLinkUnlinkResponse.from_dict(global_account_link_unlink_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


