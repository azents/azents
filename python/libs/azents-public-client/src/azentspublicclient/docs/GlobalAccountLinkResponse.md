# GlobalAccountLinkResponse

Active global provider identity owned by the current User.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**identity_scope** | **str** |  | 
**provider_user_id** | **str** |  | 
**provider_tenant_display_label** | **str** |  | 
**provider_display_label** | **str** |  | 
**linked_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.global_account_link_response import GlobalAccountLinkResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GlobalAccountLinkResponse from a JSON string
global_account_link_response_instance = GlobalAccountLinkResponse.from_json(json)
# print the JSON string representation of the object
print(GlobalAccountLinkResponse.to_json())

# convert the object into a dict
global_account_link_response_dict = global_account_link_response_instance.to_dict()
# create an instance of GlobalAccountLinkResponse from a dict
global_account_link_response_from_dict = GlobalAccountLinkResponse.from_dict(global_account_link_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


