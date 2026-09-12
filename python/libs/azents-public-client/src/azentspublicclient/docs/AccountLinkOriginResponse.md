# AccountLinkOriginResponse

Browser-safe original provider confirmation context.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**workspace_id** | **str** |  | 
**workspace_name** | **str** |  | 
**workspace_handle** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**identity_scope** | **str** |  | 
**provider_tenant_id** | **str** |  | 
**provider_tenant_display_label** | **str** |  | 
**provider_display_label** | **str** |  | 
**expires_at** | **datetime** |  | 
**state** | [**ExternalAccountLinkOriginState**](ExternalAccountLinkOriginState.md) |  | 
**candidate_count** | **int** |  | 
**candidate_limit** | **int** |  | 
**invalid_code_count** | **int** |  | 
**invalid_code_limit** | **int** |  | 
**return_context** | [**AccountLinkReturnContextResponse**](AccountLinkReturnContextResponse.md) |  | 

## Example

```python
from azentspublicclient.models.account_link_origin_response import AccountLinkOriginResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkOriginResponse from a JSON string
account_link_origin_response_instance = AccountLinkOriginResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkOriginResponse.to_json())

# convert the object into a dict
account_link_origin_response_dict = account_link_origin_response_instance.to_dict()
# create an instance of AccountLinkOriginResponse from a dict
account_link_origin_response_from_dict = AccountLinkOriginResponse.from_dict(account_link_origin_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


