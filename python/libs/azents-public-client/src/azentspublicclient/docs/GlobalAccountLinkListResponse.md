# GlobalAccountLinkListResponse

Active global provider identities owned by the current User.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[GlobalAccountLinkResponse]**](GlobalAccountLinkResponse.md) |  | 

## Example

```python
from azentspublicclient.models.global_account_link_list_response import GlobalAccountLinkListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GlobalAccountLinkListResponse from a JSON string
global_account_link_list_response_instance = GlobalAccountLinkListResponse.from_json(json)
# print the JSON string representation of the object
print(GlobalAccountLinkListResponse.to_json())

# convert the object into a dict
global_account_link_list_response_dict = global_account_link_list_response_instance.to_dict()
# create an instance of GlobalAccountLinkListResponse from a dict
global_account_link_list_response_from_dict = GlobalAccountLinkListResponse.from_dict(global_account_link_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


