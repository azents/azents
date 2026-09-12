# AccountLinkListResponse

Current User's Workspace external account links.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AccountLinkResponse]**](AccountLinkResponse.md) |  | 

## Example

```python
from azentspublicclient.models.account_link_list_response import AccountLinkListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AccountLinkListResponse from a JSON string
account_link_list_response_instance = AccountLinkListResponse.from_json(json)
# print the JSON string representation of the object
print(AccountLinkListResponse.to_json())

# convert the object into a dict
account_link_list_response_dict = account_link_list_response_instance.to_dict()
# create an instance of AccountLinkListResponse from a dict
account_link_list_response_from_dict = AccountLinkListResponse.from_dict(account_link_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


