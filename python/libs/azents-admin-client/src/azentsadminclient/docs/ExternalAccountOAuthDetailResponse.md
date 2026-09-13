# ExternalAccountOAuthDetailResponse

Redacted provider OAuth System Settings detail.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**section** | **str** |  | 
**provider** | **str** |  | 
**schema_version** | **int** |  | 
**admin_version** | **int** |  | 
**effective_status** | **str** |  | 
**callback_url** | **str** |  | 
**fields** | [**List[ExternalAccountOAuthFieldResponse]**](ExternalAccountOAuthFieldResponse.md) |  | 
**health** | [**ExternalAccountOAuthHealthResponse**](ExternalAccountOAuthHealthResponse.md) |  | 

## Example

```python
from azentsadminclient.models.external_account_o_auth_detail_response import ExternalAccountOAuthDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalAccountOAuthDetailResponse from a JSON string
external_account_o_auth_detail_response_instance = ExternalAccountOAuthDetailResponse.from_json(json)
# print the JSON string representation of the object
print(ExternalAccountOAuthDetailResponse.to_json())

# convert the object into a dict
external_account_o_auth_detail_response_dict = external_account_o_auth_detail_response_instance.to_dict()
# create an instance of ExternalAccountOAuthDetailResponse from a dict
external_account_o_auth_detail_response_from_dict = ExternalAccountOAuthDetailResponse.from_dict(external_account_o_auth_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


